# Guided, button-driven calibration for cam-putting-py (orange ball).
#
# This is the friendly front end to the keyboard-heavy camera_tune.py. It shows
# the live camera with a row of big clickable buttons and walks you through three
# steps: (1) confirm frame rate, (2) lock onto the orange ball, (3) save. When you
# finish it writes exposure/gain and the ball color (as customhsv) plus the
# resolution/fps into config.ini, which ball_tracking.py reads on startup.
#
# Why the old tool showed 30fps: it queried the camera driver for exposure/gain
# every frame, and on Windows DirectShow those reads are slow enough to throttle
# the loop to ~30fps regardless of the sensor. This tool caches those values and
# only re-reads them right after you change something, so the fps number is honest.
#
#   run_calibrate_gui.bat            (Windows)
#   ./run_calibrate_gui.sh           (macOS/Linux)
#   python calibrate_gui.py -w 0     (choose a different webcam index)

import argparse
import platform
import time
from configparser import ConfigParser

import cv2
import numpy as np

CFG_FILE = 'config.ini'

CAMERA_BACKENDS = {
    'any': cv2.CAP_ANY,
    'dshow': cv2.CAP_DSHOW,
    'msmf': cv2.CAP_MSMF,
    'avfoundation': cv2.CAP_AVFOUNDATION,
    'v4l2': cv2.CAP_V4L2,
}

# the four orange presets shipped with ball_tracking.py, brightest-to-dimmest-ish
ORANGE_PRESETS = [
    ('Orange 1', {'hmin': 0, 'smin': 219, 'vmin': 147, 'hmax': 19, 'smax': 255, 'vmax': 255}),
    ('Orange 2', {'hmin': 3, 'smin': 181, 'vmin': 134, 'hmax': 40, 'smax': 255, 'vmax': 255}),
    ('Orange 3', {'hmin': 0, 'smin': 73, 'vmin': 150, 'hmax': 40, 'smax': 255, 'vmax': 255}),
    ('Orange 4', {'hmin': 3, 'smin': 181, 'vmin': 216, 'hmax': 40, 'smax': 255, 'vmax': 255}),
]

WINDOW = "Putting Calibration"
PREVIEW_W = 820          # width the camera frame is shown at
PANEL_H = 150            # height of the button strip under the preview

# colors (BGR)
BG = (38, 38, 38)
INK = (240, 240, 240)
GOOD = (90, 210, 90)
WARN = (60, 200, 255)
BAD = (70, 70, 235)
BTN = (70, 70, 70)
BTN_HOT = (120, 90, 40)
BTN_GO = (60, 120, 60)

# buttons registered during draw, hit-tested by the mouse callback
_buttons = []
_pending = [None]


def resolve_backend(name):
    name = (name or 'auto').strip().lower()
    if name in CAMERA_BACKENDS:
        return CAMERA_BACKENDS[name]
    if platform.system() == 'Windows':
        return cv2.CAP_DSHOW
    return cv2.CAP_ANY


def open_camera(index, api, width, height, fps, use_mjpeg):
    cap = cv2.VideoCapture(index, api)
    if not cap.isOpened():
        return cap
    if use_mjpeg:
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
    if width and height:
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
    if fps:
        cap.set(cv2.CAP_PROP_FPS, fps)
    return cap


def find_ball(frame, hsv):
    hsvimg = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    lower = np.array([hsv['hmin'], hsv['smin'], hsv['vmin']])
    upper = np.array([hsv['hmax'], hsv['smax'], hsv['vmax']])
    mask = cv2.inRange(hsvimg, lower, upper)
    mask = cv2.erode(mask, None, iterations=2)
    mask = cv2.dilate(mask, None, iterations=2)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return mask, None
    largest = max(contours, key=cv2.contourArea)
    if cv2.contourArea(largest) < 8:
        return mask, None
    ((x, y), radius) = cv2.minEnclosingCircle(largest)
    return mask, (int(x), int(y), radius)


def on_mouse(event, x, y, flags, param):
    if event != cv2.EVENT_LBUTTONDOWN:
        return
    for (bx, by, bw, bh, action) in _buttons:
        if bx <= x <= bx + bw and by <= y <= by + bh:
            _pending[0] = action
            return


def draw_button(panel, x, y, w, h, label, action, color=BTN, enabled=True):
    fill = color if enabled else (50, 50, 50)
    cv2.rectangle(panel, (x, y), (x + w, y + h), fill, -1)
    cv2.rectangle(panel, (x, y), (x + w, y + h), (25, 25, 25), 2)
    ink = INK if enabled else (120, 120, 120)
    size = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.55, 1)[0]
    tx = x + (w - size[0]) // 2
    ty = y + (h + size[1]) // 2
    cv2.putText(panel, label, (tx, ty), cv2.FONT_HERSHEY_SIMPLEX, 0.55, ink, 1, cv2.LINE_AA)
    if enabled:
        _buttons.append((x, y, w, h, action))


