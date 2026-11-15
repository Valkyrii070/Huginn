"""Tempo's sound engine: instruments, drums, effects and the mix, in numpy, a block at a time.

    time            projects count in beats; the engine in samples (48 kHz, stereo, float)
    instruments     synthesisers (subtractive with unison and a filter that opens and closes, FM electric piano,
                    drawbar organ, plucked strings) and General MIDI instruments from a SoundFont, played through
                    FluidSynth once into a set of notes and then sampled, so they play instantly and live too
    drums           a kit made here, sound by sound (kick, snare, hats, clap, toms, cymbals, percussion), in three
                    flavours: Studio, Electronic (808-like) and Vintage
    regions         MIDI regions are drawn to audio once (and again only when they change); audio regions are decoded
                    once; a block of the song is the sum of whatever regions sound in it
    effects         on each track: EQ (three bands), compressor, drive, chorus, delay (in time with the song) and
                    a filter; sends to one shared reverb (partitioned convolution) and one shared echo; on the master
                    a limiter
    automation      every knob drawn over time: volume, pan, the sends and each effect's settings
    audio editing   gain, fades, reverse, transpose and following the song's tempo (a phase vocoder made here);
                    takes from cycle recording, and comps cut from them
    routing         track stacks (a bus with its own effects that tracks play into) and sidechain compression
                    (a track ducking under another, the kick pushing the bass down)
    sampler         any sound as an instrument across the keys (its pitch heard), and sounds of your own on drum pads
    MIDI effects    an arpeggiator and chord trigger in front of an instrument
    files           WAV, FLAC, MP3, Ogg and AAC out (and stems); Standard MIDI Files in and out
"""
import hashlib
import json
import math
import os
import shutil
import struct
import subprocess
import wave
from pathlib import Path

import numpy as np
from scipy.signal import lfilter

SR = 48000
BLOCK = 1024
CACHE = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "huginn" / "tempo"
SOUNDFONTS = ["/usr/share/sounds/sf2/FluidR3_GM.sf2", "/usr/share/sounds/sf2/default-GM.sf2", "/usr/share/sounds/sf2/TimGM6mb.sf2",
              "/usr/share/soundfonts/default.sf2", "/usr/share/soundfonts/FluidR3_GM.sf2"]
NOTE_NAMES = ["C", "C♯", "D", "E♭", "E", "F", "F♯", "G", "A♭", "A", "B♭", "B"]
DRUM_NAMES = {35: "Kick 2", 36: "Kick", 37: "Rim", 38: "Snare", 39: "Clap", 40: "Snare 2", 41: "Low tom", 42: "Closed hat", 43: "Low tom 2",
              44: "Pedal hat", 45: "Mid tom", 46: "Open hat", 47: "Mid tom 2", 48: "High tom", 49: "Crash", 50: "High tom 2", 51: "Ride",
              53: "Ride bell", 54: "Tambourine", 56: "Cowbell", 57: "Crash 2", 70: "Shaker", 75: "Claves"}
KIT_ROWS = [49, 51, 46, 42, 50, 47, 41, 39, 38, 37, 36, 54, 56]


def freq(pitch: float) -> float:
    return 440.0 * 2 ** ((pitch - 69) / 12)


def note_name(pitch: int) -> str:
    return f"{NOTE_NAMES[pitch % 12]}{pitch // 12 - 1}"


def beats_to_s(beats: float, tempo: float) -> float:
    return beats * 60.0 / tempo


def s_to_beats(s: float, tempo: float) -> float:
    return s * tempo / 60.0


def db(x: float) -> float:
    return 10 ** (x / 20)


# ------------------------------------------------------------------------------------------------ envelopes and waves
def adsr(n: int, sr: int, a: float, d: float, s: float, r: float, held: int) -> np.ndarray:
    """An envelope n samples long: attack, decay to sustain while held, then release from wherever it got to."""
    env = np.empty(n, np.float32)
    held = max(1, min(held, n))
    na, nd = max(1, int(a * sr)), max(1, int(d * sr))
    t = np.arange(held, dtype=np.float32)
    on = np.where(t < na, t / na, s + (1 - s) * np.exp(-(t - na) / (nd / 4.0)))
    env[:held] = on
    level = float(on[-1])
    nr = n - held
    if nr > 0:
        env[held:] = level * np.exp(-np.arange(nr, dtype=np.float32) / max(1.0, r * sr / 5.0))
    return env


def polyblep(phase: np.ndarray, dt: float) -> np.ndarray:
    out = np.zeros_like(phase)
    lo = phase < dt
    x = phase[lo] / dt
    out[lo] = x + x - x * x - 1
    hi = phase > 1 - dt
    x = (phase[hi] - 1) / dt
    out[hi] = x * x + x + x + 1
    return out


def oscillator(kind: str, f: float, n: int, sr: int, start_phase: float = 0.0) -> np.ndarray:
    dt = f / sr
    phase = (start_phase + dt * np.arange(n, dtype=np.float64)) % 1.0
    if kind == "sine":
        return np.sin(2 * np.pi * phase).astype(np.float32)
    if kind == "triangle":
        return (4 * np.abs(phase - 0.5) - 1).astype(np.float32)
    if kind == "square":
        sq = np.where(phase < 0.5, 1.0, -1.0) + polyblep(phase, dt) - polyblep((phase + 0.5) % 1.0, dt)
        return sq.astype(np.float32)
    saw = 2 * phase - 1 - polyblep(phase, dt)
    return saw.astype(np.float32)


def biquad(kind: str, f: float, q: float = 0.707, gain_db: float = 0.0, sr: int = SR):
    """RBJ cookbook biquad coefficients (b, a)."""
    f = max(10.0, min(f, sr * 0.45))
    w = 2 * math.pi * f / sr
    cw, sw = math.cos(w), math.sin(w)
    alpha = sw / (2 * max(0.05, q))
    A = 10 ** (gain_db / 40)
    if kind == "lowpass":
        b = [(1 - cw) / 2, 1 - cw, (1 - cw) / 2]
        a = [1 + alpha, -2 * cw, 1 - alpha]
    elif kind == "highpass":
        b = [(1 + cw) / 2, -(1 + cw), (1 + cw) / 2]
        a = [1 + alpha, -2 * cw, 1 - alpha]
    elif kind == "bandpass":
        b = [alpha, 0, -alpha]
        a = [1 + alpha, -2 * cw, 1 - alpha]
    elif kind == "peak":
        b = [1 + alpha * A, -2 * cw, 1 - alpha * A]
        a = [1 + alpha / A, -2 * cw, 1 - alpha / A]
    elif kind == "lowshelf":
        sq = 2 * math.sqrt(A) * alpha
        b = [A * ((A + 1) - (A - 1) * cw + sq), 2 * A * ((A - 1) - (A + 1) * cw), A * ((A + 1) - (A - 1) * cw - sq)]
        a = [(A + 1) + (A - 1) * cw + sq, -2 * ((A - 1) + (A + 1) * cw), (A + 1) + (A - 1) * cw - sq]
    else:                                                      # highshelf
        sq = 2 * math.sqrt(A) * alpha
        b = [A * ((A + 1) + (A - 1) * cw + sq), -2 * A * ((A - 1) + (A + 1) * cw), A * ((A + 1) + (A - 1) * cw - sq)]
        a = [(A + 1) - (A - 1) * cw + sq, 2 * ((A - 1) - (A + 1) * cw), (A + 1) - (A - 1) * cw - sq]
    return np.array(b) / a[0], np.array(a) / a[0]


def filt(x: np.ndarray, kind: str, f: float, q: float = 0.707) -> np.ndarray:
    b, a = biquad(kind, f, q)
    return lfilter(b, a, x).astype(np.float32)


# ------------------------------------------------------------------------------------------------ instruments
INSTRUMENTS = {
    # name, family, how it's made, its sound
    "grand": {"name": "Grand Piano", "family": "Keyboards", "engine": "gm", "program": 0, "fallback": "epiano"},
    "bright": {"name": "Bright Piano", "family": "Keyboards", "engine": "gm", "program": 1, "fallback": "epiano"},
    "epiano": {"name": "Electric Piano", "family": "Keyboards", "engine": "fm", "ratio": 1.0, "index": 3.2, "idecay": 1.2, "attack": 0.002, "decay": 1.6, "sustain": 0.25, "release": 0.4},
    "organ": {"name": "Rock Organ", "family": "Keyboards", "engine": "organ", "bars": [0.8, 1.0, 0.6, 0.0, 0.5, 0.0, 0.3, 0.2], "attack": 0.004, "decay": 0.1, "sustain": 1.0, "release": 0.06},
    "pad": {"name": "Warm Pad", "family": "Synths", "engine": "sub", "osc": "saw", "voices": 3, "detune": 14, "attack": 0.5, "decay": 0.8, "sustain": 0.85, "release": 1.4,
            "cutoff": 1400, "env": 1600, "res": 0.9, "octave": 0},
    "strings": {"name": "Strings", "family": "Orchestral", "engine": "gm", "program": 48, "fallback": "pad"},
    "lead": {"name": "Bright Lead", "family": "Synths", "engine": "sub", "osc": "square", "voices": 2, "detune": 8, "attack": 0.004, "decay": 0.25, "sustain": 0.7, "release": 0.2,
             "cutoff": 2600, "env": 4200, "res": 1.4, "octave": 0},
    "bass": {"name": "Deep Bass", "family": "Bass", "engine": "sub", "osc": "saw", "voices": 1, "detune": 0, "sub": 0.6, "attack": 0.003, "decay": 0.3, "sustain": 0.5, "release": 0.12,
             "cutoff": 380, "env": 1500, "res": 1.1, "octave": 0},
    "fingered": {"name": "Fingered Bass", "family": "Bass", "engine": "gm", "program": 33, "fallback": "bass"},
    "pluck": {"name": "Plucked Synth", "family": "Synths", "engine": "pluck", "damp": 0.996, "bright": 0.6, "release": 0.25},
    "guitar": {"name": "Acoustic Guitar", "family": "Guitar", "engine": "gm", "program": 25, "fallback": "pluck"},
    "brass": {"name": "Brass", "family": "Orchestral", "engine": "gm", "program": 61, "fallback": "lead"},
    "drums": {"name": "Studio Kit", "family": "Drums", "engine": "kit", "kit": "studio"},
    "electronic": {"name": "Electronic Kit", "family": "Drums", "engine": "kit", "kit": "electronic"},
    "vintage": {"name": "Vintage Kit", "family": "Drums", "engine": "kit", "kit": "vintage"},
    "sampler": {"name": "Sampler", "family": "Sampler", "engine": "sampler", "file": "", "root": 60, "mode": "held", "attack": 0.002, "release": 0.15,
                "start": 0.0, "end": 1.0, "tune": 0.0},
}
SMART = {   # the Smart Controls each kind of instrument has: [key, name, low, high]
    "sub": [["cutoff", "Brightness", 120, 9000], ["res", "Resonance", 0.5, 6], ["attack", "Attack", 0.001, 2.0], ["release", "Release", 0.02, 4.0], ["detune", "Width", 0, 40]],
    "fm": [["index", "Bark", 0.2, 8], ["idecay", "Ring", 0.1, 4], ["decay", "Sustain", 0.2, 4], ["release", "Release", 0.05, 2]],
    "organ": [["bar0", "Sub", 0, 1], ["bar1", "Body", 0, 1], ["bar2", "Octave", 0, 1], ["bar4", "Twelfth", 0, 1], ["bar6", "Sparkle", 0, 1]],
    "pluck": [["damp", "Sustain", 0.98, 0.9995], ["bright", "Brightness", 0.1, 1.0], ["release", "Release", 0.05, 1.5]],
    "gm": [["tone", "Tone", -1, 1], ["release", "Release", 0.05, 2.0]],
    "kit": [["tune", "Tuning", -6, 6], ["decay", "Length", 0.4, 1.8], ["punch", "Punch", 0, 1]],
    "sampler": [["start", "Start", 0, 0.95], ["end", "End", 0.05, 1], ["attack", "Attack", 0.001, 1.0], ["release", "Release", 0.01, 3.0], ["tune", "Fine tune", -1, 1]],
}


