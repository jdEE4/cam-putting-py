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
from typing import List


@dataclass(frozen=True)
class Hole:
    number: int
    name: str
    distance_ft: float          # straight-line distance ball -> cup
    break_pct: float = 0.0      # + pushes ball right, - pushes left
    slope_pct: float = 0.0      # + uphill, - downhill
    par: int = 2                # putting par (2 is standard)

    @property
    def blurb(self) -> str:
        parts = [f"{self.distance_ft:.0f} ft"]
        if abs(self.break_pct) >= 0.05:
            side = "R-to-L" if self.break_pct < 0 else "L-to-R"
            parts.append(f"{abs(self.break_pct):.1f}% {side}")
        if abs(self.slope_pct) >= 0.05:
            parts.append(("uphill " if self.slope_pct > 0 else "downhill ")
                         + f"{abs(self.slope_pct):.1f}%")
        if abs(self.break_pct) < 0.05 and abs(self.slope_pct) < 0.05:
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

COURSES: List[Course] = [CLASSIC_9, LINKS_9]
