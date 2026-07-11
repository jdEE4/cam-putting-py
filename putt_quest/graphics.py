"""Window management + 2D UI helpers for Putt Quest.

The 3D scene lives in render3d.py; this module owns the window, the
internal canvas, text, and HUD panel primitives. Everything is drawn on
an internal 640x360 surface scaled up to the window, which keeps the
software renderer fast on machines without dedicated graphics.
"""

from __future__ import annotations

import pygame

INTERNAL_W, INTERNAL_H = 640, 360
WINDOW_SCALE = 2                      # 640x360 -> 1280x720 window

# UI palette
HUD_BG = (12, 20, 14)
HUD_PANEL = (16, 26, 19)
HUD_TEXT = (236, 238, 228)
HUD_DIM = (155, 168, 155)
ACCENT = (255, 214, 90)
BAD = (226, 92, 72)
GOOD = (120, 220, 120)
INFO = (140, 235, 255)


def make_screen() -> tuple[pygame.Surface, pygame.Surface]:
    win = pygame.display.set_mode((INTERNAL_W * WINDOW_SCALE,
                                   INTERNAL_H * WINDOW_SCALE),
                                  pygame.RESIZABLE)
    pygame.display.set_caption("Putt Quest — camera putting challenge")
    canvas = pygame.Surface((INTERNAL_W, INTERNAL_H))
    return win, canvas


def blit_scaled(win: pygame.Surface, canvas: pygame.Surface) -> None:
    ww, wh = win.get_size()
    s = max(1, min(ww // INTERNAL_W, wh // INTERNAL_H))
    scaled = pygame.transform.scale(canvas, (INTERNAL_W * s, INTERNAL_H * s))
    win.fill((0, 0, 0))
    win.blit(scaled, ((ww - scaled.get_width()) // 2,
                      (wh - scaled.get_height()) // 2))


# ------------------------------- text --------------------------------
_font_cache: dict = {}


def _font(size: int) -> pygame.font.Font:
    if size not in _font_cache:
        _font_cache[size] = pygame.font.Font(None, size)
    return _font_cache[size]


def text(canvas: pygame.Surface, msg: str, x: int, y: int,
         color=HUD_TEXT, size: int = 16, center: bool = False,
         shadow: bool = False) -> None:
    surf = _font(size).render(msg, True, color)
    if center:
        x -= surf.get_width() // 2
    if shadow:
        dark = _font(size).render(msg, True, (10, 14, 10))
        canvas.blit(dark, (x + 1, y + 1))
    canvas.blit(surf, (x, y))


def text_w(msg: str, size: int = 16) -> int:
    return _font(size).size(msg)[0]


# ------------------------------ panels -------------------------------
def panel(canvas: pygame.Surface, rect: pygame.Rect,
          alpha: int = 180, border: bool = True) -> None:
    """Semi-transparent rounded HUD panel."""
    tmp = pygame.Surface(rect.size, pygame.SRCALPHA)
    pygame.draw.rect(tmp, (*HUD_PANEL, alpha), tmp.get_rect(),
                     border_radius=6)
    if border:
        pygame.draw.rect(tmp, (90, 110, 92, min(255, alpha + 40)),
                         tmp.get_rect(), 1, border_radius=6)
    canvas.blit(tmp, rect.topleft)


def status_dot(canvas: pygame.Surface, x: int, y: int, color) -> None:
    pygame.draw.circle(canvas, color, (x, y), 4)
    pygame.draw.circle(canvas, (0, 0, 0), (x, y), 4, 1)
