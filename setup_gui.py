# Visual, button-driven setup for cam-putting-py.
#
# This replaces squinting at the OpenCV trackbars. It shows the live camera at
# the SAME 640-wide scale the tracker uses (so the numbers transfer exactly) and
# lets you:
#   * DRAG a box on the video to place the start zone right on your ball
#   * click "Auto-Detect" and ROLL A PUTT - the tool measures which way the ball
#     actually travels in the frame and sets the direction for you (no more
#     guessing L-R vs R-L vs flip)
#   * watch a live READY -> PUTT! preview that confirms the direction is right
#     before you ever launch ball_tracking.py
# Save writes startx1/startx2/y1/y2/radius/direction into config.ini.
#
#   run_setup_gui.bat            (Windows)
#   ./run_setup_gui.sh           (macOS/Linux)

import argparse
import ast
import platform
import time
from configparser import ConfigParser

import cv2
import numpy as np

CFG_FILE = 'config.ini'
PROC_W = 640            # tracker processes at 640 wide - we must match it
DISP_W = 960           # on-screen size (scaled up from PROC_W for visibility)
PANEL_H = 140

CAMERA_BACKENDS = {
    'any': cv2.CAP_ANY, 'dshow': cv2.CAP_DSHOW, 'msmf': cv2.CAP_MSMF,
    'avfoundation': cv2.CAP_AVFOUNDATION, 'v4l2': cv2.CAP_V4L2,
}
ORANGE2 = {'hmin': 3, 'smin': 181, 'vmin': 134, 'hmax': 40, 'smax': 255, 'vmax': 255}

BG = (38, 38, 38); INK = (240, 240, 240)
GOOD = (90, 210, 90); WARN = (60, 200, 255); BAD = (70, 70, 235)
BTN = (70, 70, 70); BTN_GO = (60, 120, 60); BTN_HOT = (120, 90, 40)

_buttons = []
_pending = [None]
_panel_y = [0]
# zone drag state (all in DISPLAY coords until finalized)
_drag = [False]
_drag_a = [(0, 0)]
_drag_b = [(0, 0)]


def resolve_backend(name):
    name = (name or 'auto').strip().lower()
    if name in CAMERA_BACKENDS:
        return CAMERA_BACKENDS[name]
    return cv2.CAP_DSHOW if platform.system() == 'Windows' else cv2.CAP_ANY


def open_camera(index, api, w, h, fps, use_mjpeg):
    cap = cv2.VideoCapture(index, api)
    if not cap.isOpened():
        return cap
    if use_mjpeg:
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
    if w and h:
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, w)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, h)
    if fps:
        cap.set(cv2.CAP_PROP_FPS, fps)
    return cap


def find_ball(proc, hsv):
    blurred = cv2.GaussianBlur(proc, (11, 11), 0)
    hsvimg = cv2.cvtColor(blurred, cv2.COLOR_BGR2HSV)
    lower = np.array([hsv['hmin'], hsv['smin'], hsv['vmin']])
    upper = np.array([hsv['hmax'], hsv['smax'], hsv['vmax']])
    mask = cv2.inRange(hsvimg, lower, upper)
    mask = cv2.erode(mask, None, iterations=2)
    mask = cv2.dilate(mask, None, iterations=2)
    cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not cnts:
        return None
    c = max(cnts, key=cv2.contourArea)
    if cv2.contourArea(c) < 8:
        return None
    (x, y), r = cv2.minEnclosingCircle(c)
    return (int(x), int(y), r)


def on_mouse(event, x, y, flags, param):
    if event == cv2.EVENT_LBUTTONDOWN:
        if y >= _panel_y[0]:                       # click in the button strip
            for (bx, by, bw, bh, action) in _buttons:
                if bx <= x <= bx + bw and by <= y <= by + bh:
                    _pending[0] = action
                    return
        else:                                      # start dragging a zone box
            _drag[0] = True
            _drag_a[0] = (x, y)
            _drag_b[0] = (x, y)
    elif event == cv2.EVENT_MOUSEMOVE and _drag[0]:
        _drag_b[0] = (x, y)
    elif event == cv2.EVENT_LBUTTONUP and _drag[0]:
        _drag[0] = False
        _drag_b[0] = (x, y)
        _pending[0] = 'zone_set'


