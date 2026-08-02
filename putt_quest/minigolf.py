"""Mini golf features and courses for Putt Quest.

Everything here is data. A `HoleFeatures` bundle attaches obstacles to a
Hole; physics.py reads the geometry to bounce/teleport/slow the ball and
render3d.py draws it. Holes without features behave exactly as before.

Coordinates are METERS in physics space: the ball starts each hole at
(0, 0), +y runs toward the cup, +x is right of the start line. The cup
sits at (cup_x, distance). 1 ft = 0.3048 m.

Feature cheat sheet:
  Wall      straight rail segment, banks the ball (restitution ~0.78)
  Bumper    round post, lively pinball bounce
  Windmill  blades rotating around a hub; moving walls that swat the ball
  Portal    bidirectional teleporter pair (enter either ring)
  Sand      circular high-friction zone
  Boost     rectangular conveyor pad adding constant acceleration
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple

FT = 0.3048


@dataclass(frozen=True)
class Wall:
    x1: float
    y1: float
    x2: float
    y2: float
    h: float = 0.12             # visual rail height (m)


@dataclass(frozen=True)
class Bumper:
    x: float
    y: float
    r: float = 0.11


@dataclass(frozen=True)
class Windmill:
    x: float
    y: float
    blades: int = 2
    length: float = 0.55        # blade length from hub (m)
    omega: float = 1.3          # rad/s, + = counter-clockwise
    phase: float = 0.0


@dataclass(frozen=True)
class Portal:
    ax: float
    ay: float
    bx: float
    by: float
    r: float = 0.15


@dataclass(frozen=True)
class Sand:
    x: float
    y: float
    r: float
    friction: float = 3.4       # multiplier on green friction inside


@dataclass(frozen=True)
class Boost:
    x0: float
    y0: float
    x1: float
    y1: float
    ax: float = 0.0             # constant accel while inside (m/s^2)
    ay: float = 0.0


@dataclass(frozen=True)
class HoleFeatures:
    walls: Tuple[Wall, ...] = ()
    bumpers: Tuple[Bumper, ...] = ()
    windmills: Tuple[Windmill, ...] = ()
    portals: Tuple[Portal, ...] = ()
    sand: Tuple[Sand, ...] = ()
    boosts: Tuple[Boost, ...] = ()
    cup_x: float = 0.0          # lateral cup offset (doglegs)
    half_w: float = 0.0         # >0 overrides the green pad half-width
    cup_scale: float = 1.8      # mini golf cups are wider than regulation

    @property
    def tags(self) -> str:
        bits = []
        if self.walls:
            bits.append("rails")
        if self.windmills:
            bits.append("windmill")
        if self.bumpers:
            bits.append("bumpers")
        if self.portals:
            bits.append("portals")
        if self.sand:
            bits.append("sand")
        if self.boosts:
            bits.append("boost")
        return " + ".join(bits)


def rails(x0: float, y0: float, x1: float, y1: float,
          h: float = 0.12) -> Tuple[Wall, ...]:
    """Four walls enclosing the rectangle (x0,y0)-(x1,y1)."""
    return (Wall(x0, y0, x1, y0, h), Wall(x1, y0, x1, y1, h),
            Wall(x1, y1, x0, y1, h), Wall(x0, y1, x0, y0, h))
