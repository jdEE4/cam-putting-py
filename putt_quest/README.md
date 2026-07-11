# Putt Quest

A standalone putting video game driven by the webcam ball tracker in this
repo — no GSPro required. Play 9-hole putting challenges with real putts:
different lengths, breaks, and slopes on every hole, rendered in a full
3D behind-the-ball view.

## How it works

`ball_tracking.py` already reports every detected putt — ball speed in
MPH and HLA in degrees — to `http://localhost:8888/`, where a GSPro
connector normally listens. Putt Quest simply binds that port itself and
consumes the shots:

```
webcam ──> ball_tracking.py ──HTTP :8888──> putt_quest (this game)
```

The tracker in this fork also pings its live detection state
(ball locked? still searching?) to the same port twice a second, so the
game can tell you when your physical ball is placed correctly *before*
you putt. If nothing is listening the pings fail silently, so the
tracker still works stand-alone or with a GSPro connector
(set `statusping = 0` in `config.ini` to turn the pings off entirely).

## Quick start

```bash
pip install -r requirements-game.txt     # just pygame

# terminal 1 — the game (start it FIRST so it owns port 8888)
python -m putt_quest

# terminal 2 — the tracker, exactly as you already run it
python ball_tracking.py -c orange
```

Make sure no GSPro connector is running, or the game can't bind port 8888
(the menu shows the listener status).

No camera handy? Press `T` in the game for keyboard test mode: `W/S`
adjust speed, `LEFT/RIGHT` adjust HLA, `SPACE` putts. Test mode also
draws a ghost preview of where the current speed/HLA would roll —
handy for learning how break works.

## Is my ball set up correctly?

Both windows tell you, live:

- **Tracker window** (`ball_tracking.py`): a banner at the bottom walks
  you through setup — red *PLACE BALL IN START ZONE*, yellow
  *HOLD STILL — LOCKING BALL...* while it stabilizes, green
  *BALL READY — PUTT AWAY* once locked. The detected ball is circled
  yellow while locking and green when armed.
- **Game HUD**: the bottom status bar mirrors the same state ("tracker
  online — place ball in start zone" / "BALL READY — putt when ready"),
  plus warns when the tracker isn't running at all or when port 8888 is
  taken by a GSPro connector.

## Controls

| Key | Action |
| --- | --- |
| ENTER | start round / next hole |
| UP/DOWN | pick course in menu |
| T | toggle keyboard test mode |
| SPACE | (test mode) putt |
| W / S | (test mode) speed +/- |
| LEFT / RIGHT | (test mode) HLA +/- |
| D | toggle debug overlay |
| M | toggle minimap |
| R | restart round |
| Q / ESC | quit |

## Debug overlay (`D`)

Shows everything you need to diagnose a setup that "doesn't work":
render FPS, game state, ball position/velocity, the physics constants in
play, listener status, a live feed of the last HTTP requests received
(including *rejected* ones with the reason), and the age/content of the
tracker's last status ping.

## Gameplay

- Two built-in courses (`putt_quest/courses.py`): **Classic 9** and
  **Links Test**. Each hole defines distance (ft), break (%), and
  slope (%). Add your own holes/courses by editing that one data file.
- You putt from wherever the last ball stopped until you hole out
  (mercy pickup after 6 putts). Putting par is 2 per hole.
- Physics: friction derived from the course stimp rating, gravity from
  the hole's break/slope grades, speed-sensitive hole capture with
  lip-outs when you ram it.
- The HUD shows remaining distance and a suggested pace; the minimap
  gives a top-down read of the whole putt.

## Graphics: software 3D, no GPU needed

The scene is real perspective 3D (sloped green mesh, fringe/rough
surround, sky, waving flag, distance haze) rendered entirely in pygame —
no OpenGL, no dedicated graphics card required. The trick is caching:
the expensive layers (sky, terrain, cup, slope arrows) are drawn once
per camera move (i.e. once per putt) into a background surface; each
frame only redraws the ball, trail, aim line, flag, and HUD. Measured
cost: ~30 ms per putt for the background, <1 ms per frame after that.

Everything is drawn on an internal 640x360 canvas integer-scaled to the
window; raise `INTERNAL_W/H` in `putt_quest/graphics.py` for sharper
output on faster machines. The slope of each green is visually
exaggerated (`Z_EXAG` in `render3d.py`) so a 2% break is actually
visible from behind the ball.

## Roadmap ideas

- [ ] Sound effects (ball drop, lip-out groan)
- [ ] Persistent best-score file per course
- [ ] Elevation heat-map rendering of the green
- [ ] Multiplayer alternating putts
- [ ] Config file for port, window scale, mercy limit

## License

This directory is part of a fork of
[alleexx/cam-putting-py](https://github.com/alleexx/cam-putting-py) and is
licensed under **GPL-3.0**, the same as the upstream project.
