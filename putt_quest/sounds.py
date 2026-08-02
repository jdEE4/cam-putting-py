"""Procedurally synthesized sound effects for Putt Quest.

Every effect is generated with numpy at startup (sine partials, noise
bursts, pitch sweeps, ADSR-ish envelopes) and turned into pygame Sounds —
no audio files in the repo. If there is no audio device (headless tests,
CI) the manager silently disables itself and every play() is a no-op.
"""

from __future__ import annotations

import math

import numpy as np
import pygame

SR = 22050
MASTER = 0.8


def _env(n: int, attack: float = 0.005, decay: float = 1.0) -> np.ndarray:
    """Simple attack + exponential-decay envelope of n samples."""
    t = np.arange(n) / SR
    a = np.minimum(1.0, t / max(attack, 1e-4))
    d = np.exp(-t * (5.0 / max(decay, 1e-3)))
    return a * d


def _tone(freq, secs, decay=None, vibrato=0.0):
    n = int(SR * secs)
    t = np.arange(n) / SR
    ph = 2 * np.pi * freq * t
    if vibrato:
        ph = ph + vibrato * np.sin(2 * np.pi * 6.0 * t)
    return np.sin(ph) * _env(n, decay=decay or secs)


def _sweep(f0, f1, secs, decay=None):
    n = int(SR * secs)
    t = np.arange(n) / SR
    freq = f0 + (f1 - f0) * (t / secs)
    ph = 2 * np.pi * np.cumsum(freq) / SR
    return np.sin(ph) * _env(n, decay=decay or secs)


def _noise(secs, decay=None, lowpass=1):
    n = int(SR * secs)
    x = np.random.default_rng(7).uniform(-1, 1, n)
    for _ in range(lowpass):                     # crude lowpass: smoothing
        x = np.convolve(x, np.ones(8) / 8.0, mode="same")
    return x * _env(n, decay=decay or secs)


def _mix(*parts):
    n = max(len(p) for p in parts)
    out = np.zeros(n)
    for p in parts:
        out[:len(p)] += p
    peak = np.max(np.abs(out)) or 1.0
    return out / peak


def _delay(sig, secs):
    return np.concatenate([np.zeros(int(SR * secs)), sig])


def _build_all() -> dict:
    """Synthesize the full effect bank; returns {name: mono float array}."""
    fx = {}
    # putter click: tick + a touch of body
    fx["putt"] = _mix(_noise(0.03, decay=0.02, lowpass=0),
                      _tone(190, 0.06, decay=0.05) * 0.7)
    # rail thock: woody low knock
    fx["wall"] = _mix(_tone(130, 0.09, decay=0.06),
                      _noise(0.03, decay=0.02) * 0.4)
    # bumper: springy downward boing
    fx["bumper"] = _sweep(420, 180, 0.16, decay=0.12)
    # windmill: inharmonic metallic clang
    fx["windmill"] = _mix(_tone(520, 0.34, decay=0.28),
                          _tone(1372, 0.30, decay=0.20) * 0.6,
                          _tone(2145, 0.22, decay=0.12) * 0.35,
                          _noise(0.04, decay=0.03) * 0.5)
    # portal: rising warp sweep + shimmer tail
    fx["portal"] = _mix(_sweep(180, 940, 0.28, decay=0.30),
                        _delay(_tone(1240, 0.18, decay=0.15,
                                     vibrato=0.6) * 0.5, 0.12))
    # sand: soft dead thud
    fx["sand"] = _noise(0.12, decay=0.07, lowpass=3)
    # water: splash (noise burst + low bloop)
    fx["splash"] = _mix(_noise(0.30, decay=0.18, lowpass=2),
                        _sweep(300, 90, 0.18, decay=0.15) * 0.8)
    # chute: rolling rattle down a tube
    fx["chute"] = _mix(_noise(0.35, decay=0.35, lowpass=2) * 0.7,
                       _sweep(500, 240, 0.35, decay=0.35) * 0.4)
    # cup sink: pop + rising three-note chime
    fx["sink"] = _mix(_tone(660, 0.30, decay=0.22),
                      _delay(_tone(880, 0.28, decay=0.20), 0.09),
                      _delay(_tone(1108, 0.34, decay=0.26), 0.18),
                      _noise(0.02, decay=0.015) * 0.6)
    # lip out: short sour wobble
    fx["lip"] = _sweep(520, 470, 0.12, decay=0.10)
    # round-done fanfare: little arpeggio flourish
    notes = [(523, 0.0), (659, 0.11), (784, 0.22), (1046, 0.33)]
    fx["fanfare"] = _mix(*[_delay(_tone(f, 0.5, decay=0.4), d)
                           for f, d in notes])
    return fx


class SFX:
    """play('name') fire-and-forget sound manager. Safe with no audio."""

    def __init__(self) -> None:
        self.enabled = False
        self._sounds = {}
        try:
            if pygame.mixer.get_init() is None:
                pygame.mixer.init(frequency=SR, size=-16, channels=2,
                                  buffer=512)
            pygame.mixer.set_num_channels(12)
        except pygame.error:
            return                      # no audio device: stay disabled
        try:
            for name, mono in _build_all().items():
                pcm = (np.clip(mono, -1, 1) * 32767 * MASTER).astype(np.int16)
                stereo = np.column_stack([pcm, pcm])
                self._sounds[name] = pygame.sndarray.make_sound(
                    np.ascontiguousarray(stereo))
            self.enabled = True
        except (pygame.error, ValueError):
            self._sounds = {}

    def play(self, name: str, volume: float = 1.0) -> None:
        if not self.enabled:
            return
        snd = self._sounds.get(name)
        if snd is not None:
            snd.set_volume(max(0.0, min(1.0, volume)))
            snd.play()
