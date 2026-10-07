import argparse
import os.path
import platform
import shlex
import shutil
import subprocess
from datetime import datetime
from time import sleep

from flask_sqlalchemy.session import Session

from curl_utils import custom_curl_get, read_temp_file, read_header_file, is_cloudflare_block
from feature_flags import MANAGE_MEDIA
from file_utils import is_valid_url, temporary_folder
from html_utils import get_headers
from m3u8_parser import M3u8Playlist
from media_probe import get_file_formats
from media_queries import find_folder_by_id, insert_file
from media_utils import get_data_for_mediafile
from plugin_methods import plugin_filename_arg, plugin_url_arg, plugin_select_arg, plugin_select_values
from plugin_system import ActionMediaFolderPlugin
from plugins.media_download_file import DownloadFileJob
from strip_png_prefix import strip_png_prefix_from_directory
from text_utils import is_blank
from thread_utils import TaskWrapper


class DownloadM3u8PluginEx(ActionMediaFolderPlugin):
    """
    Download from YTube
    """

    def __init__(self):
        super().__init__()
        self.prefix_lang_id = 'dlm3u8ex'

    def get_sort(self):
        return {'id': 'media_dl.m3u8.ex', 'sequence': 1}

    def add_args(self, parser: argparse):
        pass

    def use_args(self, args):
        pass

    def get_action_name(self):
        return 'Save Video from M3u8 (Ex)'

    def get_action_id(self):
        return 'action.download.m3u8.ex'

    def get_action_icon(self):
        return 'download'

    def get_action_args(self):
        result = super().get_action_args()

        result.append(
            plugin_url_arg('URL', 'url', 'The link to the m3u8 file.', '', 'yes', "url", 'origin', 'Origin')
        )

        result.append(
            plugin_filename_arg('Filename', 'filename', 'The name of the file.')
        )

        result.append(
            plugin_select_arg('Location', 'dest', 'primary',
                              plugin_select_values('Primary Disk', 'primary', 'Archive Disk', 'archive'), '', 'media',
                              adv='Y')
        )

        result.append(
            plugin_url_arg('Origin', 'origin', 'The origin for the Url.', '', 'no', "Origin")
        )

        return result

    def process_action_args(self, args):
        results = []

        if 'url' not in args or args['url'] is None or args['url'] == '':
            results.append('url is required')

        if 'origin' not in args or args['origin'] is None or args['origin'] == '':
            results.append('origin is required')

        if 'filename' not in args or args['filename'] is None or args['filename'] == '':
            results.append('filename is required')

        if not is_valid_url(args['url']):
            results.append('url is not valid url')

        if not is_valid_url(args['origin']):
            results.append('origin is not valid url')

        if 'dest' not in args or is_blank(args['dest']):
            results.append('dest is required')
        elif not (args['dest'] == 'primary' or args['dest'] == 'archive'):
            results.append('Invalid dest value')

        if len(results) > 0:
            return results
        return None

    def get_feature_flags(self):
        return MANAGE_MEDIA

    def is_ready(self):
        return super().is_ready() and platform.system() == 'Linux'

    def create_task(self, db_session: Session, args):
        filename = args['filename']
        return DownloadM3u8JobEx("Download M3u8", f'Downloading {filename} from M3u8 to folder ' + args['folder_id'],
                                 args['folder_id'], filename, args['url'].strip(), args['origin'].strip(),
                                 args['dest'], self.primary_path,
                                 self.archive_path, self.temp_path)


