"""截图去留白：裁掉上下左右近背景色空白，只保留有实质内容的区域。"""
from __future__ import annotations

import io
from collections import Counter


def trim_bottom_whitespace(png: bytes, *, pad: int = 16, tol: int = 18,
                           min_hits: int = 4) -> tuple[bytes, int, int]:
    """兼容旧名：实际做四边裁切。"""
    return trim_whitespace(png, pad=pad, tol=tol, min_hits=min_hits)


def trim_image(im, *, pad: int = 16, tol: int = 18, min_hits: int = 4):
    """对已打开的 RGB/兼容图做四边裁切，返回裁后 Image（可能是原对象）。"""
    from PIL import Image

    if im.mode != "RGB":
        im = im.convert("RGB")
    w, h = im.size
    if w < 8 or h < 8:
        return im
    px = im.load()
    x_step = max(1, w // 240)
    y_step = max(1, h // 240)
    col_samples = max(1, (h + y_step - 1) // y_step)

    samples = []
    for y in (0, 1, h - 2, h - 1, max(0, int(h * 0.97))):
        for x in range(0, w, x_step * 3):
            samples.append(px[x, y])
    for x in (0, 1, w - 2, w - 1):
        for y in range(0, h, y_step * 3):
            samples.append(px[x, y])
    bg = Counter(samples).most_common(1)[0][0] if samples else (255, 255, 255)

    def is_fg(p) -> bool:
        return max(abs(p[0] - bg[0]), abs(p[1] - bg[1]), abs(p[2] - bg[2])) > tol

    def row_hits(y: int) -> int:
        return sum(1 for x in range(0, w, x_step) if is_fg(px[x, y]))

    def col_hits(x: int) -> int:
        return sum(1 for y in range(0, h, y_step) if is_fg(px[x, y]))

    # 粗扫再精修，避免 6000px 高图逐行全量扫描
    coarse = max(8, y_step)
    top_c = next((y for y in range(0, h, coarse) if row_hits(y) >= min_hits), 0)
    top = next((y for y in range(max(0, top_c - coarse), h) if row_hits(y) >= min_hits), top_c)
    bottom_c = next((y for y in range(h - 1, -1, -coarse) if row_hits(y) >= min_hits), h - 1)
    bottom = next((y for y in range(min(h - 1, bottom_c + coarse), -1, -1) if row_hits(y) >= min_hits), bottom_c)
    if bottom - top < 32:
        return im

    def solid_col(x: int) -> bool:
        hits = col_hits(x)
        if hits < min_hits:
            return False
        left_n = col_hits(x - 4) if x - 4 >= 0 else 0
        right_n = col_hits(x + 4) if x + 4 < w else 0
        dens = hits / col_samples
        if dens >= 0.40 and left_n < min_hits and right_n < min_hits:
            return False
        return True

    left = next((x for x in range(w) if solid_col(x)), 0)
    right = next((x for x in range(w - 1, -1, -1) if solid_col(x)), w - 1)
    if right - left < 32:
        left, right = 0, w - 1

    box = (
        max(0, left - pad),
        max(0, top - pad),
        min(w, right + 1 + pad),
        min(h, bottom + 1 + pad),
    )
    if box[0] <= 2 and box[1] <= 2 and box[2] >= w - 2 and box[3] >= int(h * 0.98):
        return im
    return im.crop(box)


def trim_whitespace(png: bytes, *, pad: int = 16, tol: int = 18,
                    min_hits: int = 4) -> tuple[bytes, int, int]:
    """按背景色裁掉四周留白（门户浅灰底 + 白边），忽略竖向滚动条细线。"""
    if not png:
        return png, 0, 0
    from PIL import Image

    im = Image.open(io.BytesIO(png))
    out = trim_image(im, pad=pad, tol=tol, min_hits=min_hits)
    if out.size == im.size and out is im:
        return png, im.size[0], im.size[1]
    buf = io.BytesIO()
    out.save(buf, "PNG", optimize=False, compress_level=6)
    return buf.getvalue(), out.width, out.height
