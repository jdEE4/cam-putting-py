"""Headless tests for Putt Quest (no pygame needed).

Run from the repo root:  python -m pytest putt_quest/test_putt_quest.py
"""

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