class DownloadM3u8SubtitlePluginEx(ActionMediaFolderPlugin):
    """
    Download from YTube
    """

    def __init__(self):
        super().__init__()
        self.prefix_lang_id = 'dlm3u8exsub'

    def get_sort(self):
        return {'id': 'media_dl.m3u8.ex.sub', 'sequence': 1}

    def add_args(self, parser: argparse):
        pass

    def use_args(self, args):
        pass

    def get_action_name(self):
        return 'Download M3u8 (Ex) & Subtitle'

    def get_action_id(self):
        return 'action.download.m3u8.ex.sub'

    def get_action_icon(self):
        return 'download'

    def get_action_args(self):
        result = super().get_action_args()

        result.append(
            plugin_select_arg('Location', 'dest', 'primary',
                              plugin_select_values('Primary Disk', 'primary', 'Archive Disk', 'archive'), '', 'media',
                              adv='Y')
        )

        result.append(
            plugin_filename_arg('Filename', 'filename', 'The name of the file.')
        )

        result.append(
            plugin_url_arg('Subtitle URL', 'sub_url', 'The link to the m3u8 file.', '', 'yes', "url", 'sub_origin', 'Origin')
        )

        result.append(
            plugin_url_arg('M3u8 URL', 'url', 'The link to the m3u8 file.', '', 'yes', "url", 'origin', "Origin")
        )

        result.append(
            plugin_url_arg('Subtitle Origin', 'sub_origin', 'The origin for the Url.', '', 'no', "Origin")
        )

        result.append(
            plugin_url_arg('M3u8 Origin', 'origin', 'The origin for the Url.', '', 'no', "Origin")
        )


        return result

    def process_action_args(self, args):
        results = []

        if 'url' not in args or args['url'] is None or args['url'] == '':
            results.append('url is required')

        if 'origin' not in args or args['origin'] is None or args['origin'] == '':
            results.append('origin is required')

        if 'filename' not in args or args['filename'] is None or args['filename'] == '':
            results.append('filename is required')

        results_m3u8 = []
        results_file = []

        if not is_valid_url(args['url']):
            results_m3u8.append('url is not valid url')

        if not is_valid_url(args['origin']):
            results_m3u8.append('origin is not valid url')

        if not is_valid_url(args['sub_url']):
            results_file.append('subtitle url is not valid url')

        if not is_valid_url(args['sub_origin']):
            results_file.append('subtitle origin is not valid url')

        if len(results_m3u8) == 0 or len(results_file) == 0:
            # If one side is good, we can ignore the other errors
            results_m3u8 = []
            results_file = []

        results.extend(results_m3u8)
        results.extend(results_file)

        if 'dest' not in args or is_blank(args['dest']):
            results.append('dest is required')
        elif not (args['dest'] == 'primary' or args['dest'] == 'archive'):
            results.append('Invalid dest value')

        if len(results) > 0:
            return results
        return None

    def get_feature_flags(self):
        return MANAGE_MEDIA

    def is_ready(self):
        return super().is_ready() and platform.system() == 'Linux'

    def create_task(self, db_session: Session, args):
        filename = args['filename']

        jobs = []

        if is_valid_url(args['url']) and is_valid_url(args['origin']):
            jobs.append(
                DownloadM3u8JobEx("Download M3u8", f'Downloading {filename} from M3u8 to folder ' + args['folder_id'],
                                  args['folder_id'], filename, args['url'].strip(), args['origin'].strip(),
                                  args['dest'],
                                  self.primary_path,
                                  self.archive_path,
                                  self.temp_path))

        if is_valid_url(args['sub_url']) and is_valid_url(args['sub_origin']):
            jobs.append(
                DownloadFileJob("Download File", f'Downloading {filename}.vtt from Web to folder ' + args['folder_id'],
                                args['folder_id'], filename + '.vtt', args['sub_url'], args['sub_origin'].strip(),
                                args['dest'],
                                'gcurl',
                                self.primary_path,
                                self.archive_path,
                                self.temp_path))
        return jobs


def file_to_hex_string(filepath):
    with open(filepath, "rb") as f:
        data = f.read()
    hex_string = data.hex()
    return hex_string


