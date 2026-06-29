import re
from dataclasses import dataclass, field
from typing import Union
from urllib.parse import urljoin


# ---------------------------------------------------------------------------
# Entry types
#
# Each logical unit in an M3U8 playlist is represented as one of these four
# dataclasses.  The parser produces an ordered list of them; the processor
# mutates M3u8SegmentEntry fields in place; M3u8Playlist.write() serialises
# them back to a local-path playlist ready for ffmpeg.
# ---------------------------------------------------------------------------

@dataclass
class M3u8KeyEntry:
    """
    Represents an #EXT-X-KEY tag.

    method     - encryption method string from the tag (e.g. "AES-128", "NONE")
    uri        - absolute URL of the key file, resolved at parse time
    iv         - hex IV string without the "0x" prefix, or None if absent
    is_noop    - True when method is NONE or no URI was present; no file to fetch
    local_name - filename the key will be saved as in the temp folder
    raw_line   - verbatim original tag line, used as the rewrite base
    """
    method: str
    uri: str
    iv: str | None
    is_noop: bool
    local_name: str
    raw_line: str


@dataclass
class M3u8MapEntry:
    """
    Represents an #EXT-X-MAP tag (MP4 init segment).

    uri        - absolute URL of the init segment, resolved at parse time
    local_name - filename the map file will be saved as in the temp folder
    raw_line   - verbatim original tag line
    """
    uri: str
    local_name: str
    raw_line: str


@dataclass
class M3u8SegmentEntry:
    """
    Represents one media segment — the #EXTINF line plus its URI.

    extinf_line          - verbatim #EXTINF:... line
    uri                  - absolute segment URL, resolved at parse time
    local_name           - initial download filename (e.g. seg_0.mp4)
    determined_extension - set by the processor after probing the file format;
                           None until probed.  effective_name uses this.
    valid                - set False by the processor if the segment should be
                           excluded from the rewritten playlist (404, bad format)
    missing              - set True when the segment returned 404; a separate
                           post-loop pass attempts to resolve missing segments
                           before the playlist is written
    """
    extinf_line: str
    uri: str
    local_name: str
    determined_extension: str | None = field(default=None)
    valid: bool = field(default=True)
    missing: bool = field(default=False)

    @property
    def effective_name(self) -> str:
        """Returns local_name with the extension replaced by determined_extension
        if the processor has set one, otherwise returns local_name unchanged."""
        if self.determined_extension is None:
            return self.local_name
        base = self.local_name.rsplit('.', 1)[0]
        return f'{base}.{self.determined_extension}'


@dataclass
class M3u8PassthroughEntry:
    """
    Any line that is not a key, map, or segment — including #EXTM3U,
    #EXT-X-VERSION, #EXT-X-TARGETDURATION, #EXT-X-ENDLIST, blank lines
    that were not skipped, etc.  Written back verbatim by M3u8Playlist.write().
    """
    raw_line: str


# Union type alias used for type hints elsewhere.
M3u8Entry = Union[M3u8KeyEntry, M3u8MapEntry, M3u8SegmentEntry, M3u8PassthroughEntry]


# ---------------------------------------------------------------------------
# M3u8Playlist
# ---------------------------------------------------------------------------

