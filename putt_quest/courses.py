"""Course and hole definitions for Putt Quest.

Each hole is a single putt scenario: a distance, a sideways break, and an
up/down slope. Positive break pushes the ball to the RIGHT of the target
line (so you aim left); negative break pushes LEFT. Positive slope is
UPHILL (putt plays longer); negative is DOWNHILL.

Distances are in feet, break/slope in percent grade (1.0 = 1% grade,
a noticeable break on a real green; 3.0 is severe).

This file is data-only on purpose: add your own courses by appending to
COURSES. The game auto-lists anything found here.
"""

from dataclasses import dataclass, field
from typing import List, Optional

from .minigolf import (Boost, Bumper, HoleFeatures, Portal, Sand, Wall,
                       Windmill, rails)


@dataclass(frozen=True)
class Hole:
    number: int
    name: str
    distance_ft: float          # straight-line distance ball -> cup
    break_pct: float = 0.0      # + pushes ball right, - pushes left
    slope_pct: float = 0.0      # + uphill, - downhill
    par: int = 2                # putting par (2 is standard)
    features: Optional[HoleFeatures] = None   # mini golf obstacles

    @property
    def blurb(self) -> str:
        parts = [f"{self.distance_ft:.0f} ft"]
        if abs(self.break_pct) >= 0.05:
            side = "R-to-L" if self.break_pct < 0 else "L-to-R"
            parts.append(f"{abs(self.break_pct):.1f}% {side}")
        if abs(self.slope_pct) >= 0.05:
            parts.append(("uphill " if self.slope_pct > 0 else "downhill ")
                         + f"{abs(self.slope_pct):.1f}%")
        if self.features is not None and self.features.tags:
            parts.append(self.features.tags)
        elif abs(self.break_pct) < 0.05 and abs(self.slope_pct) < 0.05:
            parts.append("dead straight")
        return ", ".join(parts)


@dataclass(frozen=True)
class Course:
    name: str
    stimp: float                # green speed (stimpmeter feet). 8 slow .. 13 fast
    holes: List[Hole] = field(default_factory=list)

    @property
    def par(self) -> int:
        return sum(h.par for h in self.holes)


CLASSIC_9 = Course(
    name="Classic 9",
    stimp=10.0,
    holes=[
        Hole(1, "Warm Up",        4.0,  0.0,  0.0),
        Hole(2, "Knee Knocker",   6.0,  0.8,  0.0),
        Hole(3, "Slider",         9.0, -1.2,  0.0),
        Hole(4, "The Climb",     12.0,  0.0,  1.5),
        Hole(5, "Downhill Racer", 10.0,  0.0, -1.5),
        Hole(6, "Double Cross",  15.0,  1.5, -0.8),
        Hole(7, "Big Bender",    18.0, -2.0,  0.5),
        Hole(8, "The Marathon",  25.0,  0.6,  0.8),
        Hole(9, "Glory Putt",     8.0, -1.8, -1.0),
    ],
)

LINKS_9 = Course(
    name="Links Test",
    stimp=11.5,
    holes=[
        Hole(1, "Opener",         5.0, -0.5,  0.0),
        Hole(2, "Falling Away",   8.0,  0.0, -2.0),
        Hole(3, "Camber",        10.0,  2.2,  0.0),
        Hole(4, "Ridge Runner",  14.0, -1.0,  1.2),
        Hole(5, "The Chute",      7.0,  0.0,  2.5),
        Hole(6, "Sidewinder",    12.0, -2.5,  0.0),
        Hole(7, "Long Bomb",     30.0,  1.0, -0.5),
        Hole(8, "Tester",         3.5,  1.5,  0.0),
        Hole(9, "Cliff Edge",    16.0, -1.5, -1.8),
    ],
)

# ======================================================================
# MINI GOLF — obstacle courses. Geometry is in meters (physics space):
# ball starts at (0,0), cup at (cup_x, distance). Every hole is fully
# railed, so bank shots are always in play and the ball can't leave.
# ======================================================================

