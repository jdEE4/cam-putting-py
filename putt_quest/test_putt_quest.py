"""Headless tests for Putt Quest (no pygame needed).

Run from the repo root:  python -m pytest putt_quest/test_putt_quest.py
"""

import json
import time
import urllib.request

from putt_quest.physics import FT_TO_M, GreenPhysics, suggest_speed_mph
from putt_quest.shot_listener import ShotListener


def test_straight_putt_at_suggested_pace_drops():
    g = GreenPhysics(4.0, 0.0, 0.0, 10.0)
    v = suggest_speed_mph(4.0, 0.0, 10.0)
    assert g.simulate((0, 0), v, 0.0).holed


def test_soft_putt_stops_short():
    g = GreenPhysics(4.0, 0.0, 0.0, 10.0)
    v = suggest_speed_mph(4.0, 0.0, 10.0)
    r = g.simulate((0, 0), 0.6 * v, 0.0)
    assert not r.holed
    assert r.final_pos[1] < g.hole_pos[1]


def test_hot_putt_lips_out():
    g = GreenPhysics(4.0, 0.0, 0.0, 10.0)
    r = g.simulate((0, 0), 8.0, 0.0)
    assert r.lipped_out and not r.holed


def test_break_pushes_ball_sideways():
    g = GreenPhysics(10.0, 2.0, 0.0, 10.0)
    v = suggest_speed_mph(10.0, 0.0, 10.0)
    r = g.simulate((0, 0), v, 0.0)
    assert r.final_pos[0] > 0.05          # drifted right


def test_breaking_putt_is_makeable_with_borrow():
    g = GreenPhysics(10.0, 2.0, 0.0, 10.0)
    base = suggest_speed_mph(10.0, 0.0, 10.0)
    made = any(
        g.simulate((0, 0), base * vmul, hla / 10.0).holed
        for hla in range(0, -200, -1)
        for vmul in (1.0, 1.05, 1.1)
    )
    assert made


def test_uphill_shortens_rollout():
    flat = GreenPhysics(12.0, 0.0, 0.0, 10.0).simulate((0, 0), 4.0, 0.0)
    up = GreenPhysics(12.0, 0.0, 2.0, 10.0).simulate((0, 0), 4.0, 0.0)
    assert up.rollout_m < flat.rollout_m


def test_render3d_camera_frames_ball_and_cup():
    """Full background render + projection sanity, no window needed."""
    from putt_quest.render3d import GreenScene

    scene = GreenScene((640, 360), 4.0, 1.5, -1.0)   # 4 m breaking hole
    scene.position_camera((0.0, 0.0))
    assert scene.bg is not None and scene.bg.get_size() == (640, 360)

    ball = scene.cam.project(scene.surface_pt(0.0, 0.0, 0.02))
    cup = scene.cam.project(scene.surface_pt(0.0, 4.0, 0.02))
    assert ball and cup
    for p in (ball, cup):
        assert 0 <= p[0] <= 640 and 0 <= p[1] <= 360
    assert ball[1] > cup[1]          # ball renders below the cup
    assert cup[2] > ball[2]          # cup is farther from the camera


def test_listener_accepts_get_and_json_post():
    lis = ShotListener(port=8897)
    assert lis.start(), lis.error
    try:
        urllib.request.urlopen(
            "http://127.0.0.1:8897/?ballspeed=4.5&hla=-1.2").read()
        req = urllib.request.Request(
            "http://127.0.0.1:8897/",
            data=b'{"BallSpeed": 6.1, "HLA": 2.0}',
            headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req).read()
        time.sleep(0.1)
        s1, s2 = ShotListener.get_shot(), ShotListener.get_shot()
        assert (s1["speed_mph"], s1["hla_deg"]) == (4.5, -1.2)
        assert (s2["speed_mph"], s2["hla_deg"]) == (6.1, 2.0)
    finally:
        lis.stop()


def test_listener_accepts_real_tracker_payload():
    """ball_tracking.py posts a NESTED payload to /putting and reads back
    res.json()['result'] — both must work end to end."""
    lis = ShotListener(port=8898)
    assert lis.start(), lis.error
    try:
        req = urllib.request.Request(
            "http://127.0.0.1:8898/putting",
            data=b'{"ballData":{"BallSpeed":"4.20","TotalSpin":0,'
                 b'"LaunchDirection":"-1.30"}}',
            headers={"Content-Type": "application/json"})
        body = urllib.request.urlopen(req).read()
        assert json.loads(body)["result"] == "success"
        time.sleep(0.1)
        s = ShotListener.get_shot()
        assert s is not None, "nested ballData payload was dropped"
        assert (s["speed_mph"], s["hla_deg"]) == (4.2, -1.3)
    finally:
        lis.stop()


