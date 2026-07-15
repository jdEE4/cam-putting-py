"""Software 3D renderer for Putt Quest.

Pure-pygame perspective rendering — no OpenGL, no GPU, no new
dependencies — designed for machines with integrated graphics:

  * The heavy part (sky, hills, striped green mesh, fringe, rough, cup,
    slope arrows) is rendered ONCE into a cached background surface every
    time the camera moves (i.e. once per putt, not per frame).
  * Per frame we only blit that background and draw the cheap dynamic
    bits: ball, shadow, trail, aim line, waving flag, minimap.

World space (meters): +x right of the target line, +y from the ball's
start toward the cup, +z up. This matches physics.py exactly; the visual
surface height just exaggerates the hole's break/slope grades so a 2%
break is actually visible from behind the ball.
"""

from __future__ import annotations

import math
import random
from typing import Iterable, List, Optional, Sequence, Tuple

import pygame

Vec2 = Tuple[float, float]

# visual exaggeration of the (physically small) slope grades
Z_EXAG = 6.0
CUP_VISUAL_R = 0.085        # a touch bigger than regulation so it reads
BALL_VISUAL_R = 0.032
FLAG_HEIGHT = 1.85          # a bit under regulation; reads better up close

# ------------------------------- palette ------------------------------
SKY_TOP = (92, 148, 218)
SKY_HORIZON = (196, 219, 235)
SUN = (255, 246, 214)
CLOUD = (250, 252, 255)
HILL_FAR = (86, 128, 96)
HILL_NEAR = (60, 108, 72)
TREELINE = (38, 82, 52)
ROUGH = (34, 76, 38)
FRINGE = (56, 116, 50)
GREEN_A = (88, 158, 74)     # light mow stripe
GREEN_B = (74, 142, 64)     # dark mow stripe
HAZE = (170, 200, 210)
CUP_DARK = (16, 20, 14)
CUP_RIM = (235, 235, 225)
POLE = (232, 232, 222)
FLAG_RED = (222, 58, 44)
FLAG_RED_DK = (176, 40, 32)
BALL_WHITE = (250, 250, 246)
BALL_SHADE = (196, 200, 204)
SHADOW = (30, 62, 34)
AIM = (255, 216, 90)
PREVIEW = (140, 235, 255)
TRAIL = (235, 244, 252)
ARROW = (255, 255, 255)


def _clamp(v, lo, hi):
    return lo if v < lo else hi if v > hi else v


def _shade(col, f: float, toward=(255, 255, 255)) -> Tuple[int, int, int]:
    """f in [-1..1]: negative darkens toward black, positive lerps toward
    `toward` (used for distance haze)."""
    if f >= 0:
        return tuple(int(c + (t - c) * min(1.0, f))
                     for c, t in zip(col, toward))
    f = max(-1.0, f)
    return tuple(int(c * (1.0 + f)) for c in col)


class Camera3D:
    """Simple look-at perspective camera projecting onto a pygame surface."""

    def __init__(self, size: Tuple[int, int], fov_deg: float = 56.0):
        self.w, self.h = size
        self.fl = 0.5 * self.h / math.tan(math.radians(fov_deg) / 2)
        self.eye = (0.0, -3.0, 2.0)
        self.fwd = (0.0, 1.0, 0.0)
        self.right = (1.0, 0.0, 0.0)
        self.up = (0.0, 0.0, 1.0)

    def look(self, eye: Sequence[float], target: Sequence[float]) -> None:
        self.eye = tuple(eye)
        f = [t - e for t, e in zip(target, eye)]
        fl = math.sqrt(sum(c * c for c in f)) or 1.0
        f = [c / fl for c in f]
        # right = f x world_up   (world up = +z)
        r = [f[1], -f[0], 0.0]
        rl = math.sqrt(sum(c * c for c in r)) or 1.0
        r = [c / rl for c in r]
        # up = r x f
        u = [r[1] * f[2] - r[2] * f[1],
             r[2] * f[0] - r[0] * f[2],
             r[0] * f[1] - r[1] * f[0]]
        self.fwd, self.right, self.up = tuple(f), tuple(r), tuple(u)

    def project(self, p: Sequence[float]) -> Optional[Tuple[float, float, float]]:
        """world point -> (screen_x, screen_y, depth); None if behind cam."""
        d = (p[0] - self.eye[0], p[1] - self.eye[1], p[2] - self.eye[2])
        depth = d[0] * self.fwd[0] + d[1] * self.fwd[1] + d[2] * self.fwd[2]
        if depth < 0.08:
            return None
        x = d[0] * self.right[0] + d[1] * self.right[1] + d[2] * self.right[2]
        y = d[0] * self.up[0] + d[1] * self.up[1] + d[2] * self.up[2]
        s = self.fl / depth
        return (self.w / 2 + x * s, self.h / 2 - y * s, depth)

    def scale_at(self, depth: float) -> float:
        """pixels per meter at a given depth."""
        return self.fl / max(depth, 0.08)


