"""Putt Quest — single-executable entry point.

One binary that does everything, so a player can download one file, double
click it, and putt. It shows a small launcher menu:

    PLAY          start the ball tracker + the game together
    CALIBRATE     camera exposure / ball colour wizard
    SETUP ZONE    drag the start zone, auto-detect putt direction
    GAME ONLY     keyboard test mode, no camera

The tracker (ball_tracking.py) and the calibration tools are OpenCV
scripts with their own main loops, so they are run as *child processes* of
this same executable via a hidden `--run <tool>` flag. That keeps one exe
while letting each tool own its window and event loop.

Run modes (also usable from the command line):
    PuttQuest.exe                 launcher menu
    PuttQuest.exe --play          tracker + game, no menu
    PuttQuest.exe --game          game only
    PuttQuest.exe --run tracker   internal: exec ball_tracking.py
    PuttQuest.exe --run setup     internal: exec setup_gui.py
    PuttQuest.exe --run calibrate internal: exec calibrate_gui.py
"""

from __future__ import annotations

import argparse
import os
import runpy
import shutil
import subprocess
import sys
import time

# tool name -> bundled script
TOOLS = {
    "tracker": "ball_tracking.py",
    "setup": "setup_gui.py",
    "calibrate": "calibrate_gui.py",
}
# files the tools expect to find in the working directory
RUNTIME_FILES = ("config.ini", "error.png", "Camera-Putting-Alignment.png")


def frozen() -> bool:
    return getattr(sys, "frozen", False)


def bundle_dir() -> str:
    """Where the bundled read-only resources live."""
    if frozen():
        return getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def app_dir() -> str:
    """Writable directory next to the executable: config, replays, settings.
    Falls back to the user's home if the exe sits somewhere read-only."""
    base = (os.path.dirname(sys.executable) if frozen()
            else os.path.dirname(os.path.abspath(__file__)))
    probe = os.path.join(base, ".write_test")
    try:
        with open(probe, "w") as fh:
            fh.write("ok")
        os.remove(probe)
        return base
    except OSError:
        home = os.path.join(os.path.expanduser("~"), "PuttQuest")
        os.makedirs(home, exist_ok=True)
        return home


def prepare_workdir() -> str:
    """Make a writable home for config/replays and seed it on first run."""
    work = app_dir()
    src = bundle_dir()
    for name in RUNTIME_FILES:
        dst = os.path.join(work, name)
        if os.path.exists(dst):
            continue
        for candidate in (name, "config-defaults.ini" if
                          name == "config.ini" else name):
            s = os.path.join(src, candidate)
            if os.path.exists(s):
                try:
                    shutil.copyfile(s, dst)
                except OSError:
                    pass
                break
    os.chdir(work)
    return work


def run_tool(tool: str, argv: list) -> int:
    """Execute a bundled OpenCV script in-process as if it were __main__."""
    script = TOOLS.get(tool)
    if script is None:
        print(f"unknown tool: {tool}")
        return 2
    path = os.path.join(bundle_dir(), script)
    if not os.path.exists(path):          # source checkout fallback
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), script)
    sys.argv = [script] + argv
    runpy.run_path(path, run_name="__main__")
    return 0


def spawn_self(args: list) -> subprocess.Popen:
    """Re-launch this same executable with different arguments."""
    if frozen():
        cmd = [sys.executable] + args
    else:
        cmd = [sys.executable, os.path.abspath(__file__)] + args
    creation = 0
    if os.name == "nt":
        creation = subprocess.CREATE_NEW_CONSOLE
    return subprocess.Popen(cmd, cwd=os.getcwd(), creationflags=creation)


def play(with_tracker: bool = True) -> int:
    """Start the tracker (optional) then run the game in this process."""
    tracker = None
    if with_tracker:
        try:
            tracker = spawn_self(["--run", "tracker"])
            time.sleep(0.4)     # let the camera window come up first
        except OSError as exc:
            print("could not start the ball tracker:", exc)
    try:
        from putt_quest.game import main as game_main
        game_main()
    finally:
        if tracker is not None and tracker.poll() is None:
            tracker.terminate()
            try:
                tracker.wait(timeout=4)
            except subprocess.TimeoutExpired:
                tracker.kill()
    return 0


