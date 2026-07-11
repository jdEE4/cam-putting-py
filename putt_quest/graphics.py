"""Rendering for Putt Quest — deliberately low-res.

Everything is drawn onto a small internal surface (default 384x216) and
scaled up with nearest-neighbor to the window, giving a crisp pixel-art
look now and a single knob (INTERNAL_W/H) to turn for HD art later. All
draw code works in green-space meters and converts through a camera, so
upscaling later requires no gameplay changes.
"""

from __future__ import annotations

import math
import random
from typing import Iterable, Tuple

import pygame

INTERNAL_W, INTERNAL_H = 384, 216
WINDOW_SCALE = 3                      # 384x216 -> 1152x648 window

# palette (keep it small on purpose)
GREEN_DARK = (34, 92, 41)
GREEN_LIGHT = (46, 116, 54)
GREEN_FRINGE = (28, 72, 34)
CUP = (18, 24, 18)
CUP_RIM = (230, 230, 220)
FLAG_POLE = (222, 222, 210)
FLAG = (214, 60, 46)
BALL_WHITE = (245, 245, 240)
BALL_SHADOW = (24, 60, 30)
AIM = (255, 214, 90)
TRAIL = (210, 235, 255)
HUD_BG = (12, 20, 14)
HUD_TEXT = (235, 235, 225)
HUD_DIM = (150, 160, 150)
ACCENT = (255, 214, 90)
BAD = (220, 90, 70)
GOOD = (120, 220, 120)


class Camera:
    """Maps green meters -> internal-surface pixels.

    Frames the region from just behind the ball start to just past the
    cup, hole running bottom -> top of the screen.
    """

    def __init__(self, hole_dist_m: float):
        self.margin = 0.6
        self.set_extent(hole_dist_m)

    def set_extent(self, hole_dist_m: float,
                   extra_pts: Iterable[Tuple[float, float]] = ()) -> None:
        ymin, ymax = -self.margin, hole_dist_m + self.margin
        half_w = max(1.2, 0.22 * hole_dist_m)
        for (px, py) in extra_pts:
            ymin = min(ymin, py - self.margin)
            ymax = max(ymax, py + self.margin)
            half_w = max(half_w, abs(px) + self.margin)
        self.ymin, self.ymax = ymin, ymax
        span_y = ymax - ymin
        span_x = 2 * half_w
        sy = (INTERNAL_H - 30) / span_y          # 30px reserved for HUD strip
        sx = INTERNAL_W / span_x
        self.scale = min(sx, sy)
        self.half_w = half_w

    def to_px(self, x_m: float, y_m: float) -> Tuple[int, int]:
        px = INTERNAL_W // 2 + int(round(x_m * self.scale))
        py = (INTERNAL_H - 22) - int(round((y_m - self.ymin) * self.scale))
        return px, py

    def m_to_px(self, meters: float) -> int:
        return max(1, int(round(meters * self.scale)))


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


# ----------------------------------------------------------------------
_mow_seed = random.Random(7)
_texture_cache: dict = {}


def draw_green(canvas: pygame.Surface, cam: Camera,
               break_pct: float, slope_pct: float) -> None:
    canvas.fill(GREEN_FRINGE)
    # mown stripes
    stripe_h = 14
    key = (canvas.get_size(), stripe_h)
    for i, ytop in enumerate(range(0, INTERNAL_H - 18, stripe_h)):
        col = GREEN_LIGHT if i % 2 == 0 else GREEN_DARK
        pygame.draw.rect(canvas, col, (6, ytop, INTERNAL_W - 12, stripe_h))
    # sprinkle of darker pixels for texture
    rnd = random.Random(42)
    for _ in range(220):
        x = rnd.randrange(6, INTERNAL_W - 6)
        y = rnd.randrange(0, INTERNAL_H - 20)
        canvas.set_at((x, y), GREEN_FRINGE)
    draw_slope_arrows(canvas, break_pct, slope_pct)


