import argparse
import base64
import json
import logging

from flask_sqlalchemy.session import Session

from feature_flags import MANAGE_MEDIA
from file_utils import is_valid_url
from media_queries import find_folder_by_id
from media_utils import get_folder_rating_checker, get_folder_group_checker
from plugin_methods import plugin_long_string_arg, plugin_select_arg, plugin_select_values, plugin_filename_arg, \
    plugin_media_folder_chooser_folder_arg
from plugin_system import ActionMediaFolderPlugin, ActionMediaPlugin
from plugins.media_download_file import DownloadFileJob
from plugins.media_download_m3u8_ex import DownloadM3u8JobEx
from plugins.media_download_m3u8 import DownloadM3u8Job
from text_utils import is_blank
from thread_utils import TaskWrapper, RunReport


class DownloadTrackerPlugin(ActionMediaFolderPlugin):
    """
    Import exported tracker extension payload (base64 JSON) and queue download jobs for each group item.
    """

    def __init__(self):
        super().__init__()
        self.prefix_lang_id = 'dltracker'

    def get_sort(self):
        return {'id': 'media_dl.tracker', 'sequence': 1}

    def add_args(self, parser: argparse):
        pass

    def use_args(self, args):
        pass

    def get_action_name(self):
        return 'Import from Media Tracker'

    def get_action_id(self):
        return 'action.download.tracker'

    def get_action_icon(self):
        return 'download'

    def get_action_args(self):
        result = super().get_action_args()

        result.append(
            plugin_long_string_arg(
                'Tracker Payload',
                'payload',
                'Paste the base64-encoded JSON exported from the Media Tracker browser extension here.',
                'com'
            )
        )

        result.append(
            plugin_select_arg(
                'Location', 'dest', 'primary',
                plugin_select_values('Primary Disk', 'primary', 'Archive Disk', 'archive'),
                '', 'media'
            )
        )

        result.append(
            plugin_select_arg(
                'M3u8 Method', 'm3u8_meth', 'ex',
                plugin_select_values('Advanced (Ex)', 'ex', 'Simple (ffmpeg)', 'simple'),
                'Which M3u8 downloader to use?', adv='Y'
            )
        )

        return result

    def process_action_args(self, args):
        return _process_tracker_args(args, require_folder=True)

    def get_feature_flags(self):
        return MANAGE_MEDIA

    def create_task(self, db_session: Session, args):
        return _create_tracker_task(args, self.primary_path, self.archive_path, self.temp_path)


def _process_tracker_args(args, require_folder: bool):
    results = []

    if 'payload' not in args or is_blank(args['payload']):
        results.append('payload is required')
        return results

    raw = args['payload'].strip()

    try:
        decoded = base64.b64decode(raw).decode('utf-8')
        groups = json.loads(decoded)
    except Exception as e:
        logging.exception('Failed to decode tracker payload')
        results.append(f'payload is not valid base64 JSON: {e}')
        return results

    if not isinstance(groups, list) or len(groups) == 0:
        results.append('payload decoded but contains no groups')
        return results

    args['_groups'] = groups

    if 'dest' not in args or is_blank(args['dest']):
        results.append('dest is required')
    elif args['dest'] not in ('primary', 'archive'):
        results.append('Invalid dest value')

    if require_folder and ('folder_id' not in args or is_blank(args['folder_id'])):
        results.append('folder_id is required')

    return results if results else None


def _create_tracker_task(args, primary_path, archive_path, temp_path):
    groups = args['_groups']
    dest = args['dest']
    default_folder_id = args.get('folder_id') or ''
    m3u8_meth = args.get('m3u8_meth', 'ex')
    user_details = args.get('_user_details')

    folder_rating_checker = get_folder_rating_checker(user_details) if user_details else None
    folder_group_checker = get_folder_group_checker(user_details) if user_details else None

    return _build_tracker_jobs(
        groups, dest, default_folder_id, m3u8_meth,
        folder_rating_checker, folder_group_checker,
        primary_path, archive_path, temp_path
    )


