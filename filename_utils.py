import os
import re
from typing import List, Tuple


def compress_filenames(filenames: List[str]) -> str:
    pattern = re.compile(r"^(\d+)\.(\w+)$")

    parsed = []
    for name in filenames:
        m = pattern.match(name)
        if not m:
            raise ValueError(f"Invalid filename format: {name}")
        num, ext = m.groups()
        parsed.append((int(num), num, ext))

    result = []
    i = 0

    while i < len(parsed):
        start_i = i
        start_num, start_raw, ext = parsed[i]
        width = len(start_raw)

        j = i + 1
        while (
                j < len(parsed)
                and parsed[j][0] == parsed[j - 1][0] + 1
                and parsed[j][2] == ext
                and len(parsed[j][1]) == width
        ):
            j += 1

        if j - i >= 2:
            end_num = parsed[j - 1][0]
            result.append(f"~{start_num:0{width}d}-{end_num:0{width}d}.{ext}")
        else:
            result.append(f"{start_raw}.{ext}")

        i = j

    return ",".join(result)


def decompress_filenames(compact: str) -> List[str]:
    range_pattern = re.compile(r"^~(\d+)-(\d+)\.(\w+)$")

    filenames = []

    for token in compact.split(","):
        token = token.strip()

        m = range_pattern.match(token)
        if m:
            start, end, ext = m.groups()
            start_i, end_i = int(start), int(end)
            width = len(start)

            for n in range(start_i, end_i + 1):
                filenames.append(f"{n:0{width}d}.{ext}")
        else:
            filenames.append(token)

    return filenames


FILENAME_RE = re.compile(r"^(\d+)\.(.+)$")


def renumber_filenames_for_compression(
        chapter_path: str
) -> Tuple[List[str], bool]:
    """
    Returns (new_filenames, changed)
    """

    files = sorted(os.listdir(chapter_path))

    parsed = []
    for name in files:
        m = FILENAME_RE.match(name)
        if not m:
            raise ValueError(f"Invalid filename format: {name}")
        num, ext = m.groups()
        parsed.append((int(num), ext))

    target_count = len(parsed)
    width = max(4, len(str(target_count)))

    new_files = [
        f"{i:0{width}d}.{ext}"
        for i, (_, ext) in enumerate(parsed, start=1)
    ]

    changed = new_files != files
    return new_files, changed


def apply_renaming(chapter_path: str, new_filenames: List[str]) -> None:
    old_files = sorted(os.listdir(chapter_path))

    if old_files == new_filenames:
        return

    temp_names = []
    for i, old in enumerate(old_files):
        tmp = f"__tmp__{i:04d}"
        os.rename(
            os.path.join(chapter_path, old),
            os.path.join(chapter_path, tmp)
        )
        temp_names.append(tmp)

    for tmp, final in zip(temp_names, new_filenames):
        os.rename(
            os.path.join(chapter_path, tmp),
            os.path.join(chapter_path, final)
        )


if __name__ == '__main__':
    demo_files = [
        "0001.webp", "0002.webp", "0003.webp",
        "0004.webp", "0005.webp",
        "0006.jpg",
        "0010.webp", "0011.webp"
    ]

    compressed = compress_filenames(demo_files)
    print(compressed)
    # ~0001-0005.webp,0006.jpg,~0010-0011.webp

    expanded = decompress_filenames(compressed)
    print(expanded == demo_files)
    # True