class DownloadM3u8JobEx(TaskWrapper):
    def __init__(self, name, description, folder_id, filename, url, origin, dest, primary_path, archive_path,
                 temp_path):
        super().__init__(name, description)
        self.folder_id = folder_id
        self.filename = filename
        self.url = url
        self.origin = origin
        self.dest = dest
        self.primary_path = primary_path
        self.archive_path = archive_path
        self.temp_path = temp_path
        self.ref_folder_id = folder_id

    def run(self, db_session: Session):

        if is_blank(self.primary_path) or is_blank(self.archive_path) or is_blank(self.temp_path):
            self.critical('This feature is not ready.  Please configure the app properties and restart the server.')

        source_row = find_folder_by_id(self.folder_id, db_session)
        if source_row is None:
            self.critical('Source Folder not found')
            self.set_failure()
            return

        self.ref_folder_preview = source_row.preview == True

        is_archive = self.dest == 'archive'

        with temporary_folder(self.temp_path, self) as temp_folder:

            self.debug(f'temp folder: {temp_folder}')

            temp_m3u8_file = os.path.join(temp_folder, 'download.m3u8')
            made_m3u8_file = os.path.join(temp_folder, 'remade.m3u8')
            temp_file = os.path.join(temp_folder, 'download.mp4')

            headers = get_headers(self.url, True, self, False, self.origin)

            if headers is None:
                self.error('Unable to get Headers, stopping')
                return False

            if not custom_curl_get(self.url, headers, temp_m3u8_file, self):
                self.error("Failed to download m3u8.")
                self.set_failure()
                return None

            if is_cloudflare_block(temp_m3u8_file):
                self.error('Cloudflare block detected on m3u8 response (403 equivalent)')
                self.set_failure()
                return None

            response_text = read_temp_file(temp_m3u8_file)
            base_url = self.url.rsplit("/", 1)[0] + "/"
            playlist = M3u8Playlist.parse(response_text, base_url)

            self.debug(f'Playlist: {len(playlist.segments())} segments, '
                       f'{len(playlist.key_entries())} keys, '
                       f'{len(playlist.map_entries())} maps')

            # --- Phase 1: download key files ---
            for entry in playlist.key_entries():
                self.info(f'Found Key Definition: {entry.method}')
                self.debug(entry.raw_line)
                key_path = os.path.join(temp_folder, entry.local_name)
                if not custom_curl_get(entry.uri, headers, key_path, self):
                    self.error("Failed to download encryption key.")
                    self.set_failure()
                    return None
                self.debug(f"Decryption key fetched from: {entry.uri}")

            # --- Phase 2: download map files ---
            for entry in playlist.map_entries():
                self.info('Found Map Definition')
                self.debug(entry.raw_line)
                map_path = os.path.join(temp_folder, entry.local_name)
                if not custom_curl_get(entry.uri, headers, map_path, self):
                    self.error("Failed to download map file.")
                    self.set_failure()
                    return None
                self.debug(f"Map file fetched from: {entry.uri}")

            encrypted = playlist.has_encryption()
            segments = playlist.segments()
            total = len(segments)
            consecutive_404s = 0
            consecutive_404_limit = max(1, int(total * 0.10))

            # --- Phase 3: download segments ---
            for idx, entry in enumerate(segments):

                if self.is_cancelled:
                    return

                self.update_progress(((idx + 1) / total) * 100.0)
                self.debug(f"Downloading segment: {entry.uri}")

                seg_file = os.path.join(temp_folder, entry.local_name)
                header_file = os.path.join(temp_folder, f'seg_{idx}.txt')

                if not custom_curl_get(entry.uri, headers, seg_file, self, header_file=header_file):
                    self.warn(f"Failed to download segment {entry.local_name}.")
                    self.set_warning()
                    entry.valid = False
                    entry.missing = True
                    consecutive_404s += 1
                else:
                    current_headers = read_header_file(header_file)
                    http_status = current_headers['@HTTP_STATUS']

                    if http_status == '404':
                        self.debug(f'{entry.local_name} returned 404, will attempt stand-in after download loop')
                        entry.valid = False
                        entry.missing = True
                        consecutive_404s += 1
                    else:
                        consecutive_404s = 0

                        if http_status != '200':
                            self.debug(f'http-status: {http_status}')

                        if 'content-type' in current_headers:
                            self.debug(f'{entry.local_name} content-type: {current_headers.get("content-type")}')

                        if encrypted:
                            determined_ext = 'ts'
                            valid_format = True
                        else:
                            available_format = get_file_formats(seg_file, self)
                            if available_format is None:
                                valid_format = False
                                determined_ext = 'mp4'
                            elif available_format == 'mp4':
                                self.trace(f'Segment {entry.local_name} is MP4')
                                valid_format = True
                                determined_ext = 'mp4'
                            else:
                                valid_format = True
                                determined_ext = available_format

                        if determined_ext == 'png_pipe':
                            determined_ext = 'ts'

                        new_seg_path = os.path.join(temp_folder, f'seg_{idx}.{determined_ext}')
                        shutil.move(seg_file, new_seg_path)
                        self.trace(f'Segment {entry.local_name} is actually {determined_ext}')

                        entry.determined_extension = determined_ext
                        entry.valid = valid_format

                if consecutive_404s >= consecutive_404_limit:
                    self.error(f'{consecutive_404s} consecutive 404s (limit is {consecutive_404_limit} for {total} segments) — aborting download, playlist is likely invalid')
                    self.set_failure()
                    return

            # --- Phase 3b: resolve missing segments ---
            missing_segments = [e for e in segments if e.missing]
            if missing_segments:
                self.info(f'{len(missing_segments)} missing segment(s) to resolve')

                # Build index of valid downloaded segments for stand-in lookup.
                # Each entry: (segment_index, absolute_file_path, extension)
                valid_index: list[tuple[int, str, str]] = []
                for idx, entry in enumerate(segments):
                    if not entry.missing and entry.valid and entry.determined_extension:
                        valid_index.append((idx, os.path.join(temp_folder, entry.effective_name), entry.determined_extension))

                if not valid_index:
                    self.warn('No valid segments available to use as stand-ins; all missing segments will be dropped')
                else:
                    for idx, entry in enumerate(segments):
                        if not entry.missing:
                            continue

                        if encrypted:
                            # AES-128 CBC: each segment uses a unique IV derived
                            # from its sequence number.  Substituting a different
                            # segment's ciphertext with the wrong IV produces
                            # completely garbled output, so we drop it instead.
                            self.warn(f'{entry.local_name} is missing in encrypted stream — dropping (IV mismatch would corrupt output)')
                            continue

                        # Find the nearest valid segment — prefer the closest one
                        # before this index, fall back to the closest one after.
                        best = min(valid_index, key=lambda v: abs(v[0] - idx))
                        _, src_path, src_ext = best

                        standin_name = f'seg_{idx}.{src_ext}'
                        standin_path = os.path.join(temp_folder, standin_name)

                        try:
                            shutil.copy2(src_path, standin_path)
                            entry.determined_extension = src_ext
                            entry.valid = True
                            self.debug(f'{entry.local_name} missing — substituted with stand-in from seg index {best[0]}')
                        except OSError:
                            self.warn(f'Could not copy stand-in for {entry.local_name}, dropping segment')

            # --- Phase 4: write rewritten playlist and run ffmpeg ---
            strip_png_prefix_from_directory(temp_folder, self)
            playlist.write(made_m3u8_file)

            arguments = ['ffmpeg', '-allowed_extensions', 'ALL', '-nostdin', '-i', made_m3u8_file, '-c', 'copy',
                         temp_file]

            if self.can_trace():
                self.trace(shlex.join(arguments))

            process = subprocess.Popen(arguments, cwd=temp_folder, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            stdout, stderr = process.communicate()
            return_code = str(process.returncode)

            if return_code == '0' and os.path.exists(temp_file) and os.path.isfile(temp_file):

                file_size = os.path.getsize(temp_file)

                if file_size > 0:

                    self.info(f'Found file with size {file_size}')

                    created_time = os.path.getctime(temp_file)
                    created_datetime = datetime.fromtimestamp(created_time)

                    new_file = insert_file(source_row.id, self.filename, 'video/mp4', is_archive, False, file_size,
                                           created_datetime, db_session)

                    dest_path = get_data_for_mediafile(new_file, self.primary_path, self.archive_path)
                    shutil.move(str(temp_file), str(dest_path))

                    self.set_worked()
                    self.set_finished()
                else:
                    self.set_failure()
                    self.error("Could not find MP4 file (0 len)")
            else:
                self.error(f'Return Code {return_code}')
                self.error(stderr.decode('utf-8'))
                self.set_failure()
                sleep(35)