def settings(inst: dict) -> dict:
    """An instrument's sound: its kind's defaults with the track's own changes over them."""
    base = dict(INSTRUMENTS.get(inst.get("id", "grand"), INSTRUMENTS["grand"]))
    base.update({k: v for k, v in inst.items() if k != "id"})
    return base


def soundfont() -> str:
    return next((f for f in SOUNDFONTS if os.path.isfile(f)), "")


_GM = {}


def gm_samples(program: int) -> dict:
    """Every note of a General MIDI instrument, played once by FluidSynth into one file and cut into notes:
    {pitch: mono float32}. Cached on disk. {} when there's no FluidSynth or SoundFont."""
    if program in _GM:
        return _GM[program]
    sf = soundfont()
    if not sf or not shutil.which("fluidsynth"):
        _GM[program] = {}
        return {}
    CACHE.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha1(f"{sf}|{os.path.getsize(sf)}|{program}|v2".encode()).hexdigest()[:16]
    npz = CACHE / f"gm-{program}-{key}.npz"
    if npz.exists():
        try:
            data = np.load(npz)
            _GM[program] = {int(k): data[k] for k in data.files}
            return _GM[program]
        except (OSError, ValueError):
            pass
    pitches = list(range(21, 109, 3))                          # every third key: the rest are tuned from neighbours
    hold, gap = 2.0, 3.0
    notes = [(i * gap, hold, p, 100) for i, p in enumerate(pitches)]
    mid = CACHE / f"gm-{program}.mid"
    mid.write_bytes(write_midi([{"channel": 0, "program": program, "notes": notes}], 120.0, (4, 4), in_seconds=True))
    wav = CACHE / f"gm-{program}.wav"
    try:
        subprocess.run(["fluidsynth", "-ni", "-g", "0.8", "-r", str(SR), "-F", str(wav), sf, str(mid)], capture_output=True, timeout=300)
        audio = read_wav(str(wav)).mean(axis=1)
    except (OSError, subprocess.SubprocessError, ValueError):
        _GM[program] = {}
        return {}
    out = {}
    for i, p in enumerate(pitches):
        a = int(i * gap * SR)
        seg = audio[a:a + int(gap * SR)].astype(np.float32)
        if seg.size:
            out[p] = seg
    np.savez_compressed(npz, **{str(k): v for k, v in out.items()})
    mid.unlink(missing_ok=True)
    wav.unlink(missing_ok=True)
    _GM[program] = out
    return out


def resample(x: np.ndarray, ratio: float) -> np.ndarray:
    """x played `ratio` times faster (linear interpolation: fine across a few semitones)."""
    n = int(len(x) / ratio)
    if n < 2:
        return x[:1]
    pos = np.arange(n) * ratio
    i = pos.astype(np.int64)
    frac = (pos - i).astype(np.float32)
    i = np.minimum(i, len(x) - 2)
    return x[i] * (1 - frac) + x[i + 1] * frac


def gm_note(s: dict, pitch: int, vel: int, dur: float, sr: int = SR) -> np.ndarray:
    samples = gm_samples(int(s.get("program", 0)))
    if not samples:
        return synth_note(dict(INSTRUMENTS[s.get("fallback", "epiano")]), pitch, vel, dur, sr)
    near = min(samples, key=lambda p: abs(p - pitch))
    x = resample(samples[near], 2 ** ((pitch - near) / 12)) if near != pitch else samples[near]
    rel = float(s.get("release", 0.3))
    n = min(len(x), int((dur + rel) * sr))
    x = x[:n].copy()
    held = min(n, int(dur * sr))
    if n > held:
        x[held:] *= np.exp(-np.arange(n - held, dtype=np.float32) / max(1.0, rel * sr / 5.0))
    tone = float(s.get("tone", 0))
    if tone < -0.01:
        x = filt(x, "lowpass", 800 + (1 + tone) * 12000)
    elif tone > 0.01:
        x = x + tone * 0.6 * filt(x, "highpass", 2500)
    return (x * (vel / 100.0) ** 1.2).astype(np.float32)


def synth_note(s: dict, pitch: int, vel: int, dur: float, sr: int = SR) -> np.ndarray:
    """One note from a synthesiser, with its release tail. Mono float32."""
    eng = s.get("engine", "sub")
    if eng == "gm":
        return gm_note(s, pitch, vel, dur, sr)
    rel = float(s.get("release", 0.2))
    n = max(16, int((dur + rel) * sr))
    held = int(dur * sr)
    amp = (vel / 127.0) ** 1.3
    f = freq(pitch + 12 * int(s.get("octave", 0)))
    if eng == "fm":
        t = np.arange(n, dtype=np.float32) / sr
        index = float(s.get("index", 3)) * (0.4 + vel / 127) * np.exp(-t / max(0.05, float(s.get("idecay", 1.0))))
        y = np.sin(2 * np.pi * f * t + index * np.sin(2 * np.pi * f * float(s.get("ratio", 1.0)) * t))
        y += 0.25 * np.sin(2 * np.pi * f * 2 * t) * np.exp(-t * 3)
        env = adsr(n, sr, float(s.get("attack", 0.002)), float(s.get("decay", 1.5)), float(s.get("sustain", 0.25)), rel, held)
        return (y * env * amp * 0.5).astype(np.float32)
    if eng == "organ":
        t = np.arange(n, dtype=np.float32) / sr
        bars = list(s.get("bars", [0.8, 1, 0.6, 0, 0.5, 0, 0.3, 0.2]))
        for k in range(8):
            if f"bar{k}" in s:
                bars[k] = float(s[f"bar{k}"])
        ratios = [0.5, 1, 2, 3, 4, 5, 6, 8]
        y = sum(b * np.sin(2 * np.pi * f * r * t) for b, r in zip(bars, ratios) if b > 0 and f * r < sr / 2)
        env = adsr(n, sr, float(s.get("attack", 0.004)), 0.1, 1.0, rel, held)
        return (y * env * amp * 0.22 * (1 + 0.04 * np.sin(2 * np.pi * 6.0 * t))).astype(np.float32)
    if eng == "pluck":
        period = max(2, int(round(sr / f)))
        noise = np.random.default_rng(pitch * 7 + vel).uniform(-1, 1, period).astype(np.float32)
        noise = filt(noise, "lowpass", 1500 + float(s.get("bright", 0.6)) * 12000)
        damp = float(s.get("damp", 0.996))
        out = np.zeros(n + period, np.float32)
        out[:period] = noise
        k = period
        while k < n:                                           # Karplus-Strong, a period at a time
            m = min(period, n - k)
            prev = out[k - period:k - period + m + 1]
            out[k:k + m] = damp * 0.5 * (prev[:m] + prev[1:m + 1] if len(prev) > m else prev[:m] * 2)
            k += m
        y = out[:n]
        if n > held:
            y[held:] *= np.exp(-np.arange(n - held, dtype=np.float32) / max(1.0, rel * sr / 5.0))
        return (y * amp * 0.8).astype(np.float32)
    # subtractive: detuned oscillators (and a sub), a filter that opens with the envelope
    voices = max(1, int(s.get("voices", 1)))
    det = float(s.get("detune", 0))
    y = np.zeros(n, np.float32)
    rng = np.random.default_rng(pitch)
    for v in range(voices):
        cents = 0 if voices == 1 else det * (2 * v / (voices - 1) - 1)
        y += oscillator(s.get("osc", "saw"), f * 2 ** (cents / 1200), n, sr, rng.random())
    y /= voices ** 0.7
    if float(s.get("sub", 0)) > 0:
        y += float(s["sub"]) * oscillator("sine", f / 2, n, sr)
    env = adsr(n, sr, float(s.get("attack", 0.01)), float(s.get("decay", 0.3)), float(s.get("sustain", 0.7)), rel, held)
    fenv = adsr(n, sr, float(s.get("attack", 0.01)) * 0.6, float(s.get("decay", 0.3)), 0.25, rel, held)
    cut = float(s.get("cutoff", 2000))
    q = float(s.get("res", 0.9))
    closed = filt(y, "lowpass", cut, q)
    opened = filt(y, "lowpass", min(sr * 0.45, cut + float(s.get("env", 1500)) * (0.5 + vel / 254)), q)
    y = closed + (opened - closed) * fenv                     # the filter envelope, as a blend
    return (y * env * amp * 0.45).astype(np.float32)


# ---- the drum kit
_KITS = {}


def _decay(n: int, secs: float) -> np.ndarray:
    return np.exp(-np.arange(n, dtype=np.float32) / (secs * SR / 5.0))