def launcher() -> int:
    """Small pygame menu so the exe is usable with zero command line."""
    import pygame

    pygame.init()
    win = pygame.display.set_mode((560, 420))
    pygame.display.set_caption("Putt Quest")
    font_b = pygame.font.SysFont("arial", 34, bold=True)
    font = pygame.font.SysFont("arial", 19)
    small = pygame.font.SysFont("arial", 14)
    clock = pygame.time.Clock()

    items = [
        ("PLAY", "ball tracker + game", "play"),
        ("CALIBRATE CAMERA", "exposure, gain and ball colour", "calibrate"),
        ("SET UP PUTT ZONE", "drag the zone, auto-detect direction", "setup"),
        ("GAME ONLY", "keyboard test mode, no camera", "game"),
        ("QUIT", "", "quit"),
    ]
    idx = 0
    while True:
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                return 0
            if ev.type == pygame.KEYDOWN:
                if ev.key in (pygame.K_ESCAPE, pygame.K_q):
                    return 0
                if ev.key in (pygame.K_UP, pygame.K_w):
                    idx = (idx - 1) % len(items)
                if ev.key in (pygame.K_DOWN, pygame.K_s):
                    idx = (idx + 1) % len(items)
                if ev.key in (pygame.K_RETURN, pygame.K_KP_ENTER,
                              pygame.K_SPACE):
                    action = items[idx][2]
                    if action == "quit":
                        return 0
                    pygame.quit()
                    if action == "play":
                        return play(True)
                    if action == "game":
                        return play(False)
                    proc = spawn_self(["--run", action])
                    proc.wait()
                    return launcher()      # back to the menu afterwards
            if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                mx, my = ev.pos
                for i in range(len(items)):
                    if 40 <= mx <= 520 and 118 + i * 56 <= my <= 118 + i * 56 + 46:
                        idx = i
                        pygame.event.post(pygame.event.Event(
                            pygame.KEYDOWN, key=pygame.K_RETURN))

        win.fill((14, 24, 17))
        pygame.draw.rect(win, (22, 40, 26), (0, 0, 560, 92))
        win.blit(font_b.render("PUTT QUEST", True, (255, 214, 90)), (40, 24))
        win.blit(small.render("webcam putting challenge", True,
                              (150, 168, 152)), (44, 64))
        for i, (label, hint, _a) in enumerate(items):
            r = pygame.Rect(40, 118 + i * 56, 480, 46)
            sel = (i == idx)
            pygame.draw.rect(win, (30, 52, 34) if sel else (20, 32, 23), r,
                             border_radius=6)
            if sel:
                pygame.draw.rect(win, (255, 214, 90), r, 2, border_radius=6)
            col = (255, 214, 90) if sel else (226, 232, 224)
            win.blit(font.render(label, True, col), (r.x + 16, r.y + 6))
            if hint:
                win.blit(small.render(hint, True, (150, 168, 152)),
                         (r.x + 16, r.y + 27))
        win.blit(small.render("UP/DOWN choose · ENTER select · ESC quit",
                              True, (150, 168, 152)), (40, 396))
        pygame.display.flip()
        clock.tick(60)


def main() -> int:
    ap = argparse.ArgumentParser(description="Putt Quest")
    ap.add_argument("--run", choices=sorted(TOOLS),
                    help="internal: run a bundled tool in this process")
    ap.add_argument("--play", action="store_true",
                    help="start tracker + game without the menu")
    ap.add_argument("--game", action="store_true",
                    help="start the game only (keyboard test mode)")
    args, rest = ap.parse_known_args()

    prepare_workdir()

    if args.run:
        return run_tool(args.run, rest)
    if args.play:
        return play(True)
    if args.game:
        return play(False)
    return launcher()


if __name__ == "__main__":
    sys.exit(main())
