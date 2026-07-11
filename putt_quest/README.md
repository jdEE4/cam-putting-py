# Putt Quest

A standalone putting video game driven by the webcam ball tracker in this
repo — no GSPro required. Play 9-hole putting challenges with real putts:
different lengths, breaks, and slopes on every hole.

## How it works

`ball_tracking.py` (unmodified, upstream) already reports every detected
putt — ball speed in MPH and HLA in degrees — to `http://localhost:8888/`,
where a GSPro connector normally listens. Putt Quest simply binds that
port itself and consumes the shots:

```
webcam ──> ball_tracking.py ──HTTP :8888──> putt_quest (this game)
```

Because nothing upstream changes, you keep all the tracker's calibration,
color options, and camera tooling, and merging future upstream fixes is
trivial.

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
adjust speed, `LEFT/RIGHT` adjust HLA, `SPACE` putts.

## Controls

| Key | Action |
| --- | --- |
| ENTER | start round / next hole |
| UP/DOWN | pick course in menu |
| T | toggle keyboard test mode |
| SPACE | (test mode) putt |
| W / S | (test mode) speed +/- |
| LEFT / RIGHT | (test mode) HLA +/- |
| R | restart round |
| Q / ESC | quit |

## Gameplay

- Two built-in courses (`putt_quest/courses.py`): **Classic 9** and
  **Links Test**. Each hole defines distance (ft), break (%), and
  slope (%). Add your own holes/courses by editing that one data file.
- You putt from wherever the last ball stopped until you hole out
  (mercy pickup after 6 putts). Putting par is 2 per hole.
- Physics: friction derived from the course stimp rating, gravity from
  the hole's break/slope grades, speed-sensitive hole capture with
  lip-outs when you ram it.
- The HUD shows remaining distance and a suggested pace.

## Graphics: low-res now, HD later (by design)

All rendering happens on a small internal canvas (`384x216`) that is
integer-scaled to the window — crisp pixel-art today. Gameplay code works
in green-space **meters** and goes through a camera transform, so
upgrading art later means only touching `putt_quest/graphics.py`:
raise `INTERNAL_W/H`, swap the primitive draws for sprites/shaders. No
physics or game-logic changes needed.

## Roadmap ideas

- [ ] Sound effects (ball drop, lip-out groan)
- [ ] Ball trail fade + minimap for long putts
- [ ] Persistent best-score file per course
- [ ] Elevation heat-map rendering of the green
- [ ] Multiplayer alternating putts
- [ ] Config file for port, window scale, mercy limit

## License

This directory is part of a fork of
[alleexx/cam-putting-py](https://github.com/alleexx/cam-putting-py) and is
licensed under **GPL-3.0**, the same as the upstream project.
