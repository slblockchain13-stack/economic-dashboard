#!/usr/bin/env python3
"""Draw the app icon and write it in the formats each system needs. Standard library only.

    python3 tools/make_icons.py

Writes:
  Economic Dashboard.app/Contents/Resources/AppIcon.icns   Mac app icon
  icons/dashboard.ico                                       Windows desktop shortcut icon
  icons/dashboard.png                                       1024 px original

The picture: a business cycle (amber wave) rising around a long-term productivity trend (teal line),
with a dot marking "now", on a navy tile. Every size is drawn directly, not scaled down, so the small
sizes stay sharp.
"""
import math
import struct
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "Economic Dashboard.app"

TOP, BOTTOM = (22, 58, 104), (9, 26, 50)      # navy gradient
TREND = (79, 209, 197)                         # teal
WAVE = (245, 184, 74)                          # amber
DOT = (255, 255, 255)


X0, X1 = 0.22, 0.78                            # where the lines start and end
PERIOD, AMP = 0.34, 0.10                       # the cycle


def trend(x):
    return 0.66 - 0.30 * (x - X0) / (X1 - X0)


def wave(x):
    return trend(x) - AMP * math.sin(2 * math.pi * (x - X0) / PERIOD)


def rounded_rect_dist(px, py, inset, radius):
    """Signed distance to a rounded square filling [inset, 1-inset]; negative inside."""
    half = 0.5 - inset
    qx, qy = abs(px - 0.5) - half + radius, abs(py - 0.5) - half + radius
    out = math.hypot(max(qx, 0), max(qy, 0))
    return out + min(max(qx, qy), 0) - radius


def cover(d, px_size):
    """Anti-aliased coverage of a shape whose edge is at distance d (negative inside), in units."""
    return min(1.0, max(0.0, 0.5 - d / px_size))


def blend(dst, src, a):
    return tuple(dst[i] * (1 - a) + src[i] * a for i in range(3))


def line_dist(size, f, reach):
    """Distance (in units) from every pixel near the curve y=f(x), X0..X1, to the curve.
    The curve is walked in steps under half a pixel and each step updates the pixels around it."""
    far = 9.0
    dist = [[far] * size for _ in range(size)]
    px = 1.0 / size
    pts, x = [], X0
    while True:
        pts.append((x, f(x)))
        if x >= X1:
            break
        # step so the arc between samples stays under 0.4 px
        dy = abs(f(min(x + px, X1)) - f(x))
        x = min(X1, x + 0.4 * px / max(1.0, dy / px))
    r = int(reach * size) + 2
    for cx, cy in pts:
        ci, cj = int(cx * size), int(cy * size)
        for j in range(max(0, cj - r), min(size, cj + r + 1)):
            yy = (j + 0.5) * px - cy
            row = dist[j]
            for i in range(max(0, ci - r), min(size, ci + r + 1)):
                d = math.hypot((i + 0.5) * px - cx, yy)
                if d < row[i]:
                    row[i] = d
    return dist


def render(size, inset):
    """RGBA rows of the icon at size x size. inset: margin around the tile (Mac icons have one)."""
    px = 1.0 / size
    radius = 0.225 * (1 - 2 * inset)
    w_wave = 0.052 if size >= 64 else 0.075        # thicker lines when tiny so they stay visible
    w_trend = 0.026 if size >= 64 else 0.045
    d_wave = line_dist(size, wave, w_wave)
    d_trend = line_dist(size, trend, w_trend)
    dot_x, dot_y = X1, wave(X1)
    rows = []
    for j in range(size):
        y = (j + 0.5) * px
        bg = blend(TOP, BOTTOM, y)
        row = bytearray()
        for i in range(size):
            x = (i + 0.5) * px
            a = cover(rounded_rect_dist(x, y, inset, radius), px)
            if a == 0:
                row += b"\0\0\0\0"
                continue
            c = blend(bg, TREND, 0.85 * cover(d_trend[j][i] - w_trend / 2, px))
            c = blend(c, WAVE, cover(d_wave[j][i] - w_wave / 2, px))
            c = blend(c, DOT, cover(math.hypot(x - dot_x, y - dot_y) - 0.055, px))
            row += bytes((round(c[0]), round(c[1]), round(c[2]), round(255 * a)))
        rows.append(bytes(row))
    return rows


def png(rows):
    size = len(rows)
    raw = b"".join(b"\0" + r for r in rows)

    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def icns(pngs):
    """Mac .icns built from PNGs (supported since OS X 10.7)."""
    types = {16: b"icp4", 32: b"icp5", 64: b"icp6", 128: b"ic07", 256: b"ic08", 512: b"ic09", 1024: b"ic10"}
    body = b"".join(types[s] + struct.pack(">I", 8 + len(d)) + d for s, d in sorted(pngs.items()))
    return b"icns" + struct.pack(">I", 8 + len(body)) + body


def ico(pngs):
    """Windows .ico holding PNG images (supported since Windows Vista)."""
    sizes = sorted(pngs)
    head = struct.pack("<HHH", 0, 1, len(sizes))
    offset = 6 + 16 * len(sizes)
    entries, data = b"", b""
    for s in sizes:
        d = pngs[s]
        entries += struct.pack("<BBBBHHII", s % 256, s % 256, 0, 0, 1, 32, len(d), offset + len(data))
        data += d
    return head + entries + data


def main():
    mac = {s: png(render(s, 0.098)) for s in (16, 32, 64, 128, 256, 512, 1024)}   # Apple's grid: 824 of 1024
    win = {s: png(render(s, 0.03)) for s in (16, 24, 32, 48, 64, 256)}
    (ROOT / "icons").mkdir(exist_ok=True)
    (ROOT / "icons" / "dashboard.png").write_bytes(mac[1024])
    (ROOT / "icons" / "dashboard.ico").write_bytes(ico(win))
    res = APP / "Contents" / "Resources"
    res.mkdir(parents=True, exist_ok=True)
    (res / "AppIcon.icns").write_bytes(icns(mac))
    print("wrote icons/dashboard.png, icons/dashboard.ico, Economic Dashboard.app/Contents/Resources/AppIcon.icns")


if __name__ == "__main__":
    main()
