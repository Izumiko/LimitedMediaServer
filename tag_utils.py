from typing import Optional

def bits_csv_to_int(value: Optional[str]) -> int:
    """
    Convert a comma-separated list of bit positions (0-based) into an integer.

    - Empty/None -> 0
    - Invalid entries are ignored
    - Duplicate bit positions are harmless (bitwise OR)
    """
    if not value:
        return 0

    result = 0
    for part in value.split(","):
        part = part.strip()
        if not part:
            continue

        try:
            bit_pos = int(part)
        except ValueError:
            continue

        if bit_pos < 0:
            continue

        result |= (1 << bit_pos)

    return result

def calculate_tag_number(tag_string: str):
    tag_number = 0
    if len(tag_string) > 0:
        fast_tags = tag_string.split(',')
        for fast_tag in fast_tags:
            position = int(fast_tag)
            if 0 <= position <= 127:
                tag_number += (1 << position)
    return tag_number

class DCBitScanner128:
    """
    Divide-and-conquer bit scanner for 128-bit integers.

    Layers: 128 -> 64 -> 32 -> 16 -> 8 -> 4
    At size == 4 we perform a simple for-loop to test the 4 bits.
    Returns a list of 0-based bit positions (LSB == 0), in ascending order.
    """
    _MAX = 1 << 128

    def __init__(self):
        self._cache = {}  # n -> tuple(positions)
        # Precompute masks for sizes we use
        self._masks = {s: ((1 << s) - 1) for s in (4, 8, 16, 32, 64, 128)}

    def positions(self, n:int):
        # input validation
        if not isinstance(n, int):
            raise TypeError("n must be an int")
        if n < 0 or n >= self._MAX:
            raise ValueError("n must be in range 0 <= n < 2**128")
        if n == 0:
            return []

        # cache hit
        if n in self._cache:
            return list(self._cache[n])

        result = []
        # stack of (base, size). Start at full 128-bit block.
        stack = [(0, 128)]

        while stack:
            base, size = stack.pop()
            # extract the block value at this base/size
            block = (n >> base) & self._masks[size]
            if block == 0:
                continue

            if size == 4:
                # smallest layer: test each of the 4 bits with a simple loop
                for i in range(4):
                    if block & (1 << i):
                        result.append(base + i)
            else:
                # subdivide: push upper half then lower half so lower is popped first
                half = size // 2
                stack.append((base + half, half))  # upper half
                stack.append((base, half))  # lower half

        # cache and return a fresh list
        self._cache[n] = tuple(result)
        return result

if __name__ == '__main__':
    scaner = DCBitScanner128()
    print(scaner.positions(1 + 2 + 8))
    print(scaner.positions(16+32))