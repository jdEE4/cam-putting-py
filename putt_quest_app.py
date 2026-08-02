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


def child_env() -> dict:
    """Environment for a re-launch of this same frozen executable.

    PyInstaller's bootloader exports private variables (_PYI_..., _MEIPASS2)
    describing the *parent's* unpacked bundle. A child that inherits them
    thinks it is already unpacked, looks in the wrong place and dies
    immediately - so they must be stripped before spawning ourselves.
    """
    env = dict(os.environ)
    for key in list(env):
        if key.startswith("_PYI") or key in ("_MEIPASS2", "_MEIPASS"):
            del env[key]
    return env


def spawn_self(args: list) -> subprocess.Popen:
    """Re-launch this same executable with different arguments."""
    if frozen():
        cmd = [sys.executable] + args
    else:
        cmd = [sys.executable, os.path.abspath(__file__)] + args
    kwargs = {"cwd": os.getcwd(), "env": child_env()}
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NEW_CONSOLE
    return subprocess.Popen(cmd, **kwargs)


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


def selftest() -> int:
    """Print everything needed to diagnose a launch problem, and exit.

    Run `PuttQuest.exe --selftest > report.txt 2>&1` and send the file."""
    ok = True
    print("=" * 58)
    print(" Putt Quest self-test")
    print("=" * 58)
    print(f"frozen        : {frozen()}")
    print(f"executable    : {sys.executable}")
    print(f"bundle dir    : {bundle_dir()}")
    print(f"work dir      : {os.getcwd()}")
    print(f"python        : {sys.version.split()[0]}")
    print(f"platform      : {sys.platform}")

    print("\n-- bundled tools --")
    for name, script in sorted(TOOLS.items()):
        path = os.path.join(bundle_dir(), script)
        found = os.path.exists(path)
        ok &= found
        print(f"  {'OK ' if found else 'MISSING'}  {name:<10} {script}")

    print("\n-- runtime files (written next to the exe) --")
    for name in RUNTIME_FILES:
        p = os.path.join(os.getcwd(), name)
        print(f"  {'OK ' if os.path.exists(p) else 'absent '}  {name}")

    print("\n-- imports --")
    for mod in ("pygame", "numpy", "cv2", "requests", "cvzone", "imutils",
                "putt_quest.game", "putt_quest.sounds"):
        try:
            __import__(mod)
            print(f"  OK       {mod}")
        except Exception as exc:                     # noqa: BLE001
            ok = False
            print(f"  FAILED   {mod}: {exc}")

    print("\n-- display / audio --")
    try:
        import pygame
        pygame.display.init()
        print(f"  OK       video driver: {pygame.display.get_driver()}")
        pygame.display.quit()
    except Exception as exc:                         # noqa: BLE001
        ok = False
        print(f"  FAILED   pygame display: {exc}")
    try:
        import pygame
        pygame.mixer.init()
        print("  OK       audio device present")
        pygame.mixer.quit()
    except Exception as exc:                         # noqa: BLE001
        print(f"  none     no audio device ({exc}) - game still runs")

    print("\n-- cameras --")
    try:
        import cv2
        found_any = False
        for idx in range(3):
            cap = cv2.VideoCapture(idx)
            if cap.isOpened():
                w = cap.get(cv2.CAP_PROP_FRAME_WIDTH)
                h = cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
                print(f"  OK       camera {idx}: {w:.0f}x{h:.0f}")
                found_any = True
            cap.release()
        if not found_any:
            print("  none     no camera opened (GAME ONLY mode still works)")
    except Exception as exc:                         # noqa: BLE001
        print(f"  FAILED   opencv camera probe: {exc}")

    print("\n" + ("ALL CORE CHECKS PASSED" if ok else "SOME CHECKS FAILED"))
    return 0 if ok else 1


def report_crash(exc: BaseException) -> None:
    """Write a crash log next to the exe and keep the console readable.

    A double-clicked exe closes its console the instant it dies, so without
    this a failure is completely invisible to the player."""
    import traceback
    text = "".join(traceback.format_exception(type(exc), exc,
                                              exc.__traceback__))
    banner = (f"Putt Quest {'(packaged)' if frozen() else '(source)'} "
              f"crashed:\n\n{text}\n"
              f"python: {sys.version}\ncwd: {os.getcwd()}\n"
              f"bundle: {bundle_dir()}\n")
    sys.stderr.write("\n" + banner)
    try:
        path = os.path.join(app_dir(), "puttquest-crash.log")
        with open(path, "w") as fh:
            fh.write(banner)
        sys.stderr.write(f"\nSaved a copy to: {path}\n")
    except OSError:
        pass
    if frozen() and os.name == "nt":
        try:
            input("\nPress ENTER to close this window...")
        except (EOFError, KeyboardInterrupt):
            pass


def main() -> int:
    ap = argparse.ArgumentParser(description="Putt Quest")
    ap.add_argument("--run", choices=sorted(TOOLS),
                    help="internal: run a bundled tool in this process")
    ap.add_argument("--play", action="store_true",
                    help="start tracker + game without the menu")
    ap.add_argument("--game", action="store_true",
                    help="start the game only (keyboard test mode)")
    ap.add_argument("--selftest", action="store_true",
                    help="print a diagnostic report and exit")
    args, rest = ap.parse_known_args()

    # unpacking a onefile bundle takes a while: say something immediately so
    # a double-click never looks like nothing happened
    print("Putt Quest — starting up...", flush=True)
    work = prepare_workdir()
    print(f"working directory: {work}", flush=True)

    if args.selftest:
        return selftest()
    if args.run:
        return run_tool(args.run, rest)
    if args.play:
        return play(True)
    if args.game:
        return play(False)
    return launcher()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except BaseException as exc:          # noqa: BLE001 - last-resort net
        report_crash(exc)
        sys.exit(1)