class GreenScene:
    """Renders one hole. Call position_camera() whenever the ball comes to
    rest (it re-renders the cached background); call draw() every frame."""

    def __init__(self, size: Tuple[int, int], hole_dist_m: float,
                 break_pct: float, slope_pct: float):
        self.size = size
        self.dist = hole_dist_m
        self.break_pct = break_pct
        self.slope_pct = slope_pct
        self.cup = (0.0, hole_dist_m)
        self.cam = Camera3D(size)
        self.bg: Optional[pygame.Surface] = None
        self.green_half_w = max(2.2, 0.26 * hole_dist_m + 1.0)
        self.green_len_pad = 2.2
        self._rnd = random.Random(int(hole_dist_m * 100) ^ 1234)

    # ----------------------------------------------------------- terrain
    def height(self, x: float, y: float) -> float:
        """Visually exaggerated surface height matching the physics tilt:
        +break pushes the ball right => ground falls toward +x;
        +slope is uphill toward the cup => ground rises with +y."""
        return Z_EXAG * ((self.slope_pct / 100.0) * y
                         - (self.break_pct / 100.0) * x)

    def surface_pt(self, x: float, y: float, lift: float = 0.0):
        return (x, y, self.height(x, y) + lift)

    def _green_zone(self, x: float, y: float) -> str:
        """'green' | 'fringe' | 'rough' via a rounded superellipse pad."""
        cy = self.dist / 2.0
        ry = self.dist / 2.0 + self.green_len_pad
        rx = self.green_half_w
        v = (abs(x) / rx) ** 4 + (abs(y - cy) / ry) ** 4
        if v <= 1.0:
            return "green"
        if v <= 1.7:
            return "fringe"
        return "rough"

    # ------------------------------------------------------------ camera
    def position_camera(self, ball_pos: Vec2) -> None:
        bx, by = ball_pos
        dx, dy = self.cup[0] - bx, self.cup[1] - by
        rem = math.hypot(dx, dy)
        if rem < 0.3:               # about to hole out: look up the line
            dx, dy, rem = 0.0, 1.0, max(rem, 0.3)
        else:
            dx, dy = dx / rem, dy / rem
        back = _clamp(2.0 + 0.18 * rem, 2.2, 5.0)
        h = _clamp(1.25 + 0.11 * rem, 1.45, 3.4)
        eye = (bx - dx * back, by - dy * back,
               self.height(bx - dx * back, by - dy * back) + h)
        t = 0.55 * rem
        target = (bx + dx * t, by + dy * t,
                  self.height(bx + dx * t, by + dy * t))
        self.cam.look(eye, target)
        self._render_bg()

    # -------------------------------------------------------- background
    def _render_bg(self) -> None:
        w, h = self.size
        bg = pygame.Surface(self.size)
        self._draw_sky(bg)
        self._draw_ground(bg)
        self._draw_slope_arrows(bg)
        self._draw_cup(bg)
        self.bg = bg

    def _horizon_y(self) -> int:
        fx, fy, _ = self.cam.fwd
        n = math.hypot(fx, fy) or 1.0
        far = (self.cam.eye[0] + fx / n * 800.0,
               self.cam.eye[1] + fy / n * 800.0, 0.0)
        p = self.cam.project(far)
        return int(p[1]) if p else self.size[1] // 3

    def _draw_sky(self, bg: pygame.Surface) -> None:
        w, h = self.size
        hy = _clamp(self._horizon_y(), h // 6, h - 20)
        for y in range(0, hy + 1):
            t = y / max(1, hy)
            col = tuple(int(a + (b - a) * t)
                        for a, b in zip(SKY_TOP, SKY_HORIZON))
            pygame.draw.line(bg, col, (0, y), (w, y))
        # soft sun
        sun = pygame.Surface((120, 120), pygame.SRCALPHA)
        for r, a in ((56, 26), (40, 40), (22, 110)):
            pygame.draw.circle(sun, (*SUN, a), (60, 60), r)
        bg.blit(sun, (int(w * 0.72) - 60, int(hy * 0.32) - 60))
        # clouds
        rnd = random.Random(9)
        for _ in range(5):
            cx = rnd.randint(0, w)
            cy = rnd.randint(int(hy * 0.12), int(hy * 0.6))
            cw = rnd.randint(40, 90)
            cloud = pygame.Surface((cw * 2, cw), pygame.SRCALPHA)
            for i in range(4):
                ex = rnd.randint(0, cw)
                ew = rnd.randint(cw // 2, cw)
                pygame.draw.ellipse(cloud, (*CLOUD, 60),
                                    (ex, cw // 3 + rnd.randint(-4, 4),
                                     ew, cw // 3))
            bg.blit(cloud, (cx - cw, cy - cw // 2))
        # hills + treeline hugging the horizon, then ground haze below
        rnd = random.Random(4)
        for base, col, amp in ((hy + 2, HILL_FAR, 14), (hy + 4, HILL_NEAR, 9)):
            pts = [(0, base + 22)]
            x = 0
            while x <= w:
                pts.append((x, base - rnd.randint(2, amp)))
                x += rnd.randint(40, 90)
            pts += [(w, base + 22)]
            pygame.draw.polygon(bg, col, pts)
        pygame.draw.rect(bg, TREELINE, (0, hy + 2, w, 6))
        pygame.draw.rect(bg, ROUGH, (0, hy + 6, w, h - hy))

    def _draw_ground(self, bg: pygame.Surface) -> None:
        cam = self.cam
        half_w = self.green_half_w + 7.0
        y0 = min(cam.eye[1], 0.0) - 4.0
        y1 = self.dist + self.green_len_pad + 9.0
        cols = 30
        rows = 40
        dxs = 2 * half_w / cols
        dys = (y1 - y0) / rows
        stripe_w = _clamp(self.dist / 7.0, 0.9, 2.2)
        fog_far = max(12.0, (y1 - cam.eye[1]) * 1.1)

        def base_color(mx: float, my: float):
            zone = self._green_zone(mx, my)
            if zone == "green":
                return GREEN_A if int(my // stripe_w) % 2 == 0 else GREEN_B
            return FRINGE if zone == "fringe" else ROUGH

        def draw_quad(xa, xb, ya, yb, noise):
            quad = []
            depth_sum = 0.0
            for (x, y) in ((xa, ya), (xb, ya), (xb, yb), (xa, yb)):
                p = cam.project(self.surface_pt(x, y))
                if p is None:
                    return
                quad.append((p[0], p[1]))
                depth_sum += p[2]
            if (max(q[0] for q in quad) < -4
                    or min(q[0] for q in quad) > self.size[0] + 4
                    or max(q[1] for q in quad) < -4
                    or min(q[1] for q in quad) > self.size[1] + 4):
                return
            col = base_color((xa + xb) / 2, (ya + yb) / 2)
            # cheap texture + aerial haze with distance
            fog = min(0.32, 0.40 * (depth_sum / 4) / fog_far)
            col = _shade(_shade(col, noise), fog, HAZE)
            pygame.draw.polygon(bg, col, quad)

        # painter's algorithm: far rows first (camera looks toward +y)
        for iy in range(rows - 1, -1, -1):
            ya, yb = y0 + iy * dys, y0 + (iy + 1) * dys
            for ix in range(cols):
                xa, xb = -half_w + ix * dxs, -half_w + (ix + 1) * dxs
                n = (((ix * 928371 + iy * 123457)
                      ^ (ix * iy * 26543 + 977)) % 13 - 6) * 0.004
                zones = {self._green_zone(x, y)
                         for x in (xa, xb, (xa + xb) / 2)
                         for y in (ya, yb, (ya + yb) / 2)}
                if len(zones) == 1:
                    draw_quad(xa, xb, ya, yb, n)
                else:
                    # zone boundary crosses this cell: subdivide 3x3 so
                    # the green's curved edge stays smooth
                    for sy in range(3):
                        for sx in range(3):
                            draw_quad(xa + sx * dxs / 3,
                                      xa + (sx + 1) * dxs / 3,
                                      ya + sy * dys / 3,
                                      ya + (sy + 1) * dys / 3, n)

    def _draw_slope_arrows(self, bg: pygame.Surface) -> None:
        mag = math.hypot(self.break_pct, self.slope_pct)
        if mag < 0.05:
            return
        # downhill direction in world space
        vx, vy = self.break_pct / mag, -self.slope_pct / mag
        alen = 0.28 + 0.06 * min(mag, 4.0)
        tmp = pygame.Surface(self.size, pygame.SRCALPHA)
        ny = max(3, int(self.dist / 2.2))
        for iy in range(ny):
            y = (iy + 0.5) * (self.dist / ny)
            for fx in (-0.55, 0.0, 0.55):
                x = fx * self.green_half_w
                if self._green_zone(x, y) != "green":
                    continue
                a = self.cam.project(self.surface_pt(x, y, 0.01))
                b = self.cam.project(self.surface_pt(x + vx * alen,
                                                     y + vy * alen, 0.01))
                if not a or not b:
                    continue
                pygame.draw.line(tmp, (*ARROW, 60), a[:2], b[:2], 1)
                ang = math.atan2(b[1] - a[1], b[0] - a[0])
                for da in (2.5, -2.5):
                    hx = b[0] + 5 * math.cos(ang + da)
                    hy = b[1] + 5 * math.sin(ang + da)
                    pygame.draw.line(tmp, (*ARROW, 60), b[:2], (hx, hy), 1)
        bg.blit(tmp, (0, 0))

    def _draw_cup(self, bg: pygame.Surface) -> None:
        cx, cy = self.cup
        rim, hole = [], []
        for i in range(20):
            a = 2 * math.pi * i / 20
            x = cx + CUP_VISUAL_R * math.cos(a)
            y = cy + CUP_VISUAL_R * math.sin(a)
            p = self.cam.project(self.surface_pt(x, y, 0.004))
            if p is None:
                return
            hole.append((p[0], p[1]))
        pygame.draw.polygon(bg, CUP_DARK, hole)
        pygame.draw.aalines(bg, CUP_RIM, True, hole)

    # ----------------------------------------------------- dynamic layer
    def draw(self, canvas: pygame.Surface, ball_pos: Optional[Vec2],
             trail: Sequence[Vec2] = (), t: float = 0.0,
             aim: Optional[Tuple[Vec2, float]] = None,
             preview: Sequence[Vec2] = ()) -> None:
        """aim: (from_pos, hla_deg) draws the dashed aim line.
        preview: optional simulated path (test mode ghost)."""
        if self.bg is None:
            self.position_camera(ball_pos or (0.0, 0.0))
        canvas.blit(self.bg, (0, 0))
        if aim is not None:
            self._draw_aim(canvas, aim[0], aim[1])
        if preview:
            self._draw_path(canvas, preview, PREVIEW, dashed=True)
        if len(trail) > 1:
            self._draw_path(canvas, trail, TRAIL)
        self._draw_flag(canvas, t)
        if ball_pos is not None:
            self._draw_ball(canvas, ball_pos)

    def _draw_path(self, canvas, path: Sequence[Vec2], color,
                   dashed: bool = False) -> None:
        pts = []
        for (x, y) in path:
            p = self.cam.project(self.surface_pt(x, y, 0.02))
            if p:
                pts.append((p[0], p[1]))
        if len(pts) < 2:
            return
        if dashed:
            for i in range(0, len(pts) - 1, 3):
                pygame.draw.line(canvas, color, pts[i], pts[i + 1], 1)
        else:
            pygame.draw.aalines(canvas, color, False, pts)

    def _draw_aim(self, canvas, ball: Vec2, hla_deg: float) -> None:
        bx, by = ball
        dx, dy = self.cup[0] - bx, self.cup[1] - by
        d = math.hypot(dx, dy)
        if d < 0.2:
            return
        base = math.atan2(dx, dy) + math.radians(hla_deg)
        ux, uy = math.sin(base), math.cos(base)
        step = 0.30
        n = int(d / step)
        for i in range(n):
            s0, s1 = i * step, i * step + 0.16
            a = self.cam.project(self.surface_pt(bx + ux * s0,
                                                 by + uy * s0, 0.015))
            b = self.cam.project(self.surface_pt(bx + ux * s1,
                                                 by + uy * s1, 0.015))
            if a and b:
                pygame.draw.line(canvas, AIM, a[:2], b[:2], 1)

    def _draw_flag(self, canvas, t: float) -> None:
        base = self.cam.project(self.surface_pt(*self.cup, lift=0.0))
        top = self.cam.project((self.cup[0], self.cup[1],
                                self.height(*self.cup) + FLAG_HEIGHT))
        if not base or not top:
            return
        w = max(1, int(self.cam.scale_at(base[2]) * 0.018))
        pygame.draw.line(canvas, (90, 100, 90),
                         (base[0] + 1, base[1] + 1), (top[0] + 1, top[1] + 1), w)
        pygame.draw.line(canvas, POLE, base[:2], top[:2], w)
        # waving cloth: three world-space columns rippling in z
        fw, fh = 0.62, 0.38
        cols = []
        for i, fx in enumerate((0.0, 0.5, 1.0)):
            wave = 0.05 * math.sin(t * 4.0 + fx * 3.0) * fx
            x = self.cup[0] + fw * fx
            z0 = self.height(*self.cup) + FLAG_HEIGHT + wave
            hi = self.cam.project((x, self.cup[1], z0))
            lo = self.cam.project((x, self.cup[1], z0 - fh * (1 - 0.25 * fx)))
            if not hi or not lo:
                return
            cols.append((hi[:2], lo[:2]))
        for i, col in ((0, FLAG_RED), (1, FLAG_RED_DK)):
            quad = [cols[i][0], cols[i + 1][0], cols[i + 1][1], cols[i][1]]
            pygame.draw.polygon(canvas, col, quad)
        pygame.draw.circle(canvas, CUP_RIM,
                           (int(top[0]), int(top[1])), max(1, w))

    def _draw_ball(self, canvas, pos: Vec2) -> None:
        x, y = pos
        p = self.cam.project(self.surface_pt(x, y, BALL_VISUAL_R))
        if p is None:
            return
        r = max(3, int(self.cam.scale_at(p[2]) * BALL_VISUAL_R))
        sh = self.cam.project(self.surface_pt(x, y, 0.004))
        if sh:
            shadow = pygame.Surface((r * 3, r * 2), pygame.SRCALPHA)
            pygame.draw.ellipse(shadow, (*SHADOW, 110),
                                (0, 0, r * 3, max(2, r)))
            canvas.blit(shadow, (sh[0] - r * 1.2, sh[1] - r * 0.4))
        cx, cy = int(p[0]), int(p[1])
        pygame.draw.circle(canvas, BALL_SHADE, (cx, cy), r)
        pygame.draw.circle(canvas, BALL_WHITE,
                           (cx - max(1, r // 4), cy - max(1, r // 4)),
                           max(1, r - max(1, r // 3)))
        if r >= 4:
            pygame.draw.circle(canvas, (255, 255, 255),
                               (cx - r // 3, cy - r // 3), max(1, r // 4))

    # ------------------------------------------------------------ minimap
    def draw_minimap(self, canvas: pygame.Surface, rect: pygame.Rect,
                     ball_pos: Optional[Vec2], trail: Sequence[Vec2] = ()) -> None:
        """Top-down overview panel (the old 2D view, miniaturized)."""
        panel = pygame.Surface(rect.size, pygame.SRCALPHA)
        panel.fill((10, 18, 12, 175))
        pad = 7
        span_y = self.dist + 3.0
        span_x = 2 * (self.green_half_w + 1.0)
        s = min((rect.h - 2 * pad) / span_y, (rect.w - 2 * pad) / span_x)

        def to_px(x: float, y: float) -> Tuple[int, int]:
            return (int(rect.w / 2 + x * s),
                    int(rect.h - pad - (y + 1.2) * s))

        stripe_w = _clamp(self.dist / 7.0, 0.9, 2.2)
        cy = self.dist / 2.0
        ry = self.dist / 2.0 + self.green_len_pad
        for py in range(pad, rect.h - pad):
            yy = (rect.h - pad - py) / s - 1.2
            v = (abs(yy - cy) / ry) ** 4
            if v >= 1.7:
                continue
            hw_f = self.green_half_w * (1.7 - min(v, 1.7)) ** 0.25 * 0.88
            x0f, x1f = rect.w / 2 - hw_f * s, rect.w / 2 + hw_f * s
            pygame.draw.line(panel, FRINGE, (x0f, py), (x1f, py))
            if v < 1.0:
                hw = self.green_half_w * (1.0 - v) ** 0.25
                col = GREEN_A if int(yy // stripe_w) % 2 == 0 else GREEN_B
                pygame.draw.line(panel, col,
                                 (rect.w / 2 - hw * s, py),
                                 (rect.w / 2 + hw * s, py))
        cp = to_px(*self.cup)
        pygame.draw.circle(panel, CUP_DARK, cp, max(2, int(s * CUP_VISUAL_R) + 1))
        pygame.draw.circle(panel, FLAG_RED, (cp[0] + 2, cp[1] - 3), 2)
        pygame.draw.line(panel, POLE, cp, (cp[0] + 2, cp[1] - 3), 1)
        if len(trail) > 1:
            pts = [to_px(x, y) for (x, y) in trail]
            pygame.draw.lines(panel, TRAIL, False, pts, 1)
        if ball_pos is not None:
            bp = to_px(*ball_pos)
            pygame.draw.circle(panel, BALL_WHITE, bp, 2)
        pygame.draw.rect(panel, (200, 210, 200, 90),
                         panel.get_rect(), 1, border_radius=4)
        canvas.blit(panel, rect.topleft)