def _build_tracker_jobs(groups, dest, default_folder_id, m3u8_meth,
                        folder_rating_checker, folder_group_checker,
                        primary_path, archive_path, temp_path):
    jobs = []

    for group in groups:
        try:
            group_name = group.get('n', 'unknown')
            group_type = group.get('t', 'file')
            items = group.get('items', [])
            group_folder_id = group.get('folder_id', '').strip() if group.get('folder_id') else ''

            report = RunReport('Import Report', f'Tracker import report for group {group_name}')

            # Resolve folder: use group-level folder_id if present and accessible
            folder_id = default_folder_id
            if group_folder_id:
                group_folder_row = find_folder_by_id(group_folder_id)
                if group_folder_row is None:
                    report.add_warn(f'folder_id {group_folder_id!r} not found — using default folder')
                elif folder_rating_checker and not folder_rating_checker(group_folder_row):
                    report.add_warn(f'folder_id {group_folder_id!r} access denied (rating) — using default folder')
                elif folder_group_checker and not folder_group_checker(group_folder_row):
                    report.add_warn(f'folder_id {group_folder_id!r} access denied (group) — using default folder')
                else:
                    folder_id = group_folder_id

            if not folder_id:
                report.add_error(f'No folder available for group {group_name!r} — skipping all jobs for this group')
                jobs.append(report)
                continue

            if group_type == 'm3u8_vtt':
                stream_item = next((it for it in items if it.get('t') == 'STREAM'), None)
                subtitle_item = next((it for it in items if it.get('t') == 'SUBTITLE'), None)

                stream_url = stream_item.get('url', '').strip() if stream_item else ''
                stream_origin = stream_item.get('origin', '').strip() if stream_item else ''
                sub_url = subtitle_item.get('url', '').strip() if subtitle_item else ''
                sub_origin = subtitle_item.get('origin', '').strip() if subtitle_item else ''

                filename = group_name + '.mp4'

                if is_valid_url(stream_url):
                    if m3u8_meth == 'ex':
                        jobs.append(
                            DownloadM3u8JobEx(
                                'Download M3u8',
                                f'Downloading {filename} from M3u8 (tracker group {group_name})',
                                folder_id, filename, stream_url,
                                stream_origin if is_valid_url(stream_origin) else stream_url,
                                dest, primary_path, archive_path, temp_path
                            )
                        )
                    else:
                        jobs.append(
                            DownloadM3u8Job(
                                'Download M3u8',
                                f'Downloading {filename} from M3u8 (tracker group {group_name})',
                                folder_id, filename, stream_url,
                                dest, primary_path, archive_path, temp_path
                            )
                        )
                else:
                    report.add_warn(f'No valid STREAM url found — skipping m3u8 job for {filename}')

                if is_valid_url(sub_url):
                    vtt_filename = group_name + '.vtt'
                    jobs.append(
                        DownloadFileJob(
                            'Download File',
                            f'Downloading {vtt_filename} from Web (tracker group {group_name})',
                            folder_id, vtt_filename, sub_url,
                            sub_origin if is_valid_url(sub_origin) else sub_url,
                            dest, 'gcurl',
                            primary_path, archive_path, temp_path
                        )
                    )

            else:
                # file group — each item is a standalone file download
                for item in items:
                    item_url = item.get('url', '').strip()
                    item_origin = item.get('origin', '').strip()

                    if not is_valid_url(item_url):
                        report.add_warn(f'Item has invalid url {item_url!r} — skipping')
                        continue

                    jobs.append(
                        DownloadFileJob(
                            'Download File',
                            f'Downloading {group_name} from Web (tracker group {group_name})',
                            folder_id, group_name, item_url,
                            item_origin if is_valid_url(item_origin) else item_url,
                            dest, 'system',
                            primary_path, archive_path, temp_path
                        )
                    )

            if report.has_entries():
                jobs.append(report)

        except Exception:
            logging.exception('tracker: unexpected error processing group %r', group)

    return jobs


class DownloadTrackerMediaPlugin(ActionMediaPlugin):
    """
    Global (non-folder-scoped) variant of DownloadTrackerPlugin.
    Accessible from the main media menu; the user picks a fallback folder via a folder chooser.
    """

    def __init__(self):
        super().__init__()
        self.prefix_lang_id = 'dltracker'

    def get_sort(self):
        return {'id': 'media_dl.tracker.global', 'sequence': 1}

    def add_args(self, parser: argparse):
        pass

    def use_args(self, args):
        pass

    def get_action_name(self):
        return 'Import from Media Tracker'

    def get_action_id(self):
        return 'action.download.tracker.global'

    def get_action_icon(self):
        return 'download'

    def get_action_args(self):
        result = super().get_action_args()

        result.append(
            plugin_long_string_arg(
                'Tracker Payload',
                'payload',
                'Paste the base64-encoded JSON exported from the Media Tracker browser extension here.',
                'com'
            )
        )

        result.append(
            plugin_media_folder_chooser_folder_arg(
                'Default Folder', 'folder_id',
                'Fallback folder used when a group does not specify its own folder.'
            )
        )

        result.append(
            plugin_select_arg(
                'Location', 'dest', 'primary',
                plugin_select_values('Primary Disk', 'primary', 'Archive Disk', 'archive'),
                '', 'media'
            )
        )

        result.append(
            plugin_select_arg(
                'M3u8 Method', 'm3u8_meth', 'ex',
                plugin_select_values('Advanced (Ex)', 'ex', 'Simple (ffmpeg)', 'simple'),
                'Which M3u8 downloader to use?', adv='Y'
            )
        )

        return result

    def process_action_args(self, args):
        return _process_tracker_args(args, require_folder=False)

    def get_feature_flags(self):
        return MANAGE_MEDIA

    def create_task(self, db_session: Session, args):
        return _create_tracker_task(args, self.primary_path, self.archive_path, self.temp_path)
