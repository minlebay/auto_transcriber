"""
Tray icon: a short sound wave followed by what it turns into.

The right half carries the state, so states differ by shape and stay
readable in the single-color (monochrome) variant:

  idle       — wave + three text lines
  processing — wave + three dots (text is being written)
  error      — wave + a cross

The colored variant draws the same glyph in the per-state colors.
"""

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPalette, QPen, QPixmap
from PySide6.QtWidgets import QApplication

STATE_COLORS = {
    'idle':       '#4A90D9',   # blue
    'processing': '#F5A623',   # amber
    'error':      '#E74C3C',   # red
}

# Same glyph colors as the monochrome icons of minl.ai and voice2text, so all
# of them look alike in one panel.
MONO_COLORS = {
    'light': '#f5f5f5',   # light glyph for dark panels
    'dark':  '#1a1a1a',   # dark glyph for light panels
}

# Every size is drawn separately so the 16/22 px tray pixmaps stay crisp
# instead of being downscaled from a large one.
_SIZES = (16, 22, 24, 32, 48, 64, 128)

# Glyph geometry in a 64x64 design grid
_STROKE       = 7
_WAVE_X       = 3
_WAVE_GAP     = 4
_WAVE_HEIGHTS = (22, 46, 32)
_TEXT_X       = 39
_TEXT_LINES   = ((19, 22), (32, 22), (45, 14))   # (center y, length)


def detect_panel_variant() -> str:
    """Pick the monochrome glyph that contrasts with the current color scheme.

    Plasma applies its color scheme to Qt apps too, so a dark scheme means a
    light glyph and vice versa. Falls back to the palette's window color when
    the platform theme doesn't report a scheme.
    """
    app = QApplication.instance()
    scheme = app.styleHints().colorScheme()
    if scheme == Qt.ColorScheme.Dark:
        return 'light'
    if scheme == Qt.ColorScheme.Light:
        return 'dark'
    c = app.palette().color(QPalette.ColorRole.Window)
    luminance = 0.299 * c.red() + 0.587 * c.green() + 0.114 * c.blue()
    return 'dark' if luminance > 140 else 'light'


def make_tray_icon(state: str, monochrome: bool = False, mono_variant: str = 'auto') -> QIcon:
    if monochrome:
        if mono_variant not in MONO_COLORS:
            mono_variant = detect_panel_variant()
        color = MONO_COLORS[mono_variant]
    else:
        color = STATE_COLORS[state]

    icon = QIcon()
    for size in _SIZES:
        icon.addPixmap(_draw_glyph(size, state, color))
    return icon


def _draw_glyph(size: int, state: str, color: str) -> QPixmap:
    pix = QPixmap(size, size)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.scale(size / 64, size / 64)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(color))

    r = _STROKE / 2
    for i, h in enumerate(_WAVE_HEIGHTS):
        x = _WAVE_X + i * (_STROKE + _WAVE_GAP)
        p.drawRoundedRect(QRectF(x, 32 - h / 2, _STROKE, h), r, r)

    if state == 'processing':
        for dx in (0, 9.5, 19):
            p.drawEllipse(QPointF(_TEXT_X + 3.5 + dx, 32), 4, 4)
    elif state == 'error':
        pen = QPen(QColor(color), 7.5)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        c, d = QPointF(50, 32), 9
        p.drawLine(c + QPointF(-d, -d), c + QPointF(d, d))
        p.drawLine(c + QPointF(-d, d), c + QPointF(d, -d))
    else:
        for y, length in _TEXT_LINES:
            p.drawRoundedRect(QRectF(_TEXT_X, y - r, length, _STROKE), r, r)

    p.end()
    return pix