def drum_sound(kit: str, pitch: int, tune: float = 0.0, length: float = 1.0, punch: float = 0.5) -> np.ndarray:
    """One drum of a kit, made from sines and noise."""
    key = (kit, pitch, round(tune, 2), round(length, 2), round(punch, 2))
    if key in _KITS:
        return _KITS[key]
    rng = np.random.default_rng(pitch * 31 + len(kit))
    tf = 2 ** (tune / 12)
    L = length
    elec, vint = kit == "electronic", kit == "vintage"

    def tone(f0, f1, secs, sweep=0.04):
        n = int(secs * SR)
        t = np.arange(n, dtype=np.float32) / SR
        fr = (f1 + (f0 - f1) * np.exp(-t / sweep)) * tf
        return np.sin(2 * np.pi * np.cumsum(fr) / SR).astype(np.float32), n

    def noise(secs):
        n = int(secs * SR)
        return rng.uniform(-1, 1, n).astype(np.float32), n
    if pitch in (35, 36):
        y, n = tone(160 if not elec else 120, 48 if not elec else 42, (0.45 if not elec else 1.1) * L, 0.035 if not elec else 0.06)
        y = y * _decay(n, (0.42 if not elec else 1.0) * L)
        click, m = noise(0.006)
        y[:m] += click * (0.3 + 0.5 * punch)
        if elec:
            y = np.tanh(y * (1.5 + punch * 2)) / np.tanh(1.5 + punch * 2)
        y *= 1.0
    elif pitch in (38, 40):
        body, n = tone(220, 180, 0.2 * L, 0.02)
        nz, _ = noise(0.25 * L)
        nz = filt(nz, "bandpass", 3500 if not vint else 2200, 0.7)
        nz = nz[:n] if len(nz) >= n else np.pad(nz, (0, n - len(nz)))
        y = body * _decay(n, 0.12 * L) * (0.6 if not elec else 0.4) + nz * _decay(n, 0.22 * L) * (0.9 + 0.5 * punch)
    elif pitch == 37:
        y, n = tone(800, 600, 0.05)
        y = y * _decay(n, 0.04)
        y += filt(noise(0.05)[0], "highpass", 2000) * _decay(n, 0.02) * 0.6
    elif pitch == 39:
        nz, n = noise(0.3 * L)
        nz = filt(nz, "bandpass", 1500, 1.2)
        env = np.zeros(n, np.float32)
        for k, off in enumerate((0, 0.011, 0.023, 0.034)):
            a = int(off * SR)
            env[a:] += _decay(n - a, 0.012 if k < 3 else 0.2 * L)
        y = nz * env * 2.5
    elif pitch in (42, 44, 46):
        secs = {42: 0.07, 44: 0.05, 46: 0.45}[pitch] * L
        nz, n = noise(secs)
        if not vint:                                          # metallic: square partials over noise
            t = np.arange(n, dtype=np.float32) / SR
            metal = sum(np.sign(np.sin(2 * np.pi * f * tf * t)) for f in (205, 304, 369, 522, 540, 800)) / 6
            nz = 0.6 * nz + 0.6 * metal
        y = filt(filt(nz, "highpass", 7000 if not vint else 5000), "highpass", 6000) * _decay(n, secs * 0.9) * 0.9
    elif pitch in (41, 43, 45, 47, 48, 50):
        f0 = {41: 90, 43: 105, 45: 125, 47: 145, 48: 170, 50: 200}[pitch]
        y, n = tone(f0 * 1.6, f0, 0.5 * L, 0.05)
        y = y * _decay(n, 0.4 * L) + filt(noise(0.5 * L)[0][:n], "lowpass", 2000) * _decay(n, 0.05) * 0.2
    elif pitch in (49, 57, 51, 53):
        secs = (2.2 if pitch in (49, 57) else 1.4) * L
        nz, n = noise(secs)
        t = np.arange(n, dtype=np.float32) / SR
        partials = (340, 510, 777, 1045, 1430, 2210) if pitch in (49, 57) else (530, 820, 1270, 2110, 3170)
        metal = sum(np.sin(2 * np.pi * f * tf * t + k) for k, f in enumerate(partials)) / len(partials)
        mix = (0.75 * nz + 0.5 * metal) if pitch in (49, 57) else (0.3 * nz + 0.8 * metal)
        y = filt(mix, "highpass", 3000 if pitch in (49, 57) else 2000) * _decay(n, secs * (0.8 if pitch in (49, 57) else 0.6)) * 0.55
        if pitch == 53:
            y = y * 0.6 + np.sin(2 * np.pi * 2400 * tf * t) * _decay(n, 0.6) * 0.3
    elif pitch == 54:
        nz, n = noise(0.25)
        y = filt(nz, "highpass", 6000) * _decay(n, 0.18) * 0.7
    elif pitch == 56:
        n = int(0.3 * SR)
        t = np.arange(n, dtype=np.float32) / SR
        y = (np.sign(np.sin(2 * np.pi * 562 * tf * t)) + np.sign(np.sin(2 * np.pi * 845 * tf * t))) * 0.25
        y = filt(y, "bandpass", 900, 1.5) * _decay(n, 0.2) * 1.5
    elif pitch == 70:
        nz, n = noise(0.12)
        y = filt(nz, "highpass", 5000) * np.sin(np.linspace(0, np.pi, n)).astype(np.float32) * 0.6
    elif pitch == 75:
        y, n = tone(2500, 2500, 0.06)
        y = y * _decay(n, 0.04)
    else:
        y, n = tone(freq(pitch), freq(pitch), 0.3)
        y = y * _decay(n, 0.2)
    if vint:
        y = filt(y, "lowpass", 7000)
        y = np.tanh(y * 1.4) / np.tanh(1.4)
    y = np.asarray(y, np.float32) * 0.8
    _KITS[key] = y
    return y


def instrument_note(inst: dict, pitch: int, vel: int, dur: float, base: Path = None) -> np.ndarray:
    s = settings(inst)
    if s.get("engine") == "kit":
        pad = (s.get("pads") or {}).get(str(pitch))
        if pad:                                                # a sound of your own on this pad
            x = sample_mono(pad, base)
            if x.size:
                tune = float(s.get("tune", 0))
                x = resample(x, 2 ** (tune / 12)) if abs(tune) > 0.01 else x
                return (x * (vel / 110.0)).astype(np.float32)
        return drum_sound(s.get("kit", "studio"), pitch, float(s.get("tune", 0)), float(s.get("decay", 1.0)), float(s.get("punch", 0.5))) * (vel / 110.0)
    if s.get("engine") == "sampler":
        return sampler_note(s, pitch, vel, dur, base)
    return synth_note(s, pitch, vel, dur)


# ---- the sampler: any sound across the keys
_SAMPLES = {}


def resolve(path: str, base: Path = None) -> str:
    return str(base / path) if base is not None and path and not os.path.isabs(path) else path


def sample_mono(path: str, base: Path = None) -> np.ndarray:
    full = resolve(path, base)
    try:
        st = os.stat(full)
    except OSError:
        return np.zeros(0, np.float32)
    key = (full, st.st_mtime, st.st_size)
    if key not in _SAMPLES:
        a = load_audio(full)
        _SAMPLES[key] = a.mean(axis=1).astype(np.float32) if a.size else np.zeros(0, np.float32)
    return _SAMPLES[key]


def detect_pitch(x: np.ndarray, sr: int = SR) -> float:
    """The note a sound plays (as a MIDI pitch with a fraction), from its loudest steady part: the difference
    function of YIN, its first dip under a threshold, refined between samples. 0 when there's no clear pitch."""
    if x.size < sr // 20:
        return 0.0
    win = int(0.12 * sr)                                       # long enough for a few periods of a low bass note
    hop = win // 2
    if x.size > win:
        energy = np.array([float((x[k:k + win] ** 2).mean()) for k in range(0, x.size - win, hop)])
        k0 = int(np.argmax(energy)) * hop
    else:
        k0 = 0
    seg = x[k0:k0 + win].astype(np.float64)
    seg = seg - seg.mean()
    W = len(seg) // 2
    if W < 64 or not np.any(seg):
        return 0.0
    tau_min, tau_max = int(sr / 1500), min(W - 1, int(sr / 40))
    nfft = 1
    while nfft < 2 * len(seg):
        nfft *= 2
    F = np.fft.rfft(seg, nfft)
    A = np.fft.rfft(seg[:W], nfft)
    ac = np.fft.irfft(F * np.conj(A), nfft)[:W + 1]            # sum over the first W samples of x[j] x[j + tau]
    cs = np.cumsum(np.concatenate([[0.0], seg ** 2]))
    taus = np.arange(W + 1)
    d = cs[W] - cs[0] + (cs[taus + W] - cs[taus]) - 2 * ac                  # the difference function
    d[0] = 0
    cmnd = np.ones_like(d)
    run = np.cumsum(d[1:])
    cmnd[1:] = d[1:] * np.arange(1, W + 1) / np.maximum(run, 1e-12)
    tau = 0
    for t in range(tau_min, tau_max):
        if cmnd[t] < 0.15:
            while t + 1 < tau_max and cmnd[t + 1] < cmnd[t]:
                t += 1
            tau = t
            break
    if tau == 0:
        t = tau_min + int(np.argmin(cmnd[tau_min:tau_max]))
        if cmnd[t] > 0.4:
            return 0.0
        tau = t
    a, b, c = cmnd[tau - 1], cmnd[tau], cmnd[tau + 1] if tau + 1 < len(cmnd) else cmnd[tau]
    shift = 0.5 * (a - c) / (a - 2 * b + c) if (a - 2 * b + c) != 0 else 0.0
    f0 = sr / (tau + shift)
    return 69 + 12 * math.log2(f0 / 440.0)


def sampler_note(s: dict, pitch: int, vel: int, dur: float, base: Path = None) -> np.ndarray:
    """The sample played at `pitch`: tuned from its root, trimmed to its start and end, held for the note (and
    let go with the release) or played to its end in one shot."""
    x = sample_mono(s.get("file", ""), base)
    if not x.size:
        return np.zeros(16, np.float32)
    a, b = float(s.get("start", 0)), float(s.get("end", 1))
    x = x[int(len(x) * max(0.0, min(a, 0.99))):max(int(len(x) * max(a + 0.01, min(1.0, b))), 2)]
    ratio = 2 ** ((pitch - float(s.get("root", 60)) + float(s.get("tune", 0))) / 12)
    y = resample(x, ratio) if abs(ratio - 1) > 1e-4 else x.copy()
    y = y.astype(np.float32)
    att = int(float(s.get("attack", 0.002)) * SR)
    if att > 1:
        y[:att] *= np.linspace(0, 1, min(att, len(y)), dtype=np.float32)[:len(y[:att])]
    if s.get("mode", "held") == "held":
        rel = float(s.get("release", 0.15))
        held = int(dur * SR)
        n = min(len(y), held + int(rel * SR))
        y = y[:n]
        if n > held:
            y[held:] *= np.linspace(1, 0, n - held, dtype=np.float32)
    return (y * (vel / 100.0) ** 1.2).astype(np.float32)


