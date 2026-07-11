"""Putt Quest — standalone 9-hole putting challenge, now in 3D.

Run the upstream tracker (`python ball_tracking.py -c orange`) and it
will deliver each real putt's ball speed + HLA to this game over
localhost:8888, exactly as it would to a GSPro connector. The tracker
also pings ball-setup status to the game, so the HUD can tell you when
your physical ball is placed and locked before you putt.

Keys:
  ENTER       start round / next hole / next course action
  UP/DOWN     choose course on the menu
  T           toggle keyboard test mode (no camera needed)
  SPACE       (test mode) fire a putt with the test speed/HLA
  LEFT/RIGHT  (test mode) adjust test HLA
  W/S         (test mode) adjust test speed
  D           toggle debug overlay (FPS, physics, raw shot feed)
  M           toggle minimap
  R           restart round
  Q / ESC     quit
"""

from __future__ import annotations

import math
import sys
import time
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import List, Optional, Tuple

import pygame

from . import graphics as gfx
from .courses import COURSES, Course, Hole
from .physics import (FT_TO_M, Ball, GreenPhysics, suggest_speed_mph)
from .render3d import GreenScene
from .shot_listener import ShotListener

FPS = 60
PHYS_SUBSTEPS = 4
MAX_PUTTS_PER_HOLE = 6      # mercy rule: pick up after this many
TRACKER_FRESH_SECS = 2.5    # status ping older than this = tracker gone


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
        self.scene: Optional[GreenScene] = None
        self.banner = ""
        self.banner_time = 0.0
        self.last_shot_info = ""
        self.lipped = False
        self.time = 0.0             # for flag wave etc.
        self.shots_received = 0

        # toggles
        self.debug = False
        self.show_minimap = True

        # keyboard test harness
        self.test_mode = False
        self.test_speed = 4.0     # mph
        self.test_hla = 0.0       # degrees
        self._preview: List[tuple] = []
        self._preview_key: Optional[Tuple] = None

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
        self.scene = GreenScene((gfx.INTERNAL_W, gfx.INTERNAL_H),
                                h.distance_ft * FT_TO_M,
                                h.break_pct, h.slope_pct)
        self.scene.position_camera(self.ball.pos)
        self.state = State.AWAIT_PUTT
        self.last_shot_info = ""
        self._preview_key = None
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
        self.time += dt
        if self.banner_time > 0:
            self.banner_time -= dt

        # drain camera shots (only meaningful while awaiting a putt)
        shot = ShotListener.get_shot()
        if shot:
            self.shots_received += 1
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
                        # camera walks up behind the new ball position
                        self.scene.position_camera(self.ball.pos)
                        self._preview_key = None
                    break

    # ----------------------------------------------------------------
    def handle_key(self, key: int) -> None:
        if key in (pygame.K_q, pygame.K_ESCAPE):
            self.quit()
        if key == pygame.K_t:
            self.test_mode = not self.test_mode
            self.set_banner("Test mode " +
                            ("ON — SPACE putts" if self.test_mode else "OFF"))
        if key == pygame.K_d:
            self.debug = not self.debug
        if key == pygame.K_m:
            self.show_minimap = not self.show_minimap

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

    # ------------------------------------------------- tracker status
    def tracker_line(self) -> Tuple[str, tuple]:
        """(message, color) describing camera/ball setup right now."""
        age, st = ShotListener.get_tracker_status()
        if not self.listener_ok:
            return "PORT 8888 BUSY — close the GSPro connector", gfx.BAD
        if age is None or age > TRACKER_FRESH_SECS:
            return "tracker not detected — start ball_tracking.py", gfx.HUD_DIM
        if st.get("balldetected"):
            return "BALL READY — putt when ready", gfx.GOOD
        if st.get("locking"):
            return "ball seen — hold still, locking...", gfx.ACCENT
        return "tracker online — place ball in start zone", gfx.INFO

    # ----------------------------------------------------------------
    def _test_preview(self) -> List[tuple]:
        """Ghost path for the current test speed/HLA (cached)."""
        key = (round(self.test_speed, 3), round(self.test_hla, 2),
               round(self.ball.x, 3), round(self.ball.y, 3))
        if key != self._preview_key:
            r = self.physics.simulate(self.ball.pos, self.test_speed,
                                      self.test_hla, dt=1 / 120.0)
            self._preview = r.path[::4]
            self._preview_key = key
        return self._preview

    # ----------------------------------------------------------------
    def draw(self) -> None:
        if self.state == State.MENU:
            self.draw_menu()
        elif self.state == State.ROUND_DONE:
            self.draw_scorecard()
        else:
            self.draw_hole()
        if self.debug:
            self.draw_debug()
        gfx.blit_scaled(self.win, self.canvas)
        pygame.display.flip()

    # ------------------------------------------------------------ menu
    def draw_menu(self) -> None:
        c = self.canvas
        W, H = gfx.INTERNAL_W, gfx.INTERNAL_H
        c.fill(gfx.HUD_BG)
        # subtle backdrop stripes
        for i in range(0, H, 24):
            pygame.draw.rect(c, (14, 24, 16) if (i // 24) % 2 else gfx.HUD_BG,
                             (0, i, W, 24))
        gfx.text(c, "PUTT QUEST", W // 2, 34, gfx.ACCENT, 52,
                 center=True, shadow=True)
        gfx.text(c, "webcam putting challenge — now in 3D", W // 2, 78,
                 gfx.HUD_DIM, 18, center=True)

        for i, course in enumerate(COURSES):
            sel = (i == self.menu_idx)
            rect = pygame.Rect(W // 2 - 170, 112 + i * 52, 340, 44)
            gfx.panel(c, rect, alpha=220 if sel else 140)
            if sel:
                pygame.draw.rect(c, gfx.ACCENT, rect, 1, border_radius=6)
            col = gfx.ACCENT if sel else gfx.HUD_TEXT
            gfx.text(c, course.name, rect.x + 14, rect.y + 7, col, 22)
            gfx.text(c, f"stimp {course.stimp:.0f}   par {course.par}   "
                        f"{len(course.holes)} holes",
                     rect.x + 14, rect.y + 26, gfx.HUD_DIM, 15)

        # status footer: listener + live tracker/ball state
        foot = pygame.Rect(W // 2 - 220, H - 66, 440, 40)
        gfx.panel(c, foot, alpha=200)
        lst_col = gfx.GOOD if self.listener_ok else gfx.BAD
        lst_msg = ("listening on :8888" if self.listener_ok
                   else "PORT 8888 BUSY — close the GSPro connector")
        gfx.status_dot(c, foot.x + 14, foot.y + 12, lst_col)
        gfx.text(c, lst_msg, foot.x + 24, foot.y + 6, lst_col, 15)
        msg, col = self.tracker_line()
        gfx.status_dot(c, foot.x + 14, foot.y + 29, col)
        gfx.text(c, msg, foot.x + 24, foot.y + 23, col, 15)

        gfx.text(c, "ENTER play    UP/DOWN choose    T test mode    "
                    "D debug    Q quit",
                 W // 2, H - 18, gfx.HUD_DIM, 15, center=True)

    # ------------------------------------------------------------ hole
    def draw_hole(self) -> None:
        c = self.canvas
        W, H = gfx.INTERNAL_W, gfx.INTERNAL_H
        h = self.round.hole

        aim = None
        preview: List[tuple] = []
        if self.state == State.AWAIT_PUTT:
            aim = (self.ball.pos, self.test_hla if self.test_mode else 0.0)
            if self.test_mode:
                preview = self._test_preview()
        ball_pos = None if self.state == State.HOLE_DONE else self.ball.pos
        self.scene.draw(c, ball_pos, trail=self.trail[::3], t=self.time,
                        aim=aim, preview=preview)

        if self.show_minimap:
            mm = pygame.Rect(W - 106, 8, 98, 132)
            self.scene.draw_minimap(c, mm, ball_pos, self.trail[::3])

        # header panel
        score = self.round.scores[self.round.hole_idx]
        head = pygame.Rect(6, 6, 250, 62)
        gfx.panel(c, head)
        gfx.text(c, f"Hole {h.number} — {h.name}", head.x + 10, head.y + 6,
                 gfx.HUD_TEXT, 20)
        gfx.text(c, h.blurb, head.x + 10, head.y + 25, gfx.HUD_DIM, 15)
        if self.state != State.HOLE_DONE:
            d_ft = math.hypot(self.ball.x - self.physics.hole_pos[0],
                              self.ball.y - self.physics.hole_pos[1]) / FT_TO_M
            hint = suggest_speed_mph(d_ft, h.slope_pct,
                                     self.round.course.stimp)
            gfx.text(c, f"{d_ft:.1f} ft to the cup — pace ~{hint:.1f} mph",
                     head.x + 10, head.y + 42, gfx.INFO, 15)

        # score chip
        chip = pygame.Rect(W - 106, 146 if self.show_minimap else 8, 98, 40)
        gfx.panel(c, chip)
        gfx.text(c, f"putt {score.putts + (self.state == State.AWAIT_PUTT)}",
                 chip.x + 10, chip.y + 5, gfx.HUD_TEXT, 17)
        gfx.text(c, f"total {self.round.total}", chip.x + 10, chip.y + 22,
                 gfx.HUD_DIM, 15)

        # bottom status bar
        bar = pygame.Rect(6, H - 30, W - 12, 24)
        gfx.panel(c, bar, alpha=200)
        if self.test_mode and self.state == State.AWAIT_PUTT:
            gfx.text(c, f"TEST  W/S speed {self.test_speed:.2f} mph    "
                        f"LEFT/RIGHT HLA {self.test_hla:+.1f} deg    "
                        "SPACE putt", bar.x + 10, bar.y + 5, gfx.ACCENT, 15)
        elif self.state == State.AWAIT_PUTT:
            msg, col = self.tracker_line()
            gfx.status_dot(c, bar.x + 14, bar.y + 12, col)
            gfx.text(c, msg, bar.x + 24, bar.y + 5, col, 15)
        elif self.state == State.HOLE_DONE:
            gfx.text(c, "ENTER for next hole", bar.x + 10, bar.y + 5,
                     gfx.HUD_TEXT, 15)
        elif self.state == State.ROLLING:
            mph = self.ball.speed / 0.44704
            gfx.text(c, f"rolling...  {mph:.1f} mph", bar.x + 10, bar.y + 5,
                     gfx.HUD_TEXT, 15)
        if self.last_shot_info:
            gfx.text(c, self.last_shot_info,
                     bar.right - 10 - gfx.text_w(self.last_shot_info, 15),
                     bar.y + 5, gfx.HUD_DIM, 15)

        # banner
        if self.banner_time > 0 and self.banner:
            bw = gfx.text_w(self.banner, 30) + 30
            br = pygame.Rect(W // 2 - bw // 2, 84, bw, 34)
            gfx.panel(c, br, alpha=200)
            gfx.text(c, self.banner, W // 2, br.y + 7, gfx.ACCENT, 30,
                     center=True, shadow=True)

    # ------------------------------------------------------- scorecard
    def draw_scorecard(self) -> None:
        c = self.canvas
        W, H = gfx.INTERNAL_W, gfx.INTERNAL_H
        r = self.round
        c.fill(gfx.HUD_BG)
        gfx.text(c, "SCORECARD", W // 2, 30, gfx.ACCENT, 40,
                 center=True, shadow=True)
        gfx.text(c, r.course.name, W // 2, 66, gfx.HUD_DIM, 18, center=True)

        n = len(r.scores)
        bw = 52
        x0 = W // 2 - (n * bw) // 2
        for i, s in enumerate(r.scores):
            box = pygame.Rect(x0 + i * bw + 3, 100, bw - 6, 74)
            gfx.panel(c, box, alpha=170)
            gfx.text(c, f"{s.hole.number}", box.centerx, box.y + 6,
                     gfx.HUD_DIM, 15, center=True)
            col = (gfx.GOOD if s.strokes == 1 else
                   gfx.HUD_TEXT if s.strokes <= s.hole.par else gfx.BAD)
            label = f"{s.strokes}" + ("*" if s.picked_up else "")
            gfx.text(c, label, box.centerx, box.y + 24, col, 28, center=True)
            gfx.text(c, f"{s.hole.distance_ft:.0f}ft", box.centerx,
                     box.y + 54, gfx.HUD_DIM, 13, center=True)

        total, par = r.total, r.course.par
        diff = total - par
        rel = "E" if diff == 0 else (f"+{diff}" if diff > 0 else str(diff))
        gfx.text(c, f"TOTAL {total}   (par {par}, {rel})", W // 2, 200,
                 gfx.HUD_TEXT, 26, center=True)
        if any(s.picked_up for s in r.scores):
            gfx.text(c, "* picked up", W // 2, 228, gfx.HUD_DIM, 14,
                     center=True)
        gfx.text(c, "ENTER menu    R replay course", W // 2, H - 34,
                 gfx.HUD_DIM, 16, center=True)

    # ----------------------------------------------------------- debug
    def draw_debug(self) -> None:
        c = self.canvas
        rect = pygame.Rect(6, 76, 300, 190)
        gfx.panel(c, rect, alpha=215)
        x, y = rect.x + 10, rect.y + 8

        def line(msg, col=gfx.HUD_TEXT):
            nonlocal y
            gfx.text(c, msg, x, y, col, 14)
            y += 15

        line(f"DEBUG   fps {self.clock.get_fps():.0f}   "
             f"state {self.state.name}", gfx.ACCENT)
        if self.physics:
            mph = self.ball.speed / 0.44704
            line(f"ball ({self.ball.x:+.2f}, {self.ball.y:+.2f}) m   "
                 f"{mph:.2f} mph")
            line(f"phys mu_a {self.physics.mu_a:.3f}  "
                 f"gx {self.physics.gx:+.3f}  gy {self.physics.gy:+.3f}")
        line(f"listener {'OK :8888' if self.listener_ok else 'FAILED'}   "
             f"shots recv {self.shots_received}",
             gfx.GOOD if self.listener_ok else gfx.BAD)
        age, st = ShotListener.get_tracker_status()
        if age is None:
            line("tracker: no status pings yet", gfx.HUD_DIM)
        else:
            line(f"tracker ping {age:.1f}s ago  ball="
                 f"{'YES' if st.get('balldetected') else 'no'}  "
                 f"r={st.get('ballradius', '?')}  "
                 f"fps={st.get('fps', '?')}",
                 gfx.GOOD if age < TRACKER_FRESH_SECS else gfx.BAD)
        line("recent requests:", gfx.HUD_DIM)
        events = ShotListener.get_events()
        if not events:
            line("  (none yet)", gfx.HUD_DIM)
        for ts, msg in events[:6]:
            line(f"  {time.strftime('%H:%M:%S', time.localtime(ts))} "
                 f"{msg[:38]}", gfx.INFO)

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
