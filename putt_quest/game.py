"""Putt Quest — standalone 9-hole putting challenge, in 3D.

Run the upstream tracker (`python ball_tracking.py -c orange`) and it
will deliver each real putt's ball speed + HLA to this game over
localhost:8888, exactly as it would to a GSPro connector. The tracker
also pings ball-setup status and (optionally) a live webcam thumbnail to
the game, so the HUD can tell you when your physical ball is recognized
and locked *before* you putt — and the debug overlay can show the camera.

Keys:
  ENTER       start round / next hole / next course action
  UP/DOWN     choose course on the menu
  T           toggle keyboard test mode (no camera needed)
  SPACE       (test mode) fire a putt with the test speed/HLA
  LEFT/RIGHT  (test mode) adjust test HLA
  W/S         (test mode) adjust test speed
  [ / ]       lower / raise render resolution
  G           toggle the auto-resolution guard
  D           toggle debug overlay (camera preview, FPS, shot feed)
  M           toggle minimap
  R           restart round
  Q / ESC     quit
"""

from __future__ import annotations

import io
import json
import math
import os
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
from .sounds import SFX

import random as _random

FPS = 60
PHYS_SUBSTEPS = 4
DEFAULT_MERCY_LIMIT = 6         # pick up after this many putts (adjustable)
MIN_MERCY_LIMIT = 3
MAX_MERCY_LIMIT = 9
MIN_STIMP = 6.0
MAX_STIMP = 14.0
STIMP_STEP = 0.5
AIM_TRIM_STEP = 0.5
MAX_AIM_TRIM = 10.0            # ± degrees you can bias camera-mode putts
TRACKER_FRESH_SECS = 2.5       # status ping older than this = tracker gone
PREVIEW_FRESH_SECS = 2.0       # webcam frame older than this = feed lost
GUARD_LOW_FPS = FPS * 0.8      # sustained fps below this trips the guard
GUARD_TRIP_SECS = 3.0          # ...for this long before dropping a preset