# ---- MIDI effects: chords and the arpeggiator, between the notes and the instrument
CHORD_SHAPES = {"major": [0, 4, 7], "minor": [0, 3, 7], "power": [0, 7, 12], "sus": [0, 5, 7], "seventh": [0, 4, 7, 10], "octaves": [0, 12]}
ARP_MODES = {"up": "Up", "down": "Down", "updown": "Up and down", "played": "As played", "random": "Random"}


def apply_midi_fx(notes: list, mfx: dict, length: float, key: int = 0, mode: str = "major") -> list:
    """Notes after the track's MIDI effects. `chord` turns each note into a chord (a fixed shape, or "key": the
    chord of the song's key that note starts); `arp` plays what's held one note at a time at `rate` beats, over
    `octaves`, each `gate` of a step long."""
    mfx = mfx or {}
    ch = mfx.get("chord") or {}
    if ch.get("on"):
        out = []
        scale = SCALES.get(mode, SCALES["major"])
        for n in notes:
            p = int(n["p"])
            if ch.get("shape", "major") == "key":
                deg = (p - key) % 12
                k = min(range(7), key=lambda i: abs(scale[i] - deg))      # the nearest step of the scale
                ivs = [0] + [(scale[(k + j) % 7] + 12 * ((k + j) // 7)) - scale[k] for j in (2, 4)]
            else:
                ivs = CHORD_SHAPES.get(ch.get("shape", "major"), [0, 4, 7])
            out += [dict(n, p=p + iv) for iv in ivs if 0 <= p + iv < 128]
        notes = out
    arp = mfx.get("arp") or {}
    if arp.get("on") and notes:
        rate = max(1 / 16, float(arp.get("rate", 0.25)))
        octs = max(1, min(4, int(arp.get("octaves", 1))))
        gate = max(0.05, min(1.0, float(arp.get("gate", 0.8))))
        order = arp.get("mode", "up")
        rng = np.random.default_rng(int(arp.get("seed", 3)))
        out, step, last = [], 0, ()
        t = 0.0
        while t < length - 1e-6:
            held = [n for n in notes if float(n["t"]) <= t + 1e-6 < float(n["t"]) + float(n["d"])]
            if held:
                key_set = tuple(sorted(int(n["p"]) for n in held))
                if not last:
                    step = 0
                last = key_set
                if order == "played":
                    base = [int(n["p"]) for n in sorted(held, key=lambda q: (float(q["t"]), int(q["p"])))]
                else:
                    base = sorted({int(n["p"]) for n in held})
                pat = [p + 12 * o for o in range(octs) for p in base]
                if order == "down":
                    pat = pat[::-1]
                elif order == "updown" and len(pat) > 2:
                    pat = pat + pat[-2:0:-1]
                p = int(rng.choice(pat)) if order == "random" else pat[step % len(pat)]
                vel = max(int(n.get("v", 100)) for n in held)
                if p < 128:
                    out.append({"t": round(t, 4), "d": round(rate * gate, 4), "p": p, "v": vel})
                step += 1
            else:
                last = ()
            t += rate
        notes = out
    return notes


# ------------------------------------------------------------------------------------------------ regions to audio
_REGIONS = {}


def region_key(region: dict, inst: dict, tempo: float, extra=None) -> str:
    return hashlib.sha1(json.dumps([region.get("notes"), region.get("length"), inst, tempo, region.get("kind"), extra], sort_keys=True).encode()).hexdigest()


def render_midi_region(region: dict, inst: dict, tempo: float, base: Path = None, mfx: dict = None, key: int = 0, mode: str = "major") -> np.ndarray:
    """A MIDI region as mono audio, from its start to its last note's tail. Cached until anything in it changes."""
    use_fx = bool(mfx) and region.get("kind") != "drummer" and settings(inst).get("engine") != "kit"
    cache = region_key(region, inst, tempo, [mfx, key, mode, str(base)] if use_fx or settings(inst).get("engine") in ("sampler", "kit") else None)
    if cache in _REGIONS:
        return _REGIONS[cache]
    length_s = beats_to_s(float(region.get("length", 4)), tempo)
    pieces = []
    end = int(length_s * SR)
    notes = region.get("notes") or []
    if use_fx:
        notes = apply_midi_fx(notes, mfx, float(region.get("length", 4)), key, mode)
    for nt in notes:
        t = float(nt["t"])
        if t >= float(region.get("length", 4)) or t < 0:
            continue
        d = min(float(nt["d"]), float(region.get("length", 4)) - t)
        sound = instrument_note(inst, int(nt["p"]), int(nt.get("v", 100)), beats_to_s(max(0.01, d), tempo), base)
        at = int(beats_to_s(t, tempo) * SR)
        pieces.append((at, sound))
        end = max(end, at + len(sound))
    out = np.zeros(end, np.float32)
    for at, sound in pieces:
        out[at:at + len(sound)] += sound
    if len(_REGIONS) > 400:
        _REGIONS.clear()
    _REGIONS[cache] = out
    return out


_AUDIO = {}


def read_wav(path: str) -> np.ndarray:
    """A WAV file as float32 stereo at its own rate (PCM 16/24/32 or float)."""
    with open(path, "rb") as fh:
        data = fh.read()
    if data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise ValueError("not a WAV file")
    pos, fmt, raw = 12, None, None
    while pos + 8 <= len(data):
        cid, size = data[pos:pos + 4], struct.unpack("<I", data[pos + 4:pos + 8])[0]
        body = data[pos + 8:pos + 8 + size]
        if cid == b"fmt ":
            fmt = struct.unpack("<HHIIHH", body[:16])
        elif cid == b"data":
            raw = body
        pos += 8 + size + (size & 1)
    if fmt is None or raw is None:
        raise ValueError("broken WAV file")
    tag, ch, rate, _, align, bits = fmt
    if tag == 3:
        a = np.frombuffer(raw[:len(raw) // 4 * 4], np.float32)
    elif bits == 16:
        a = np.frombuffer(raw[:len(raw) // 2 * 2], np.int16).astype(np.float32) / 32768
    elif bits == 24:
        b = np.frombuffer(raw[:len(raw) // 3 * 3], np.uint8).reshape(-1, 3).astype(np.int32)
        a = ((b[:, 0] | (b[:, 1] << 8) | (b[:, 2] << 16)) << 8 >> 8).astype(np.float32) / 8388608
    elif bits == 32:
        a = np.frombuffer(raw[:len(raw) // 4 * 4], np.int32).astype(np.float32) / 2147483648
    else:
        a = (np.frombuffer(raw, np.uint8).astype(np.float32) - 128) / 128
    a = a[:len(a) // ch * ch].reshape(-1, ch)
    if ch == 1:
        a = np.repeat(a, 2, axis=1)
    return a[:, :2].copy()


def load_audio(path: str) -> np.ndarray:
    """Any sound file as float32 stereo at 48 kHz (ffmpeg decodes what WAV reading can't). Cached."""
    try:
        st = os.stat(path)
    except OSError:
        return np.zeros((0, 2), np.float32)
    key = (path, st.st_mtime, st.st_size)
    if key in _AUDIO:
        return _AUDIO[key]
    out = None
    try:
        with wave.open(path) as w:
            if w.getframerate() == SR:
                out = read_wav(path)
    except (wave.Error, EOFError, ValueError, OSError):
        out = None
    if out is None:
        try:
            raw = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-f", "f32le", "-ac", "2", "-ar", str(SR), "-"], capture_output=True, timeout=600).stdout
            out = np.frombuffer(raw[:len(raw) // 8 * 8], np.float32).reshape(-1, 2).copy()
        except (OSError, subprocess.SubprocessError):
            out = np.zeros((0, 2), np.float32)
    _AUDIO[key] = out
    return out


def resample_stereo(x: np.ndarray, ratio: float) -> np.ndarray:
    if x.ndim == 1:
        return resample(x, ratio)
    return np.stack([resample(x[:, c], ratio) for c in range(x.shape[1])], axis=1)


def stretch(x: np.ndarray, ratio: float, N: int = 2048) -> np.ndarray:
    """x made `ratio` times longer without changing its pitch: a phase vocoder (each frame's spectrum keeps its
    magnitudes; the phases run on at each partial's own frequency), with the phases of the bins around each peak
    locked to it so chords and voices stay clear. Mono or stereo float32."""
    if abs(ratio - 1) < 1e-3 or x.shape[0] < N:
        return x.astype(np.float32)
    if x.ndim == 2:
        return np.stack([stretch(x[:, c], ratio, N) for c in range(x.shape[1])], axis=1)
    H = N // 4
    win = np.hanning(N).astype(np.float32)
    xp = np.concatenate([np.zeros(N, np.float32), x.astype(np.float32), np.zeros(N, np.float32)])
    M = 1 + (len(xp) - N) // H
    idx = np.arange(N)[None, :] + H * np.arange(M)[:, None]
    X = np.fft.rfft(xp[idx] * win, axis=1)
    mag, ph = np.abs(X), np.angle(X)
    bins = np.arange(N // 2 + 1)
    omega = 2 * np.pi * bins * H / N
    dphi = ph[1:] - ph[:-1] - omega
    dphi -= 2 * np.pi * np.round(dphi / (2 * np.pi))
    adv = omega + dphi                                          # how far each bin's phase turns in one hop
    steps = np.arange(0, M - 1, 1 / ratio)
    i = steps.astype(np.int64)
    f = (steps - i)[:, None]
    m_out = (1 - f) * mag[i] + f * mag[i + 1]
    run = np.vstack([ph[:1], ph[0] + np.cumsum(adv[i[:-1]], axis=0)])
    # lock each bin to the peak it belongs to (identity phase locking): bins keep their offset from the peak
    a_now = ph[i]
    peaks_mask = np.zeros_like(m_out, bool)
    peaks_mask[:, 1:-1] = (m_out[:, 1:-1] > m_out[:, :-2]) & (m_out[:, 1:-1] >= m_out[:, 2:])
    owner = np.where(peaks_mask, bins[None, :], -1)
    # the nearest peak for each bin: fill forward and back, then take the closer
    fwd = np.maximum.accumulate(np.where(owner >= 0, owner, -1), axis=1)
    rev_owner = np.where(owner >= 0, owner, N)
    back = np.minimum.accumulate(rev_owner[:, ::-1], axis=1)[:, ::-1]
    use_back = (fwd < 0) | ((back < N) & ((back - bins[None, :]) < (bins[None, :] - fwd)))
    near = np.where(use_back, back, fwd)
    near = np.clip(near, 0, N // 2)
    rows = np.arange(len(steps))[:, None]
    locked = run[rows, near] + (a_now - a_now[rows, near])
    Y = m_out * np.exp(1j * locked)
    frames = np.fft.irfft(Y, n=N, axis=1).astype(np.float32) * win
    K = len(frames)
    out = np.zeros(K * H + N, np.float32)
    for r in range(4):                                          # frames four apart don't overlap: add them as one long strip
        sel = frames[r::4]
        if len(sel):
            strip = sel.reshape(-1)
            out[r * H:r * H + len(strip)] += strip
    out /= 1.5                                                  # Hann windows at a quarter overlap add up to 1.5
    a = int(round(N * ratio))
    return out[a:a + int(round(len(x) * ratio))]


def pitch_shift(x: np.ndarray, semis: float, ratio: float = 1.0) -> np.ndarray:
    """x moved `semis` semitones (and made `ratio` times longer): stretched, then played faster to match."""
    f = 2 ** (semis / 12)
    if abs(f - 1) < 1e-4:
        return stretch(x, ratio)
    return resample_stereo(stretch(x, ratio * f), f)


_PROCESSED = {}


def processed_audio(path: str, reverse: bool = False, semis: float = 0.0, ratio: float = 1.0) -> np.ndarray:
    """A sound file reversed, transposed and stretched, as asked. Cached."""
    a = load_audio(path)
    if not a.size or (not reverse and abs(semis) < 0.01 and abs(ratio - 1) < 1e-3):
        return a
    try:
        st = os.stat(path)
        key = (path, st.st_mtime, st.st_size, bool(reverse), round(semis, 2), round(ratio, 4))
    except OSError:
        return a
    if key in _PROCESSED:
        return _PROCESSED[key]
    out = a[::-1].copy() if reverse else a
    if abs(semis) >= 0.01 or abs(ratio - 1) >= 1e-3:
        out = pitch_shift(out, semis, ratio)
    if len(_PROCESSED) > 24:
        _PROCESSED.clear()
    _PROCESSED[key] = out.astype(np.float32)
    return _PROCESSED[key]


def peaks(audio: np.ndarray, count: int) -> list:
    if audio.size == 0 or count <= 0:
        return []
    mono = np.abs(audio).max(axis=1) if audio.ndim == 2 else np.abs(audio)
    step = max(1, len(mono) // count)
    m = mono[:step * (len(mono) // step)].reshape(-1, step).max(axis=1)
    return [round(float(v), 3) for v in m[:count]]


# ------------------------------------------------------------------------------------------------ effects (one block at a time)
class Eq:
    def __init__(self, p: dict):
        self.set(p)

    def set(self, p: dict):
        self.p = p
        self.coef = [biquad("lowshelf", float(p.get("lowF", 120)), 0.7, float(p.get("low", 0))),
                     biquad("peak", float(p.get("midF", 1000)), float(p.get("midQ", 0.9)), float(p.get("mid", 0))),
                     biquad("highshelf", float(p.get("highF", 6000)), 0.7, float(p.get("high", 0)))]
        if float(p.get("cut", 0)) > 20:
            self.coef.insert(0, biquad("highpass", float(p["cut"]), 0.707))
        old = getattr(self, "zi", None)                         # a knob turned while playing keeps the filters' state
        self.zi = old if old is not None and len(old) == len(self.coef) else [np.zeros((2, 2)) for _ in self.coef]

    def run(self, x: np.ndarray) -> np.ndarray:
        for k, (b, a) in enumerate(self.coef):
            if np.allclose(b, a):
                continue
            x, self.zi[k] = lfilter(b, a, x, axis=0, zi=self.zi[k])
        return x


class Compressor:
    """RMS level followed with its own attack and release (a quick follower and a slow one, whichever is higher:
    the quick one catches a hit, the slow one holds it as it lets go), a gain curve with a soft knee. With a `key`
    track it listens to that track instead (sidechain: the bass ducking under the kick)."""

    def __init__(self, p: dict):
        self.set(p)
        self.za = None
        self.zr = None
        self.reduction = 0.0

    def set(self, p: dict):
        self.p = p
        self.key = p.get("key") or ""                           # sidechain: listen to this track instead
        self.thr, self.ratio = float(p.get("threshold", -18)), max(1.0, float(p.get("ratio", 3)))
        self.makeup = float(p.get("makeup", 0))
        rel = max(0.01, float(p.get("release", 0.15)))
        att = max(0.0005, float(p.get("attack", 0.01)))
        self.ca = math.exp(-1 / (SR * att))
        self.cr = math.exp(-1 / (SR * rel))

    def run(self, x: np.ndarray, key: np.ndarray = None) -> np.ndarray:
        src = key if key is not None and len(key) == len(x) else x
        sq = (src * src).mean(axis=1) if src.ndim == 2 else src * src
        if self.za is None:
            self.za = np.zeros(1)
            self.zr = np.zeros(1)
        fast, self.za = lfilter([1 - self.ca], [1, -self.ca], sq, zi=self.za)
        slow, self.zr = lfilter([1 - self.cr], [1, -self.cr], sq, zi=self.zr)
        ms = np.maximum(fast, slow)
        level = 10 * np.log10(np.maximum(ms, 1e-10))
        over = level - self.thr
        knee = 6.0
        gr = np.where(over <= -knee / 2, 0.0, np.where(over >= knee / 2, over * (1 - 1 / self.ratio),
                                                         (1 - 1 / self.ratio) * (over + knee / 2) ** 2 / (2 * knee)))
        self.reduction = float(gr.max()) if gr.size else 0.0
        return x * (10 ** ((self.makeup - gr) / 20))[:, None].astype(np.float32)


class Drive:
    def __init__(self, p: dict):
        self.set(p)

    def set(self, p: dict):
        self.p = p
        self.g = 1 + float(p.get("amount", 0.4)) * 12
        self.tone = biquad("lowpass", 1500 + float(p.get("tone", 0.5)) * 12000)
        self.mix = float(p.get("mix", 1.0))
        if getattr(self, "zi", None) is None:
            self.zi = np.zeros((2, 2))

    def run(self, x):
        y = np.tanh(x * self.g) / math.tanh(self.g) * 0.8
        y, self.zi = lfilter(self.tone[0], self.tone[1], y, axis=0, zi=self.zi)
        return x * (1 - self.mix) + y * self.mix


class Delay:
    """An echo in time with the song: `time` in beats; the repeats bounce between left and right when `pingpong`."""

    def __init__(self, p: dict, tempo: float):
        self.tempo = tempo
        self.set(p)

    def set(self, p: dict):
        self.p = p
        d = max(BLOCK, int(beats_to_s(float(p.get("time", 0.75)), self.tempo) * SR))
        self.fb, self.mix = min(0.92, float(p.get("feedback", 0.35))), float(p.get("mix", 0.25))
        self.pp = bool(p.get("pingpong", True))
        if getattr(self, "d", None) != d:                       # only a new time empties the echoes
            self.d = d
            self.buf = np.zeros((self.d + BLOCK * 2, 2), np.float32)
            self.w = 0
            self.zi = np.zeros((2, 2))
        self.lp = biquad("lowpass", float(p.get("tone", 5000)))

    def run(self, x):
        n = len(x)
        L = len(self.buf)
        idx = (self.w + np.arange(n)) % L
        rd = (self.w - self.d + np.arange(n)) % L
        echo = self.buf[rd]
        echo, self.zi = lfilter(self.lp[0], self.lp[1], echo, axis=0, zi=self.zi)
        fbk = echo[:, ::-1] if self.pp else echo
        self.buf[idx] = x + fbk * self.fb
        self.w = (self.w + n) % L
        return x + echo * self.mix


class Chorus:
    def __init__(self, p: dict):
        self.set(p)
        self.buf = np.zeros((4096, 2), np.float32)
        self.w = 0
        self.ph = 0.0

    def set(self, p: dict):
        self.p = p
        self.rate, self.depth, self.mix = float(p.get("rate", 0.8)), float(p.get("depth", 0.5)), float(p.get("mix", 0.4))

    def run(self, x):
        n = len(x)
        L = len(self.buf)
        idx = (self.w + np.arange(n)) % L
        self.buf[idx] = x
        t = self.ph + np.arange(n) / SR
        out = np.empty_like(x)
        for c, off in ((0, 0.0), (1, 0.25)):
            dly = (0.012 + 0.006 * self.depth * np.sin(2 * np.pi * (self.rate * t + off))) * SR
            pos = (self.w + np.arange(n) - dly) % L
            i = pos.astype(np.int64)
            fr = (pos - i).astype(np.float32)
            out[:, c] = self.buf[i, c] * (1 - fr) + self.buf[(i + 1) % L, c] * fr
        self.w = (self.w + n) % L
        self.ph = float(t[-1] + 1 / SR) % 1000
        return x * (1 - self.mix * 0.5) + out * self.mix


class Filter:
    def __init__(self, p: dict):
        self.set(p)

    def set(self, p: dict):
        self.p = p
        self.coef = biquad(p.get("mode", "lowpass"), float(p.get("cutoff", 2000)), float(p.get("res", 0.9)))
        if getattr(self, "zi", None) is None:
            self.zi = np.zeros((2, 2))

    def run(self, x):
        y, self.zi = lfilter(self.coef[0], self.coef[1], x, axis=0, zi=self.zi)
        return y


EFFECTS = {"eq": ("EQ", Eq, {"low": 0, "mid": 0, "high": 0, "lowF": 120, "midF": 1000, "highF": 6000, "cut": 0}),
           "comp": ("Compressor", Compressor, {"threshold": -18, "ratio": 3, "attack": 0.01, "release": 0.15, "makeup": 3}),
           "drive": ("Drive", Drive, {"amount": 0.35, "tone": 0.5, "mix": 1.0}),
           "chorus": ("Chorus", Chorus, {"rate": 0.8, "depth": 0.5, "mix": 0.4}),
           "delay": ("Delay", Delay, {"time": 0.75, "feedback": 0.35, "mix": 0.25, "pingpong": True, "tone": 5000}),
           "filter": ("Filter", Filter, {"mode": "lowpass", "cutoff": 2000, "res": 0.9})}


# what each effect's knobs go between, for automation lanes: [low, high, unit]
PARAM_RANGES = {"eq": {"low": [-15, 15, "dB"], "mid": [-15, 15, "dB"], "high": [-15, 15, "dB"], "cut": [0, 400, "Hz"]},
                "comp": {"threshold": [-50, 0, "dB"], "ratio": [1, 20, ":1"], "makeup": [0, 18, "dB"]},
                "drive": {"amount": [0, 1, ""], "tone": [0, 1, ""], "mix": [0, 1, ""]},
                "chorus": {"rate": [0.1, 5, "Hz"], "depth": [0, 1, ""], "mix": [0, 1, ""]},
                "delay": {"feedback": [0, 0.9, ""], "mix": [0, 1, ""], "tone": [500, 12000, "Hz"]},
                "filter": {"cutoff": [40, 16000, "Hz"], "res": [0.5, 8, ""]}}
PARAM_NAMES = {"low": "Low", "mid": "Middle", "high": "High", "cut": "Low cut", "threshold": "Threshold", "ratio": "Ratio", "makeup": "Make-up",
               "amount": "Amount", "tone": "Tone", "mix": "Mix", "rate": "Rate", "depth": "Depth", "feedback": "Feedback", "cutoff": "Cutoff", "res": "Resonance"}


def make_effect(fx: dict, tempo: float):
    kind = fx.get("kind")
    if kind not in EFFECTS:
        return None
    params = dict(EFFECTS[kind][2])
    params.update(fx.get("params") or {})
    return Delay(params, tempo) if kind == "delay" else EFFECTS[kind][1](params)


def impulse(seconds: float, damp: float = 0.5, seed: int = 7) -> np.ndarray:
    """A room for the reverb: stereo noise dying away, darker as it goes, with a few early reflections."""
    n = int(max(0.2, seconds) * SR)
    rng = np.random.default_rng(seed)
    t = np.arange(n, dtype=np.float32) / SR
    env = np.exp(-6.9 * t / seconds).astype(np.float32)
    ir = rng.standard_normal((n, 2)).astype(np.float32) * env[:, None]
    dark = filt(ir[:, 0], "lowpass", 9000 - damp * 6000), filt(ir[:, 1], "lowpass", 9000 - damp * 6000)
    mix = np.clip(t / (seconds * 0.6), 0, 1)[:, None]
    ir = ir * (1 - mix) + np.stack(dark, 1) * mix
    for k, (ms, g) in enumerate(((11, 0.7), (17, 0.5), (23, 0.45), (31, 0.35), (43, 0.3))):
        i = int(ms * SR / 1000)
        ir[i, k % 2] += g
    ir[: int(0.004 * SR)] = 0
    return (ir / np.sqrt((ir ** 2).sum(axis=0))).astype(np.float32) * 1.6


class Reverb:
    """Convolution with a room, in blocks: the room cut into block-long pieces whose spectra wait in a line, so each
    block costs one small FFT and a sum of products (uniformly partitioned convolution)."""

    def __init__(self, seconds: float = 1.8, damp: float = 0.5):
        ir = impulse(seconds, damp)
        parts = int(math.ceil(len(ir) / BLOCK))
        ir = np.pad(ir, ((0, parts * BLOCK - len(ir)), (0, 0)))
        self.H = np.stack([np.fft.rfft(ir[k * BLOCK:(k + 1) * BLOCK], n=2 * BLOCK, axis=0) for k in range(parts)])   # (P, B+1, 2)
        self.X = np.zeros_like(self.H)
        self.prev = np.zeros((BLOCK, 2), np.float32)
        self.k = 0

    def run(self, x: np.ndarray) -> np.ndarray:
        n = len(x)
        if n < BLOCK:
            x = np.pad(x, ((0, BLOCK - n), (0, 0)))
        frame = np.concatenate([self.prev, x])
        self.prev = x
        self.X = np.roll(self.X, 1, axis=0)
        self.X[0] = np.fft.rfft(frame, axis=0)
        Y = (self.X * self.H).sum(axis=0)
        y = np.fft.irfft(Y, n=2 * BLOCK, axis=0)[BLOCK:]
        return y[:n].astype(np.float32)


# ------------------------------------------------------------------------------------------------ the mix
def automation_curve(points: list, beats0: float, beats1: float, n: int, default: float) -> np.ndarray:
    if not points:
        return np.full(n, default, np.float32)
    pts = sorted(points)
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return np.interp(np.linspace(beats0, beats1, n, endpoint=False), xs, ys).astype(np.float32)


class Mixer:
    """The song, a block at a time: each track's regions, its effects, volume, pan and sends; the reverb and echo;
    the master and its limiter. Effects keep their state from block to block; seeking starts them afresh."""

    def __init__(self, project: dict, audio_dir: Path = None):
        self.audio_dir = audio_dir
        self.load(project)
        self.levels = {}
        self.pos = 0

    def load(self, project: dict) -> None:
        self.p = project
        self.tempo = float(project.get("tempo", 120))
        self.fx = {}
        for t in project.get("tracks", []):
            self.fx[t["id"]] = [(i, f, make_effect(f, self.tempo)) for i, f in enumerate(t.get("effects", [])) if f.get("on", True)]
        m = project.get("master") or {}
        self.reverb = Reverb(float(m.get("room", 1.8)), float(m.get("damp", 0.5)))
        self.echo = Delay({"time": float(m.get("echoTime", 0.75)), "feedback": float(m.get("echoFeedback", 0.4)), "mix": 1.0, "pingpong": True}, self.tempo)
        self.master_fx = [(i, f, make_effect(f, self.tempo)) for i, f in enumerate(m.get("effects", [])) if f.get("on", True)]
        self.lim_gain = 1.0

    def seek(self, sample: int) -> None:
        self.pos = max(0, int(sample))
        self.load(self.p)

    def _take_audio(self, r: dict, file: str) -> np.ndarray:
        """A take's sound as the region plays it: reversed, transposed and following the tempo, as the region says."""
        ratio = float(r.get("srcTempo") or self.tempo) / self.tempo if r.get("follow") else 1.0
        return processed_audio(resolve(file, self.audio_dir), bool(r.get("reverse")), float(r.get("transpose", 0)), ratio), ratio

    def _region_audio(self, track: dict, r: dict):
        if r.get("kind") == "audio":
            length = int(beats_to_s(float(r.get("length", 4)), self.tempo) * SR)
            if r.get("comp") and r.get("takes"):               # a comp: pieces of several takes, crossfaded
                a = np.zeros((length, 2), np.float32)
                xf = int(0.005 * SR)
                for b0, b1, k in r["comp"]:
                    take = r["takes"][max(0, min(len(r["takes"]) - 1, int(k)))]
                    src, ratio = self._take_audio(r, take.get("file", ""))
                    off = int(float(take.get("offset", r.get("offset", 0))) * ratio * SR)
                    s0, s1 = int(beats_to_s(float(b0), self.tempo) * SR), min(length, int(beats_to_s(float(b1), self.tempo) * SR))
                    sa, sb = max(0, s0 - xf // 2), min(length, s1 + xf // 2)
                    piece = src[off + sa:off + sb]
                    if not len(piece):
                        continue
                    env = np.ones(len(piece), np.float32)
                    if sa > 0:
                        env[:min(xf, len(env))] = np.linspace(0, 1, min(xf, len(env)))
                    if sb < length:
                        env[-min(xf, len(env)):] = np.minimum(env[-min(xf, len(env)):], np.linspace(1, 0, min(xf, len(env))))
                    a[sa:sa + len(piece)] += piece * env[:, None]
            else:
                src, ratio = self._take_audio(r, r.get("file", ""))
                off = int(float(r.get("offset", 0)) * ratio * SR)
                a = src[off:off + length]
            g = db(float(r.get("gain", 0)))
            if g != 1.0:
                a = a * g
            fi, fo = int(float(r.get("fadeIn", 0)) * SR), int(float(r.get("fadeOut", 0)) * SR)
            if fi or fo:
                a = a.copy()
                if fi:
                    a[:fi] *= np.linspace(0, 1, min(fi, len(a)))[:, None]
                if fo:
                    a[-fo:] *= np.linspace(1, 0, min(fo, len(a)))[:, None]
            return a
        return render_midi_region(r, track.get("instrument") or {"id": "grand"}, self.tempo, self.audio_dir, track.get("midiFx"),
                                  int(self.p.get("key", 0)), self.p.get("mode", "major"))

    def track_block(self, track: dict, s0: int, n: int) -> np.ndarray:
        """One track's sound for samples [s0, s0+n), before its effects: stereo."""
        out = np.zeros((n, 2), np.float32)
        for r in self.p.get("regions", []):
            if r.get("track") != track["id"] or r.get("muted"):
                continue
            start = int(beats_to_s(float(r["start"]), self.tempo) * SR)
            reps = max(1, int(r.get("loops", 1)))
            span = int(beats_to_s(float(r.get("length", 4)), self.tempo) * SR)
            for k in range(reps):
                at = start + k * span
                if at >= s0 + n:
                    break
                audio = None
                # a cheap test before drawing it: does this region (with its tail) reach the block at all?
                if at + span + int(6 * SR) < s0:
                    continue
                audio = self._region_audio(track, r)
                end = at + len(audio)
                if end <= s0:
                    continue
                a, b = max(s0, at), min(s0 + n, end)
                piece = audio[a - at:b - at]
                if piece.ndim == 1:
                    out[a - s0:b - s0] += piece[:, None]
                else:
                    out[a - s0:b - s0] += piece
        return out

    def _automate(self, t: dict, fxs: list, b0: float, b1: float) -> None:
        """Effects whose knobs are drawn over time: set to where the line is in the middle of this block."""
        auto = t.get("automation") or {}
        if not any(k.startswith("fx.") for k in auto):
            return
        mid = (b0 + b1) / 2
        for i, f, fx in fxs:
            if fx is None:
                continue
            keys = {k.split(".", 2)[2]: v for k, v in auto.items() if k.startswith(f"fx.{i}.") and v}
            if not keys:
                continue
            p = dict(EFFECTS[f["kind"]][2])
            p.update(f.get("params") or {})
            for k, pts in keys.items():
                pts = sorted(pts)
                p[k] = float(np.interp(mid, [q[0] for q in pts], [q[1] for q in pts]))
            if p != getattr(fx, "p", None):
                fx.set(p)

    def _strip(self, t: dict, x: np.ndarray, raw: dict, b0: float, b1: float, n: int):
        """A track's channel strip: its effects (a compressor may listen to another track), then volume and pan,
        all as drawn over time. Gives the sound after the fader, and the send amounts."""
        fxs = self.fx.get(t["id"], [])
        self._automate(t, fxs, b0, b1)
        for _i, _f, fx in fxs:
            if fx is None:
                continue
            if isinstance(fx, Compressor) and fx.key:
                x = fx.run(x, raw.get(fx.key))
            else:
                x = fx.run(x)
        auto = t.get("automation") or {}
        vol = automation_curve(auto.get("volume"), b0, b1, n, float(t.get("volume", 0)))
        pan = automation_curve(auto.get("pan"), b0, b1, n, float(t.get("pan", 0)))
        g = (10 ** (vol / 20)).astype(np.float32)
        ang = (np.clip(pan, -1, 1) + 1) * np.pi / 4
        x = x * np.stack([np.cos(ang) * g * 1.4142, np.sin(ang) * g * 1.4142], axis=1)
        rv = automation_curve(auto.get("reverb"), b0, b1, n, float(t.get("reverb", 0)))
        ec = automation_curve(auto.get("echo"), b0, b1, n, float(t.get("echo", 0)))
        return x, rv, ec

    def render(self, n: int = BLOCK) -> np.ndarray:
        """The next n samples of the whole song (stereo float32), and each track's level for the meters. Tracks in a
        stack play into it; the stack's own effects and fader shape them together."""
        s0 = self.pos
        b0, b1 = s_to_beats(s0 / SR, self.tempo), s_to_beats((s0 + n) / SR, self.tempo)
        tracks = self.p.get("tracks", [])
        stacks = {t["id"]: t for t in tracks if t.get("kind") == "stack"}
        soloed = {t["id"] for t in tracks if t.get("solo")}
        solo_on = bool(soloed)

        def audible(t):
            if t.get("mute"):
                return False
            if not solo_on or t["id"] in soloed:
                return True
            if t.get("output") in soloed:                       # its stack is soloed
                return True
            return t.get("kind") == "stack" and any(o.get("output") == t["id"] and o["id"] in soloed for o in tracks)

        raw = {t["id"]: self.track_block(t, s0, n) for t in tracks if t.get("kind") != "stack"}
        bus = {sid: np.zeros((n, 2), np.float32) for sid in stacks}
        mix = np.zeros((n, 2), np.float32)
        rev = np.zeros((n, 2), np.float32)
        ech = np.zeros((n, 2), np.float32)
        for t in tracks:
            if t.get("kind") == "stack":
                continue
            x, rv, ec = self._strip(t, raw[t["id"]], raw, b0, b1, n)
            heard = audible(t)
            self.levels[t["id"]] = float(np.abs(x).max()) if heard and x.size else 0.0
            if not heard:
                continue
            (bus[t["output"]] if t.get("output") in bus else mix)[:] += x
            rev += x * rv[:, None]
            ech += x * ec[:, None]
        for sid, st in stacks.items():
            x, rv, ec = self._strip(st, bus[sid], raw, b0, b1, n)
            heard = audible(st)
            self.levels[sid] = float(np.abs(x).max()) if heard and x.size else 0.0
            if not heard:
                continue
            mix += x
            rev += x * rv[:, None]
            ech += x * ec[:, None]
        mix += self.reverb.run(rev) * 0.9 + self.echo.run(ech) * 0.8
        self._automate(self.p.get("master") or {}, self.master_fx, b0, b1)
        for _i, _f, fx in self.master_fx:
            if fx is not None:
                mix = fx.run(mix)
        mix *= db(float((self.p.get("master") or {}).get("volume", 0)))
        # a limiter that never lets the peak past -0.3 dBFS, easing back over a quarter second
        peak = float(np.abs(mix).max()) if mix.size else 0.0
        target = min(1.0, 0.966 / peak) if peak > 0 else 1.0
        new = target if target < self.lim_gain else self.lim_gain + (1.0 - self.lim_gain) * min(1.0, n / (0.25 * SR))
        ramp = np.linspace(self.lim_gain, new, n, dtype=np.float32)[:, None]
        mix = np.clip(mix * ramp, -0.98, 0.98)
        self.lim_gain = new
        self.levels["master"] = float(np.abs(mix).max()) if mix.size else 0.0
        self.pos += n
        return mix


def song_length(project: dict) -> float:
    """In beats: where the last region ends (with its loops)."""
    end = 0.0
    for r in project.get("regions", []):
        end = max(end, float(r["start"]) + float(r.get("length", 4)) * max(1, int(r.get("loops", 1))))
    return end


def render_song(project: dict, audio_dir: Path = None, tracks: list = None, tail: float = 2.0, start_beats: float = 0.0, end_beats: float = None) -> np.ndarray:
    """The whole song (or only some tracks: stems), as stereo float32 at 48 kHz, with `tail` seconds for echoes."""
    p = json.loads(json.dumps(project))
    if tracks is not None:
        wanted = set(tracks)
        for t in p.get("tracks", []):                          # a stack plays when any track asked for goes into it
            if t.get("kind") == "stack" and any(o.get("output") == t["id"] for o in p["tracks"] if o["id"] in wanted):
                wanted.add(t["id"])
        for t in p.get("tracks", []):
            t["mute"] = t["id"] not in wanted
            t["solo"] = False
    tempo = float(p.get("tempo", 120))
    end = song_length(p) if end_beats is None else end_beats
    total = int((beats_to_s(end - start_beats, tempo) + tail) * SR)
    m = Mixer(p, audio_dir)
    m.seek(int(beats_to_s(start_beats, tempo) * SR))
    out = np.zeros((max(0, total), 2), np.float32)
    k = 0
    while k < total:
        n = min(BLOCK, total - k)
        out[k:k + n] = m.render(BLOCK)[:n]
        k += n
    return out


def write_wav(path: str, audio: np.ndarray, bits: int = 24) -> None:
    a = np.clip(audio, -1, 1)
    with open(path, "wb") as fh:
        frames = len(a)
        if bits == 16:
            data = (a * 32767).astype("<i2").tobytes()
        else:
            v = (a * 8388607).astype(np.int32).reshape(-1)
            b = np.empty((v.size, 3), np.uint8)
            b[:, 0], b[:, 1], b[:, 2] = v & 0xFF, (v >> 8) & 0xFF, (v >> 16) & 0xFF
            data = b.tobytes()
        align = 2 * bits // 8
        fh.write(b"RIFF" + struct.pack("<I", 36 + len(data)) + b"WAVE")
        fh.write(b"fmt " + struct.pack("<IHHIIHH", 16, 1, 2, SR, SR * align, align, bits))
        fh.write(b"data" + struct.pack("<I", len(data)) + data)
        del frames


def encode(audio: np.ndarray, target: str, kind: str) -> bool:
    """FLAC, MP3, Ogg or AAC through ffmpeg (raw float in, so nothing is lost on the way)."""
    codec = {"flac": ["-c:a", "flac"], "mp3": ["-c:a", "libmp3lame", "-b:a", "256k"], "ogg": ["-c:a", "libvorbis", "-q:a", "7"],
             "m4a": ["-c:a", "aac", "-b:a", "256k"]}.get(kind)
    if not codec or not shutil.which("ffmpeg"):
        return False
    r = subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "f32le", "-ar", str(SR), "-ac", "2", "-i", "-"] + codec + [target],
                       input=np.ascontiguousarray(audio, np.float32).tobytes(), capture_output=True, timeout=900)
    return r.returncode == 0


# ------------------------------------------------------------------------------------------------ MIDI files
def _vlq(n: int) -> bytes:
    out = [n & 0x7F]
    n >>= 7
    while n:
        out.append(0x80 | (n & 0x7F))
        n >>= 7
    return bytes(reversed(out))


def write_midi(tracks: list, tempo: float, sig=(4, 4), in_seconds: bool = False, names: list = None) -> bytes:
    """A Standard MIDI File (type 1). tracks: [{channel, program, notes: [(start, dur, pitch, vel)]}] in beats
    (or seconds with in_seconds)."""
    ppq = 480
    conv = (lambda x: x * tempo / 60.0) if in_seconds else (lambda x: x)
    head = b"MThd" + struct.pack(">IHHH", 6, 1, len(tracks) + 1, ppq)
    us = int(60_000_000 / tempo)
    meta = (b"\x00\xFF\x51\x03" + us.to_bytes(3, "big") + b"\x00\xFF\x58\x04" + bytes([sig[0], int(math.log2(sig[1])), 24, 8]) + b"\x00\xFF\x2F\x00")
    chunks = [b"MTrk" + struct.pack(">I", len(meta)) + meta]
    for k, t in enumerate(tracks):
        ch = int(t.get("channel", 0)) & 0x0F
        events = []
        for st, d, p, v in t["notes"]:
            a = int(round(conv(st) * ppq))
            b = int(round(conv(st + d) * ppq))
            events.append((a, 1, bytes([0x90 | ch, int(p) & 0x7F, max(1, int(v)) & 0x7F])))
            events.append((max(a + 1, b), 0, bytes([0x80 | ch, int(p) & 0x7F, 0])))
        events.sort(key=lambda e: (e[0], e[1]))
        body = b""
        if names and k < len(names):
            nm = names[k].encode()[:120]
            body += b"\x00\xFF\x03" + _vlq(len(nm)) + nm
        body += b"\x00" + bytes([0xC0 | ch, int(t.get("program", 0)) & 0x7F])
        last = 0
        for tick, _, ev in events:
            body += _vlq(tick - last) + ev
            last = tick
        body += b"\x00\xFF\x2F\x00"
        chunks.append(b"MTrk" + struct.pack(">I", len(body)) + body)
    return head + b"".join(chunks)


def read_midi(data: bytes) -> dict:
    """A Standard MIDI File -> {tempo, sig, tracks: [{name, channel, program, notes: [(start, dur, pitch, vel)]}]}
    with times in beats (the first tempo is used for the whole song)."""
    if data[:4] != b"MThd":
        raise ValueError("not a MIDI file")
    _, fmt, ntrk, div = struct.unpack(">IHHH", data[4:14])
    ppq = div if not div & 0x8000 else 480
    pos = 14
    tempo, sig = 120.0, (4, 4)
    out = []
    for _ in range(ntrk):
        if data[pos:pos + 4] != b"MTrk":
            break
        size = struct.unpack(">I", data[pos + 4:pos + 8])[0]
        chunk = data[pos + 8:pos + 8 + size]
        pos += 8 + size
        i, tick, status = 0, 0, 0
        name, program, chans = "", 0, {}
        on = {}
        notes = []
        while i < len(chunk):
            delta = 0
            while True:
                b = chunk[i]
                i += 1
                delta = (delta << 7) | (b & 0x7F)
                if not b & 0x80:
                    break
            tick += delta
            b = chunk[i]
            if b & 0x80:
                status = b
                i += 1
            if status == 0xFF:
                kind = chunk[i]
                i += 1
                ln = 0
                while True:
                    c = chunk[i]
                    i += 1
                    ln = (ln << 7) | (c & 0x7F)
                    if not c & 0x80:
                        break
                body = chunk[i:i + ln]
                i += ln
                if kind == 0x51 and ln == 3:
                    tempo = 60_000_000 / int.from_bytes(body, "big")
                elif kind == 0x58 and ln >= 2:
                    sig = (body[0], 2 ** body[1])
                elif kind == 0x03:
                    name = body.decode(errors="replace")
                status = 0
            elif status in (0xF0, 0xF7):
                ln = 0
                while True:
                    c = chunk[i]
                    i += 1
                    ln = (ln << 7) | (c & 0x7F)
                    if not c & 0x80:
                        break
                i += ln
            else:
                hi, ch = status & 0xF0, status & 0x0F
                nb = 1 if hi in (0xC0, 0xD0) else 2
                d = chunk[i:i + nb]
                i += nb
                chans[ch] = chans.get(ch, 0) + 1
                if hi == 0xC0:
                    program = d[0]
                elif hi == 0x90 and d[1] > 0:
                    on.setdefault((ch, d[0]), []).append((tick, d[1]))
                elif hi == 0x80 or (hi == 0x90 and d[1] == 0):
                    if on.get((ch, d[0])):
                        t0, v = on[(ch, d[0])].pop(0)
                        notes.append((t0 / ppq, max(1, tick - t0) / ppq, d[0], v))
        if notes:
            ch = max(chans, key=chans.get) if chans else 0
            out.append({"name": name, "channel": ch, "program": program, "notes": sorted(notes)})
    return {"tempo": tempo, "sig": sig, "tracks": out}


# ------------------------------------------------------------------------------------------------ loops and the drummer
SCALES = {"major": [0, 2, 4, 5, 7, 9, 11], "minor": [0, 2, 3, 5, 7, 8, 10]}
PROGRESSIONS = {"pop": [0, 4, 5, 3], "ballad": [0, 5, 3, 4], "minor": [0, 5, 2, 6], "uplift": [3, 4, 0, 5]}
DRUM_STYLES = {
    # per 16 steps: kick, snare, hat (velocity 0..1)
    "pop": ([1, 0, 0, 0, 0, 0, 0, .6, 1, 0, .5, 0, 0, 0, 0, 0], [0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0], [.8, .4, .7, .4] * 4),
    "rock": ([1, 0, 0, 0, 0, 0, 0, 0, 1, 0, 1, 0, 0, 0, 0, 0], [0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0], [.9, 0, .7, 0] * 4),
    "hiphop": ([1, 0, 0, 0, 0, 0, 0, 1, 0, 0, 1, 0, 0, 0, 0, 0], [0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0, .3], [.8, .3, .6, .3, .8, .3, .6, .5] * 2),
    "house": ([1, 0, 0, 0] * 4, [0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0], [0, 0, .9, 0] * 4),
    "funk": ([1, 0, 0, .7, 0, 0, 1, 0, 0, 0, .6, 0, 0, .5, 0, 0], [0, 0, 0, 0, 1, 0, 0, .3, 0, .3, 0, 0, 1, 0, 0, .4], [.8, .5] * 8),
    "trap": ([1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0], [0, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0], [.8, .5, .8, .5, .8, .5, .8, .5, .8, .4, .6, .3, .8, .5, .9, .7]),
}


def drummer(style: str, complexity: float, loudness: float, bars: int, beats_per_bar: int = 4, fills: float = 0.5, seed: int = 1) -> list:
    """A drum part as notes: the style's groove, busier with complexity (ghost notes, open hats, extra kicks),
    harder with loudness (ride instead of hats, stronger hits), and a fill at the end of every fourth bar."""
    kick, snare, hat = DRUM_STYLES.get(style, DRUM_STYLES["pop"])
    rng = np.random.default_rng(seed)
    notes = []
    steps = beats_per_bar * 4
    vel = lambda v: int(max(1, min(127, (45 + 70 * loudness) * v + rng.integers(-6, 7))))
    for bar in range(bars):
        base = bar * beats_per_bar
        fill = fills > 0.05 and bar % 4 == 3
        for s in range(steps):
            k16 = s % 16
            t = base + s / 4
            in_fill = fill and s >= steps - (4 if fills < 0.5 else 8)
            if in_fill:
                tom = [50, 48, 47, 45, 43, 41][(s - (steps - 8)) % 6]
                if s % 2 == 0 or complexity > 0.6:
                    notes.append({"t": t, "d": 0.25, "p": tom if s % 4 else 38, "v": vel(0.9)})
                continue
            if kick[k16] > 0 and (kick[k16] >= 0.6 or complexity > 0.35):
                notes.append({"t": t, "d": 0.25, "p": 36, "v": vel(kick[k16])})
            elif complexity > 0.75 and k16 in (3, 11) and rng.random() < complexity - 0.6:
                notes.append({"t": t, "d": 0.25, "p": 36, "v": vel(0.5)})
            if snare[k16] > 0 and (snare[k16] >= 0.5 or complexity > 0.45):
                notes.append({"t": t, "d": 0.25, "p": 38 if style not in ("house", "trap") or snare[k16] < 1 else 39, "v": vel(snare[k16])})
            elif complexity > 0.55 and k16 % 2 == 1 and rng.random() < (complexity - 0.5) * 0.5:
                notes.append({"t": t, "d": 0.25, "p": 38, "v": vel(0.25)})          # ghost notes
            hv = hat[k16]
            if hv == 0 and complexity > 0.65 and rng.random() < complexity - 0.3:
                hv = 0.35                                       # busier: the hats fill in the sixteenths
            if hv > 0 and (hv >= 0.5 or complexity > 0.3):
                pitch = 51 if loudness > 0.75 and style in ("rock", "pop") else (46 if complexity > 0.7 and k16 in (6, 14) else 42)
                notes.append({"t": t, "d": 0.25, "p": pitch, "v": vel(hv)})
        if bar % 8 == 0 and loudness > 0.4:
            notes.append({"t": base, "d": 0.5, "p": 49, "v": vel(0.9)})
    return notes


def chord_notes(key: int, mode: str, degree: int, octave: int = 4, size: int = 3) -> list:
    sc = SCALES.get(mode, SCALES["major"])
    root = 12 * (octave + 1) + key
    return [root + sc[(degree + 2 * k) % 7] + 12 * ((degree + 2 * k) // 7) for k in range(size)]


LOOPS = [
    # id, name, family, instrument, style, bars
    ("drums-pop", "Pop Groove", "Drums", "drums", "pop", 4), ("drums-rock", "Rock Steady", "Drums", "drums", "rock", 4),
    ("drums-hiphop", "Boom Bap", "Drums", "vintage", "hiphop", 4), ("drums-house", "Four on the Floor", "Drums", "electronic", "house", 4),
    ("drums-funk", "Funk Pocket", "Drums", "drums", "funk", 4), ("drums-trap", "Trap Rolls", "Drums", "electronic", "trap", 4),
    ("bass-root", "Root Bass", "Bass", "bass", "root", 4), ("bass-walk", "Walking Bass", "Bass", "fingered", "walk", 4),
    ("bass-octave", "Octave Pulse", "Bass", "bass", "octave", 4),
    ("keys-pop", "Pop Chords", "Keys", "grand", "pop", 4), ("keys-ballad", "Ballad Piano", "Keys", "grand", "ballad", 4),
    ("keys-epiano", "Soul Keys", "Keys", "epiano", "minor", 4), ("organ-rock", "Rock Organ", "Keys", "organ", "pop", 4),
    ("pad-warm", "Warm Pad", "Synth", "pad", "ballad", 4), ("pad-uplift", "Uplifting Pad", "Synth", "pad", "uplift", 4),
    ("arp-pluck", "Pluck Arpeggio", "Synth", "pluck", "pop", 4), ("lead-hook", "Synth Hook", "Synth", "lead", "minor", 4),
    ("strings-swell", "String Swell", "Strings", "strings", "ballad", 4),
]


def loop_notes(loop_id: str, key: int = 0, mode: str = "major", beats_per_bar: int = 4) -> list:
    """A loop's notes in the song's key: drum grooves, bass lines and chord parts made from a chord progression."""
    lp = next((x for x in LOOPS if x[0] == loop_id), None)
    if lp is None:
        return []
    _, _, fam, _inst, style, bars = lp
    if fam == "Drums":
        return drummer(style, 0.55, 0.6, bars, beats_per_bar, fills=0.4, seed=hash(loop_id) & 0xFFFF)
    prog = PROGRESSIONS.get(style if style in PROGRESSIONS else "pop", PROGRESSIONS["pop"])
    notes = []
    for bar in range(bars):
        deg = prog[bar % len(prog)]
        base = bar * beats_per_bar
        if fam == "Bass":
            root = chord_notes(key, mode, deg, 2, 1)[0]
            if style == "walk":
                sc = SCALES[mode]
                for b in range(beats_per_bar):
                    p = root + [0, sc[2], sc[4], sc[5] if b == 3 else sc[4]][b % 4]
                    notes.append({"t": base + b, "d": 0.9, "p": p, "v": 96})
            elif style == "octave":
                for e in range(beats_per_bar * 2):
                    notes.append({"t": base + e / 2, "d": 0.4, "p": root + (12 if e % 2 else 0), "v": 100 if e % 2 == 0 else 84})
            else:
                for b, (t, d) in enumerate(((0, 1.5), (1.5, 0.5), (2, 1.5), (3.5, 0.5))):
                    if t < beats_per_bar:
                        notes.append({"t": base + t, "d": d, "p": root + (7 if b == 3 else 0), "v": 100})
        elif loop_id.startswith("arp"):
            ch = chord_notes(key, mode, deg, 4, 3) + [chord_notes(key, mode, deg, 5, 1)[0]]
            for s in range(beats_per_bar * 4):
                notes.append({"t": base + s / 4, "d": 0.24, "p": ch[[0, 1, 2, 3, 2, 1][s % 6]], "v": 88 if s % 4 else 104})
        elif loop_id.startswith("lead"):
            sc = SCALES[mode]
            motif = [(0, 0.5, 4), (0.5, 0.5, 2), (1, 1, 0), (2.5, 0.5, 2), (3, 1, 4)] if bar % 2 == 0 else [(0, 1, 5), (1, 0.5, 4), (1.5, 0.5, 2), (2, 2, 0)]
            for t, d, s_ in motif:
                notes.append({"t": base + t, "d": d, "p": 12 * 6 + key + sc[(deg + s_) % 7], "v": 100})
        else:                                                   # chords: held (pads, strings) or played in a rhythm (keys)
            ch = chord_notes(key, mode, deg, 4, 3) + ([chord_notes(key, mode, deg, 3, 1)[0]] if fam != "Strings" else [])
            if fam in ("Synth", "Strings") or style == "ballad":
                for p in ch:
                    notes.append({"t": base, "d": beats_per_bar - 0.05, "p": p, "v": 84})
            else:
                for t, d in ((0, 1.4), (1.5, 0.45), (2, 1.4), (3.5, 0.45)):
                    if t < beats_per_bar:
                        for p in ch:
                            notes.append({"t": base + t, "d": d, "p": p, "v": 90 if t in (0, 2) else 72})
    return notes
