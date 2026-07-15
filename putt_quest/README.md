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
(ball locked? still searching?) to the same port twice a second, and
streams a small webcam thumbnail (~10 fps) for the in-game camera
preview, so the game can tell you when your physical ball is recognized
*before* you putt. If nothing is listening these fail silently, so the
tracker still works stand-alone or with a GSPro connector. Turn them off
in `config.ini` with `statusping = 0` (status) and `previewstream = 0`
(webcam thumbnail) if you want the tracker completely quiet.

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

## Is my ball recognized? (this matters most)

A putt only counts if the tracker has *locked* your ball first, so both
windows make that state impossible to miss:

- **Tracker window** (`ball_tracking.py`): the whole frame gets a thick
  colored border — red while searching, cyan with a progress bar while
  *locking* (the ball has to hold still for ~10 frames), green once
  *BALL READY*. A bottom banner spells out the same, and the detected
  ball is ringed (yellow locking → green armed).
- **Game — big ready badge**: while waiting for a putt, a large pill
  above the status bar shows a red **NO BALL DETECTED**, an amber
  **LOCKING 60%** with a fill bar, or a green pulsing **BALL READY**.
  Don't putt until it's green.
- **Game — debug camera panel** (`D`): a live thumbnail of your webcam
  feed (streamed from the tracker) with the same colored border and
  label, so you can confirm ball recognition without leaving the game
  window. Shows "camera feed lost" if the stream goes stale.

The lock meter means a wobbling or still-rolling ball never reads as
ready, so you can't accidentally fire a putt at a ball that isn't set.

## Controls

| Key | Action |
| --- | --- |
| ENTER | start round / next hole |
| UP/DOWN | pick course in menu |
| T | toggle keyboard test mode |
| SPACE | (test mode) putt |
| W / S | (test mode) speed +/- |
| LEFT / RIGHT | (test mode) HLA +/- |
| `[` / `]` | lower / raise render resolution |
| G | toggle the auto-resolution guard |
| D | toggle debug overlay (camera preview + stats) |
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

### Resolution & keeping your machine happy

The 3D scene renders onto an internal canvas that is smooth-scaled to the
window. Four presets — **Low 640×360, Medium 960×540, High 1280×720,
Ultra 1600×900** — trade sharpness for CPU. Change it live with `[` and
`]`; a small readout in the bottom-right shows the current resolution and
live FPS so you can watch the load.

Because there's no dedicated GPU, higher presets cost more CPU. Two
safeguards keep that from crashing or stuttering a laptop:

- **Auto-resolution guard** (on by default, toggle with `G`): if the
  frame rate stays below ~48 fps for a few seconds it automatically drops
  one preset. So even if you pick Ultra and it's too much, it self-heals
  down to something smooth within seconds.
- The expensive part (the terrain/sky/cup background) is rendered once
  per putt and cached, not every frame — so raising the resolution mostly
  affects that one-time cost, not the steady-state frame rate.

Your chosen preset, guard setting, and minimap toggle persist in
`putt_quest_settings.json`. Start Low and step up with `]` while watching
the FPS readout; if it dips, either let the guard handle it or step back
down. The slope of each green is visually exaggerated (`Z_EXAG` in
`render3d.py`) so a 2% break is actually visible from behind the ball.

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
