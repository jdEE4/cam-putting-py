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
                 slope_pct: float, stimp: float):
        self.hole_pos = (0.0, distance_ft * FT_TO_M)
        self.stimp = stimp
        # deceleration magnitude from green friction
        stimp_m = stimp * FT_TO_M
        self.mu_a = (1.83 ** 2) / (2.0 * stimp_m)
        # gravity vector from grades: +break pushes ball right (+x),
        # +slope is uphill toward the cup, i.e. gravity pulls -y.
        self.gx = G * (break_pct / 100.0)
        self.gy = -G * (slope_pct / 100.0)

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
    def step(self, ball: Ball, dt: float) -> Optional[str]:
        """Advance one time slice. Returns 'holed', 'lipout', 'stopped'
        or None while still rolling."""
        sp = ball.speed
        if sp < STOP_SPEED:
            ball.vx = ball.vy = 0.0
            return "stopped"

        # friction opposes motion; slope gravity is constant
        ax = -self.mu_a * ball.vx / sp + self.gx
        ay = -self.mu_a * ball.vy / sp + self.gy
        ball.vx += ax * dt
        ball.vy += ay * dt

        # if friction reversed the velocity this tick, the ball stopped
        if ball.speed < STOP_SPEED:
            ball.vx = ball.vy = 0.0
            return "stopped"

        ball.x += ball.vx * dt
        ball.y += ball.vy * dt

        # cup interaction
        d = math.hypot(ball.x - self.hole_pos[0], ball.y - self.hole_pos[1])
        if d < CUP_RADIUS:
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
            ball.x = self.hole_pos[0] + nrmx * (CUP_RADIUS + 0.005)
            ball.y = self.hole_pos[1] + nrmy * (CUP_RADIUS + 0.005)
            return "lipout"
        return None

    # ------------------------------------------------------------------
    def simulate(self, start: Tuple[float, float], speed_mph: float,
                 hla_deg: float, dt: float = 1 / 240.0) -> PuttResult:
        """Headless full simulation (used for tests / AI preview)."""
        ball = Ball(start[0], start[1])
        self.launch(ball, speed_mph, hla_deg)
        path = [ball.pos]
        lipped = False
        t = 0.0
        travelled = 0.0
        px, py = ball.pos
        while t < MAX_SIM_TIME:
            state = self.step(ball, dt)
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