def draw_button(panel, x, y, w, h, label, action, color=BTN):
    cv2.rectangle(panel, (x, y), (x + w, y + h), color, -1)
    cv2.rectangle(panel, (x, y), (x + w, y + h), (25, 25, 25), 2)
    sz = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.52, 1)[0]
    cv2.putText(panel, label, (x + (w - sz[0]) // 2, y + (h + sz[1]) // 2),
                cv2.FONT_HERSHEY_SIMPLEX, 0.52, INK, 1, cv2.LINE_AA)
    _buttons.append((x, y + _panel_y[0], w, h, action))


def text(img, s, x, y, color=INK, scale=0.6, thick=1):
    cv2.putText(img, s, (x, y), cv2.FONT_HERSHEY_SIMPLEX, scale, (0, 0, 0), thick + 2, cv2.LINE_AA)
    cv2.putText(img, s, (x, y), cv2.FONT_HERSHEY_SIMPLEX, scale, color, thick, cv2.LINE_AA)


def main():
    parser = ConfigParser(strict=False)
    parser.read(CFG_FILE)

    def cfg(opt, fb):
        return parser.get('putting', opt) if parser.has_option('putting', opt) else fb

    ap = argparse.ArgumentParser(description="Visual putt-zone + direction setup")
    ap.add_argument("-w", "--camera", type=int, default=0)
    ap.add_argument("--width", type=int, default=int(cfg('width', 1280)))
    ap.add_argument("--height", type=int, default=int(cfg('height', 720)))
    ap.add_argument("--fps", type=int, default=int(cfg('fps', 60)) or 60)
    ap.add_argument("--backend", default=cfg('backend', 'auto'))
    args = ap.parse_args()

    use_mjpeg = int(cfg('mjpeg', 1)) != 0
    flip_img = int(cfg('flip', 0))
    hsv = ORANGE2
    if parser.has_option('putting', 'customhsv'):
        try:
            hsv = ast.literal_eval(parser.get('putting', 'customhsv'))
        except (ValueError, SyntaxError):
            hsv = ORANGE2

    cap = open_camera(args.camera, resolve_backend(args.backend),
                      args.width, args.height, args.fps, use_mjpeg)
    if not cap.isOpened():
        print("Could not open camera at index %d." % args.camera)
        return

    # zone + direction (all in PROC_W space, exactly like the tracker)
    sx1 = int(cfg('startx1', 10)); sx2 = int(cfg('startx2', 180))
    y1 = int(cfg('y1', 40)); y2 = int(cfg('y2', 320))
    radius = int(cfg('radius', 0))
    direction = cfg('direction', 'lefttoright').strip().lower()

    scale = [1.0]           # DISP_W / proc width, set once we know proc size
    mode = ['idle']         # 'idle' or 'detect'
    detect_anchor = [None]
    msg = ['']; msg_until = [0.0]
    # live preview state
    armed = [False]; putt_flash_until = [0.0]; putt_dir_txt = ['']
    last_center = [None]

    def flash(m, secs=3.0):
        msg[0] = m; msg_until[0] = time.time() + secs

    def gateway(sign):
        # sign: +1 L-R (gate right of sx2), -1 R-L (gate left of sx1)
        return (sx2 + 10) if sign == 1 else (sx1 - 10)

    cv2.namedWindow("Putt Setup")
    cv2.setMouseCallback("Putt Setup", on_mouse)

    while True:
        ret, frame = cap.read()
        now = time.time()
        if not ret:
            print("Frame grab failed.")
            break
        if flip_img == 1:
            frame = cv2.flip(frame, 1)

        proc = cv2.resize(frame, (PROC_W, int(frame.shape[0] * PROC_W / frame.shape[1])))
        pph = proc.shape[0]
        disp = cv2.resize(proc, (DISP_W, int(pph * DISP_W / PROC_W)))
        dh, dw = disp.shape[:2]
        scale[0] = DISP_W / float(PROC_W)
        s = scale[0]
        sign = -1 if direction == 'righttoleft' else 1

        ball = find_ball(proc, hsv)          # (x,y,r) in PROC space

        # ---- auto-detect direction from a real roll ----
        if mode[0] == 'detect':
            if ball is not None:
                if detect_anchor[0] is None:
                    detect_anchor[0] = (ball[0], ball[1])
                dx = ball[0] - detect_anchor[0][0]
                dy = ball[1] - detect_anchor[0][1]
                if max(abs(dx), abs(dy)) > 60:       # a real roll happened
                    if abs(dx) >= abs(dy):
                        direction = 'lefttoright' if dx > 0 else 'righttoleft'
                        flash("Detected: ball rolls %s" %
                              ("LEFT to RIGHT" if dx > 0 else "RIGHT to LEFT"), 4)
                    else:
                        # vertical in-frame - horizontal tracker can't use this
                        flash("Ball moves VERTICALLY in frame - rotate the camera "
                              "so the putt runs across the width.", 6)
                    mode[0] = 'idle'; detect_anchor[0] = None
            # nudge if they haven't moved yet
            if detect_anchor[0] is not None and ball is None:
                detect_anchor[0] = None

        # ---- live READY -> PUTT preview (mirrors the tracker's arm/cross) ----
        gate_x = gateway(sign)
        if ball is not None and mode[0] == 'idle':
            bx, by, br = ball
            in_zone = (sx1 <= bx <= sx2 and y1 <= by <= y2)
            if in_zone:
                armed[0] = True
                last_center[0] = (bx, by)
            elif armed[0] and last_center[0] is not None:
                # crossed the gate in the configured direction?
                crossed = (sign * (bx - gate_x) > 0)
                moved = (sign * (bx - last_center[0][0]) > 40)
                if crossed and moved:
                    putt_flash_until[0] = now + 1.5
                    putt_dir_txt[0] = "PUTT %s" % (">>" if sign == 1 else "<<")
                    armed[0] = False

        # ================= draw =================
        # start zone (yellow) and gateway (red), in display coords
        cv2.rectangle(disp, (int(sx1 * s), int(y1 * s)), (int(sx2 * s), int(y2 * s)), (0, 210, 255), 2)
        gx = int(gate_x * s)
        cv2.line(disp, (gx, int(y1 * s)), (gx, int(y2 * s)), (0, 0, 255), 2)
        # big direction arrow across the zone
        ay = int((y1 + y2) / 2 * s)
        ax0 = int((sx1 if sign == 1 else sx2) * s)
        ax1 = int((sx2 + 120 if sign == 1 else sx1 - 120) * s)
        cv2.arrowedLine(disp, (ax0, ay), (ax1, ay), (255, 255, 255), 3, tipLength=0.25)

        if ball is not None:
            bx, by, br = ball
            col = GOOD if (sx1 <= bx <= sx2 and y1 <= by <= y2) else WARN
            cv2.circle(disp, (int(bx * s), int(by * s)), int(max(br, 3) * s), col, 2)

        if _drag[0]:                              # live drag rectangle
            cv2.rectangle(disp, _drag_a[0], _drag_b[0], (255, 255, 255), 1)

        # status text
        text(disp, "Direction: %s" % ("LEFT to RIGHT" if sign == 1 else "RIGHT to LEFT"),
             14, 30, INK, 0.7, 2)
        if ball is None:
            text(disp, "no ball detected", 14, 58, BAD, 0.55)
        elif armed[0]:
            text(disp, "READY - ball in zone", 14, 58, GOOD, 0.55)
        if mode[0] == 'detect':
            text(disp, "ROLL A PUTT NOW...", dw // 2 - 130, 40, WARN, 0.9, 2)
        if now < putt_flash_until[0]:
            text(disp, putt_dir_txt[0], dw // 2 - 120, dh // 2, GOOD, 2.2, 4)

        # ---- panel ----
        panel = np.full((PANEL_H, dw, 3), BG, np.uint8)
        _buttons.clear(); _panel_y[0] = dh
        text(panel, "DRAG a box on the video to set the start zone (put it on your resting ball).",
             14, 22, INK, 0.5)
        text(panel, "zone x[%d-%d] y[%d-%d]" % (sx1, sx2, y1, y2), 14, 44, WARN, 0.46)
        draw_button(panel, 14, 56, 210, 54, "Auto-Detect (roll a putt)", "detect", BTN_HOT)
        draw_button(panel, 234, 56, 150, 54, "Ball rolls  L>R", "set_lr",
                    BTN_GO if sign == 1 else BTN)
        draw_button(panel, 392, 56, 150, 54, "Ball rolls  R>L", "set_rl",
                    BTN_GO if sign == -1 else BTN)
        draw_button(panel, dw - 300, 56, 140, 54, "Save & Finish", "save", BTN_GO)
        draw_button(panel, dw - 150, 56, 136, 54, "Quit", "quit")
        if msg[0] and now < msg_until[0]:
            text(panel, msg[0], 14, PANEL_H - 10, GOOD, 0.55)

        cv2.imshow("Putt Setup", np.vstack([disp, panel]))
        key = cv2.waitKey(1) & 0xFF

        action = _pending[0]; _pending[0] = None
        if key == ord('q'):
            action = 'quit'

        if action == 'quit':
            break
        elif action == 'detect':
            mode[0] = 'detect'; detect_anchor[0] = None
        elif action == 'set_lr':
            direction = 'lefttoright'
        elif action == 'set_rl':
            direction = 'righttoleft'
        elif action == 'zone_set':
            ax, ay_ = _drag_a[0]; bx_, by_ = _drag_b[0]
            nx1, nx2 = sorted((ax, bx_)); ny1, ny2 = sorted((ay_, by_))
            # map display -> proc space, clamp
            sx1 = max(0, min(PROC_W - 2, int(nx1 / s)))
            sx2 = max(sx1 + 2, min(PROC_W, int(nx2 / s)))
            y1 = max(0, int(ny1 / s)); y2 = max(y1 + 2, int(ny2 / s))
            armed[0] = False
        elif action == 'save':
            if not parser.has_section('putting'):
                parser.add_section('putting')
            parser.set('putting', 'startx1', str(sx1))
            parser.set('putting', 'startx2', str(sx2))
            parser.set('putting', 'y1', str(y1))
            parser.set('putting', 'y2', str(y2))
            parser.set('putting', 'radius', str(radius))
            parser.set('putting', 'direction', direction)
            with open(CFG_FILE, 'w') as f:
                parser.write(f)
            flash("Saved. Launch ball_tracking next.", 4)
            print("Saved zone x[%d-%d] y[%d-%d] direction=%s to %s"
                  % (sx1, sx2, y1, y2, direction, CFG_FILE))

    cap.release()
    cv2.destroyAllWindows()


if __name__ == '__main__':
    main()
