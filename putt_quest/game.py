"""Putt Quest — standalone 9-hole putting challenge.

Run the upstream tracker unmodified (`python ball_tracking.py -c orange`)
and it will deliver each real putt's ball speed + HLA to this game over
localhost:8888, exactly as it would to a GSPro connector.

Keys:
  ENTER       start round / next hole / next course action
  UP/DOWN     choose course on the menu
  T           toggle keyboard test mode (no camera needed)
  SPACE       (test mode) fire a putt with the test speed/HLA
  LEFT/RIGHT  (test mode) adjust test HLA
  W/S         (test mode) adjust test speed
  R           restart round
  Q / ESC     quit
"""

from __future__ import annotations

import math
import sys
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import List, Optional

import pygame

from . import graphics as gfx
from .courses import COURSES, Course, Hole
from .physics import (FT_TO_M, Ball, GreenPhysics, suggest_speed_mph)
from .shot_listener import ShotListener

FPS = 60
PHYS_SUBSTEPS = 4
MAX_PUTTS_PER_HOLE = 6      # mercy rule: pick up after this many


class State(Enum):
    MENU = auto()
    AWAIT_PUTT = auto()
    ROLLING = auto()
    HOLE_DONE = auto()
    ROUND_DONE = auto()


@dataclass
class HoleScore:
    hole: Hole
    putts: int = 0
    picked_up: bool = False

    @property
    def strokes(self) -> int:
        return self.putts


@dataclass
class Round:
    course: Course
    hole_idx: int = 0
    scores: List[HoleScore] = field(default_factory=list)

    @property
    def hole(self) -> Hole:
        return self.course.holes[self.hole_idx]

    @property
    def total(self) -> int:
        return sum(s.strokes for s in self.scores)


