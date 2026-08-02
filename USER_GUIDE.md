# Putt Quest — User Guide

Play a full 3D putting round using a real webcam and a real putter.
This guide covers the day-to-day workflow, all keyboard shortcuts, and
the settings you'll actually touch.

## 1. Launch (one click)

Double-click **`play.bat`** in the project root. It opens two windows:

1. **Putt Quest - Ball Tracker** — the camera view. Waits for a ball in
   the yellow start zone, then times the putt across the red gateway.
2. **Putt Quest - Game** — the 3D game itself. It binds
   `http://127.0.0.1:8888` and listens for shots from the tracker.

Both must be running at the same time. Close either with `Q` or the
window's X. Everything auto-installs into `.venv/` on first run.

Manual launch (advanced): run [run_ball_tracking.bat](run_ball_tracking.bat)
and [run_putt_quest.bat](run_putt_quest.bat) in separate terminals.

## 2. Setup workflow (before every session)

1. Place your ball in the **yellow start zone** in the tracker window.
2. Watch the tracker's status banner:
   - Red `PLACE BALL IN START ZONE` → no ball detected yet
   - Cyan `HOLD STILL - LOCKING BALL...` (with progress bar) → seen,
     not settled
   - **Green `BALL READY - PUTT AWAY`** → putt now
3. In the game window the same state shows as the big pill above the
   status bar and (if enabled) the camera monitor in the top-right.
4. Putt. The tracker sends `speed_mph` and `hla_deg` to the game, which
   simulates the ball on the current green.

If you never reach **BALL READY**, retune the color mask (see §5) or
adjust the start-zone box (tracker Advanced Settings — key `A`).

## 3. Common gameplay controls (Putt Quest window)

Everything you'll use during a round. **You never have to memorize
these** — press `H` (or `F1`, or `?`) in the game at any time for a
pop-up shortcut reference, and press `O` for the full settings menu.

| Key | Action |
| --- | --- |
| `ENTER` | Start round / next hole / confirm menu choice |
| `UP` / `DOWN` | Choose course on the main menu |
| **`O`** or `TAB` | **Open in-game settings menu** |
| **`H`** or `F1` or `?` | **Show the keyboard-shortcut help overlay** |
| `LEFT` / `RIGHT` | **Aim trim ±0.5°** for camera putts (narrow-mat helper) |
| `P` | Toggle the **read line** (ghost curve at suggested pace) |
| `X` | Reset aim trim to 0° |
| **`U`** | **Mulligan** — undo the last putt (works during the roll or after it settles) |
| `T` | Toggle keyboard test mode (no camera needed) |
| `SPACE` | (test mode) fire a putt with current speed/HLA |
| `LEFT` / `RIGHT` | (test mode) adjust absolute test HLA |
| `W` / `S` | (test mode) adjust test putt speed |
| `R` | Restart the current course |
| `Q` / `ESC` | Quit (ESC also closes any open overlay) |

### Help overlay (`H` / `F1` / `?`)

Modal pop-up that lists every shortcut grouped by context (menu,
gameplay, test mode, display/debug) plus the tracker window's own
keys. Press **any key** to dismiss it. `Q` still quits while help is
open.

### Settings menu (`O`)

The in-game settings menu covers everything you'll change during a
session, without needing keyboard shortcuts to remember:

- **Green Speed (Stimp)** — LEFT/RIGHT to adjust in 0.5-ft steps
  between 6.0 (very slow) and 14.0 (tour-level slick). Overrides the
  course's default stimp for the rest of the session. Change is
  reflected immediately in the current hole's physics.
- **Mercy Limit** — after this many putts the ball is picked up
  (default 6, range 3–9).
- **Aim Trim (camera mode)** — bias every real putt by ±0.5° up to
  ±10°. Persists across holes and sessions because the mat orientation
  doesn't change. Also adjustable with `LEFT`/`RIGHT` while waiting for
  a putt, or reset with `X`.
- **Show Read Line** — draws a ghost curve from the ball showing
  where a well-struck putt at the suggested pace would roll (with your
  current aim trim). Great for learning break. Also toggled with `P`.
- **Resolution** — Low / Medium / High / Ultra render preset.
- **Auto FPS Guard** — drops one preset if fps sags below ~48.
- **Camera Monitor** — live webcam thumbnail in the game's corner.
- **Minimap** — top-down mini view of the green.
- **Debug Overlay** — fps, physics constants, listener status, shot
  log (also toggled with `D`).
- **Reset stimp to course default** — clears the manual override.
- **Reset aim trim to 0°** — clears the manual aim bias.
- **Mulligan (undo last putt)** — uncount the last stroke and re-putt
  from where it started. Also fires immediately from key `U`.
- **Help / Keyboard Shortcuts** — opens the help overlay.
- **Close** — back to the game (also `ESC` / `O` / `TAB`).

