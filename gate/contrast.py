import colorsys


def _rgb(h: str) -> tuple[float, float, float]:
    h = h.lstrip("#")
    if len(h) == 3:  # ponytail: no rgb()/named colours; axe reports hex
        h = "".join(c * 2 for c in h)
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))


def _lum(h: str) -> float:
    r, g, b = (c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in _rgb(h))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def ratio(fg: str, bg: str) -> float:
    hi, lo = sorted((_lum(fg), _lum(bg)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def fix_fg(fg: str, bg: str, target: float) -> str:
    h, l, s = colorsys.rgb_to_hls(*_rgb(fg))
    step = 0.01 if ratio("#ffffff", bg) >= ratio("#000000", bg) else -0.01
    while True:
        l = min(1.0, max(0.0, l + step))
        new = "#%02x%02x%02x" % tuple(round(c * 255) for c in colorsys.hls_to_rgb(h, l, s))
        if ratio(new, bg) >= target or l in (0.0, 1.0):
            return new