def _mg(n, name, ft, feats, brk=0.0, slope=0.0, par=2):
    return Hole(n, name, ft, brk, slope, par, features=feats)


WINDMILL_GARDENS = Course(
    name="Windmill Gardens",
    stimp=9.0,
    holes=[
        # 1 — straight rail alley to learn the bounce
        _mg(1, "Bank Alley", 8.0, HoleFeatures(
            walls=rails(-0.85, -0.8, 0.85, 3.25),
            half_w=1.5)),
        # 2 — cup offset right; the only way in is a slot on the diagonal
        _mg(2, "The Mail Slot", 10.0, HoleFeatures(
            walls=rails(-1.6, -0.8, 1.6, 3.85)
                  + (Wall(-1.6, 1.65, 0.42, 1.65),
                     Wall(0.75, 1.65, 1.6, 1.65)),
            cup_x=1.0, half_w=2.2)),
        # 3 — the mandatory windmill
        _mg(3, "The Old Windmill", 11.0, HoleFeatures(
            walls=rails(-1.0, -0.8, 1.0, 4.15),
            windmills=(Windmill(0.0, 1.7, blades=2, length=0.55, omega=1.4),),
            half_w=1.7)),
        # 4 — staggered posts
        _mg(4, "Bumper Garden", 12.0, HoleFeatures(
            walls=rails(-1.1, -0.8, 1.1, 4.45),
            bumpers=(Bumper(-0.45, 1.3), Bumper(0.5, 1.9),
                     Bumper(-0.1, 2.6)),
            half_w=1.8)),
        # 5 — walls pinch to a narrow waist
        _mg(5, "The Hourglass", 12.0, HoleFeatures(
            walls=rails(-1.1, -0.8, 1.1, 4.45)
                  + (Wall(-1.1, 1.55, -0.24, 1.95),
                     Wall(1.1, 1.55, 0.24, 1.95)),
            half_w=1.8)),
        # 6 — twin sand crescents guard the cup
        _mg(6, "Beach, Please", 10.0, HoleFeatures(
            walls=rails(-1.0, -0.8, 1.0, 3.85),
            sand=(Sand(-0.36, 2.4, 0.34), Sand(0.36, 2.4, 0.34)),
            half_w=1.7), slope=0.5),
        # 7 — thread the keyhole gate to reach an offset cup
        _mg(7, "The Keyhole", 13.0, HoleFeatures(
            walls=rails(-1.9, -0.8, 1.9, 4.75)
                  + (Wall(-1.9, 2.0, -0.78, 2.0),
                     Wall(-0.32, 2.0, 1.9, 2.0)),
            cup_x=-1.1, half_w=2.5)),
        # 8 — windmill AND sand (blade phase tuned so the window is fair)
        _mg(8, "Windy Beach", 13.0, HoleFeatures(
            walls=rails(-1.2, -0.8, 1.2, 4.75),
            windmills=(Windmill(0.0, 2.0, blades=2, length=0.6, omega=1.1,
                                phase=1.178),),
            sand=(Sand(-0.55, 1.0, 0.3), Sand(0.55, 2.95, 0.3)),
            half_w=1.9)),
        # 9 — pinch + posts + sand behind the cup, slightly downhill
        _mg(9, "The Gauntlet", 16.0, HoleFeatures(
            walls=rails(-1.3, -0.8, 1.3, 5.7)
                  + (Wall(-1.3, 1.7, -0.3, 2.1), Wall(1.3, 1.7, 0.3, 2.1)),
            bumpers=(Bumper(-0.5, 3.0), Bumper(0.5, 3.55)),
            sand=(Sand(0.0, 5.35, 0.4),),
            half_w=2.0), slope=-0.6, par=3),
    ],
)