Every change is saved to `putt_quest_settings.json` and restored next
run.

### Aim trim & the read line (camera mode)

The tracker measures the actual launch angle of your putter, but a
narrow mat may not let you physically aim more than a couple degrees
off. Aim trim closes that gap:

- Press `LEFT` / `RIGHT` while the badge reads **BALL READY** (or any
  time you're waiting for a putt) to bias the launch angle in half-degree
  steps. Your trim is added to whatever the tracker measures.
- The aim line drawn from the ball updates instantly so you can see
  the direction your struck putt will actually launch.
- Turn on the **read line** with `P` to see the full break-curve of a
  well-paced putt from the ball's current position. Combined with aim
  trim it becomes a "try this line" preview — nudge trim until the
  curve dies at the cup.
- The bottom status bar shows the active trim (in yellow) and whether
  the read line is on, so you never forget you have a bias applied.
- **Test mode is unaffected**: `T`-mode's `LEFT`/`RIGHT` still sets an
  absolute test HLA and does *not* pick up the trim.

### Mulligans (`U`)

Hit the wrong pace or misread the break? Press `U`:

- The last stroke is un-counted from your score.
- The ball is teleported back to where it started that putt, at rest.
- You return to **AWAIT PUTT** so you can re-address and putt again.
- Works both **during the roll** (stops the ball mid-flight) and **after
  it settles** (before the hole is officially over). Once the ball is
  in the cup or you've been picked up, mulligans are locked out.
- One undo per shot. Take a real putt after the mulligan and only *that*
  new shot becomes undoable.
- The scorecard marks any hole where a mulligan was used with a `†`
  next to the score so you know it's not a legit round.

## 4. Low-level keyboard shortcuts (Putt Quest window)

These are the "power user" toggles. Everything here is also in the
settings menu — you rarely need to remember them. Hit `H` in-game for
the same list on-screen.

| Key | Action |
| --- | --- |
| `H` / `F1` / `?` | Show the on-screen keyboard-shortcut help |
| `D` | Debug overlay (fps, physics, shot log) |
| `M` | Toggle minimap |
| `C` | Toggle camera monitor panel |
| `G` | Toggle auto-resolution guard |
| `[` / `-` | Lower render resolution one preset |
| `]` / `=` / `+` | Raise render resolution one preset |

## 5. Ball tracker window controls

The camera window has its own live-tuning shortcuts.

| Key | Action |
| --- | --- |
| `Q` | Quit the tracker |
| `A` | Open **Advanced Settings** trackbars (X/Y start zone, ball radius, flip, MJPEG, FPS, darkness, putt direction). Also opens the camera driver's own settings dialog on Windows/DirectShow. Press `A` again to save changes and close. |
| `D` | Open the **color tuner** (HSV `TrackBars` + `MaskFrame` preview). Every change auto-saves to `customhsv` in `config.ini`. Press `D` again to close. |

### Retuning the ball color when lighting shifts

1. Press `D` in the tracker window.
2. In the `TrackBars` window, adjust Hue/Sat/Val min & max until the
   `MaskFrame` window shows **only your ball as a white blob** on a
   black background. Kill any stray white specks from the mat or
   background.
3. Press `D` again to close.

If a tuning session goes sideways, restore the last known-good config:

```powershell
Copy-Item .\config-good.ini .\config.ini -Force
```

Save a new snapshot after a good tuning session:

```powershell
Copy-Item .\config.ini .\config-good.ini -Force
```

## 6. Settings & data files

- `config.ini` — tracker config (start zone, camera, HSV, direction).
  Written live by the tracker as you drag its trackbars.
- `config-good.ini` — hand-managed backup of a known-good tracker
  config. Restore it manually (see §5).
- `putt_quest_settings.json` — in-game settings (stimp override, mercy
  limit, resolution, toggles). Written by the game.

## 7. Troubleshooting

**Tracker window flashes and closes.** You launched `ball_tracking.py`
directly. Windows' file association uses the system Python which
doesn't have OpenCV. Use `play.bat` or `run_ball_tracking.bat`, both of
which route through the project `.venv`.

**`PORT 8888 BUSY` in the game menu.** A GSPro connector (or a stale
copy of the game) already owns that port. Close it and relaunch, or
start Putt Quest before the tracker.

**`HTTPConnectionPool ... refused` in the tracker log.** The game
isn't running. Shot data has nowhere to go. Start `run_putt_quest.bat`.

**Putts fire before you're ready.** Wait for the **green** `BALL
READY` banner in the tracker window (or the pulsing pill in the game).
The lock meter enforces ~10 stable frames — a wobbling ball never
reads as ready.

**Ball never detected.** In the tracker window: (1) make sure the ball
is inside the yellow start zone (press `A` to move the zone), (2)
retune the HSV mask (press `D` — see §5), (3) verify `Putt Dir` in
Advanced Settings matches the direction the ball actually rolls.

**Green feels wrong.** Open the game settings (`O`) and change
**Green Speed (Stimp)**. Higher = faster / longer roll. Real greens
are typically 8–12; tour majors run 12–14.

**Every putt drifts the same way.** Your mat probably isn't perfectly
square with the camera direction. Nudge **Aim Trim** in the settings
menu (or press `LEFT`/`RIGHT` while waiting for a putt) until the read
line lands on target. Reset with `X` any time.

**Tracker log full of `False Exit after the Ball`.** Fixed — that spam
now only appears when the tracker is launched with `-d` (debug).

## Mini Golf Mode

Two obstacle courses appear on the course menu alongside Classic 9 and
Links Test:

- **Windmill Gardens** (stimp 9) — classic crazy golf: railed fairways,
  bank shots, a rotating windmill, bumper posts, sand traps, a mail-slot
  dogleg and a keyhole gate.
- **Portal Park** (stimp 10.5) — physics-park golf: teleporter rings,
  conveyor boost pads, a pinball field, a four-armed windmill, and the
  everything-at-once finale "Event Horizon". Played under a dusk sky.
- **Summit Falls** (stimp 10) — alpine elevation golf: real raised ramps
  and hills, water hazards, and flume chutes that carry the ball over the
  ponds. Finale: "Summit Falls", over the summit and down the flume.

How the obstacles behave:

| Feature | Behavior |
| --- | --- |
| Wooden rails | ball banks off them (lively, ~86% speed kept) |
| Red posts | pinball-style bounce |
| Windmill | rotating blades swat the ball; roll under between sweeps |
| Portal rings | entering either ring teleports the ball out of the other, keeping its direction |
| Sand | heavy friction — the ball dies quickly |
| Boost pads | push the ball along the printed chevrons |
| Ramps / hills | real elevation — uphill kills pace, downhill adds it |
| Flume chutes | swallow the ball at the mouth and carry it along the tube (even over water), releasing it at a controlled speed |
| Water | splash! The ball is replayed from where the putt started (the stroke counts) |

Every hole is fully enclosed (the ball cannot leave) and every hole is
verified ace-able with a realistic putt (max ~6.4 mph, within about 24
degrees of the cup line) — the test suite brute-forces each one. Cups in
mini golf mode are wider than regulation, like the real thing.

### Presentation

The game now ships with synthesized sound effects (putter click, rail
knocks, bumper boings, windmill clangs, portal warps, splashes, the cup
chime, and a round-end fanfare — all generated at startup, no audio files),
particle effects (confetti on a make, sparks, splashes, sand poofs),
a sink animation, screen shake on hard hits, directional lighting on the
terrain, and per-course sky themes. Toggle audio in Settings (O) under
"Sound Effects"; everything degrades gracefully on machines with no audio
device.

## One-click executable

You can build a single self-contained file that needs **no Python install**
on the target machine:

```
build_exe.bat          (Windows  -> dist\PuttQuest.exe)
./build_exe.sh         (macOS/Linux -> dist/PuttQuest)
```

The build takes a few minutes and produces one ~100 MB binary. Share that
file; the player double-clicks it and gets a menu:

| Menu item | What it does |
| --- | --- |
| PLAY | starts the ball tracker **and** the game together |
| CALIBRATE CAMERA | exposure / gain / ball-colour wizard |
| SET UP PUTT ZONE | drag the start zone, auto-detect putt direction |
| GAME ONLY | keyboard test mode, no camera needed |

On first run the exe writes `config.ini`, `error.png` and its settings next
to itself (or to `~/PuttQuest` if that folder is read-only), so calibration
persists between runs. Command-line shortcuts still work:
`PuttQuest.exe --play`, `--game`.

> First launch takes ~10–20 seconds while the bundle unpacks itself; later
> launches are quicker. The console window stays open on purpose — the
> tracker prints each putt's ball speed and HLA there.

## Auto-advance and shot stats

- **Auto-advance**: after a hole is finished the next one loads by itself.
  A countdown ring shows the remaining time and ENTER always skips ahead
  immediately. Change the delay (or turn it off) in Settings → *Auto-Advance
  Hole*; the timer pauses while the settings or help overlay is open.
- **Shot stats card**: every putt automatically pops a card with ball speed,
  HLA, rollout, how your pace compared to the ideal for that distance, and
  the result — plus a plain-English verdict (GOOD PACE / TOO FIRM / LEFT
  SHORT / PUSHED / PULLED). Toggle it in Settings → *Shot Stats Card*.
- **Round stats**: the scorecard now shows putts, makes and make %, average
  ball speed, average pace error, average absolute HLA and your longest roll.
- **Ball setup animation**: while the game waits for a putt, an animated
  reticle is drawn on the green where your ball sits — sonar rings while the
  tracker searches, a filling arc while the ball locks, and a steady pulse
  with rotating ticks once it's READY.