SETTINGS_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                             "putt_quest_settings.json")


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
    mulligans: int = 0

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
        self.time = 0.0
        self.shots_received = 0

        # juice: sounds, screen shake, sink animation, sand-transition edge
        self.sfx = SFX()
        self.sound_on = True
        self.shake = 0.0
        self._sink_start: Optional[float] = None
        self._in_sand = False

        # display / performance
        self.preset_idx = 0
        self.auto_scale = True
        self._low_fps_time = 0.0
        self._guard_cooldown = 0.0

        # toggles
        self.debug = False
        self.show_minimap = True
        self.camera_monitor = True   # live tracker view w/ zone confirmation

        # tunables surfaced in the in-game settings menu
        self.stimp_override: Optional[float] = None   # None = use course stimp
        self.mercy_limit: int = DEFAULT_MERCY_LIMIT
        # Aim trim: added to every real (camera) putt's HLA. Handy when the
        # mat is too narrow to physically aim off-center. Persists across
        # holes and sessions (mat orientation doesn't change hole-to-hole).
        self.aim_trim_deg: float = 0.0
        self.show_read: bool = False   # draw the pro-read curve on the green

        # settings overlay state
        self.settings_open = False
        self.settings_idx = 0
        # keyboard-shortcut help overlay (H / F1). Not persisted.
        self.show_help = False

        # webcam preview decode cache
        self._pv_seq = -1
        self._pv_surf: Optional[pygame.Surface] = None

        # keyboard test harness
        self.test_mode = False
        self.test_speed = 4.0
        self.test_hla = 0.0
        self._preview: List[tuple] = []
        self._preview_key: Optional[Tuple] = None
        # cache for the camera-mode "read" preview (independent of test mode)
        self._read_path: List[tuple] = []
        self._read_key: Optional[Tuple] = None
        # snapshot of the ball state right before the most recent putt,
        # so `U` (mulligan) can undo it. None = no undo available.
        self._pre_shot: Optional[dict] = None

        self._load_settings()
        self.apply_preset(self.preset_idx, announce=False)

    # ---------------------------------------------------- settings I/O
    def _load_settings(self) -> None:
        try:
            with open(SETTINGS_PATH) as fh:
                data = json.load(fh)
            self.preset_idx = int(data.get("preset_idx", 0))
            self.preset_idx = max(0, min(len(gfx.RES_PRESETS) - 1,
                                         self.preset_idx))
            self.auto_scale = bool(data.get("auto_scale", True))
            self.show_minimap = bool(data.get("show_minimap", True))
            self.camera_monitor = bool(data.get("camera_monitor", True))
            so = data.get("stimp_override")
            if so is not None:
                try:
                    self.stimp_override = max(MIN_STIMP,
                                              min(MAX_STIMP, float(so)))
                except (TypeError, ValueError):
                    self.stimp_override = None
            ml = data.get("mercy_limit", DEFAULT_MERCY_LIMIT)
            try:
                self.mercy_limit = max(MIN_MERCY_LIMIT,
                                       min(MAX_MERCY_LIMIT, int(ml)))
            except (TypeError, ValueError):
                self.mercy_limit = DEFAULT_MERCY_LIMIT
            try:
                trim = float(data.get("aim_trim_deg", 0.0))
                self.aim_trim_deg = max(-MAX_AIM_TRIM,
                                        min(MAX_AIM_TRIM, trim))
            except (TypeError, ValueError):
                self.aim_trim_deg = 0.0
            self.show_read = bool(data.get("show_read", False))
            self.sound_on = bool(data.get("sound_on", True))
        except (OSError, ValueError, TypeError):
            pass

    def _save_settings(self) -> None:
        try:
            with open(SETTINGS_PATH, "w") as fh:
                json.dump({"preset_idx": self.preset_idx,
                           "auto_scale": self.auto_scale,
                           "show_minimap": self.show_minimap,
                           "camera_monitor": self.camera_monitor,
                           "stimp_override": self.stimp_override,
                           "mercy_limit": self.mercy_limit,
                           "aim_trim_deg": self.aim_trim_deg,
                           "show_read": self.show_read,
                           "sound_on": self.sound_on}, fh)
        except OSError:
            pass

    def _snd(self, name: str, volume: float = 1.0) -> None:
        if self.sound_on:
            self.sfx.play(name, volume)

    # ---------------------------------------------------- tunables
    def current_stimp(self) -> float:
        """Effective green speed: manual override if set, else course value."""
        if self.stimp_override is not None:
            return self.stimp_override
        if self.round is not None:
            return self.round.course.stimp
        return 10.0

    def _rebuild_physics(self) -> None:
        """Recreate the physics for the current hole (e.g. after a live
        stimp change) without disturbing the ball position or trail."""
        if self.round is None or self.physics is None:
            return
        h = self.round.hole
        self.physics = GreenPhysics(h.distance_ft, h.break_pct,
                                    h.slope_pct, self.current_stimp(),
                                    features=h.features)
        self._preview_key = None

    # ---------------------------------------------------- resolution
    def apply_preset(self, idx: int, announce: bool = True) -> None:
        idx = max(0, min(len(gfx.RES_PRESETS) - 1, idx))
        self.preset_idx = idx
        label, w, h = gfx.RES_PRESETS[idx]
        self.canvas = gfx.set_internal(w, h)
        # rebuild the 3D scene at the new resolution if we're mid-hole
        if (self.scene is not None and self.round is not None
                and self.physics is not None):
            hole = self.round.hole
            self.scene = GreenScene((w, h), hole.distance_ft * FT_TO_M,
                                    hole.break_pct, hole.slope_pct,
                                    features=hole.features,
                                    theme=self.round.course.theme)
            self.scene.position_camera(self.ball.pos)
        self._guard_cooldown = 2.0
        self._low_fps_time = 0.0
        if announce:
            self.set_banner(f"Resolution: {label}  {w}x{h}")
        self._save_settings()

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
                                    h.slope_pct, self.current_stimp(),
                                    features=h.features)
        self.ball = Ball(0.0, 0.0)
        self.trail = []
        self.scene = GreenScene((gfx.INTERNAL_W, gfx.INTERNAL_H),
                                h.distance_ft * FT_TO_M,
                                h.break_pct, h.slope_pct,
                                features=h.features,
                                theme=self.round.course.theme)
        self.scene.position_camera(self.ball.pos)
        self.state = State.AWAIT_PUTT
        self.last_shot_info = ""
        self._preview_key = None
        self._pre_shot = None       # fresh hole = nothing to undo
        self.set_banner(f"Hole {h.number} — {h.name}")

    def set_banner(self, msg: str, secs: float = 2.5) -> None:
        self.banner = msg
        self.banner_time = secs

    # ----------------------------------------------------------------
    def take_shot(self, speed_mph: float, hla_deg: float) -> None:
        if self.state != State.AWAIT_PUTT or not self.physics:
            return
        score = self.round.scores[self.round.hole_idx]
        # snapshot for mulligan (undo) BEFORE mutating anything
        self._pre_shot = {
            "pos": (self.ball.x, self.ball.y),
            "trail": list(self.trail),
            "last_shot_info": self.last_shot_info,
            "lipped": self.lipped,
        }
        score.putts += 1
        # Camera-mode putts pick up the aim trim; test mode uses the HLA
        # supplied by the caller as-is so W/S/LEFT/RIGHT stay absolute.
        applied_hla = hla_deg
        if not self.test_mode and self.aim_trim_deg:
            applied_hla = hla_deg + self.aim_trim_deg
        self.physics.launch(self.ball, speed_mph, applied_hla)
        self._snd("putt", min(1.0, 0.4 + speed_mph / 8.0))
        self.trail = [self.ball.pos]
        self.lipped = False
        self._in_sand = False
        if applied_hla != hla_deg:
            self.last_shot_info = (f"{speed_mph:.1f} mph  HLA {hla_deg:+.1f}"
                                   f"° + trim {self.aim_trim_deg:+.1f}°")
        else:
            self.last_shot_info = f"{speed_mph:.1f} mph  HLA {hla_deg:+.1f} deg"
        self.state = State.ROLLING

    def mulligan(self) -> bool:
        """Undo the most recent putt: restore ball position, uncount the
        stroke, stop the roll, and go back to AWAIT_PUTT. Only the last
        shot can be undone (one snapshot deep). Returns True on success."""
        if self._pre_shot is None or self.round is None:
            self.set_banner("Nothing to mulligan", 1.5)
            return False
        if self.state not in (State.ROLLING, State.AWAIT_PUTT):
            self.set_banner("Can't mulligan now", 1.5)
            return False
        snap = self._pre_shot
        self._pre_shot = None       # one undo per shot
        score = self.round.scores[self.round.hole_idx]
        score.putts = max(0, score.putts - 1)
        score.mulligans += 1
        px, py = snap["pos"]
        self.ball.x, self.ball.y = px, py
        self.ball.vx = 0.0
        self.ball.vy = 0.0
        self.trail = list(snap["trail"])
        self.last_shot_info = snap["last_shot_info"]
        self.lipped = snap["lipped"]
        self.state = State.AWAIT_PUTT
        self.scene.position_camera(self.ball.pos)
        self._preview_key = None
        self._read_key = None
        self.set_banner(f"Mulligan — putt {score.putts + 1} again", 2.0)
        return True

    def finish_hole(self, holed: bool) -> None:
        score = self.round.scores[self.round.hole_idx]
        if not holed:
            score.picked_up = True
        n = score.putts
        label = {1: "ACE! One-putt!", 2: "Two putts — par.",
                 3: "Three putts."}.get(n, f"{n} putts.")
        if score.picked_up:
            label = f"Picked up after {self.mercy_limit} putts."
        self.set_banner(label, 3.0)
        self.state = State.HOLE_DONE

    def next_hole(self) -> None:
        if self.round.hole_idx + 1 < len(self.round.course.holes):
            self.load_hole(self.round.hole_idx + 1)
        else:
            self._snd("fanfare")
            self.state = State.ROUND_DONE

    # ----------------------------------------------------------------
    def update(self, dt: float) -> None:
        self.time += dt
        if self.banner_time > 0:
            self.banner_time -= dt
        if self.shake > 0:
            self.shake = max(0.0, self.shake - dt * 1.4)
        self._update_guard(dt)

        shot = ShotListener.get_shot()
        if shot:
            self.shots_received += 1
            if self.state == State.AWAIT_PUTT:
                self.take_shot(shot["speed_mph"], shot["hla_deg"])
            else:
                self.set_banner("Shot ignored — not ready", 1.5)

        if self.state == State.ROLLING and self.physics:
            for _ in range(PHYS_SUBSTEPS):
                result = self.physics.step(self.ball, dt / PHYS_SUBSTEPS,
                                           self.time)
                self.trail.append(self.ball.pos)
                # sand entry (rising edge only): soft thud + dust
                if self.scene and self.physics.features is not None:
                    sandy = self.physics._friction_mult(
                        self.ball.x, self.ball.y) > 1.0
                    if sandy and not self._in_sand:
                        self._snd("sand")
                        self.scene.spawn_particles("poof", *self.ball.pos)
                    self._in_sand = sandy
                if result == "lipout":
                    self.lipped = True
                    self._snd("lip")
                    self.set_banner("Lip out!", 1.5)
                elif result == "bounce":
                    self._snd("wall", min(1.0, 0.3 + self.ball.speed / 3.0))
                    self.shake = max(self.shake, 0.08)
                elif result == "bumper":
                    self._snd("bumper")
                    self.shake = max(self.shake, 0.14)
                    if self.scene:
                        self.scene.spawn_particles("spark", *self.ball.pos)
                elif result == "portal":
                    self._snd("portal")
                    if self.scene:
                        self.scene.spawn_particles("shimmer", *self.ball.pos)
                    self.set_banner("Warped!", 1.2)
                elif result == "chute_enter":
                    self._snd("chute")
                    self.set_banner("Down the chute!", 1.2)
                elif result == "windmill":
                    self._snd("windmill")
                    self.shake = max(self.shake, 0.26)
                    if self.scene:
                        self.scene.spawn_particles("spark", *self.ball.pos)
                    self.set_banner("Clang! Off the windmill", 1.2)
                elif result == "water":
                    self._snd("splash")
                    if self.scene:
                        self.scene.spawn_particles("splash", *self.ball.pos)
                    # fished out: replay from where this putt started
                    # (the stroke already counts, like real mini golf)
                    back = (self._pre_shot["pos"] if self._pre_shot
                            else (0.0, 0.0))
                    self.ball.x, self.ball.y = back
                    self.ball.vx = self.ball.vy = 0.0
                    self.state = State.AWAIT_PUTT
                    self.scene.position_camera(self.ball.pos)
                    self._preview_key = None
                    self.set_banner("Splash! Replay from the last spot", 2.5)
                    break
                elif result == "holed":
                    self._snd("sink")
                    self._sink_start = self.time
                    if self.scene:
                        self.scene.spawn_particles(
                            "confetti", *self.physics.hole_pos)
                    self.finish_hole(holed=True)
                    break
                elif result == "stopped":
                    score = self.round.scores[self.round.hole_idx]
                    if score.putts >= self.mercy_limit:
                        self.finish_hole(holed=False)
                    else:
                        d_ft = math.hypot(
                            self.ball.x - self.physics.hole_pos[0],
                            self.ball.y - self.physics.hole_pos[1]) / FT_TO_M
                        self.set_banner(f"{d_ft:.1f} ft left", 2.0)
                        self.state = State.AWAIT_PUTT
                        self.scene.position_camera(self.ball.pos)
                        self._preview_key = None
                    break

    def _update_guard(self, dt: float) -> None:
        """Auto-drop resolution if the frame rate can't keep up, so a high
        preset can never bog the machine down for long."""
        if self._guard_cooldown > 0:
            self._guard_cooldown -= dt
            return
        if not (self.auto_scale and self.state in
                (State.AWAIT_PUTT, State.ROLLING)):
            return
        fps = self.clock.get_fps()
        if 0 < fps < GUARD_LOW_FPS:
            self._low_fps_time += dt
            if self._low_fps_time > GUARD_TRIP_SECS and self.preset_idx > 0:
                self.apply_preset(self.preset_idx - 1, announce=False)
                self.set_banner("Auto-reduced resolution to stay smooth", 3.0)
        else:
            self._low_fps_time = max(0.0, self._low_fps_time - dt)

    # ----------------------------------------------------------------
    def handle_key(self, key: int) -> None:
        # Help overlay grabs input first: any key dismisses it so it can't
        # trap the player. H / F1 / ? toggle it.
        if self.show_help:
            self.show_help = False
            # let ESC/Q still quit even if help was open
            if key == pygame.K_q:
                self.quit()
            return
        if key in (pygame.K_h, pygame.K_F1) or (
                key == pygame.K_SLASH
                and (pygame.key.get_mods() & pygame.KMOD_SHIFT)):
            self.show_help = True
            return

        # Settings overlay swallows everything except its own controls.
        if self.settings_open:
            self._handle_settings_key(key)
            return

        if key == pygame.K_ESCAPE:
            # ESC closes menus, quits otherwise (Q always quits)
            self.quit()
        if key == pygame.K_q:
            self.quit()
        if key in (pygame.K_o, pygame.K_TAB):
            # open the in-game settings menu
            self.settings_open = True
            self.settings_idx = 0
            return
        if key == pygame.K_t:
            self.test_mode = not self.test_mode
            self.set_banner("Test mode " +
                            ("ON — SPACE putts" if self.test_mode else "OFF"))
        if key == pygame.K_d:
            self.debug = not self.debug
        if key == pygame.K_m:
            self.show_minimap = not self.show_minimap
            self._save_settings()
        if key == pygame.K_c:
            self.camera_monitor = not self.camera_monitor
            self.set_banner("Camera monitor " +
                            ("ON" if self.camera_monitor else "OFF"))
            self._save_settings()
        if key in (pygame.K_RIGHTBRACKET, pygame.K_EQUALS, pygame.K_PLUS):
            if self.preset_idx < len(gfx.RES_PRESETS) - 1:
                self.apply_preset(self.preset_idx + 1)
            else:
                self.set_banner("Already at max resolution")
        if key in (pygame.K_LEFTBRACKET, pygame.K_MINUS):
            if self.preset_idx > 0:
                self.apply_preset(self.preset_idx - 1)
            else:
                self.set_banner("Already at min resolution")
        if key == pygame.K_g:
            self.auto_scale = not self.auto_scale
            self._save_settings()
            self.set_banner("Auto-resolution guard "
                            + ("ON" if self.auto_scale else "OFF"))
        if key == pygame.K_u:
            # Mulligan: undo the last putt. Works during the roll or
            # right after the ball settles.
            self.mulligan()
            return

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
        elif self.state == State.AWAIT_PUTT and not self.test_mode:
            # Camera mode: arrows nudge the aim trim so putts can be
            # biased left/right without physically re-aiming on a narrow mat.
            if key == pygame.K_LEFT:
                self._nudge_aim_trim(-AIM_TRIM_STEP)
            elif key == pygame.K_RIGHT:
                self._nudge_aim_trim(+AIM_TRIM_STEP)
            elif key == pygame.K_p:
                self.show_read = not self.show_read
                self._save_settings()
                self.set_banner("Read line "
                                + ("ON" if self.show_read else "OFF"))
            elif key == pygame.K_x:
                if self.aim_trim_deg != 0.0:
                    self.aim_trim_deg = 0.0
                    self._read_key = None
                    self._save_settings()
                    self.set_banner("Aim trim reset to 0°")
        elif self.state == State.HOLE_DONE:
            if key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE):
                self.next_hole()
        elif self.state == State.ROUND_DONE:
            if key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                self.state = State.MENU

    def _nudge_aim_trim(self, delta: float) -> None:
        new = self.aim_trim_deg + delta
        # snap to the step grid so repeated presses don't drift
        new = round(new / AIM_TRIM_STEP) * AIM_TRIM_STEP
        new = max(-MAX_AIM_TRIM, min(MAX_AIM_TRIM, new))
        if new != self.aim_trim_deg:
            self.aim_trim_deg = new
            self._read_key = None      # invalidate cached read curve
            self._save_settings()

    # ---------------------------------------------- settings overlay
    # Each row: (label, value_getter, kind, hint). `kind` drives editing:
    #   "float"  = LEFT/RIGHT change by step (stimp)
    #   "int"    = LEFT/RIGHT change by 1 (mercy limit)
    #   "choice" = LEFT/RIGHT cycle choices (resolution)
    #   "toggle" = ENTER / LEFT / RIGHT flip a bool
    #   "action" = ENTER runs an action
    def _settings_rows(self) -> List[Tuple[str, str, str, str]]:
        rows: List[Tuple[str, str, str, str]] = []
        stimp_val = f"{self.current_stimp():.1f} ft"
        if self.stimp_override is not None:
            stimp_val += "  (override)"
        rows.append(("Green Speed (Stimp)", stimp_val, "float",
                     f"LEFT/RIGHT ±{STIMP_STEP} — bigger = faster green"))
        rows.append(("Mercy Limit", f"{self.mercy_limit} putts", "int",
                     "auto pick-up after this many strokes"))
        rows.append(("Aim Trim (camera mode)",
                     f"{self.aim_trim_deg:+.1f}°", "float",
                     "LEFT/RIGHT bias for real putts (narrow-mat helper)"))
        rows.append(("Show Read Line",
                     "ON" if self.show_read else "OFF", "toggle",
                     "ghost curve of a well-struck putt at good pace"))
        snd_val = ("ON" if self.sound_on else "OFF")
        if not self.sfx.enabled:
            snd_val = "no audio device"
        rows.append(("Sound Effects", snd_val, "toggle",
                     "synthesized SFX: putts, rails, windmill, splash..."))
        rows.append(("Resolution",
                     gfx.RES_PRESETS[self.preset_idx][0], "choice",
                     "internal render size (also on [ and ])"))
        rows.append(("Auto FPS Guard",
                     "ON" if self.auto_scale else "OFF", "toggle",
                     "auto-drops preset if fps sags"))
        rows.append(("Camera Monitor",
                     "ON" if self.camera_monitor else "OFF", "toggle",
                     "live webcam panel in the corner"))
        rows.append(("Minimap",
                     "ON" if self.show_minimap else "OFF", "toggle",
                     "top-down mini view of the green"))
        rows.append(("Debug Overlay",
                     "ON" if self.debug else "OFF", "toggle",
                     "fps + physics + shot log (also key D)"))
        rows.append(("Reset stimp to course default",
                     "" if self.stimp_override is None else "override active",
                     "action", "restore the course's own green speed"))
        rows.append(("Reset aim trim to 0°",
                     "" if self.aim_trim_deg == 0.0 else "trim active",
                     "action", "clear the manual aim bias (also key X)"))
        rows.append(("Mulligan (undo last putt)",
                     "available" if self._pre_shot is not None else "none",
                     "action",
                     "un-count the last stroke and re-putt (also key U)"))
        rows.append(("Help / Keyboard Shortcuts", "H", "action",
                     "pop up the full shortcut reference"))
        rows.append(("Close (ESC / O)", "", "action",
                     "back to the game"))
        return rows

    def _handle_settings_key(self, key: int) -> None:
        rows = self._settings_rows()
        n = len(rows)
        if key in (pygame.K_ESCAPE, pygame.K_o, pygame.K_TAB):
            self.settings_open = False
            self._save_settings()
            return
        if key == pygame.K_UP:
            self.settings_idx = (self.settings_idx - 1) % n
            return
        if key == pygame.K_DOWN:
            self.settings_idx = (self.settings_idx + 1) % n
            return
        idx = self.settings_idx
        label, _val, kind, _hint = rows[idx]
        delta = 0
        if key in (pygame.K_LEFT, pygame.K_a):
            delta = -1
        elif key in (pygame.K_RIGHT, pygame.K_d):
            delta = 1
        enter = key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE)

        if label.startswith("Green Speed"):
            if delta:
                base = self.current_stimp()
                new = base + STIMP_STEP * delta
                # snap to STIMP_STEP grid
                new = round(new / STIMP_STEP) * STIMP_STEP
                new = max(MIN_STIMP, min(MAX_STIMP, new))
                self.stimp_override = new
                self._rebuild_physics()
                self._save_settings()
        elif label.startswith("Mercy"):
            if delta:
                self.mercy_limit = max(MIN_MERCY_LIMIT,
                                       min(MAX_MERCY_LIMIT,
                                           self.mercy_limit + delta))
                self._save_settings()
        elif label.startswith("Aim Trim"):
            if delta:
                self._nudge_aim_trim(AIM_TRIM_STEP * delta)
        elif label.startswith("Show Read"):
            if enter or delta:
                self.show_read = not self.show_read
                self._save_settings()
        elif label.startswith("Sound Effects"):
            if enter or delta:
                self.sound_on = not self.sound_on
                if self.sound_on:
                    self._snd("sink")      # audible confirmation
                self._save_settings()
        elif label.startswith("Resolution"):
            if delta:
                target = max(0, min(len(gfx.RES_PRESETS) - 1,
                                    self.preset_idx + delta))
                if target != self.preset_idx:
                    self.apply_preset(target, announce=False)
        elif label.startswith("Auto FPS Guard"):
            if enter or delta:
                self.auto_scale = not self.auto_scale
                self._save_settings()
        elif label.startswith("Camera Monitor"):
            if enter or delta:
                self.camera_monitor = not self.camera_monitor
                self._save_settings()
        elif label.startswith("Minimap"):
            if enter or delta:
                self.show_minimap = not self.show_minimap
                self._save_settings()
        elif label.startswith("Debug"):
            if enter or delta:
                self.debug = not self.debug
        elif label.startswith("Reset stimp"):
            if enter:
                self.stimp_override = None
                self._rebuild_physics()
                self._save_settings()
        elif label.startswith("Reset aim trim"):
            if enter and self.aim_trim_deg != 0.0:
                self.aim_trim_deg = 0.0
                self._read_key = None
                self._save_settings()
        elif label.startswith("Mulligan"):
            if enter:
                self.settings_open = False
                self.mulligan()
        elif label.startswith("Help"):
            if enter:
                self.settings_open = False
                self.show_help = True
        elif label.startswith("Close"):
            if enter:
                self.settings_open = False
                self._save_settings()

    def draw_settings_overlay(self) -> None:
        c = self.canvas
        W, H = gfx.INTERNAL_W, gfx.INTERNAL_H
        # dim the game behind the panel
        dim = pygame.Surface((W, H), pygame.SRCALPHA)
        dim.fill((0, 0, 0, 170))
        c.blit(dim, (0, 0))

        pw = gfx.sc(400)
        ph = gfx.sc(330)
        panel_rect = pygame.Rect(W // 2 - pw // 2, H // 2 - ph // 2, pw, ph)
        gfx.panel(c, panel_rect, alpha=235)
        pygame.draw.rect(c, gfx.ACCENT, panel_rect, 1,
                         border_radius=gfx.sc(6))

        gfx.text(c, "SETTINGS", panel_rect.centerx,
                 panel_rect.y + gfx.sc(8), gfx.ACCENT, 26,
                 center=True, shadow=True)

        rows = self._settings_rows()
        row_h = gfx.sc(22)
        top = panel_rect.y + gfx.sc(40)
        for i, (label, value, _kind, _hint) in enumerate(rows):
            y = top + i * row_h
            sel = (i == self.settings_idx)
            if sel:
                sel_rect = pygame.Rect(panel_rect.x + gfx.sc(6), y - gfx.sc(2),
                                       pw - gfx.sc(12), row_h)
                pygame.draw.rect(c, (40, 60, 44), sel_rect,
                                 border_radius=gfx.sc(4))
                pygame.draw.rect(c, gfx.ACCENT, sel_rect, 1,
                                 border_radius=gfx.sc(4))
            col = gfx.ACCENT if sel else gfx.HUD_TEXT
            gfx.text(c, label, panel_rect.x + gfx.sc(16), y, col, 15)
            if value:
                vw = gfx.text_w(value, 15)
                gfx.text(c, value, panel_rect.right - gfx.sc(16) - vw, y,
                         col, 15)

        # hint / help footer
        _, _, _, hint = rows[self.settings_idx]
        gfx.text(c, hint, panel_rect.centerx,
                 panel_rect.bottom - gfx.sc(34), gfx.INFO, 13, center=True)
        gfx.text(c, "UP/DOWN move · LEFT/RIGHT change · ENTER toggle · H help · ESC/O close",
                 panel_rect.centerx, panel_rect.bottom - gfx.sc(18),
                 gfx.HUD_DIM, 13, center=True)

    # ---------------------------------------------- help overlay
    def draw_help_overlay(self) -> None:
        """Modal keyboard-shortcut reference. Any key dismisses it."""
        c = self.canvas
        W, H = gfx.INTERNAL_W, gfx.INTERNAL_H
        dim = pygame.Surface((W, H), pygame.SRCALPHA)
        dim.fill((0, 0, 0, 200))
        c.blit(dim, (0, 0))

        pw = gfx.sc(540)
        ph = gfx.sc(430)
        panel_rect = pygame.Rect(W // 2 - pw // 2, H // 2 - ph // 2, pw, ph)
        gfx.panel(c, panel_rect, alpha=240)
        pygame.draw.rect(c, gfx.ACCENT, panel_rect, 1,
                         border_radius=gfx.sc(6))

        gfx.text(c, "KEYBOARD SHORTCUTS", panel_rect.centerx,
                 panel_rect.y + gfx.sc(10), gfx.ACCENT, 24,
                 center=True, shadow=True)

        # Two columns of grouped shortcuts. Each entry is (key, label).
        sections = [
            ("Menu", [
                ("ENTER", "start selected course"),
                ("UP/DOWN", "pick course"),
                ("O / TAB", "settings"),
                ("H / F1 / ?", "this help"),
                ("Q / ESC", "quit"),
            ]),
            ("Gameplay (camera mode)", [
                ("LEFT / RIGHT", "aim trim \u00b10.5\u00b0"),
                ("P", "toggle read line"),
                ("X", "reset aim trim to 0\u00b0"),
                ("U", "mulligan (undo last putt)"),
                ("O / TAB", "settings"),
                ("H / F1", "help"),
                ("R", "restart current course"),
                ("ENTER", "next hole (after holed)"),
            ]),
            ("Test mode (T)", [
                ("SPACE", "fire test putt"),
                ("W / S", "\u00b10.25 mph speed"),
                ("LEFT / RIGHT", "\u00b10.5\u00b0 test HLA"),
                ("T", "leave test mode"),
            ]),
            ("Display / debug", [
                ("D", "debug overlay"),
                ("M", "minimap"),
                ("C", "camera monitor"),
                ("G", "auto-FPS guard"),
                ("[ / ]", "resolution down / up"),
            ]),
        ]

        col_w = (pw - gfx.sc(40)) // 2
        col_x = [panel_rect.x + gfx.sc(20),
                 panel_rect.x + gfx.sc(20) + col_w]
        col_y = [panel_rect.y + gfx.sc(46),
                 panel_rect.y + gfx.sc(46)]
        for i, (title, items) in enumerate(sections):
            col = i % 2
            x = col_x[col]
            y = col_y[col]
            gfx.text(c, title, x, y, gfx.ACCENT, 15)
            y += gfx.sc(18)
            for k, lbl in items:
                gfx.text(c, k, x, y, gfx.HUD_TEXT, 13)
                gfx.text(c, lbl, x + gfx.sc(90), y, gfx.HUD_DIM, 13)
                y += gfx.sc(15)
            y += gfx.sc(6)
            col_y[col] = y

        # Ball tracker window has its own reference
        note_y = max(col_y) + gfx.sc(4)
        if note_y < panel_rect.bottom - gfx.sc(38):
            gfx.text(c, "Tracker window: A advanced settings  \u00b7  "
                        "D HSV color tuner  \u00b7  Q quit",
                     panel_rect.centerx, note_y, gfx.INFO, 12, center=True)

        gfx.text(c, "press any key to close",
                 panel_rect.centerx, panel_rect.bottom - gfx.sc(20),
                 gfx.HUD_DIM, 13, center=True)

    # ------------------------------------------------- tracker status
    def tracker_line(self) -> Tuple[str, tuple]:
        msg, col, _frac, _ready = self.tracker_badge()
        return msg, col

    def tracker_badge(self) -> Tuple[str, tuple, float, bool]:
        """(message, color, lock_fraction, ready?) for the setup indicator."""
        age, st = ShotListener.get_tracker_status()
        if not self.listener_ok:
            return "PORT 8888 BUSY", gfx.BAD, 0.0, False
        if age is None or age > TRACKER_FRESH_SECS:
            return "TRACKER OFFLINE", gfx.HUD_DIM, 0.0, False
        lock = 0.0
        try:
            lock = float(st.get("lock", 0.0) or 0.0)
        except (TypeError, ValueError):
            pass
        if st.get("balldetected"):
            return "BALL READY", gfx.GOOD, 1.0, True
        if st.get("locking"):
            return f"LOCKING {int(lock * 100)}%", gfx.WARN, lock, False
        return "NO BALL DETECTED", gfx.BAD, 0.0, False

    def _get_preview_surface(self):
        age, jpg, meta, seq = ShotListener.get_preview()
        if jpg is None:
            return None, meta, age
        if seq != self._pv_seq:
            try:
                self._pv_surf = pygame.image.load(io.BytesIO(jpg)).convert()
            except (pygame.error, ValueError):
                self._pv_surf = None
            self._pv_seq = seq
        return self._pv_surf, meta, age

    # ----------------------------------------------------------------
    def _test_preview(self) -> List[tuple]:
        key = (round(self.test_speed, 3), round(self.test_hla, 2),
               round(self.ball.x, 3), round(self.ball.y, 3))
        if key != self._preview_key:
            r = self.physics.simulate(self.ball.pos, self.test_speed,
                                      self.test_hla, dt=1 / 120.0)
            self._preview = r.path[::4]
            self._preview_key = key
        return self._preview

    def _read_preview(self) -> List[tuple]:
        """Ghost path a well-struck putt would take at suggested pace with
        the current aim trim. This is the 'pro read' overlay."""
        if self.physics is None or self.round is None:
            return []
        h = self.round.hole
        d_ft = math.hypot(self.ball.x - self.physics.hole_pos[0],
                          self.ball.y - self.physics.hole_pos[1]) / FT_TO_M
        pace = suggest_speed_mph(d_ft, h.slope_pct, self.current_stimp())
        key = (round(pace, 3), round(self.aim_trim_deg, 2),
               round(self.ball.x, 3), round(self.ball.y, 3),
               round(self.current_stimp(), 2))
        if key != self._read_key:
            r = self.physics.simulate(self.ball.pos, pace,
                                      self.aim_trim_deg, dt=1 / 120.0)
            self._read_path = r.path[::4]
            self._read_key = key
        return self._read_path

    # ----------------------------------------------------------------
    def draw(self) -> None:
        if self.state == State.MENU:
            self.draw_menu()
        elif self.state == State.ROUND_DONE:
            self.draw_scorecard()
        else:
            self.draw_hole()
        self.draw_perf_readout()
        if self.debug:
            self.draw_debug()
        # live tracker monitor: ball view + zone confirmation. Shown on the
        # menu and during play so setup can be verified without leaving the game
        if self.state != State.ROUND_DONE and (self.camera_monitor or self.debug):
            self.draw_camera_panel()
        # settings menu sits on top of everything else
        if self.settings_open:
            self.draw_settings_overlay()
        # help overlay sits above even the settings menu
        if self.show_help:
            self.draw_help_overlay()
        if self.shake > 0.005:
            amp = self.shake * gfx.sc(9)
            offset = (int(_random.uniform(-amp, amp)),
                      int(_random.uniform(-amp, amp)))
        else:
            offset = (0, 0)
        gfx.blit_scaled(self.win, self.canvas, offset)
        pygame.display.flip()

    # ------------------------------------------------------------ menu
    def draw_menu(self) -> None:
        c = self.canvas
        W, H = gfx.INTERNAL_W, gfx.INTERNAL_H
        c.fill(gfx.HUD_BG)
        stripe = gfx.sc(24)
        for i in range(0, H, stripe):
            pygame.draw.rect(c, (14, 24, 16) if (i // stripe) % 2 else
                             gfx.HUD_BG, (0, i, W, stripe))
        gfx.text(c, "PUTT QUEST", W // 2, gfx.sc(34), gfx.ACCENT, 52,
                 center=True, shadow=True)
        gfx.text(c, "webcam putting challenge — 3D", W // 2, gfx.sc(78),
                 gfx.HUD_DIM, 18, center=True)

        for i, course in enumerate(COURSES):
            sel = (i == self.menu_idx)
            rect = pygame.Rect(W // 2 - gfx.sc(170), gfx.sc(112 + i * 52),
                               gfx.sc(340), gfx.sc(44))
            gfx.panel(c, rect, alpha=220 if sel else 140)
            if sel:
                pygame.draw.rect(c, gfx.ACCENT, rect, 1,
                                 border_radius=gfx.sc(6))
            col = gfx.ACCENT if sel else gfx.HUD_TEXT
            gfx.text(c, course.name, rect.x + gfx.sc(14), rect.y + gfx.sc(7),
                     col, 22)
            gfx.text(c, f"stimp {course.stimp:.0f}   par {course.par}   "
                        f"{len(course.holes)} holes",
                     rect.x + gfx.sc(14), rect.y + gfx.sc(26), gfx.HUD_DIM, 15)

        foot = pygame.Rect(W // 2 - gfx.sc(220), H - gfx.sc(66),
                           gfx.sc(440), gfx.sc(40))
        gfx.panel(c, foot, alpha=200)
        lst_col = gfx.GOOD if self.listener_ok else gfx.BAD
        lst_msg = ("listening on :8888" if self.listener_ok
                   else "PORT 8888 BUSY — close the GSPro connector")
        gfx.status_dot(c, foot.x + gfx.sc(14), foot.y + gfx.sc(12), lst_col)
        gfx.text(c, lst_msg, foot.x + gfx.sc(24), foot.y + gfx.sc(6),
                 lst_col, 15)
        msg, col = self.tracker_line()
        gfx.status_dot(c, foot.x + gfx.sc(14), foot.y + gfx.sc(29), col)
        gfx.text(c, msg, foot.x + gfx.sc(24), foot.y + gfx.sc(23), col, 15)

        gfx.text(c, "ENTER play   O settings   H help   T test   C camera   "
                    "[ ] resolution   D debug   Q quit",
                 W // 2, H - gfx.sc(18), gfx.HUD_DIM, 15, center=True)

    # ------------------------------------------------------------ hole
    def draw_hole(self) -> None:
        c = self.canvas
        W, H = gfx.INTERNAL_W, gfx.INTERNAL_H
        h = self.round.hole

        aim = None
        preview: List[tuple] = []
        if self.state == State.AWAIT_PUTT:
            if self.test_mode:
                aim = (self.ball.pos, self.test_hla)
                preview = self._test_preview()
            else:
                # camera mode: aim line follows the manual trim; optional
                # "read" curve shows where a well-struck putt would go
                aim = (self.ball.pos, self.aim_trim_deg)
                if self.show_read:
                    preview = self._read_preview()
        ball_pos = None if self.state == State.HOLE_DONE else self.ball.pos
        ball_scale = 1.0
        if (self.state == State.HOLE_DONE and self._sink_start is not None):
            # sink animation: the ball shrinks into the cup for ~0.45s
            frac = (self.time - self._sink_start) / 0.45
            if frac < 1.0:
                ball_pos = self.physics.hole_pos
                ball_scale = max(0.05, 1.0 - frac)
        self.scene.draw(c, ball_pos, trail=self.trail[::3], t=self.time,
                        aim=aim, preview=preview, ball_scale=ball_scale)

        # minimap (hidden when the camera panel occupies that corner)
        if self.show_minimap and not (self.debug or self.camera_monitor):
            mm = pygame.Rect(W - gfx.sc(106), gfx.sc(8),
                             gfx.sc(98), gfx.sc(132))
            self.scene.draw_minimap(c, mm, ball_pos, self.trail[::3])

        # header panel
        score = self.round.scores[self.round.hole_idx]
        head = pygame.Rect(gfx.sc(6), gfx.sc(6), gfx.sc(250), gfx.sc(62))
        gfx.panel(c, head)
        gfx.text(c, f"Hole {h.number} — {h.name}", head.x + gfx.sc(10),
                 head.y + gfx.sc(6), gfx.HUD_TEXT, 20)
        gfx.text(c, h.blurb, head.x + gfx.sc(10), head.y + gfx.sc(25),
                 gfx.HUD_DIM, 15)
        if self.state != State.HOLE_DONE:
            d_ft = math.hypot(self.ball.x - self.physics.hole_pos[0],
                              self.ball.y - self.physics.hole_pos[1]) / FT_TO_M
            hint = suggest_speed_mph(d_ft, h.slope_pct,
                                     self.round.course.stimp)
            gfx.text(c, f"{d_ft:.1f} ft to the cup — pace ~{hint:.1f} mph",
                     head.x + gfx.sc(10), head.y + gfx.sc(42), gfx.INFO, 15)

        # score chip (drop below the minimap when it's shown)
        panel_corner = self.debug or self.camera_monitor
        chip_y = gfx.sc(146) if (self.show_minimap and not panel_corner) else gfx.sc(8)
        if panel_corner:
            chip_y = gfx.sc(212)     # drop below the camera monitor
        chip = pygame.Rect(W - gfx.sc(106), chip_y, gfx.sc(98), gfx.sc(40))
        gfx.panel(c, chip)
        gfx.text(c, f"putt {score.putts + (self.state == State.AWAIT_PUTT)}",
                 chip.x + gfx.sc(10), chip.y + gfx.sc(5), gfx.HUD_TEXT, 17)
        gfx.text(c, f"total {self.round.total}", chip.x + gfx.sc(10),
                 chip.y + gfx.sc(22), gfx.HUD_DIM, 15)

        # BIG ball-ready badge during setup (camera mode only)
        if self.state == State.AWAIT_PUTT and not self.test_mode:
            self.draw_ready_badge()

        # bottom status bar
        bar = pygame.Rect(gfx.sc(6), H - gfx.sc(30), W - gfx.sc(12), gfx.sc(24))
        gfx.panel(c, bar, alpha=200)
        if self.test_mode and self.state == State.AWAIT_PUTT:
            gfx.text(c, f"TEST  W/S speed {self.test_speed:.2f} mph    "
                        f"LEFT/RIGHT HLA {self.test_hla:+.1f} deg    "
                        "SPACE putt", bar.x + gfx.sc(10), bar.y + gfx.sc(5),
                     gfx.ACCENT, 15)
        elif self.state == State.HOLE_DONE:
            gfx.text(c, "ENTER for next hole", bar.x + gfx.sc(10),
                     bar.y + gfx.sc(5), gfx.HUD_TEXT, 15)
        elif self.state == State.ROLLING:
            mph = self.ball.speed / 0.44704
            gfx.text(c, f"rolling...  {mph:.1f} mph", bar.x + gfx.sc(10),
                     bar.y + gfx.sc(5), gfx.HUD_TEXT, 15)
        else:
            trim_bit = ""
            if self.aim_trim_deg:
                trim_bit = f"   aim trim {self.aim_trim_deg:+.1f}°"
            read_bit = "   read ON" if self.show_read else ""
            gfx.text(c, "waiting for putt from camera   "
                        "LEFT/RIGHT aim   P read   X reset   U mulligan   H help"
                        + trim_bit + read_bit,
                     bar.x + gfx.sc(10), bar.y + gfx.sc(5),
                     gfx.ACCENT if self.aim_trim_deg else gfx.HUD_DIM, 15)
        if self.last_shot_info:
            gfx.text(c, self.last_shot_info,
                     bar.right - gfx.sc(10) - gfx.text_w(self.last_shot_info, 15),
                     bar.y + gfx.sc(5), gfx.HUD_DIM, 15)

        # banner
        if self.banner_time > 0 and self.banner:
            bw = gfx.text_w(self.banner, 30) + gfx.sc(30)
            br = pygame.Rect(W // 2 - bw // 2, gfx.sc(84), bw, gfx.sc(34))
            gfx.panel(c, br, alpha=200)
            gfx.text(c, self.banner, W // 2, br.y + gfx.sc(7), gfx.ACCENT, 30,
                     center=True, shadow=True)

    def draw_ready_badge(self) -> None:
        """Large, unmissable indicator of whether the physical ball is
        recognized and locked. Green + pulsing = safe to putt. Sits just
        above the status bar so it never hides the hole."""
        c = self.canvas
        W, H = gfx.INTERNAL_W, gfx.INTERNAL_H
        msg, col, frac, ready = self.tracker_badge()
        bw = max(gfx.sc(200), gfx.text_w(msg, 22) + gfx.sc(48))
        bh = gfx.sc(40)
        rect = pygame.Rect(W // 2 - bw // 2, H - gfx.sc(30) - bh - gfx.sc(6),
                           bw, bh)
        pulse = int(45 * (0.5 + 0.5 * math.sin(self.time * 6))) if ready else 0
        gfx.panel(c, rect, alpha=205)
        pygame.draw.rect(c, col, rect, 2, border_radius=gfx.sc(6))
        if ready and pulse:
            glow = pygame.Surface(rect.size, pygame.SRCALPHA)
            pygame.draw.rect(glow, (*col, pulse), glow.get_rect(), 3,
                             border_radius=gfx.sc(6))
            c.blit(glow, rect.topleft)
        gfx.status_dot(c, rect.x + gfx.sc(18), rect.centery, col, r=6)
        gfx.text(c, msg, rect.x + gfx.sc(34), rect.y + gfx.sc(6), col, 22,
                 shadow=True)
        if 0.0 < frac < 1.0:
            barr = pygame.Rect(rect.x + gfx.sc(12), rect.bottom - gfx.sc(8),
                               rect.w - gfx.sc(24), gfx.sc(4))
            gfx.progress_bar(c, barr, frac, col)

    # ------------------------------------------------- perf readout
    def draw_perf_readout(self) -> None:
        c = self.canvas
        label, w, h = gfx.RES_PRESETS[self.preset_idx]
        fps = self.clock.get_fps()
        txt = f"{w}x{h} · {fps:4.0f} fps · guard {'on' if self.auto_scale else 'off'}"
        col = gfx.GOOD if fps >= GUARD_LOW_FPS else gfx.WARN
        pad = gfx.sc(4)
        tw = gfx.text_w(txt, 13)
        x = gfx.INTERNAL_W - tw - gfx.sc(6)
        y = gfx.INTERNAL_H - gfx.sc(44)
        r = pygame.Rect(x - pad, y - pad, tw + 2 * pad, gfx.sc(15) + pad)
        gfx.panel(c, r, alpha=150)
        gfx.text(c, txt, x, y, col, 13)

    # ------------------------------------------------------- scorecard
    def draw_scorecard(self) -> None:
        c = self.canvas
        W, H = gfx.INTERNAL_W, gfx.INTERNAL_H
        r = self.round
        c.fill(gfx.HUD_BG)
        gfx.text(c, "SCORECARD", W // 2, gfx.sc(30), gfx.ACCENT, 40,
                 center=True, shadow=True)
        gfx.text(c, r.course.name, W // 2, gfx.sc(66), gfx.HUD_DIM, 18,
                 center=True)

        n = len(r.scores)
        bw = gfx.sc(52)
        x0 = W // 2 - (n * bw) // 2
        for i, s in enumerate(r.scores):
            box = pygame.Rect(x0 + i * bw + gfx.sc(3), gfx.sc(100),
                              bw - gfx.sc(6), gfx.sc(74))
            gfx.panel(c, box, alpha=170)
            gfx.text(c, f"{s.hole.number}", box.centerx, box.y + gfx.sc(6),
                     gfx.HUD_DIM, 15, center=True)
            col = (gfx.GOOD if s.strokes == 1 else
                   gfx.HUD_TEXT if s.strokes <= s.hole.par else gfx.BAD)
            label = f"{s.strokes}" + ("*" if s.picked_up else "") + (
                "\u2020" if s.mulligans else "")
            gfx.text(c, label, box.centerx, box.y + gfx.sc(24), col, 28,
                     center=True)
            gfx.text(c, f"{s.hole.distance_ft:.0f}ft", box.centerx,
                     box.y + gfx.sc(54), gfx.HUD_DIM, 13, center=True)

        total, par = r.total, r.course.par
        diff = total - par
        rel = "E" if diff == 0 else (f"+{diff}" if diff > 0 else str(diff))
        gfx.text(c, f"TOTAL {total}   (par {par}, {rel})", W // 2, gfx.sc(200),
                 gfx.HUD_TEXT, 26, center=True)
        if any(s.picked_up for s in r.scores):
            gfx.text(c, "* picked up", W // 2, gfx.sc(228), gfx.HUD_DIM, 14,
                     center=True)
        if any(s.mulligans for s in r.scores):
            gfx.text(c, "\u2020 mulligan used", W // 2, gfx.sc(244),
                     gfx.HUD_DIM, 14, center=True)
        gfx.text(c, "ENTER menu    R replay course", W // 2, H - gfx.sc(34),
                 gfx.HUD_DIM, 16, center=True)

    # ----------------------------------------------------------- debug
    def draw_debug(self) -> None:
        c = self.canvas
        rect = pygame.Rect(gfx.sc(6), gfx.sc(76), gfx.sc(300), gfx.sc(190))
        gfx.panel(c, rect, alpha=215)
        x, y = rect.x + gfx.sc(10), rect.y + gfx.sc(8)

        def line(msg, col=gfx.HUD_TEXT):
            nonlocal y
            gfx.text(c, msg, x, y, col, 14)
            y += gfx.sc(15)

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
                 f"lock={st.get('lock', '?')}  "
                 f"r={st.get('ballradius', '?')}  fps={st.get('fps', '?')}",
                 gfx.GOOD if age < TRACKER_FRESH_SECS else gfx.BAD)
        line("recent requests:", gfx.HUD_DIM)
        events = ShotListener.get_events()
        if not events:
            line("  (none yet)", gfx.HUD_DIM)
        for ts, msg in events[:5]:
            line(f"  {time.strftime('%H:%M:%S', time.localtime(ts))} "
                 f"{msg[:38]}", gfx.INFO)

    def draw_camera_panel(self) -> None:
        """Live tracker monitor: the annotated camera view (start zone,
        gateway and ball circle are drawn by ball_tracking.py) plus a bold
        ready/lock border, putt direction and camera fps."""
        c = self.canvas
        W = gfx.INTERNAL_W
        pw, ph = gfx.sc(236), gfx.sc(200)
        rect = pygame.Rect(W - pw - gfx.sc(6), gfx.sc(6), pw, ph)
        gfx.panel(c, rect, alpha=210)
        surf, meta, age = self._get_preview_surface()

        img_area = pygame.Rect(rect.x + gfx.sc(4), rect.y + gfx.sc(4),
                               rect.w - gfx.sc(8), rect.h - gfx.sc(40))
        if surf is not None and age is not None and age < PREVIEW_FRESH_SECS:
            iw, ih = surf.get_size()
            scale = min(img_area.w / iw, img_area.h / ih)
            dw, dh = max(1, int(iw * scale)), max(1, int(ih * scale))
            scaled = pygame.transform.smoothscale(surf, (dw, dh))
            ix = img_area.x + (img_area.w - dw) // 2
            iy = img_area.y + (img_area.h - dh) // 2
            c.blit(scaled, (ix, iy))
            ready = bool(meta.get("ready"))
            state = str(meta.get("state", ""))
            try:
                lock = float(meta.get("lock", 0.0) or 0.0)
            except (TypeError, ValueError):
                lock = 0.0
            if ready:
                bcol, blabel = gfx.GOOD, "BALL READY"
            elif state == "locking":
                bcol, blabel = gfx.WARN, f"LOCKING {int(lock*100)}%"
            elif state in ("rolling", "shot"):
                bcol, blabel = gfx.INFO, "TRACKING PUTT"
            else:
                bcol, blabel = gfx.BAD, "NO BALL"
            pygame.draw.rect(c, bcol, (ix, iy, dw, dh), gfx.sc(3))
            lw = gfx.text_w(blabel, 15)
            gfx.status_dot(c, rect.centerx - lw // 2 - gfx.sc(8),
                           rect.bottom - gfx.sc(30), bcol, r=4)
            gfx.text(c, blabel, rect.centerx + gfx.sc(4),
                     rect.bottom - gfx.sc(36), bcol, 15, center=True)
            info = "putt dir %s   ·   cam %s fps" % (
                meta.get("dir", "?"), meta.get("fps", "?"))
            gfx.text(c, info, rect.centerx, rect.bottom - gfx.sc(18),
                     gfx.HUD_DIM, 13, center=True)
        else:
            gfx.text(c, "CAMERA", rect.centerx, img_area.y + gfx.sc(6),
                     gfx.HUD_DIM, 15, center=True)
            reason = ("no preview — start ball_tracking.py"
                      if age is None else "camera feed lost")
            gfx.text(c, reason, rect.centerx, img_area.centery,
                     gfx.HUD_DIM, 12, center=True)
            gfx.text(c, "(previewstream=1 in config.ini)", rect.centerx,
                     rect.bottom - gfx.sc(16), gfx.HUD_DIM, 11, center=True)

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
