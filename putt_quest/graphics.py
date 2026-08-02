"""Window management + 2D UI helpers for Putt Quest.

The 3D scene lives in render3d.py; this module owns the window, the
internal render canvas, text, and HUD panel primitives.

Resolution model
----------------
The window is a fixed, resizable frame (default 1280x720). The game
renders onto an *internal* canvas whose size is one of RES_PRESETS; that
canvas is smooth-scaled to fit the window each frame. Raising the preset
makes the 3D scene sharper at a higher CPU cost — nothing else changes,
so it's safe to switch live. All HUD sizes/offsets are expressed in a
360px-tall "design space" and scaled by `ui()` so the interface stays
proportional at every preset.
"""

from __future__ import annotations

from typing import List, Tuple

import pygame

# (label, internal_w, internal_h) — ascending cost
RES_PRESETS: List[Tuple[str, int, int]] = [
    ("Low", 640, 360),
    ("Medium", 960, 540),
    ("High", 1280, 720),
    ("Ultra", 1600, 900),
]
BASE_H = 360                          # design-space height for UI scaling

# active internal resolution (mutated by set_internal)
INTERNAL_W, INTERNAL_H = 640, 360

# physical window (fixed; user-resizable)
WINDOW_W, WINDOW_H = 1280, 720

# UI palette
HUD_BG = (12, 20, 14)
HUD_PANEL = (16, 26, 19)
HUD_TEXT = (236, 238, 228)
HUD_DIM = (155, 168, 155)
ACCENT = (255, 214, 90)
BAD = (226, 92, 72)
GOOD = (120, 220, 120)
INFO = (140, 235, 255)
WARN = (255, 176, 64)


def ui() -> float:
    """Design-space -> current-canvas scale factor."""
    return INTERNAL_H / BASE_H


def sc(v: float) -> int:
    """Scale a design-space pixel length to the current canvas."""
    return int(round(v * ui()))


def make_screen() -> tuple[pygame.Surface, pygame.Surface]:
    win = pygame.display.set_mode((WINDOW_W, WINDOW_H), pygame.RESIZABLE)
    pygame.display.set_caption("Putt Quest — camera putting challenge")
    canvas = pygame.Surface((INTERNAL_W, INTERNAL_H))
    return win, canvas


def set_internal(w: int, h: int) -> pygame.Surface:
    """Switch the internal render resolution; returns a fresh canvas."""
    global INTERNAL_W, INTERNAL_H
    INTERNAL_W, INTERNAL_H = w, h
    return pygame.Surface((w, h))


def blit_scaled(win: pygame.Surface, canvas: pygame.Surface,
                offset: Tuple[int, int] = (0, 0)) -> None:
    """Smooth-fit the canvas into the window, preserving aspect ratio.
    `offset` shifts the blit a few pixels (screen-shake effect)."""
    ww, wh = win.get_size()
    iw, ih = canvas.get_size()
    scale = min(ww / iw, wh / ih)
    dw, dh = max(1, int(iw * scale)), max(1, int(ih * scale))
    scaled = pygame.transform.smoothscale(canvas, (dw, dh))
    win.fill((0, 0, 0))
    win.blit(scaled, ((ww - dw) // 2 + offset[0],
                      (wh - dh) // 2 + offset[1]))


# ------------------------------- text --------------------------------
_font_cache: dict = {}


def _font(size: int) -> pygame.font.Font:
    if size not in _font_cache:
        _font_cache[size] = pygame.font.Font(None, size)
    return _font_cache[size]


def _real_size(size: int) -> int:
    return max(8, int(round(size * ui())))


def text(canvas: pygame.Surface, msg: str, x: int, y: int,
         color=HUD_TEXT, size: int = 16, center: bool = False,
         shadow: bool = False) -> None:
    """`size` is design-space; it is scaled to the active canvas."""
    f = _font(_real_size(size))
    surf = f.render(msg, True, color)
    if center:
        x -= surf.get_width() // 2
    if shadow:
        dark = f.render(msg, True, (10, 14, 10))
        canvas.blit(dark, (x + 1, y + 1))
    canvas.blit(surf, (x, y))


def text_w(msg: str, size: int = 16) -> int:
    return _font(_real_size(size)).size(msg)[0]


# ------------------------------ panels -------------------------------
def panel(canvas: pygame.Surface, rect: pygame.Rect,
          alpha: int = 180, border: bool = True) -> None:
    """Semi-transparent rounded HUD panel."""
    tmp = pygame.Surface(rect.size, pygame.SRCALPHA)
    pygame.draw.rect(tmp, (*HUD_PANEL, alpha), tmp.get_rect(),
                     border_radius=sc(6))
    if border:
        pygame.draw.rect(tmp, (90, 110, 92, min(255, alpha + 40)),
                         tmp.get_rect(), 1, border_radius=sc(6))
    canvas.blit(tmp, rect.topleft)


def status_dot(canvas: pygame.Surface, x: int, y: int, color,
               r: int = 4) -> None:
    r = sc(r)
    pygame.draw.circle(canvas, color, (x, y), r)
    pygame.draw.circle(canvas, (0, 0, 0), (x, y), r, 1)


def progress_bar(canvas: pygame.Surface, rect: pygame.Rect,
                 frac: float, color, bg=(40, 48, 42)) -> None:
    frac = max(0.0, min(1.0, frac))
    pygame.draw.rect(canvas, bg, rect, border_radius=sc(3))
    if frac > 0:
        fill = pygame.Rect(rect.x, rect.y, int(rect.w * frac), rect.h)
        pygame.draw.rect(canvas, color, fill, border_radius=sc(3))
    pygame.draw.rect(canvas, (90, 110, 92), rect, 1, border_radius=sc(3))
