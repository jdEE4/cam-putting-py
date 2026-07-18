# Webcam exposure / FPS tuning helper for cam-putting-py
#
# The usual reason a "60fps" webcam only delivers ~30fps is auto exposure:
# in dim light the driver picks a shutter time longer than 1/60s and the
# sensor physically cannot produce 60 frames per second anymore. This tool
# shows the MEASURED fps next to the fps the driver reports, lets you step
# the exposure down until the measured value holds your target, and saves
# the result to config.ini so ball_tracking.py starts with the same values.
#
# Usage:
#   python camera_tune.py                  live tuning view (settings from config.ini)
#   python camera_tune.py --probe          scan resolution/fps combinations and exit
#   python camera_tune.py -w 1 --fps 60 --width 640 --height 480
#   python camera_tune.py --color orange2  overlay ball mask with this color preset
#
# Keys in the live view:
#   e / E   exposure down / up          g / G   gain down / up
#   b / B   brightness down / up        a       toggle auto exposure
#   r       reset: hand exposure back to auto (recover from a black screen)
#   m       toggle ball mask + radius preview
#   c       open driver settings dialog (Windows DirectShow only)
#   s       save current camera values to config.ini (skipped if frame is black)
#   q       quit without saving

import argparse
import ast
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

# same presets as ball_tracking.py
BALL_COLORS = {
    'red':     {'hmin': 1, 'smin': 208, 'vmin': 0, 'hmax': 50, 'smax': 255, 'vmax': 249},
    'red2':    {'hmin': 1, 'smin': 240, 'vmin': 61, 'hmax': 50, 'smax': 255, 'vmax': 249},
    'white':   {'hmin': 168, 'smin': 218, 'vmin': 118, 'hmax': 179, 'smax': 247, 'vmax': 216},
    'white2':  {'hmin': 159, 'smin': 217, 'vmin': 152, 'hmax': 179, 'smax': 255, 'vmax': 255},
    'white3':  {'hmin': 0, 'smin': 181, 'vmin': 0, 'hmax': 42, 'smax': 255, 'vmax': 255},
    'yellow':  {'hmin': 0, 'smin': 210, 'vmin': 0, 'hmax': 15, 'smax': 255, 'vmax': 255},
    'yellow2': {'hmin': 0, 'smin': 150, 'vmin': 100, 'hmax': 46, 'smax': 255, 'vmax': 206},
    'green':   {'hmin': 0, 'smin': 169, 'vmin': 161, 'hmax': 177, 'smax': 204, 'vmax': 255},
    'green2':  {'hmin': 0, 'smin': 109, 'vmin': 74, 'hmax': 81, 'smax': 193, 'vmax': 117},
    'orange':  {'hmin': 0, 'smin': 219, 'vmin': 147, 'hmax': 19, 'smax': 255, 'vmax': 255},
    'orange2': {'hmin': 3, 'smin': 181, 'vmin': 134, 'hmax': 40, 'smax': 255, 'vmax': 255},
    'orange3': {'hmin': 0, 'smin': 73, 'vmin': 150, 'hmax': 40, 'smax': 255, 'vmax': 255},
    'orange4': {'hmin': 3, 'smin': 181, 'vmin': 216, 'hmax': 40, 'smax': 255, 'vmax': 255},
}

PROBE_RESOLUTIONS = [(640, 480), (800, 600), (1024, 576), (1280, 720), (320, 240)]
PROBE_FPS = [120, 90, 60, 50, 30]


def resolve_backend(name):
    name = (name or 'auto').strip().lower()
    if name in CAMERA_BACKENDS:
        return CAMERA_BACKENDS[name]
    if platform.system() == 'Windows':
        return cv2.CAP_DSHOW
    return cv2.CAP_ANY


def backend_label(cap):
    try:
        return cap.getBackendName()
    except cv2.error:
        return 'unknown'


def open_camera(index, api, width, height, fps, use_mjpeg):
    cap = cv2.VideoCapture(index, api)
    if not cap.isOpened():
        return cap
    if use_mjpeg:
        # MJPG first - high fps modes are usually only available compressed
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
    if width and height:
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
    if fps:
        cap.set(cv2.CAP_PROP_FPS, fps)
    return cap


def measure_fps(cap, frames=60, warmup=10):
    for _ in range(warmup):
        cap.read()
    start = time.time()
    good = 0
    for _ in range(frames):
        ret, _ = cap.read()
        if ret:
            good += 1
    elapsed = time.time() - start
    if elapsed <= 0 or good == 0:
        return 0.0
    return good / elapsed


