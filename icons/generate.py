"""
Generate 22x22 PNG icons for the tray app.
Design: 5-bar audio equalizer — thematic for a transcription tool.

  idle       — bell-curve bars, steel blue  (#4A90D9)   calm / waiting
  processing — irregular tall bars, amber   (#F5A623)   active / lively
  error      — flat minimal bars, red       (#E74C3C)   signal lost / failed

No external dependencies — pure Python stdlib PNG writer.
"""
import struct
import zlib
from pathlib import Path

HERE = Path(__file__).parent

BAR_W  = 3   # bar width in pixels
GAP    = 1   # gap between bars
N_BARS = 5
SIZE   = 22
BOTTOM = SIZE - 3   # bottom edge row (2px margin at bottom)

# (color_rgb, bar_heights_from_bottom)
ICONS: dict[str, tuple[tuple[int, int, int], list[int]]] = {
    'idle.png': (
        (74, 144, 217),          # #4A90D9 steel blue
        [6, 10, 14, 10, 6],      # symmetric bell — resting
    ),
    'processing.png': (
        (245, 166, 35),          # #F5A623 amber
        [14, 7, 17, 5, 12],      # irregular — active
    ),
    'error.png': (
        (231, 76, 60),           # #E74C3C red
        [3, 3, 3, 3, 3],         # flatline — dead signal
    ),
}


def _png_bars(r: int, g: int, b: int, heights: list[int], size: int = SIZE) -> bytes:
    total_w = N_BARS * BAR_W + (N_BARS - 1) * GAP
    left = (size - total_w) // 2

    # RGBA pixel grid (transparent by default)
    px: list[list[tuple[int, int, int, int]]] = [
        [(0, 0, 0, 0)] * size for _ in range(size)
    ]

    for i, h in enumerate(heights):
        x0 = left + i * (BAR_W + GAP)
        bar_top    = BOTTOM - h + 1   # inclusive top row of filled area
        soft_top   = bar_top - 1      # anti-alias fringe row above bar

        for y in range(size):
            for x in range(x0, x0 + BAR_W):
                if y > BOTTOM:
                    continue
                if y >= bar_top:
                    px[y][x] = (r, g, b, 255)
                elif y == soft_top:
                    px[y][x] = (r, g, b, 90)

    rows: list[bytes] = []
    for row in px:
        raw = bytearray()
        for (pr, pg, pb, pa) in row:
            raw += bytes([pr, pg, pb, pa])
        rows.append(bytes([0]) + bytes(raw))

    compressed = zlib.compress(b''.join(rows), 9)

    def chunk(tag: bytes, data: bytes) -> bytes:
        body = tag + data
        return struct.pack('>I', len(data)) + body + struct.pack('>I', zlib.crc32(body) & 0xFFFFFFFF)

    ihdr = struct.pack('>IIBBBBB', size, size, 8, 6, 0, 0, 0)
    return (
        b'\x89PNG\r\n\x1a\n'
        + chunk(b'IHDR', ihdr)
        + chunk(b'IDAT', compressed)
        + chunk(b'IEND', b'')
    )


def generate(dest: Path = HERE) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    for name, ((r, g, b), heights) in ICONS.items():
        (dest / name).write_bytes(_png_bars(r, g, b, heights))
        print(f'  written {dest / name}')


if __name__ == '__main__':
    generate()