def test_listener_preview_frames_are_decoded_not_shots():
    import base64
    lis = ShotListener(port=8896)
    assert lis.start(), lis.error
    try:
        # a tiny valid JPEG (1x1) is enough to exercise the pipeline
        jpg = base64.b64decode(
            "/9j/4AAQSkZJRgABAQEAYABgAAD/2wBDAAEBAQEBAQEBAQEBAQEBAQEBAQEBAQEB"
            "AQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQH/wgALCAAB"
            "AAEBAREA/8QAFAABAAAAAAAAAAAAAAAAAAAAB//aAAgBAQAAPwA//9k=")
        payload = json.dumps({"frame": base64.b64encode(jpg).decode(),
                              "ready": True, "lock": 1.0,
                              "state": "ready", "w": 1, "h": 1}).encode()
        req = urllib.request.Request(
            "http://127.0.0.1:8896/preview", data=payload,
            headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req).read()
        time.sleep(0.1)
        assert ShotListener.get_shot() is None
        age, blob, meta, seq = ShotListener.get_preview()
        assert age is not None and blob == jpg and seq >= 1
        assert meta["ready"] is True and meta["state"] == "ready"
    finally:
        lis.stop()


def test_listener_status_pings_do_not_become_shots():
    lis = ShotListener(port=8899)
    assert lis.start(), lis.error
    try:
        req = urllib.request.Request(
            "http://127.0.0.1:8899/status",
            data=b'{"trackerStatus":{"ballDetected":true,"ballRadius":14,'
                 b'"fps":58.2}}',
            headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req).read()
        time.sleep(0.1)
        assert ShotListener.get_shot() is None
        age, st = ShotListener.get_tracker_status()
        assert age is not None and age < 5
        assert st["balldetected"] is True
        assert st["ballradius"] == 14
    finally:
        lis.stop()


def test_mulligan_undoes_last_putt():
    """Mulligan must uncount the stroke, restore position, and refuse
    when there's nothing to undo."""
    import os
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    from putt_quest.game import Game, State
    from putt_quest.courses import COURSES
    g = Game()
    g.start_round(COURSES[0])
    # nothing to undo yet
    assert g.mulligan() is False
    assert g.round.scores[0].putts == 0

    # fire a putt, then mulligan while it rolls
    g.take_shot(4.0, 0.0)
    assert g.state == State.ROLLING
    assert g.round.scores[0].putts == 1
    ok = g.mulligan()
    assert ok is True
    assert g.state == State.AWAIT_PUTT
    assert g.round.scores[0].putts == 0
    assert g.round.scores[0].mulligans == 1
    assert g.ball.vx == 0.0 and g.ball.vy == 0.0

    # only one undo per shot
    assert g.mulligan() is False
    assert g.round.scores[0].putts == 0



# ---------------------------------------------------------- mini golf
import math

from putt_quest.courses import COURSES, PORTAL_PARK, WINDMILL_GARDENS
from putt_quest.minigolf import (Boost, HoleFeatures, Portal, Sand, Wall,
                                 Windmill, rails)


def test_minigolf_courses_registered():
    names = [c.name for c in COURSES]
    assert "Windmill Gardens" in names and "Portal Park" in names
    for course in (WINDMILL_GARDENS, PORTAL_PARK):
        assert len(course.holes) == 9
        for h in course.holes:
            assert h.features is not None
            assert h.features.walls, f"{h.name} must be fully railed"


def test_wall_bounces_ball_back():
    feats = HoleFeatures(walls=(Wall(-1.0, 1.0, 1.0, 1.0),))
    g = GreenPhysics(10.0, 0.0, 0.0, 10.0, features=feats)
    r = g.simulate((0, 0), 4.0, 0.0)
    assert not r.holed
    # ball hit the wall at y=1.0 and came back: never got past it
    assert max(y for _, y in r.path) < 1.05
    assert r.final_pos[1] < 1.0