class M3u8Playlist:
    """
    Parses a raw M3U8 playlist text into an ordered list of typed entries and
    can serialise them back to a local-path playlist file.

    Typical usage:

        playlist = M3u8Playlist.parse(text, base_url)

        for entry in playlist.key_entries():
            # download entry.uri → temp_folder/entry.local_name

        for entry in playlist.map_entries():
            # download entry.uri → temp_folder/entry.local_name

        for entry in playlist.segments():
            # download entry.uri → temp_folder/entry.local_name
            # probe format, set entry.determined_extension and entry.valid

        playlist.write(output_path)
    """

    def __init__(self):
        self.entries: list[M3u8Entry] = []

    @classmethod
    def parse(cls, text: str, base_url: str) -> 'M3u8Playlist':
        """
        Parse raw M3U8 text into an M3u8Playlist.

        base_url is used to resolve relative URIs found in the playlist to
        absolute URLs (via urljoin).  It should be the directory portion of
        the playlist URL, e.g. "https://cdn.example.com/hls/stream/".

        Empty lines are skipped.  Segment URIs are found by consuming the
        next non-empty line after each #EXTINF tag.  Multiple #EXT-X-KEY and
        #EXT-X-MAP tags are supported; each gets a unique local filename.
        """
        playlist = cls()
        lines = [l.strip() for l in text.splitlines()]
        key_counter = 0
        map_counter = 0
        seg_counter = 0
        i = 0

        while i < len(lines):
            line = lines[i]

            if not line:
                i += 1
                continue

            if line.startswith('#EXT-X-KEY:'):
                method_match = re.search(r'METHOD=([^,\s]+)', line)
                uri_match = re.search(r'URI="([^"]+)"', line)
                iv_match = re.search(r'IV=0x([0-9a-fA-F]+)', line)

                method = method_match.group(1) if method_match else 'NONE'
                is_noop = method.upper() == 'NONE'
                iv = iv_match.group(1) if iv_match else None

                if uri_match:
                    uri = urljoin(base_url, uri_match.group(1))
                    local_name = f'download_{key_counter}.key'
                    key_counter += 1
                else:
                    uri = ''
                    local_name = ''
                    is_noop = True

                playlist.entries.append(M3u8KeyEntry(
                    method=method,
                    uri=uri,
                    iv=iv,
                    is_noop=is_noop,
                    local_name=local_name,
                    raw_line=line,
                ))
                i += 1

            elif line.startswith('#EXT-X-MAP:'):
                uri_match = re.search(r'URI="([^"]+)"', line)
                uri = urljoin(base_url, uri_match.group(1)) if uri_match else ''
                local_name = f'download_{map_counter}.map'
                map_counter += 1

                playlist.entries.append(M3u8MapEntry(
                    uri=uri,
                    local_name=local_name,
                    raw_line=line,
                ))
                i += 1

            elif line.startswith('#EXTINF:'):
                # The segment URI is on the next non-empty line.
                j = i + 1
                while j < len(lines) and not lines[j]:
                    j += 1

                if j < len(lines):
                    seg_uri = urljoin(base_url, lines[j])
                    local_name = f'seg_{seg_counter}.mp4'
                    seg_counter += 1

                    playlist.entries.append(M3u8SegmentEntry(
                        extinf_line=line,
                        uri=seg_uri,
                        local_name=local_name,
                    ))
                    i = j + 1
                else:
                    # #EXTINF with no following URI — preserve as passthrough.
                    playlist.entries.append(M3u8PassthroughEntry(raw_line=line))
                    i += 1

            else:
                playlist.entries.append(M3u8PassthroughEntry(raw_line=line))
                i += 1

        return playlist

    def segments(self) -> list[M3u8SegmentEntry]:
        """Return all segment entries in playlist order."""
        return [e for e in self.entries if isinstance(e, M3u8SegmentEntry)]

    def key_entries(self) -> list[M3u8KeyEntry]:
        """Return all non-noop key entries (i.e. keys that have a file to fetch)."""
        return [e for e in self.entries if isinstance(e, M3u8KeyEntry) and not e.is_noop]

    def map_entries(self) -> list[M3u8MapEntry]:
        """Return all map (init segment) entries."""
        return [e for e in self.entries if isinstance(e, M3u8MapEntry)]

    def has_encryption(self) -> bool:
        """True if the playlist contains any active key or map entries.
        Used by the processor to decide whether to probe segment formats."""
        return bool(self.key_entries() or self.map_entries())

    def write(self, path: str) -> None:
        """
        Write the rewritten playlist to path.

        - M3u8KeyEntry    : tag line with the original URI replaced by local_name.
                            Noop keys (METHOD=NONE) are written verbatim.
        - M3u8MapEntry    : emits '#EXT-X-MAP:URI="<local_name>"'.
        - M3u8SegmentEntry: emits the #EXTINF line then effective_name.
                            Entries marked valid=False are omitted entirely.
        - M3u8PassthroughEntry: written verbatim.
        """
        with open(path, 'w') as f:
            for entry in self.entries:
                if isinstance(entry, M3u8KeyEntry):
                    if entry.is_noop or not entry.local_name:
                        f.write(entry.raw_line + '\n')
                    else:
                        f.write(entry.raw_line.replace(entry.uri, entry.local_name) + '\n')
                elif isinstance(entry, M3u8MapEntry):
                    f.write(f'#EXT-X-MAP:URI="{entry.local_name}"\n')
                elif isinstance(entry, M3u8SegmentEntry):
                    if entry.valid:
                        f.write(entry.extinf_line + '\n')
                        f.write(entry.effective_name + '\n')
                elif isinstance(entry, M3u8PassthroughEntry):
                    f.write(entry.raw_line + '\n')