def draw_slope_arrows(canvas: pygame.Surface,
                      break_pct: float, slope_pct: float) -> None:
    """Faint arrows showing which way gravity pulls the ball."""
    mag = math.hypot(break_pct, slope_pct)
    if mag < 0.05:
        return
    # gravity direction in screen space: +break -> right, uphill -> ball
    # pulled down-screen (away from cup at top)
    ang = math.atan2(break_pct, -slope_pct)   # screen: x right, y down
    length = min(10, 4 + int(mag * 3))
    col = (255, 255, 255)
    step = 42
    for gx in range(28, INTERNAL_W - 20, step):
        for gy in range(24, INTERNAL_H - 40, step):
            x2 = gx + length * math.sin(ang)
            y2 = gy + length * math.cos(ang)
            _faint_line(canvas, (gx, gy), (x2, y2), col, alpha=34)
            _faint_arrowhead(canvas, (x2, y2), ang, col, alpha=34)


def _faint_line(canvas, p1, p2, col, alpha=40):
    tmp = pygame.Surface(canvas.get_size(), pygame.SRCALPHA)
    pygame.draw.line(tmp, (*col, alpha), p1, p2, 1)
    canvas.blit(tmp, (0, 0))


def _faint_arrowhead(canvas, tip, ang, col, alpha=40):
    tmp = pygame.Surface(canvas.get_size(), pygame.SRCALPHA)
    for da in (2.6, -2.6):
        x = tip[0] + 4 * math.sin(ang + da)
        y = tip[1] + 4 * math.cos(ang + da)
        pygame.draw.line(tmp, (*col, alpha), tip, (x, y), 1)
    canvas.blit(tmp, (0, 0))


def draw_cup(canvas: pygame.Surface, cam: Camera,
             hole_pos_m: Tuple[float, float]) -> None:
    px, py = cam.to_px(*hole_pos_m)
    r = max(2, cam.m_to_px(0.054))
    pygame.draw.circle(canvas, CUP_RIM, (px, py), r + 1)
    pygame.draw.circle(canvas, CUP, (px, py), r)
    # flagstick
    pygame.draw.line(canvas, FLAG_POLE, (px, py - 1), (px, py - 16), 1)
    pygame.draw.polygon(canvas, FLAG,
                        [(px + 1, py - 16), (px + 9, py - 13),
                         (px + 1, py - 10)])


def draw_ball(canvas: pygame.Surface, cam: Camera,
              pos_m: Tuple[float, float]) -> None:
    px, py = cam.to_px(*pos_m)
    r = max(1, cam.m_to_px(0.021))
    pygame.draw.circle(canvas, BALL_SHADOW, (px + 1, py + 1), r)
    pygame.draw.circle(canvas, BALL_WHITE, (px, py), r)


def draw_trail(canvas: pygame.Surface, cam: Camera,
               path_m: Iterable[Tuple[float, float]]) -> None:
    pts = [cam.to_px(x, y) for (x, y) in path_m]
    if len(pts) >= 2:
        pygame.draw.lines(canvas, TRAIL, False, pts, 1)


def draw_aim_line(canvas: pygame.Surface, cam: Camera,
                  ball_m: Tuple[float, float],
                  hole_m: Tuple[float, float]) -> None:
    p1 = cam.to_px(*ball_m)
    p2 = cam.to_px(*hole_m)
    # dashed line
    dx, dy = p2[0] - p1[0], p2[1] - p1[1]
    dist = max(1.0, math.hypot(dx, dy))
    n = int(dist // 6)
    for i in range(n):
        t0, t1 = i / n, (i + 0.5) / n
        a = (p1[0] + dx * t0, p1[1] + dy * t0)
        b = (p1[0] + dx * t1, p1[1] + dy * t1)
        _faint_line(canvas, a, b, AIM, alpha=90)


# ------------------------------- text --------------------------------
_font_cache: dict = {}


def _font(size: int) -> pygame.font.Font:
    if size not in _font_cache:
        _font_cache[size] = pygame.font.Font(None, size)
    return _font_cache[size]


def text(canvas: pygame.Surface, msg: str, x: int, y: int,
         color=HUD_TEXT, size: int = 12, center: bool = False) -> None:
    surf = _font(size).render(msg, False, color)
    if center:
        x -= surf.get_width() // 2
    canvas.blit(surf, (x, y))


def hud_bar(canvas: pygame.Surface) -> None:
    pygame.draw.rect(canvas, HUD_BG, (0, INTERNAL_H - 18, INTERNAL_W, 18))
    pygame.draw.line(canvas, (60, 80, 62),
                     (0, INTERNAL_H - 18), (INTERNAL_W, INTERNAL_H - 18), 1)