def test_bank_shot_reflects_angle():
    # fire at 45 degrees into the right rail; ball must come back leftward
    feats = HoleFeatures(walls=(Wall(0.5, -1.0, 0.5, 4.0),))
    g = GreenPhysics(10.0, 0.0, 0.0, 10.0, features=feats)
    r = g.simulate((0, 0), 5.0, 40.0)
    assert min(x for x, _ in r.path) < -0.1   # crossed back over the line
    assert max(x for x, _ in r.path) <= 0.55  # never passed the rail


def test_portal_teleports_ball():
    feats = HoleFeatures(portals=(Portal(0.0, 1.0, 1.5, 2.5),))
    g = GreenPhysics(12.0, 0.0, 0.0, 10.0, features=feats)
    r = g.simulate((0, 0), 3.0, 0.0)
    # the path must jump: some point lands near the B ring exit
    assert any(math.hypot(x - 1.5, y - 2.5) < 0.6 for x, y in r.path)


def test_sand_shortens_rollout():
    g_clean = GreenPhysics(20.0, 0.0, 0.0, 10.0)
    sandy = HoleFeatures(sand=(Sand(0.0, 1.5, 0.8, friction=4.0),))
    g_sand = GreenPhysics(20.0, 0.0, 0.0, 10.0, features=sandy)
    clean = g_clean.simulate((0, 0), 5.0, 0.0).rollout_m
    sand = g_sand.simulate((0, 0), 5.0, 0.0).rollout_m
    assert sand < clean * 0.8


def test_boost_lengthens_rollout():
    boosted = HoleFeatures(boosts=(Boost(-1.0, 0.5, 1.0, 2.0, ay=2.0),))
    g_boost = GreenPhysics(20.0, 0.0, 0.0, 10.0, features=boosted)
    g_clean = GreenPhysics(20.0, 0.0, 0.0, 10.0)
    assert (g_boost.simulate((0, 0), 3.0, 0.0).rollout_m
            > g_clean.simulate((0, 0), 3.0, 0.0).rollout_m)


def test_static_windmill_blade_blocks():
    # omega=0 with phase 90deg parks one blade vertically across the line
    feats = HoleFeatures(windmills=(
        Windmill(0.0, 1.5, blades=2, length=0.6, omega=0.0,
                 phase=math.pi / 2),))
    g = GreenPhysics(10.0, 0.0, 0.0, 10.0, features=feats)
    r = g.simulate((0, 0), 3.0, 0.0)
    assert not r.holed
    assert r.final_pos[1] < 1.5


def test_offset_cup_dogleg_reachable():
    # The Mail Slot: cup at (1.0, 3.05m); the slot on the diagonal must
    # let a realistic putt drop
    hole = WINDMILL_GARDENS.holes[1]
    g = GreenPhysics(hole.distance_ft, hole.break_pct, hole.slope_pct,
                     WINDMILL_GARDENS.stimp, features=hole.features)
    assert g.hole_pos[0] == 1.0
    made = any(g.simulate((0, 0), spd / 10.0, hla / 10.0).holed
               for spd in range(18, 66, 2)
               for hla in range(-240, 241, 15))
    assert made


def test_every_minigolf_hole_is_winnable():
    """Brute-force each hole with a REALISTIC putt fan (<= 6.4 mph and
    |HLA| <= 24 deg relative to the cup line, which is what a real putt
    off the mat can deliver). Every hole must be aceable from the tee."""
    for course in (WINDMILL_GARDENS, PORTAL_PARK):
        for hole in course.holes:
            g = GreenPhysics(hole.distance_ft, hole.break_pct,
                             hole.slope_pct, course.stimp,
                             features=hole.features)
            made = False
            for spd in range(18, 66, 2):
                for hla in range(-240, 241, 15):
                    if g.simulate((0, 0), spd / 10.0, hla / 10.0,
                                  dt=1 / 240.0).holed:
                        made = True
                        break
                if made:
                    break
            assert made, f"{course.name} #{hole.number} {hole.name} unwinnable"


def test_simulation_always_terminates_in_rails():
    # hardest case: lively bumper field fully enclosed
    hole = PORTAL_PARK.holes[2]
    g = GreenPhysics(hole.distance_ft, 0.0, 0.0, 12.0,
                     features=hole.features)
    r = g.simulate((0, 0), 8.0, 13.0)
    fx, fy = r.final_pos
    assert -1.25 <= fx <= 1.25 and -0.85 <= fy <= 4.5