class Game:
    def __init__(self) -> None:
        pygame.init()
        self.win, self.canvas = gfx.make_screen()
        self.clock = pygame.time.Clock()
        self.listener = ShotListener()
        self.listener_ok = self.listener.start()

        self.state = State.MENU
        self.menu_idx = 0
        self.round: Optional[Round] = None
        self.physics: Optional[GreenPhysics] = None
        self.ball = Ball()
        self.trail: List[tuple] = []
        self.cam: Optional[gfx.Camera] = None
        self.banner = ""
        self.banner_time = 0.0
        self.last_shot_info = ""
        self.lipped = False

        # keyboard test harness
        self.test_mode = False
        self.test_speed = 4.0     # mph
        self.test_hla = 0.0       # degrees

    # ----------------------------------------------------------------
    def start_round(self, course: Course) -> None:
        self.round = Round(course=course,
                           scores=[HoleScore(h) for h in course.holes])
        self.load_hole(0)

    def load_hole(self, idx: int) -> None:
        assert self.round is not None
        self.round.hole_idx = idx
        h = self.round.hole
        self.physics = GreenPhysics(h.distance_ft, h.break_pct,
                                    h.slope_pct, self.round.course.stimp)
        self.ball = Ball(0.0, 0.0)
        self.trail = []
        self.cam = gfx.Camera(h.distance_ft * FT_TO_M)
        self.state = State.AWAIT_PUTT
        self.last_shot_info = ""
        self.set_banner(f"Hole {h.number} — {h.name}")

    def set_banner(self, msg: str, secs: float = 2.5) -> None:
        self.banner = msg
        self.banner_time = secs

    # ----------------------------------------------------------------
    def take_shot(self, speed_mph: float, hla_deg: float) -> None:
        if self.state != State.AWAIT_PUTT or not self.physics:
            return
        score = self.round.scores[self.round.hole_idx]
        score.putts += 1
        self.physics.launch(self.ball, speed_mph, hla_deg)
        self.trail = [self.ball.pos]
        self.lipped = False
        self.last_shot_info = f"{speed_mph:.1f} mph  HLA {hla_deg:+.1f} deg"
        self.state = State.ROLLING

    def finish_hole(self, holed: bool) -> None:
        score = self.round.scores[self.round.hole_idx]
        if not holed:
            score.picked_up = True
        n = score.putts
        label = {1: "ACE! One-putt!", 2: "Two putts — par.",
                 3: "Three putts."}.get(n, f"{n} putts.")
        if score.picked_up:
            label = f"Picked up after {MAX_PUTTS_PER_HOLE} putts."
        self.set_banner(label, 3.0)
        self.state = State.HOLE_DONE

    def next_hole(self) -> None:
        if self.round.hole_idx + 1 < len(self.round.course.holes):
            self.load_hole(self.round.hole_idx + 1)
        else:
            self.state = State.ROUND_DONE

    # ----------------------------------------------------------------
    def update(self, dt: float) -> None:
        if self.banner_time > 0:
            self.banner_time -= dt

        # drain camera shots (only meaningful while awaiting a putt)
        shot = ShotListener.get_shot()
        if shot:
            if self.state == State.AWAIT_PUTT:
                self.take_shot(shot["speed_mph"], shot["hla_deg"])
            else:
                self.set_banner("Shot ignored — not ready", 1.5)

        if self.state == State.ROLLING and self.physics:
            for _ in range(PHYS_SUBSTEPS):
                result = self.physics.step(self.ball, dt / PHYS_SUBSTEPS)
                self.trail.append(self.ball.pos)
                if result == "lipout":
                    self.lipped = True
                    self.set_banner("Lip out!", 1.5)
                elif result == "holed":
                    self.finish_hole(holed=True)
                    break
                elif result == "stopped":
                    score = self.round.scores[self.round.hole_idx]
                    if score.putts >= MAX_PUTTS_PER_HOLE:
                        self.finish_hole(holed=False)
                    else:
                        d_ft = math.hypot(
                            self.ball.x - self.physics.hole_pos[0],
                            self.ball.y - self.physics.hole_pos[1]) / FT_TO_M
                        self.set_banner(f"{d_ft:.1f} ft left", 2.0)
                        self.state = State.AWAIT_PUTT
                    break
            # widen camera if the ball rolls out of frame
            if self.cam:
                self.cam.set_extent(self.physics.hole_pos[1],
                                    extra_pts=[self.ball.pos])

    # ----------------------------------------------------------------
    def handle_key(self, key: int) -> None:
        if key in (pygame.K_q, pygame.K_ESCAPE):
            self.quit()
        if key == pygame.K_t:
            self.test_mode = not self.test_mode
            self.set_banner("Test mode " +
                            ("ON — SPACE putts" if self.test_mode else "OFF"))

        if self.state == State.MENU:
            if key == pygame.K_UP:
                self.menu_idx = (self.menu_idx - 1) % len(COURSES)
            elif key == pygame.K_DOWN:
                self.menu_idx = (self.menu_idx + 1) % len(COURSES)
            elif key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                self.start_round(COURSES[self.menu_idx])
            return

        if key == pygame.K_r and self.round:
            self.start_round(self.round.course)
            return

        if self.state == State.AWAIT_PUTT and self.test_mode:
            if key == pygame.K_SPACE:
                self.take_shot(self.test_speed, self.test_hla)
            elif key == pygame.K_w:
                self.test_speed = min(20.0, self.test_speed + 0.25)
            elif key == pygame.K_s:
                self.test_speed = max(0.5, self.test_speed - 0.25)
            elif key == pygame.K_LEFT:
                self.test_hla -= 0.5
            elif key == pygame.K_RIGHT:
                self.test_hla += 0.5
        elif self.state == State.HOLE_DONE:
            if key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE):
                self.next_hole()
        elif self.state == State.ROUND_DONE:
            if key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                self.state = State.MENU

    # ----------------------------------------------------------------
    def draw(self) -> None:
        c = self.canvas
        if self.state == State.MENU:
            self.draw_menu()
        elif self.state == State.ROUND_DONE:
            self.draw_scorecard()
        else:
            self.draw_hole()
        gfx.blit_scaled(self.win, c)
        pygame.display.flip()

    def draw_menu(self) -> None:
        c = self.canvas
        c.fill(gfx.HUD_BG)
        gfx.text(c, "PUTT QUEST", gfx.INTERNAL_W // 2, 26,
                 gfx.ACCENT, 28, center=True)
        gfx.text(c, "webcam putting challenge", gfx.INTERNAL_W // 2, 48,
                 gfx.HUD_DIM, 12, center=True)
        for i, course in enumerate(COURSES):
            y = 84 + i * 26
            sel = (i == self.menu_idx)
            col = gfx.ACCENT if sel else gfx.HUD_TEXT
            prefix = "> " if sel else "  "
            gfx.text(c, f"{prefix}{course.name}", 96, y, col, 16)
            gfx.text(c, f"stimp {course.stimp:.0f} — par {course.par}",
                     238, y + 2, gfx.HUD_DIM, 11)
        status = ("listening on :8888" if self.listener_ok
                  else "PORT 8888 BUSY — close the GSPro connector")
        gfx.text(c, status, gfx.INTERNAL_W // 2, gfx.INTERNAL_H - 36,
                 gfx.GOOD if self.listener_ok else gfx.BAD, 11, center=True)
        gfx.text(c, "ENTER play    T test mode    Q quit",
                 gfx.INTERNAL_W // 2, gfx.INTERNAL_H - 22,
                 gfx.HUD_DIM, 11, center=True)

    def draw_hole(self) -> None:
        c = self.canvas
        h = self.round.hole
        gfx.draw_green(c, self.cam, h.break_pct, h.slope_pct)
        gfx.draw_cup(c, self.cam, self.physics.hole_pos)
        if self.state == State.AWAIT_PUTT:
            gfx.draw_aim_line(c, self.cam, self.ball.pos,
                              self.physics.hole_pos)
        if len(self.trail) > 1:
            gfx.draw_trail(c, self.cam, self.trail[::3])
        gfx.draw_ball(c, self.cam, self.ball.pos)

        # header
        score = self.round.scores[self.round.hole_idx]
        gfx.text(c, f"H{h.number} {h.name}", 6, 4, gfx.HUD_TEXT, 13)
        gfx.text(c, h.blurb, 6, 16, gfx.HUD_DIM, 11)
        gfx.text(c, f"putt {score.putts + (self.state==State.AWAIT_PUTT)}",
                 gfx.INTERNAL_W - 6 - 50, 4, gfx.HUD_TEXT, 12)
        gfx.text(c, f"total {self.round.total}",
                 gfx.INTERNAL_W - 6 - 50, 16, gfx.HUD_DIM, 11)

        # hint: suggested pace
        if self.state == State.AWAIT_PUTT:
            d_ft = math.hypot(self.ball.x - self.physics.hole_pos[0],
                              self.ball.y - self.physics.hole_pos[1]) / FT_TO_M
            hint = suggest_speed_mph(d_ft, h.slope_pct,
                                     self.round.course.stimp)
            gfx.text(c, f"{d_ft:.1f} ft — pace ~{hint:.1f} mph", 6, 28,
                     gfx.HUD_DIM, 11)

        # HUD strip
        gfx.hud_bar(c)
        if self.test_mode and self.state == State.AWAIT_PUTT:
            msg = (f"TEST  W/S speed {self.test_speed:.2f} mph   "
                   f"</> HLA {self.test_hla:+.1f}   SPACE putt")
            gfx.text(c, msg, 6, gfx.INTERNAL_H - 14, gfx.ACCENT, 11)
        elif self.state == State.AWAIT_PUTT:
            gfx.text(c, "waiting for putt from camera...",
                     6, gfx.INTERNAL_H - 14, gfx.HUD_TEXT, 11)
        elif self.state == State.HOLE_DONE:
            gfx.text(c, "ENTER for next hole", 6, gfx.INTERNAL_H - 14,
                     gfx.HUD_TEXT, 11)
        if self.last_shot_info:
            gfx.text(c, self.last_shot_info,
                     gfx.INTERNAL_W - 6 - 118, gfx.INTERNAL_H - 14,
                     gfx.HUD_DIM, 11)

        # banner
        if self.banner_time > 0 and self.banner:
            gfx.text(c, self.banner, gfx.INTERNAL_W // 2, 44,
                     gfx.ACCENT, 16, center=True)

    def draw_scorecard(self) -> None:
        c = self.canvas
        c.fill(gfx.HUD_BG)
        r = self.round
        gfx.text(c, "SCORECARD", gfx.INTERNAL_W // 2, 14, gfx.ACCENT, 20,
                 center=True)
        gfx.text(c, r.course.name, gfx.INTERNAL_W // 2, 32, gfx.HUD_DIM, 12,
                 center=True)
        x0 = 30
        for i, s in enumerate(r.scores):
            x = x0 + i * 36
            gfx.text(c, f"{s.hole.number}", x, 58, gfx.HUD_DIM, 11)
            col = (gfx.GOOD if s.strokes == 1 else
                   gfx.HUD_TEXT if s.strokes <= s.hole.par else gfx.BAD)
            label = f"{s.strokes}" + ("*" if s.picked_up else "")
            gfx.text(c, label, x, 72, col, 14)
        total = r.total
        par = r.course.par
        diff = total - par
        rel = "E" if diff == 0 else (f"+{diff}" if diff > 0 else str(diff))
        gfx.text(c, f"TOTAL {total}  (par {par}, {rel})",
                 gfx.INTERNAL_W // 2, 108, gfx.HUD_TEXT, 16, center=True)
        if any(s.picked_up for s in r.scores):
            gfx.text(c, "* picked up", gfx.INTERNAL_W // 2, 126,
                     gfx.HUD_DIM, 10, center=True)
        gfx.text(c, "ENTER menu    R replay course", gfx.INTERNAL_W // 2,
                 gfx.INTERNAL_H - 24, gfx.HUD_DIM, 11, center=True)

    # ----------------------------------------------------------------
    def quit(self) -> None:
        self.listener.stop()
        pygame.quit()
        sys.exit(0)

    def run(self) -> None:
        while True:
            dt = self.clock.tick(FPS) / 1000.0
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    self.quit()
                elif event.type == pygame.KEYDOWN:
                    self.handle_key(event.key)
            self.update(min(dt, 0.05))
            self.draw()


def main() -> None:
    Game().run()


if __name__ == "__main__":
    main()