PORTAL_PARK = Course(
    name="Portal Park",
    stimp=10.5,
    holes=[
        # 1 — a wall seals the hole off completely; the portal IS the route
        _mg(1, "Warp Opener", 9.0, HoleFeatures(
            walls=rails(-1.2, -0.8, 1.2, 3.55)
                  + (Wall(-1.2, 1.55, 1.2, 1.55),),
            portals=(Portal(0.0, 1.15, 0.0, 2.0),),
            half_w=1.9)),
        # 2 — a sideways conveyor shoves the ball right: aim left
        _mg(2, "Conveyor Canyon", 12.0, HoleFeatures(
            walls=rails(-1.3, -0.8, 1.3, 4.45),
            boosts=(Boost(-1.3, 1.2, 1.3, 2.3, ax=1.3),),
            half_w=2.0)),
        # 3 — slalom through a five-post pinball field
        _mg(3, "Pinball Wizard", 12.0, HoleFeatures(
            walls=rails(-1.2, -0.8, 1.2, 4.45),
            bumpers=(Bumper(-0.75, 1.35), Bumper(0.75, 1.35),
                     Bumper(0.28, 2.0), Bumper(-0.28, 2.7),
                     Bumper(0.75, 2.95)),
            half_w=1.9)),
        # 4 — dogleg where the wormhole skips the corner (enter straight,
        # exit straight at the cup; the long way around the wall also works)
        _mg(4, "Wormhole Dogleg", 14.0, HoleFeatures(
            walls=rails(-1.7, -0.8, 1.7, 5.1)
                  + (Wall(-0.1, 2.1, 1.7, 2.1),),
            portals=(Portal(0.0, 1.4, 1.2, 3.5),),
            cup_x=1.2, half_w=2.4)),
        # 5 — boost straight at the cup, sand catches the greedy
        _mg(5, "Speedway", 18.0, HoleFeatures(
            walls=rails(-0.9, -0.8, 0.9, 6.3),
            boosts=(Boost(-0.9, 1.2, 0.9, 1.9, ay=1.8),
                    Boost(-0.9, 3.1, 0.9, 3.8, ay=1.8)),
            sand=(Sand(0.0, 6.0, 0.42),),
            half_w=1.6)),
        # 6 — four whirling arms with corner posts
        _mg(6, "The Kraken", 13.0, HoleFeatures(
            walls=rails(-1.3, -0.8, 1.3, 4.75),
            windmills=(Windmill(0.0, 2.0, blades=4, length=0.6, omega=1.05),),
            bumpers=(Bumper(-0.95, 1.1), Bumper(0.95, 2.9)),
            half_w=2.0)),
        # 7 — through the left gap, then bank off the kicker to the cup
        _mg(7, "Ricochet Rally", 15.0, HoleFeatures(
            walls=rails(-1.7, -0.8, 1.7, 5.4)
                  + (Wall(-0.35, 2.3, 1.7, 2.3),
                     Wall(-0.84, 3.2, -0.36, 4.2)),
            cup_x=0.9, half_w=2.4)),
        # 8 — warp across a sand sea (the exit ring is offset so the warp
        # line continues straight into the cup)
        _mg(8, "Quantum Beach", 14.0, HoleFeatures(
            walls=rails(-1.3, -0.8, 1.3, 5.1),
            sand=(Sand(-0.5, 2.2, 0.5), Sand(0.5, 2.2, 0.5),
                  Sand(0.0, 2.9, 0.45)),
            portals=(Portal(-0.4, 1.5, 0.18, 3.6),),
            half_w=2.0)),
        # 9 — everything at once. Good luck.
        _mg(9, "Event Horizon", 20.0, HoleFeatures(
            walls=rails(-1.6, -0.8, 1.6, 6.9),
            windmills=(Windmill(0.0, 2.2, blades=2, length=0.6, omega=1.5),),
            portals=(Portal(-1.0, 3.2, 0.9, 4.6),),
            boosts=(Boost(-1.6, 4.9, 1.6, 5.5, ay=1.2),),
            sand=(Sand(-0.75, 1.35, 0.32), Sand(0.85, 5.9, 0.38)),
            bumpers=(Bumper(0.55, 3.4),),
            half_w=2.3), slope=-0.8, par=3),
    ],
)


COURSES: List[Course] = [CLASSIC_9, LINKS_9, WINDMILL_GARDENS, PORTAL_PARK]
