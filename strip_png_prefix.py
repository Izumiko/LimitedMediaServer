import os
import sys
from pathlib import Path

from thread_utils import TaskWrapper

PNG_SIG = b"\x89PNG\r\n\x1a\n"
IEND = b"IEND\xaeB`\x82"


def strip_png_prefix(filepath):
    """
    If the file starts with a PNG and contains data after the PNG's IEND chunk,
    remove the PNG portion and overwrite the file with the remaining payload.

    Returns:
        (modified: bool, message: str)
    """
    filepath = Path(filepath)

    with open(filepath, "rb") as f:
        data = f.read()

    if not data.startswith(PNG_SIG):
        return False, "Not a PNG-prefixed file"

    iend_pos = data.find(IEND)
    if iend_pos == -1:
        return False, "PNG IEND chunk not found"

    png_end = iend_pos + len(IEND)

    if png_end >= len(data):
        return False, "No payload after PNG"

    payload = data[png_end:]

    with open(filepath, "wb") as f:
        f.write(payload)

    return (
        True,
        f"Removed {png_end} PNG bytes, kept {len(payload)} payload bytes",
    )


def strip_png_prefix_from_directory(directory, logger: TaskWrapper):
    """
    Recursively process all files under a directory.
    """
    directory = Path(directory)

    for path in directory.rglob("*"):
        if not path.is_file():
            continue

        try:
            modified, message = strip_png_prefix(path)

            if modified:
                logger.debug(f"[MODIFIED] {path}: {message}")

        except Exception as e:
            logger.error(f"[ERROR] {path}: {e}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <directory>")
        sys.exit(1)

    strip_png_prefix_from_directory(sys.argv[1])