def probe(index, api, use_mjpeg, target_fps):
    print("Probing camera %d (this reopens the camera per mode, be patient)..." % index)
    print("%-12s %-10s %-12s %-12s %s" % ("requested", "got res", "driver fps", "measured", "verdict"))
    results = []
    for (w, h) in PROBE_RESOLUTIONS:
        for fps in PROBE_FPS:
            cap = open_camera(index, api, w, h, fps, use_mjpeg)
            if not cap.isOpened():
                print("could not open camera at index %d" % index)
                return results
            got_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            got_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            driver_fps = cap.get(cv2.CAP_PROP_FPS)
            measured = measure_fps(cap, frames=40, warmup=8)
            cap.release()
            ok = measured >= target_fps * 0.95
            verdict = "OK" if ok else ""
            print("%-12s %-10s %-12.1f %-12.1f %s"
                  % ("%dx%d@%d" % (w, h, fps), "%dx%d" % (got_w, got_h), driver_fps, measured, verdict))
            results.append((w, h, fps, got_w, got_h, driver_fps, measured))
    good = [r for r in results if r[6] >= target_fps * 0.95]
    if good:
        best = max(good, key=lambda r: (r[6], r[3] * r[4]))
        print("\nBest mode >= %dfps: %dx%d requested @%d (measured %.1f fps)"
              % (target_fps, best[0], best[1], best[2], best[6]))
        print("Suggested config.ini values:  width = %d  height = %d  fps = %d" % (best[0], best[1], best[2]))
    else:
        print("\nNo mode reached %d fps. Add light, lower the resolution, or force manual" % target_fps)
        print("exposure (run the live view and press 'a' then 'e' to shorten the shutter).")
    return results


def find_ball(frame, hsv_vals):
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    lower = np.array([hsv_vals['hmin'], hsv_vals['smin'], hsv_vals['vmin']])
    upper = np.array([hsv_vals['hmax'], hsv_vals['smax'], hsv_vals['vmax']])
    mask = cv2.inRange(hsv, lower, upper)
    mask = cv2.erode(mask, None, iterations=2)
    mask = cv2.dilate(mask, None, iterations=2)
    contours, _ = cv2.findContours(mask.copy(), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return mask, None
    largest = max(contours, key=cv2.contourArea)
    ((x, y), radius) = cv2.minEnclosingCircle(largest)
    return mask, (int(x), int(y), radius)


def put_line(img, text, row, color=(255, 255, 255)):
    cv2.putText(img, text, (10, 22 + row * 22), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 0), 3)
    cv2.putText(img, text, (10, 22 + row * 22), cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 1)


