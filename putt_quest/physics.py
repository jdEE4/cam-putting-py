"""Rolling-ball physics for Putt Quest.

Coordinate system (meters, top-down):
    +y = toward the hole along the original target line
    +x = to the right of the target line
The ball starts each HOLE at (0, 0); the cup is at (0, distance).
Subsequent putts on the same hole start from wherever the ball stopped,
still aimed at the cup (HLA 0 from the camera = straight at the cup).

Friction model: a ball leaving a stimpmeter at 1.83 m/s rolls `stimp`
feet, so constant deceleration a = v0^2 / (2 * stimp_ft * 0.3048).
Stimp 10 => ~0.55 m/s^2, which matches real green behavior well.

Slope model: a grade of s% adds gravity acceleration g * s/100 in the
downhill direction. Each hole defines break (x) and slope (y) grades.

Hole capture: the ball drops if it crosses the cup within an effective
radius that shrinks as speed grows (physics-lite version of the classic
"ball must be under ~1.6 m/s to fall" rule). Faster than that near the
cup => lip-out: deflect slightly and bleed speed.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

G = 9.81
MPH_TO_MS = 0.44704
FT_TO_M = 0.3048

CUP_RADIUS = 0.054          # regulation cup: 4.25 in diameter
CAPTURE_SPEED = 1.63        # m/s: max speed at which the ball can drop
LIPOUT_SPEED_LOSS = 0.55    # fraction of speed kept after a lip-out
LIPOUT_REFLECT = 1.15       # 1.0 = graze, 2.0 = full mirror bounce
STOP_SPEED = 0.02           # below this the ball is at rest
MAX_SIM_TIME = 60.0

# ---- mini golf feature constants ----
BALL_R = 0.021              # regulation ball radius (m)
WALL_RESTITUTION = 0.86     # rail bank: lively, keeps most speed
BUMPER_RESTITUTION = 0.95   # pinball post: lively
BLADE_HALF_W = 0.035        # windmill blade half thickness
BLADE_KICK = 0.6            # fraction of blade surface speed transferred
PORTAL_COOLDOWN = 0.6       # s before the ball can warp again
MAX_BALL_SPEED = 6.0        # cap after windmill smacks (m/s)


@dataclass
class Ball:
    x: float = 0.0
    y: float = 0.0
    vx: float = 0.0
    vy: float = 0.0

    @property
    def speed(self) -> float:
        return math.hypot(self.vx, self.vy)

    @property
    def pos(self) -> Tuple[float, float]:
        return (self.x, self.y)


@dataclass
class PuttResult:
    holed: bool
    lipped_out: bool
    final_pos: Tuple[float, float]
    rollout_m: float            # total distance traveled
    path: List[Tuple[float, float]] = field(default_factory=list)


class GreenPhysics:
    """Simulates one hole's green."""

    def __init__(self, distance_ft: float, break_pct: float,
                 slope_pct: float, stimp: float, features=None):
        cup_x = features.cup_x if features is not None else 0.0
        self.hole_pos = (cup_x, distance_ft * FT_TO_M)
        self.stimp = stimp
        self.features = features
        self.cup_r = CUP_RADIUS * (features.cup_scale
                                   if features is not None else 1.0)
        self._portal_cd = 0.0       # portal re-entry cooldown timer
        # deceleration magnitude from green friction
        stimp_m = stimp * FT_TO_M
        self.mu_a = (1.83 ** 2) / (2.0 * stimp_m)
        # gravity vector from grades: +break pushes ball right (+x),
        # +slope is uphill toward the cup, i.e. gravity pulls -y.
        self.gx = G * (break_pct / 100.0)
        self.gy = -G * (slope_pct / 100.0)

    # ---------------------------------------------- mini golf features
    def _friction_mult(self, x: float, y: float) -> float:
        if self.features is None:
            return 1.0
        for s in self.features.sand:
            if (x - s.x) ** 2 + (y - s.y) ** 2 <= s.r * s.r:
                return s.friction
        return 1.0

    def _boost_accel(self, x: float, y: float) -> Tuple[float, float]:
        if self.features is None:
            return (0.0, 0.0)
        ax = ay = 0.0
        for b in self.features.boosts:
            if b.x0 <= x <= b.x1 and b.y0 <= y <= b.y1:
                ax += b.ax
                ay += b.ay
        return (ax, ay)

    @staticmethod
    def _bounce_off_point(ball: Ball, cx: float, cy: float, min_dist: float,
                          restitution: float) -> bool:
        """Push the ball out of a circle around (cx,cy) and reflect its
        velocity if it is moving inward. Returns True on contact."""
        dx, dy = ball.x - cx, ball.y - cy
        d2 = dx * dx + dy * dy
        if d2 >= min_dist * min_dist:
            return False
        d = math.sqrt(d2) or 1e-6
        nx, ny = dx / d, dy / d
        vdotn = ball.vx * nx + ball.vy * ny
        if vdotn < 0:
            ball.vx -= (1.0 + restitution) * vdotn * nx
            ball.vy -= (1.0 + restitution) * vdotn * ny
        ball.x = cx + nx * (min_dist + 1e-4)
        ball.y = cy + ny * (min_dist + 1e-4)
        return True

    def _collide_segment(self, ball: Ball, x1, y1, x2, y2,
                         pad: float, restitution: float) -> bool:
        """Circle-vs-segment: bounce the ball off the closest point."""
        wx, wy = x2 - x1, y2 - y1
        L2 = wx * wx + wy * wy
        if L2 <= 1e-12:
            return False
        tp = ((ball.x - x1) * wx + (ball.y - y1) * wy) / L2
        tp = 0.0 if tp < 0.0 else 1.0 if tp > 1.0 else tp
        return self._bounce_off_point(ball, x1 + tp * wx, y1 + tp * wy,
                                      pad, restitution)

    def _collide_features(self, ball: Ball, t: float) -> Optional[str]:
        f = self.features
        if f is None:
            return None
        event = None
        for w in f.walls:
            if self._collide_segment(ball, w.x1, w.y1, w.x2, w.y2,
                                     BALL_R, WALL_RESTITUTION):
                event = "bounce"
        for b in f.bumpers:
            if self._bounce_off_point(ball, b.x, b.y, b.r + BALL_R,
                                      BUMPER_RESTITUTION):
                event = "bounce"
        for m in f.windmills:
            # NOTE: no hub collision — the ball rolls under the axle like a
            # real crazy-golf windmill; only the sweeping blades block.
            for k in range(m.blades):
                ang = m.phase + m.omega * t + k * 2.0 * math.pi / m.blades
                tipx = m.x + m.length * math.cos(ang)
                tipy = m.y + m.length * math.sin(ang)
                if self._collide_segment(ball, m.x, m.y, tipx, tipy,
                                         BLADE_HALF_W + BALL_R,
                                         WALL_RESTITUTION):
                    # moving blade swats the ball: add its surface speed
                    # (omega x r) at the contact point, perpendicular to arm
                    cx = ball.x - m.x
                    cy = ball.y - m.y
                    ball.vx += BLADE_KICK * (-m.omega * cy)
                    ball.vy += BLADE_KICK * (m.omega * cx)
                    sp = ball.speed
                    if sp > MAX_BALL_SPEED:
                        ball.vx *= MAX_BALL_SPEED / sp
                        ball.vy *= MAX_BALL_SPEED / sp
                    event = "windmill"
        if self._portal_cd <= 0.0:
            for p in f.portals:
                for (ex, ey, ox, oy) in ((p.ax, p.ay, p.bx, p.by),
                                         (p.bx, p.by, p.ax, p.ay)):
                    if (ball.x - ex) ** 2 + (ball.y - ey) ** 2 <= p.r * p.r:
                        sp = ball.speed
                        if sp > STOP_SPEED:
                            # exit continuing in the direction of travel,
                            # just outside the destination ring
                            ux, uy = ball.vx / sp, ball.vy / sp
                        else:
                            ux, uy = 0.0, 1.0
                        ball.x = ox + ux * (p.r + BALL_R + 0.01)
                        ball.y = oy + uy * (p.r + BALL_R + 0.01)
                        self._portal_cd = PORTAL_COOLDOWN
                        return "portal"
        return event

    # ------------------------------------------------------------------
    def launch(self, ball: Ball, speed_mph: float, hla_deg: float) -> None:
        """Aim from the ball's current spot toward the cup, offset by HLA.

        HLA sign convention matches the tracker: positive = right of the
        target line (from the golfer's view).
        """
        v = max(0.0, speed_mph) * MPH_TO_MS
        dx = self.hole_pos[0] - ball.x
        dy = self.hole_pos[1] - ball.y
        base = math.atan2(dx, dy)               # 0 = straight up the line
        ang = base + math.radians(hla_deg)
        ball.vx = v * math.sin(ang)
        ball.vy = v * math.cos(ang)

    # ------------------------------------------------------------------
    def step(self, ball: Ball, dt: float, t: float = 0.0) -> Optional[str]:
        """Advance one time slice. Returns 'holed', 'lipout', 'stopped',
        a mini golf event ('bounce', 'windmill', 'portal') or None while
        still rolling. `t` is absolute time, used to phase windmills."""
        if self._portal_cd > 0.0:
            self._portal_cd -= dt
        sp = ball.speed
        if sp < STOP_SPEED:
            ball.vx = ball.vy = 0.0
            return "stopped"

        # friction opposes motion (stronger in sand); slope gravity and
        # any boost-pad push are constant accelerations
        mu = self.mu_a * self._friction_mult(ball.x, ball.y)
        bax, bay = self._boost_accel(ball.x, ball.y)
        ax = -mu * ball.vx / sp + self.gx + bax
        ay = -mu * ball.vy / sp + self.gy + bay
        ball.vx += ax * dt
        ball.vy += ay * dt

        # if friction reversed the velocity this tick, the ball stopped
        if ball.speed < STOP_SPEED:
            ball.vx = ball.vy = 0.0
            return "stopped"

        ball.x += ball.vx * dt
        ball.y += ball.vy * dt

        # mini golf obstacles (walls, bumpers, windmills, portals)
        feat_event = self._collide_features(ball, t)

        # cup interaction
        d = math.hypot(ball.x - self.hole_pos[0], ball.y - self.hole_pos[1])
        if d < self.cup_r:
            if ball.speed <= CAPTURE_SPEED:
                ball.x, ball.y = self.hole_pos
                ball.vx = ball.vy = 0.0
                return "holed"
            # too hot: lip out — deflect perpendicular-ish and slow down
            nrmx = (ball.x - self.hole_pos[0]) / max(d, 1e-6)
            nrmy = (ball.y - self.hole_pos[1]) / max(d, 1e-6)
            dot = ball.vx * nrmx + ball.vy * nrmy
            ball.vx = (ball.vx - LIPOUT_REFLECT * dot * nrmx) * LIPOUT_SPEED_LOSS
            ball.vy = (ball.vy - LIPOUT_REFLECT * dot * nrmy) * LIPOUT_SPEED_LOSS
            # nudge outside the cup so we don't re-trigger every frame
            ball.x = self.hole_pos[0] + nrmx * (self.cup_r + 0.005)
            ball.y = self.hole_pos[1] + nrmy * (self.cup_r + 0.005)
            return "lipout"
        return feat_event

    # ------------------------------------------------------------------
    def simulate(self, start: Tuple[float, float], speed_mph: float,
                 hla_deg: float, dt: float = 1 / 240.0,
                 t0: float = 0.0) -> PuttResult:
        """Headless full simulation (used for tests / AI preview)."""
        ball = Ball(start[0], start[1])
        self._portal_cd = 0.0
        self.launch(ball, speed_mph, hla_deg)
        path = [ball.pos]
        lipped = False
        t = 0.0
        travelled = 0.0
        px, py = ball.pos
        while t < MAX_SIM_TIME:
            state = self.step(ball, dt, t0 + t)
            travelled += math.hypot(ball.x - px, ball.y - py)
            px, py = ball.pos
            if len(path) == 0 or (abs(path[-1][0] - ball.x) +
                                  abs(path[-1][1] - ball.y)) > 0.01:
                path.append(ball.pos)
            if state == "lipout":
                lipped = True
            elif state == "holed":
                return PuttResult(True, lipped, ball.pos, travelled, path)
            elif state == "stopped":
                break
            t += dt
        return PuttResult(False, lipped, ball.pos, travelled, path)


def suggest_speed_mph(distance_ft: float, slope_pct: float,
                      stimp: float) -> float:
    """Rough 'pro read' of required ball speed for HUD hints:
    speed to roll distance + 1 ft past the cup on this green."""
    target_m = (distance_ft + 1.0) * FT_TO_M
    stimp_m = stimp * FT_TO_M
    mu_a = (1.83 ** 2) / (2.0 * stimp_m)
    a_eff = max(0.1, mu_a + G * (slope_pct / 100.0))
    v = math.sqrt(2.0 * a_eff * target_m)
    return v / MPH_TO_MS