def text(img, s, x, y, color=INK, scale=0.6, thick=1):
    cv2.putText(img, s, (x, y), cv2.FONT_HERSHEY_SIMPLEX, scale, (0, 0, 0), thick + 2, cv2.LINE_AA)
    cv2.putText(img, s, (x, y), cv2.FONT_HERSHEY_SIMPLEX, scale, color, thick, cv2.LINE_AA)


def main():
    parser = ConfigParser()
    parser.read(CFG_FILE)

    def cfg(opt, fallback):
        return parser.get('putting', opt) if parser.has_option('putting', opt) else fallback

    ap = argparse.ArgumentParser(description="Guided orange-ball calibration")
    ap.add_argument("-w", "--camera", type=int, default=0, help="webcam index - default 0")
    ap.add_argument("--width", type=int, default=int(cfg('width', 1280)), help="capture width")
    ap.add_argument("--height", type=int, default=int(cfg('height', 720)), help="capture height")
    ap.add_argument("--fps", type=int, default=int(cfg('fps', 60)) or 60, help="target fps")
    ap.add_argument("--backend", default=cfg('backend', 'auto'))
    ap.add_argument("--no-mjpeg", action="store_true")
    args = ap.parse_args()

    api = resolve_backend(args.backend)
    use_mjpeg = not args.no_mjpeg and int(cfg('mjpeg', 1)) != 0

    cap = open_camera(args.camera, api, args.width, args.height, args.fps, use_mjpeg)
    if not cap.isOpened():
        print("Could not open camera at index %d (backend %s)." % (args.camera, args.backend))
        print("Try a different -w index, or set backend = msmf in config.ini.")
        return

    cv2.namedWindow(WINDOW)
    cv2.setMouseCallback(WINDOW, on_mouse)

    step = 1
    preset_idx = 1                 # default to Orange 2
    hsv = dict(ORANGE_PRESETS[preset_idx][1])
    # cached camera props (read only after a change, never every frame)
    cam = {
        'exposure': cap.get(cv2.CAP_PROP_EXPOSURE),
        'gain': cap.get(cv2.CAP_PROP_GAIN),
        'brightness': cap.get(cv2.CAP_PROP_BRIGHTNESS),
        'auto': cap.get(cv2.CAP_PROP_AUTO_EXPOSURE),
    }

    def refresh_cam():
        cam['exposure'] = cap.get(cv2.CAP_PROP_EXPOSURE)
        cam['gain'] = cap.get(cv2.CAP_PROP_GAIN)
        cam['brightness'] = cap.get(cv2.CAP_PROP_BRIGHTNESS)
        cam['auto'] = cap.get(cv2.CAP_PROP_AUTO_EXPOSURE)

    stamps = []
    saved_msg = ['']
    saved_until = [0.0]

    def flash(msg):
        saved_msg[0] = msg
        saved_until[0] = time.time() + 3.0

    while True:
        ret, frame = cap.read()
        now = time.time()
        if not ret:
            print("Frame grab failed - camera disconnected?")
            break
        stamps.append(now)
        stamps = [t for t in stamps if now - t <= 1.0]
        fps = (len(stamps) - 1) / (stamps[-1] - stamps[0]) if len(stamps) > 3 else 0.0

        preview = cv2.resize(frame, (PREVIEW_W, int(frame.shape[0] * PREVIEW_W / frame.shape[1])))
        ph, pw = preview.shape[:2]

        ball = None
        if step == 2:
            scale = frame.shape[1] / float(pw)
            mask, ball = find_ball(frame, hsv)
            mask_small = cv2.resize(mask, (pw, ph))
            preview[mask_small > 0] = (0, 165, 255)  # tint detected pixels orange
            if ball is not None:
                bx, by, br = ball
                cv2.circle(preview, (int(bx / scale), int(by / scale)), int(br / scale), (0, 0, 255), 2)

        # ---- status overlay on the preview ----
        fps_ok = fps >= args.fps * 0.9
        text(preview, "%.0f FPS" % fps, 14, 40, GOOD if fps_ok else BAD, 1.1, 2)
        text(preview, "target %d" % args.fps, 150, 40, INK, 0.55, 1)
        titles = {1: "Step 1 of 3   Frame rate", 2: "Step 2 of 3   Find the orange ball",
                  3: "Step 3 of 3   Save"}
        text(preview, titles[step], 14, ph - 18, INK, 0.6, 1)
        if step == 2 and ball is not None:
            good = 8 <= ball[2] <= 20
            text(preview, "ball radius %.0f px %s" % (ball[2], "GOOD" if good else "move camera"),
                 pw - 320, 40, GOOD if good else WARN, 0.6, 1)
        elif step == 2:
            text(preview, "no ball - try another preset", pw - 340, 40, BAD, 0.6, 1)

        # ---- build the button panel ----
        panel = np.full((PANEL_H, pw, 3), BG, np.uint8)
        _buttons.clear()

        if step == 1:
            text(panel, "Is the FPS number green and near %d? If yes, click Next." % args.fps, 16, 26, INK, 0.5)
            text(panel, "If it is stuck low with a bright image, it is not exposure - tell Claude.", 16, 46, WARN, 0.45)
            draw_button(panel, 16, 60, 150, 60, "Auto Exp: %s" % ("ON" if cam['auto'] > 0.5 else "OFF"), "auto")
            draw_button(panel, 176, 60, 120, 60, "Darker", "exp_down")
            draw_button(panel, 306, 60, 120, 60, "Brighter", "exp_up")
            draw_button(panel, 436, 60, 120, 60, "Reset", "reset")
            draw_button(panel, pw - 150, 60, 134, 60, "Next  >", "next", BTN_GO)
        elif step == 2:
            text(panel, "Put the ORANGE ball on the mat. Pick the preset that circles it cleanly.", 16, 26, INK, 0.5)
            bw = 118
            for i, (name, _) in enumerate(ORANGE_PRESETS):
                hot = (i == preset_idx)
                draw_button(panel, 16 + i * (bw + 8), 44, bw, 46, name, "preset_%d" % i,
                            BTN_HOT if hot else BTN)
            draw_button(panel, 16, 98, 150, 40, "Detect looser", "looser")
            draw_button(panel, 174, 98, 150, 40, "Detect tighter", "tighter")
            draw_button(panel, pw - 300, 98, 130, 40, "<  Back", "back")
            draw_button(panel, pw - 160, 98, 144, 40, "Next  >", "next", BTN_GO)
        else:
            text(panel, "Save exposure + orange color + %dx%d@%d to config.ini." %
                 (args.width, args.height, args.fps), 16, 26, INK, 0.5)
            text(panel, "ball_tracking.py will use these automatically on next launch.", 16, 46, INK, 0.45)
            draw_button(panel, 16, 60, 150, 60, "<  Back", "back")
            draw_button(panel, pw - 320, 60, 150, 60, "Save & Finish", "save", BTN_GO)
            draw_button(panel, pw - 160, 60, 144, 60, "Quit", "quit")

        if saved_msg[0] and now < saved_until[0]:
            text(panel, saved_msg[0], 16, PANEL_H - 10, GOOD, 0.55, 1)

        canvas = np.vstack([preview, panel])
        cv2.imshow(WINDOW, canvas)
        key = cv2.waitKey(1) & 0xFF

        action = _pending[0]
        _pending[0] = None
        if key == ord('q'):
            action = 'quit'

        if action == 'quit':
            break
        elif action == 'next':
            step = min(3, step + 1)
        elif action == 'back':
            step = max(1, step - 1)
        elif action == 'auto':
            cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 0.25 if cam['auto'] > 0.5 else 0.75)
            refresh_cam()
        elif action == 'exp_down':
            cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 0.25)      # manual, or the change is ignored
            cap.set(cv2.CAP_PROP_EXPOSURE, cam['exposure'] - 1)
            refresh_cam()
        elif action == 'exp_up':
            cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 0.25)
            cap.set(cv2.CAP_PROP_EXPOSURE, cam['exposure'] + 1)
            refresh_cam()
        elif action == 'reset':
            cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 0.75)
            refresh_cam()
            flash("Exposure reset to auto")
        elif action is not None and action.startswith('preset_'):
            preset_idx = int(action.split('_')[1])
            hsv = dict(ORANGE_PRESETS[preset_idx][1])
        elif action == 'looser':
            hsv['smin'] = max(0, hsv['smin'] - 12)
            hsv['vmin'] = max(0, hsv['vmin'] - 12)
        elif action == 'tighter':
            hsv['smin'] = min(255, hsv['smin'] + 12)
            hsv['vmin'] = min(255, hsv['vmin'] + 12)
        elif action == 'save':
            brightness_mean = float(frame.mean())
            if brightness_mean < 5 or fps < 1:
                flash("NOT saved: image is black / no frames. Click Reset first.")
            else:
                if not parser.has_section('putting'):
                    parser.add_section('putting')
                parser.set('putting', 'exposure', str(cam['exposure']))
                parser.set('putting', 'gain', str(cam['gain']))
                parser.set('putting', 'brightness', str(cam['brightness']))
                parser.set('putting', 'autoexposure', str(cam['auto']))
                parser.set('putting', 'customhsv', str(hsv))
                parser.set('putting', 'width', str(args.width))
                parser.set('putting', 'height', str(args.height))
                parser.set('putting', 'fps', str(args.fps))
                with open(CFG_FILE, 'w') as f:
                    parser.write(f)
                flash("Saved to config.ini - launch ball_tracking next")
                print("Saved calibration to %s (color=%s)" % (CFG_FILE, ORANGE_PRESETS[preset_idx][0]))

    cap.release()
    cv2.destroyAllWindows()


if __name__ == '__main__':
    main()