def main():
    parser = ConfigParser(strict=False)
    parser.read(CFG_FILE)

    def cfg(option, fallback):
        if parser.has_option('putting', option):
            return parser.get('putting', option)
        return fallback

    ap = argparse.ArgumentParser(description="Webcam exposure / FPS tuning for cam-putting-py")
    ap.add_argument("-w", "--camera", type=int, default=0, help="webcam index - default 0")
    ap.add_argument("--width", type=int, default=int(cfg('width', 0)), help="capture width (default from config.ini)")
    ap.add_argument("--height", type=int, default=int(cfg('height', 0)), help="capture height (default from config.ini)")
    ap.add_argument("--fps", type=int, default=int(cfg('fps', 60)) or 60, help="target fps (default from config.ini, min goal 60)")
    ap.add_argument("--backend", default=cfg('backend', 'auto'), help="auto | dshow | msmf | avfoundation | v4l2 | any")
    ap.add_argument("--no-mjpeg", action="store_true", help="do not force the MJPG compressed format")
    ap.add_argument("--color", default=None, help="ball color preset for the mask preview (e.g. orange2)")
    ap.add_argument("--probe", action="store_true", help="scan resolution/fps combinations and exit")
    args = ap.parse_args()

    api = resolve_backend(args.backend)
    use_mjpeg = not args.no_mjpeg and int(cfg('mjpeg', 1)) != 0

    if args.probe:
        probe(args.camera, api, use_mjpeg, args.fps)
        return

    # ball mask source: customhsv from config.ini wins, else --color preset
    hsv_vals = None
    if parser.has_option('putting', 'customhsv'):
        hsv_vals = ast.literal_eval(parser.get('putting', 'customhsv'))
        print("Using customhsv from config.ini for the mask preview")
    if args.color:
        hsv_vals = BALL_COLORS.get(args.color, hsv_vals)
    if hsv_vals is None:
        hsv_vals = BALL_COLORS['yellow']

    cap = open_camera(args.camera, api, args.width, args.height, args.fps, use_mjpeg)
    if not cap.isOpened():
        print("Could not open camera at index %d (backend %s)" % (args.camera, args.backend))
        return

    print("Backend: %s" % backend_label(cap))
    print("Driver reports %.1f fps at %dx%d"
          % (cap.get(cv2.CAP_PROP_FPS), cap.get(cv2.CAP_PROP_FRAME_WIDTH), cap.get(cv2.CAP_PROP_FRAME_HEIGHT)))

    show_mask = False
    frame_times = []
    is_windows = platform.system() == 'Windows'

    def bump(prop, delta):
        cap.set(prop, cap.get(prop) + delta)

    while True:
        ret, frame = cap.read()
        now = time.time()
        if not ret:
            print("Frame grab failed - camera disconnected?")
            break
        frame_times.append(now)
        frame_times = [t for t in frame_times if now - t <= 2.0]
        measured = (len(frame_times) - 1) / (frame_times[-1] - frame_times[0]) if len(frame_times) > 5 else 0.0

        exposure = cap.get(cv2.CAP_PROP_EXPOSURE)
        gain = cap.get(cv2.CAP_PROP_GAIN)
        brightness = cap.get(cv2.CAP_PROP_BRIGHTNESS)
        autoexposure = cap.get(cv2.CAP_PROP_AUTO_EXPOSURE)

        display = frame.copy()
        fps_ok = measured >= args.fps * 0.95
        put_line(display, "measured %.1f fps  (target %d)" % (measured, args.fps),
                 0, (0, 255, 0) if fps_ok else (0, 0, 255))
        put_line(display, "driver fps %.1f  res %dx%d  backend %s"
                 % (cap.get(cv2.CAP_PROP_FPS), cap.get(cv2.CAP_PROP_FRAME_WIDTH),
                    cap.get(cv2.CAP_PROP_FRAME_HEIGHT), backend_label(cap)), 1)
        put_line(display, "exposure %.2f (e/E)  gain %.1f (g/G)  brightness %.1f (b/B)"
                 % (exposure, gain, brightness), 2)
        put_line(display, "autoexposure %.2f (a toggles, r resets)  mask (m)  save (s)  quit (q)" % autoexposure, 3)
        if not fps_ok and measured > 0:
            put_line(display, "below target: shorten exposure (e) or add light", 4, (0, 255, 255))

        if show_mask:
            mask, ball = find_ball(frame, hsv_vals)
            if ball is not None:
                (bx, by, radius) = ball
                cv2.circle(display, (bx, by), int(radius), (0, 0, 255), 2)
                # ball_tracking.py derives mm-per-pixel from this radius; a
                # radius around 8-20 px means the mounting distance is usable
                good_radius = 8 <= radius <= 20
                put_line(display, "ball radius %.1f px %s" % (radius, "(good)" if good_radius else "(adjust camera distance)"),
                         5, (0, 255, 0) if good_radius else (0, 255, 255))
            else:
                put_line(display, "no ball found for current HSV values", 5, (0, 0, 255))
            cv2.imshow("Ball Mask", mask)

        cv2.imshow("Camera Tune - q quits", display)
        key = cv2.waitKey(1) & 0xFF

        if key == ord('q'):
            break
        elif key == ord('e'):
            bump(cv2.CAP_PROP_EXPOSURE, -1)
        elif key == ord('E'):
            bump(cv2.CAP_PROP_EXPOSURE, 1)
        elif key == ord('g'):
            bump(cv2.CAP_PROP_GAIN, -1)
        elif key == ord('G'):
            bump(cv2.CAP_PROP_GAIN, 1)
        elif key == ord('b'):
            bump(cv2.CAP_PROP_BRIGHTNESS, -1)
        elif key == ord('B'):
            bump(cv2.CAP_PROP_BRIGHTNESS, 1)
        elif key == ord('a'):
            # OpenCV convention: 0.25 = manual, 0.75 = auto
            current = cap.get(cv2.CAP_PROP_AUTO_EXPOSURE)
            cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 0.25 if current != 0.25 else 0.75)
        elif key == ord('r'):
            # panic reset: hand exposure back to the camera's auto so a
            # blacked-out manual setting is always recoverable without a restart
            cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 0.75)
            print("Reset: auto exposure re-enabled")
        elif key == ord('m'):
            show_mask = not show_mask
            if not show_mask:
                cv2.destroyWindow("Ball Mask")
        elif key == ord('c') and is_windows:
            cap.set(cv2.CAP_PROP_SETTINGS, 37)
        elif key == ord('s'):
            # refuse to persist a broken state - a black or dead frame saved
            # here would make ball_tracking.py start black on every launch
            brightness_mean = float(frame.mean())
            if brightness_mean < 5 or measured < 1:
                print("NOT saving: frame looks black (mean %.1f) or fps is %.1f. "
                      "Press 'r' to reset exposure, get a good image, then save."
                      % (brightness_mean, measured))
            else:
                if not parser.has_section('putting'):
                    parser.add_section('putting')
                parser.set('putting', 'exposure', str(cap.get(cv2.CAP_PROP_EXPOSURE)))
                parser.set('putting', 'gain', str(cap.get(cv2.CAP_PROP_GAIN)))
                parser.set('putting', 'brightness', str(cap.get(cv2.CAP_PROP_BRIGHTNESS)))
                parser.set('putting', 'autoexposure', str(cap.get(cv2.CAP_PROP_AUTO_EXPOSURE)))
                if args.width and args.height:
                    parser.set('putting', 'width', str(args.width))
                    parser.set('putting', 'height', str(args.height))
                parser.set('putting', 'fps', str(args.fps))
                with open(CFG_FILE, 'w') as f:
                    parser.write(f)
                print("Saved camera settings to %s" % CFG_FILE)

    cap.release()
    cv2.destroyAllWindows()


if __name__ == '__main__':
    main()
