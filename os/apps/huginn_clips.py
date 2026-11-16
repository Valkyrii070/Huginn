"""Clips: a multi-track video editor on MLT, the engine behind Kdenlive and Shotcut.

The project is plain JSON: media in bins, video and audio tracks, clips placed on them (with their colour, effects,
transform, keyframes, speed, sound and transitions), titles, markers. From it Clips writes an MLT project, which
both the viewer and the export read, so what you see is what you get. The viewer plays it through MLT's Python
bindings (sound through MLT's own audio output); exporting runs `melt` in the background. Without the Python
bindings the viewer still shows the exact frame under the playhead, rendered by `melt`."""
import copy
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path
from xml.sax.saxutils import escape, quoteattr

import numpy as np
from PySide6.QtCore import Property, QObject, QProcess, QStandardPaths, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QImage

try:
    import cv2
except ImportError:                                         # tracking still works, more slowly
    cv2 = None
try:
    import mlt7 as mlt
except ImportError:                                         # the viewer falls back to frames rendered by melt
    mlt = None

HERE = Path(__file__).resolve().parent
LUMAS = HERE / "data" / "lumas"
STORE = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share") / "huginn" / "clips"
CACHE = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "huginn" / "clips"
VIDEO = (".mp4", ".mov", ".m4v", ".mkv", ".webm", ".avi", ".mts", ".m2ts", ".3gp", ".ogv", ".wmv", ".mpg", ".mpeg", ".mxf")
AUDIO = (".mp3", ".m4a", ".aac", ".wav", ".flac", ".ogg", ".opus", ".aiff", ".aif", ".wma")
IMAGE = (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tif", ".tiff", ".heic")
SIZES = {"1080p": (1920, 1080, "Wide · 1080p"), "4k": (3840, 2160, "Wide · 4K"), "720p": (1280, 720, "Wide · 720p"),
         "vertical": (1080, 1920, "Upright · phones"), "square": (1080, 1080, "Square")}
RATES = [24, 25, 30, 50, 60]
TRANSITIONS = {"dissolve": ("Cross dissolve", ""), "wipe-left": ("Wipe left", "wipe-left.pgm"), "wipe-right": ("Wipe right", "wipe-right.pgm"),
               "wipe-down": ("Wipe down", "wipe-down.pgm"), "wipe-up": ("Wipe up", "wipe-up.pgm"), "circle": ("Circle", "circle.pgm"),
               "clock": ("Clock", "clock.pgm"), "barn-door": ("Barn door", "barn-door.pgm"), "diagonal": ("Diagonal", "diagonal.pgm")}
PRESETS = {
    "h264": {"name": "Best for sharing", "detail": "H.264 MP4: plays everywhere", "ext": ".mp4",
             "args": ["f=mp4", "vcodec=libx264", "preset=medium", "acodec=aac", "ab=192k", "movflags=+faststart", "pix_fmt=yuv420p"], "crf": {"high": 17, "medium": 21, "small": 26}},
    "h265": {"name": "Smaller file", "detail": "H.265 MP4: half the size, newer players", "ext": ".mp4",
             "args": ["f=mp4", "vcodec=libx265", "preset=medium", "acodec=aac", "ab=192k", "tag=hvc1", "movflags=+faststart", "pix_fmt=yuv420p"], "crf": {"high": 20, "medium": 24, "small": 29}},
    "av1": {"name": "For the web", "detail": "AV1 WebM: smallest, modern browsers", "ext": ".webm",
            "args": ["f=webm", "vcodec=libsvtav1", "acodec=libopus", "ab=160k", "pix_fmt=yuv420p"], "crf": {"high": 28, "medium": 34, "small": 42}},
    "prores": {"name": "Editing master", "detail": "ProRes 422 HQ MOV: for other editors and colourists", "ext": ".mov",
               "args": ["f=mov", "vcodec=prores_ks", "vprofile=3", "pix_fmt=yuv422p10le", "acodec=pcm_s16le"], "crf": None},
    "m4a": {"name": "Sound only", "detail": "AAC in M4A", "ext": ".m4a", "args": ["f=ipod", "vn=1", "acodec=aac", "ab=256k"], "crf": None},
    "wav": {"name": "Sound only, uncompressed", "detail": "WAV", "ext": ".wav", "args": ["f=wav", "vn=1", "acodec=pcm_s16le"], "crf": None},
}
TITLE_STYLES = {
    "lower": {"name": "Lower third", "size": 54, "place": "lower", "box": True, "align": "left"},
    "centre": {"name": "Big title", "size": 110, "place": "centre", "box": False, "align": "centre"},
    "top": {"name": "Heading", "size": 72, "place": "top", "box": False, "align": "centre"},
    "caption": {"name": "Subtitle", "size": 46, "place": "bottom", "box": True, "align": "centre"},
}
EPS = 1e-6


# ============================================================================================ small things
def probe(path: str) -> dict:
    """{kind: video | audio | image, duration, width, height, fps, audio} of a file, or raises ValueError."""
    p = Path(path)
    if p.suffix.lower() in IMAGE:
        try:
            out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height", "-of", "json", path],
                                 capture_output=True, text=True, timeout=20)
            s = (json.loads(out.stdout or "{}").get("streams") or [{}])[0]
        except (OSError, subprocess.SubprocessError, ValueError):
            s = {}
        return {"kind": "image", "duration": 5.0, "width": int(s.get("width") or 1920), "height": int(s.get("height") or 1080), "fps": 0, "audio": False}
    try:
        out = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                              "format=duration:stream=codec_type,width,height,avg_frame_rate:stream_tags=rotate:stream_side_data=rotation", "-of", "json", path],
                             capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        raise ValueError("ffprobe (part of ffmpeg) isn't installed.") from None
    try:
        data = json.loads(out.stdout or "{}")
    except ValueError:
        data = {}
    streams = data.get("streams") or []
    video = next((s for s in streams if s.get("codec_type") == "video" and s.get("width")), None)
    has_audio = any(s.get("codec_type") == "audio" for s in streams)
    try:
        duration = float((data.get("format") or {}).get("duration") or 0)
    except ValueError:
        duration = 0
    if duration <= 0 or not (video or has_audio):
        raise ValueError(f"{p.name} isn't something Clips can read.")
    if not video:
        return {"kind": "audio", "duration": duration, "width": 0, "height": 0, "fps": 0, "audio": True}
    w, h = int(video["width"]), int(video["height"])
    turn = 0
    for side in video.get("side_data_list") or []:
        if "rotation" in side:
            turn = int(side["rotation"])
    if str((video.get("tags") or {}).get("rotate", "0")).lstrip("-") in ("90", "270") or abs(turn) in (90, 270):
        w, h = h, w
    fps = 0.0
    try:
        a, b = (video.get("avg_frame_rate") or "0/1").split("/")
        fps = float(a) / float(b) if float(b) else 0.0
    except (ValueError, ZeroDivisionError):
        pass
    return {"kind": "video", "duration": duration, "width": w, "height": h, "fps": round(fps, 3), "audio": has_audio}


def timecode(seconds: float, fps: int = 30) -> str:
    seconds = max(0.0, seconds)
    frames = int(round(seconds * fps))
    s, f = divmod(frames, fps)
    m, s = divmod(s, 60)
    h, m = divmod(m, 60)
    return f"{h:02d}:{m:02d}:{s:02d}:{f:02d}"


def clock(seconds: float) -> str:
    seconds = max(0.0, seconds)
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def font_file(family: str = "Inter", bold: bool = True) -> str:
    for want in (f"{family}:{'bold' if bold else 'regular'}", "Inter:bold", "Noto Sans:bold", "DejaVu Sans:bold", "sans-serif"):
        try:
            out = subprocess.run(["fc-match", "-f", "%{file}", want], capture_output=True, text=True, timeout=10).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            out = ""
        if out and os.path.isfile(out):
            return out
    return ""


def peaks(path: str, per_second: int = 20) -> list:
    """The loudness outline of a file's sound, 0..1, `per_second` values a second (for the timeline's waveforms)."""
    try:
        raw = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-vn", "-ac", "1", "-ar", str(per_second * 100), "-f", "s16le", "-"],
                             capture_output=True, timeout=180).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    import array
    data = array.array("h")
    data.frombytes(raw[:len(raw) // 2 * 2])
    out = []
    for i in range(0, len(data), 100):
        chunk = data[i:i + 100]
        out.append(round(min(1.0, max((abs(x) for x in chunk), default=0) / 32768 * 1.4), 3))
    return out


def proxy_path(path: str) -> Path:
    st = Path(path).stat()
    key = hashlib.sha1(f"{path}|{st.st_size}|{int(st.st_mtime)}".encode()).hexdigest()[:16]
    return CACHE / "proxies" / f"{key}.mp4"


def proxy_command(path: str, target: Path) -> list:
    """A light copy for smooth editing: 540 lines tall, a key frame every half second, quick to decode."""
    return ["ffmpeg", "-v", "error", "-y", "-i", path, "-vf", "scale=-2:540", "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
            "-g", "15", "-tune", "fastdecode", "-c:a", "aac", "-b:a", "128k", str(target)]


# ============================================================================================ the project
def new_project(name: str = "My Movie") -> dict:
    return {"version": 2, "name": name, "size": "1080p", "fps": 30, "media": [], "bins": ["Footage"],
            "tracks": [{"id": "v2", "kind": "video", "name": "V2", "hidden": False, "locked": False},
                       {"id": "v1", "kind": "video", "name": "V1", "hidden": False, "locked": False},
                       {"id": "a1", "kind": "audio", "name": "Music", "role": "music", "muted": False, "locked": False},
                       {"id": "a2", "kind": "audio", "name": "Voice", "role": "voice", "muted": False, "locked": False}],
            "clips": [], "markers": [], "duck": False, "duckBy": -12, "loudness": False, "next": 1}


def migrate(old: dict) -> dict:
    """A project from the first Clips (one row of clips, captions on top) becomes a multi-track one."""
    if old.get("version") == 2:
        return old
    p = new_project(old.get("name") or "My Movie")
    p["size"] = {"1080": "1080p", "720": "720p", "vertical": "vertical", "square": "square"}.get(old.get("size"), "1080p")
    at, n = 0.0, 1
    for c in old.get("clips") or []:
        mid = f"m{n}"
        p["media"].append({"id": mid, "path": c.get("path", ""), "name": Path(c.get("path", "")).name, "kind": "video", "duration": c.get("duration", 0),
                           "width": c.get("width", 0), "height": c.get("height", 0), "fps": 0, "audio": c.get("audio", True), "bin": "Footage"})
        length = max(0.1, float(c.get("end", 0)) - float(c.get("start", 0)))
        clip = blank_clip(f"c{n}", mid, "v1", at, float(c.get("start", 0)), float(c.get("end", length)))
        clip["mute"] = bool(c.get("muted"))
        clip["volume"] = 0.0 if c.get("volume", 1.0) >= 1 else round(20 * math.log10(max(0.01, c.get("volume", 1.0))), 1)
        p["clips"].append(clip)
        at += length
        n += 1
    for cap in old.get("captions") or []:
        t = blank_title(f"c{n}", "v2", float(cap.get("at", 0)), float(cap.get("length", 3)), cap.get("text", ""), "caption")
        t["style"]["place"] = {"top": "top", "middle": "centre"}.get(cap.get("place"), "bottom")
        p["clips"].append(t)
        n += 1
    p["next"] = n
    return p


def blank_clip(cid: str, media: str, track: str, at: float, cin: float, cout: float) -> dict:
    return {"id": cid, "kind": "media", "media": media, "track": track, "at": round(at, 4), "in": round(cin, 4), "out": round(cout, 4),
            "speed": 1.0, "keepPitch": True, "volume": 0.0, "mute": False, "fadeIn": 0.0, "fadeOut": 0.0, "denoise": False,
            "colour": {"exposure": 0.0, "contrast": 1.0, "saturation": 1.0, "temperature": 6500, "tint": 0.0, "lut": "",
                       "shadows": [0, 0], "midtones": [0, 0], "highlights": [0, 0]},
            "effects": {"blur": 0.0, "sharpen": 0.0, "vignette": 0.0, "bw": False, "flipH": False, "flipV": False, "videoNoise": False},
            "transform": {"x": 0.0, "y": 0.0, "scale": 1.0, "rotation": 0.0, "opacity": 1.0, "crop": [0, 0, 0, 0]},
            "keys": {}, "transition": None}


def blank_title(cid: str, track: str, at: float, length: float, text: str, style: str = "lower") -> dict:
    st = dict(TITLE_STYLES.get(style, TITLE_STYLES["lower"]))
    st.update(font="Inter", colour="#FFFFFF", boxColour="#000000", boxOpacity=0.55, outline=0, shadow=True)
    c = blank_clip(cid, "", track, at, 0.0, length)
    c.update(kind="title", text=text, style=st, fadeIn=0.3, fadeOut=0.3)
    return c


def clip_len(c: dict) -> float:
    if ramped(c):
        r = Remap(c)
        return max(0.0, r.out(float(c["out"])) - r.out(float(c["in"])))
    return max(0.0, (c["out"] - c["in"]) / max(0.01, c.get("speed", 1.0)))


def clip_end(c: dict) -> float:
    return c["at"] + clip_len(c)


def track_of(p: dict, tid: str) -> dict:
    return next((t for t in p["tracks"] if t["id"] == tid), {})


def on_track(p: dict, tid: str) -> list:
    return sorted((c for c in p["clips"] if c["track"] == tid), key=lambda c: c["at"])


def media_of(p: dict, mid: str) -> dict:
    return next((m for m in p["media"] if m["id"] == mid), {})


def total(p: dict) -> float:
    return max([clip_end(c) for c in p["clips"]] + [0.0])


def fits(p: dict, tid: str, at: float, length: float, ignore: str = "") -> bool:
    if at < -EPS:
        return False
    for c in p["clips"]:
        if c["track"] == tid and c["id"] != ignore and at < clip_end(c) - EPS and at + length > c["at"] + EPS:
            return False
    return True


def accepts(track: dict, clip: dict, media: dict) -> bool:
    if clip.get("kind") == "compound":
        return track.get("kind") == compound_content(clip) and track.get("role") != "captions"
    if track.get("kind") == "audio":
        return clip["kind"] == "media" and media.get("kind") in ("audio", "video") and (media.get("kind") == "audio" or media.get("audio"))
    return clip["kind"] == "title" or media.get("kind") in ("video", "image")


def beats_in(c: dict) -> list:
    """A clip's marked beats as seconds into the clip (those inside it), with which start a bar."""
    lo, hi = float(c.get("in", 0)), float(c.get("out", 0))
    return [[round(out_of(c, b), 3), k % 4 == 0] for k, b in enumerate(c.get("beats") or []) if lo <= b < hi]


def snap(p: dict, t: float, within: float, ignore: str = "", playhead: float = -1) -> float:
    points = [0.0] + [m["t"] for m in p["markers"]] + ([playhead] if playhead >= 0 else [])
    for c in p["clips"]:
        if c["id"] != ignore:
            points += [c["at"], clip_end(c)]
        if c.get("beats"):
            points += [c["at"] + u for u, _ in beats_in(c)]
    best = min(points, key=lambda x: abs(x - t), default=t)
    return best if abs(best - t) <= within else t


def blade(p: dict, t: float, ids: list = None) -> list:
    """Cut every clip under `t` (or only `ids`) in two. Returns the new clips' ids."""
    made = []
    for c in list(p["clips"]):
        if ids and c["id"] not in ids:
            continue
        if track_of(p, c["track"]).get("locked"):
            continue
        if c["at"] + 0.05 < t < clip_end(c) - 0.05:
            second = copy.deepcopy(c)
            second["id"] = f"c{p['next']}"
            p["next"] += 1
            src = src_of(c, t - c["at"])
            c["out"], second["in"] = round(src, 4), round(src, 4)
            second["at"] = round(c["at"] + clip_len(c), 4) if ramped(c) else round(t, 4)   # a cut in a held frame goes before it
            c["fadeOut"], second["fadeIn"] = 0.0, 0.0
            c["transition"] = None
            cut = t - c["at"]
            for prop, keys in list(c.get("keys", {}).items()):
                c["keys"][prop] = [k for k in keys if k[0] <= cut + EPS]
                second["keys"][prop] = [[round(k[0] - cut, 4), k[1]] for k in keys if k[0] >= cut - EPS]
            p["clips"].append(second)
            made.append(second["id"])
    return made


def ripple_delete(p: dict, ids: list) -> None:
    """Remove clips and close the gaps they leave on their tracks."""
    for cid in ids:
        c = next((x for x in p["clips"] if x["id"] == cid), None)
        if not c:
            continue
        gap, start = clip_len(c), c["at"]
        p["clips"].remove(c)
        for other in p["clips"]:
            if other["track"] == c["track"] and other["at"] >= start - EPS:
                other["at"] = round(max(0.0, other["at"] - gap), 4)


def anim(keys: list, fps: int, scale=lambda v: v, fmt="{:.4f}") -> str:
    """Keyframes [[seconds, value]] -> an MLT animation string "frame=value;frame=value"."""
    return ";".join(f"{int(round(t * fps))}={fmt.format(scale(v))}" for t, v in sorted(keys))


def keyed(c: dict, prop: str, base: float) -> list:
    keys = c.get("keys", {}).get(prop) or []
    return [[k[0], k[1]] for k in keys] if keys else [[0.0, base]]


def wheel(xy) -> tuple:
    """A colour wheel's point (x, y in -1..1) -> red, green and blue shifts for ffmpeg's colorbalance."""
    x, y = (xy or [0, 0])[:2]
    amount, angle = min(1.0, math.hypot(x, y)), math.atan2(y, x)
    return tuple(round(amount * 0.6 * math.cos(angle - math.radians(a)), 4) for a in (0, 120, 240))


def duck_spans(p: dict) -> list:
    """When someone is talking: spans of clips with sound that aren't on a music track."""
    spans = []
    for c in p["clips"]:
        t = track_of(p, c["track"])
        if c["kind"] != "media" or c.get("mute") or t.get("muted") or t.get("role") == "music":
            continue
        m = media_of(p, c["media"])
        if m.get("audio") and (t.get("kind") == "audio" or t.get("id") == "v1" or t.get("kind") == "video"):
            spans.append((c["at"], clip_end(c)))
    spans.sort()
    merged = []
    for a, b in spans:
        if merged and a <= merged[-1][1] + 0.5:
            merged[-1] = (merged[-1][0], max(merged[-1][1], b))
        else:
            merged.append((a, b))
    return merged



# ------------------------------------------------------------------ round two: curves, steadying, the mixer, captions
CURVE_CHANNELS = {"rgb": "av.master", "r": "av.red", "g": "av.green", "b": "av.blue"}


def curve_points(points) -> list:
    """Points for a curve, tidied: inside 0..1, in order, no two at the same x, at least the two ends."""
    out = {}
    for pt in points or []:
        try:
            x, y = float(pt[0]), float(pt[1])
        except (TypeError, ValueError, IndexError):
            continue
        out[round(max(0.0, min(1.0, x)), 3)] = round(max(0.0, min(1.0, y)), 3)
    pts = sorted(out.items())
    if len(pts) < 2:
        return [[0.0, 0.0], [1.0, 1.0]]
    return [[x, y] for x, y in pts]


def curve_plain(points) -> bool:
    return all(abs(x - y) < 1e-3 for x, y in curve_points(points))


def curve_arg(points) -> str:
    return " ".join(f"{x:.3f}/{y:.3f}" for x, y in curve_points(points))


def curve_samples(points, n: int = 64) -> list:
    """The curve as ffmpeg draws it (a natural cubic spline through the points), `n` + 1 heights from 0 to 1."""
    pts = curve_points(points)
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    k = len(pts)
    if k == 2:
        return [round(max(0.0, min(1.0, ys[0] + (ys[1] - ys[0]) * (max(xs[0], min(xs[1], i / n)) - xs[0]) / max(1e-6, xs[1] - xs[0]))), 4) for i in range(n + 1)]
    h = [xs[i + 1] - xs[i] for i in range(k - 1)]
    a = [0.0] * k                                           # second derivatives, natural ends (zero)
    lo, di, up, rhs = [0.0] * k, [1.0] * k, [0.0] * k, [0.0] * k
    for i in range(1, k - 1):
        lo[i], di[i], up[i] = h[i - 1], 2 * (h[i - 1] + h[i]), h[i]
        rhs[i] = 6 * ((ys[i + 1] - ys[i]) / h[i] - (ys[i] - ys[i - 1]) / h[i - 1])
    for i in range(1, k):                                    # tridiagonal solve
        w = lo[i] / di[i - 1]
        di[i] -= w * up[i - 1]
        rhs[i] -= w * rhs[i - 1]
    a[k - 1] = rhs[k - 1] / di[k - 1]
    for i in range(k - 2, -1, -1):
        a[i] = (rhs[i] - up[i] * a[i + 1]) / di[i]
    a[0] = a[k - 1] = 0.0
    out = []
    for j in range(n + 1):
        x = j / n
        if x <= xs[0]:
            y = ys[0]
        elif x >= xs[-1]:
            y = ys[-1]
        else:
            i = max(0, min(k - 2, next(q for q in range(k - 1) if xs[q] <= x <= xs[q + 1])))
            t0, t1 = xs[i + 1] - x, x - xs[i]
            y = (a[i] * t0 ** 3 + a[i + 1] * t1 ** 3) / (6 * h[i]) + (ys[i] / h[i] - a[i] * h[i] / 6) * t0 + (ys[i + 1] / h[i] - a[i + 1] * h[i] / 6) * t1
        out.append(round(max(0.0, min(1.0, y)), 4))
    return out


# ------------------------------------------------------------------ round three: easing, sound effects, multicam, tracking
EASES = {"linear": "Even", "in": "Ease in", "out": "Ease out", "inout": "Ease in and out", "hold": "Hold"}


def db_lin(d: float) -> float:
    return 10 ** (d / 20)


def ease(kind: str, u: float) -> float:
    u = max(0.0, min(1.0, u))
    if kind == "in":
        return u * u * u
    if kind == "out":
        return 1 - (1 - u) ** 3
    if kind == "inout":
        return 4 * u ** 3 if u < 0.5 else 1 - (-2 * u + 2) ** 3 / 2
    if kind == "hold":
        return 0.0 if u < 1.0 else 1.0
    return u


def eased_value(keys: list, t: float, kind: str):
    """A keyframed value at time t with the clip's easing between keys (keys: [[t, value], ...] sorted)."""
    if not keys:
        return None
    if t <= keys[0][0]:
        return keys[0][1]
    for (t0, v0), (t1, v1) in zip(keys, keys[1:]):
        if t0 <= t <= t1:
            return v0 + (v1 - v0) * ease(kind, (t - t0) / max(1e-6, t1 - t0))
    return keys[-1][1]


def dense_times(times: list, fps: int, kind: str) -> list:
    """Between keyframes that ease, a sample every couple of frames, so MLT's straight lines follow the curve."""
    if kind in ("linear", "") or len(times) < 2:
        return times
    out = set(times)
    step = 2.0 / fps
    for a, b in zip(times, times[1:]):
        t = a + step
        while t < b - 1e-6:
            out.add(round(t, 4))
            t += step
        if kind == "hold":
            out.add(round(max(a, b - 1.0 / fps), 4))
    return sorted(out)


SOUND_FX = {"eq": "EQ", "comp": "Even out loudness", "voice": "Clear voice", "echo": "Echo"}


def audio_sync(a: np.ndarray, b: np.ndarray, rate: int) -> float:
    """How many seconds later the same sound happens in b than in a (cross-correlation of loudness envelopes).
    Positive: b started recording before a."""
    if a.size == 0 or b.size == 0:
        return 0.0
    def env(x):
        x = np.abs(x.astype(np.float32))
        k = max(1, rate // 100)
        x = x[:len(x) // k * k].reshape(-1, k).mean(axis=1)
        x = x - x.mean()
        return x / (x.std() + 1e-9)
    ea, eb = env(a), env(b)
    n = 1
    while n < len(ea) + len(eb):
        n *= 2
    corr = np.fft.irfft(np.fft.rfft(eb, n) * np.conj(np.fft.rfft(ea, n)), n)
    lag = int(np.argmax(corr))
    if lag > n // 2:
        lag -= n
    return lag / 100.0


def sound_of(path: str, seconds: float = 180, rate: int = 8000) -> np.ndarray:
    try:
        raw = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-t", str(seconds), "-vn", "-ac", "1", "-ar", str(rate), "-f", "s16le", "-"],
                             capture_output=True, timeout=300).stdout
    except (OSError, subprocess.SubprocessError):
        return np.zeros(0, np.int16)
    return np.frombuffer(raw[:len(raw) // 2 * 2], np.int16)


def track_box(frames: list, box: tuple) -> list:
    """Follow a box through frames (grey numpy images): template matching near where it was, the template
    refreshed as it goes so it copes with slow changes. box = (x, y, w, h) in pixels of the frames. Gives the box
    in each frame."""
    x, y, w, h = [int(round(v)) for v in box]
    out = [(x, y, w, h)]
    if not frames:
        return out
    tmpl = frames[0][y:y + h, x:x + w].astype(np.float32)
    first = tmpl.copy()
    H, W = frames[0].shape
    for f in frames[1:]:
        r = max(w, h)
        x0, y0 = max(0, x - r), max(0, y - r)
        x1, y1 = min(W, x + w + r), min(H, y + h + r)
        area = f[y0:y1, x0:x1].astype(np.float32)
        if area.shape[0] < h or area.shape[1] < w:
            out.append((x, y, w, h))
            continue
        if cv2 is not None:
            res = cv2.matchTemplate(area, tmpl, cv2.TM_CCOEFF_NORMED)
            _, score, _, loc = cv2.minMaxLoc(res)
            dx, dy = loc
        else:                                                  # without OpenCV: sum of squared differences on a grid
            best, dx, dy = None, 0, 0
            for yy in range(0, area.shape[0] - h + 1, 2):
                for xx in range(0, area.shape[1] - w + 1, 2):
                    d = float(((area[yy:yy + h, xx:xx + w] - tmpl) ** 2).mean())
                    if best is None or d < best:
                        best, dx, dy = d, xx, yy
            score = 1.0
        x, y = x0 + dx, y0 + dy
        out.append((x, y, w, h))
        if score > 0.6:
            tmpl = 0.85 * tmpl + 0.15 * f[y:y + h, x:x + w].astype(np.float32)
        if cv2 is not None and score < 0.3:                  # lost it: look for the first look again, wider
            res = cv2.matchTemplate(f.astype(np.float32), first, cv2.TM_CCOEFF_NORMED)
            _, sc2, _, loc2 = cv2.minMaxLoc(res)
            if sc2 > 0.5:
                x, y = loc2
                out[-1] = (x, y, w, h)
    return out


STAB = CACHE / "steadied"


def stab_path(media: str, strength: float) -> Path:
    """Where the steadied copy of a file at a given strength is kept (it follows the file: a changed file is
    steadied again)."""
    try:
        st = os.stat(media)
        sig = f"{media}|{st.st_size}|{int(st.st_mtime)}"
    except OSError:
        sig = media
    return STAB / f"{hashlib.sha1(sig.encode()).hexdigest()[:16]}-{int(round(max(0.0, min(1.0, strength)) * 100)):03d}.mp4"


def stab_commands(src: str, trf: str, out: str, strength: float) -> tuple:
    """Two ffmpeg passes (vid.stab): find how the camera moved, then move each picture back, zooming just
    enough to hide the edges. Stronger is smoother (it follows the camera's path less closely)."""
    smoothing = int(round(5 + max(0.0, min(1.0, strength)) * 55))
    detect = ["ffmpeg", "-v", "error", "-y", "-i", src, "-vf", f"vidstabdetect=shakiness=6:accuracy=15:result={trf}", "-f", "null", "-"]
    apply = ["ffmpeg", "-v", "error", "-y", "-i", src, "-vf",
             f"vidstabtransform=input={trf}:smoothing={smoothing}:optzoom=1:zoomspeed=0.2:interpol=bicubic,unsharp=5:5:0.5:3:3:0.2",
             "-c:v", "libx264", "-preset", "veryfast", "-crf", "16", "-pix_fmt", "yuv420p", "-c:a", "copy", "-movflags", "+faststart", out]
    return detect, apply


def sounding(p: dict) -> list:
    """Tracks whose sound reaches the mix: not muted, and the soloed ones when any track is soloed."""
    tracks = p.get("tracks") or []
    solo = [t for t in tracks if t.get("solo")]
    return [t for t in tracks if not t.get("muted") and (not solo or t.get("solo"))]


def caption_track(p: dict) -> dict:
    return next((t for t in p.get("tracks") or [] if t.get("role") == "captions"), {})


def captions_of(p: dict) -> list:
    """[(start, end, text)] from the captions track, in order."""
    t = caption_track(p)
    if not t:
        return []
    return [(round(c["at"], 3), round(clip_end(c), 3), c.get("text", "")) for c in on_track(p, t["id"]) if c["kind"] == "title" and c.get("text", "").strip()]


_STAMP = re.compile(r"(?:(\d+):)?(\d{1,2}):(\d{2})[.,](\d{1,3})")


def _secs(m) -> float:
    h, mi, se, ms = m.groups()
    return int(h or 0) * 3600 + int(mi) * 60 + int(se) + int(ms.ljust(3, "0")) / 1000


def parse_captions(text: str) -> list:
    """SubRip (.srt) or WebVTT (.vtt) captions -> [(start, end, text)]. Styling tags are dropped."""
    text = text.replace("\r\n", "\n").replace("\r", "\n").lstrip("﻿")
    out = []
    for block in re.split(r"\n\s*\n", text):
        lines = [l for l in block.split("\n") if l.strip()]
        k = next((i for i, l in enumerate(lines) if "-->" in l), -1)
        if k < 0:
            continue
        a, _, b = lines[k].partition("-->")
        ma, mb = _STAMP.search(a), _STAMP.search(b)
        if not ma or not mb:
            continue
        words = "\n".join(re.sub(r"<[^>]+>|\{\\[^}]*\}", "", l).strip() for l in lines[k + 1:]).strip()
        start, end = _secs(ma), _secs(mb)
        if words and end > start:
            out.append((round(start, 3), round(end, 3), words))
    return sorted(out)


def _stamp(t: float, sep: str) -> str:
    ms = int(round(max(0.0, t) * 1000))
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d}{sep}{ms % 1000:03d}"


def to_srt(items: list) -> str:
    return "\n".join(f"{n}\n{_stamp(a, ',')} --> {_stamp(b, ',')}\n{t}\n" for n, (a, b, t) in enumerate(items, start=1))


def to_vtt(items: list) -> str:
    return "WEBVTT\n\n" + "\n".join(f"{_stamp(a, '.')} --> {_stamp(b, '.')}\n{t}\n" for a, b, t in items)


WHISPER_DIRS = [Path.home() / ".local/share/huginn/whisper", Path("/usr/share/huginn/whisper"), Path("/usr/share/whisper.cpp/models"),
                Path("/usr/local/share/whisper.cpp/models"), Path.home() / ".cache/whisper.cpp", Path.home() / "whisper.cpp/models"]


def whisper_tool() -> dict:
    """What can turn speech into captions on this computer: whisper.cpp (whisper-cli and a ggml model), else
    the faster-whisper Python package. {} when neither is here."""
    cli = next((shutil.which(n) for n in ("whisper-cli", "whisper-cpp", "whisper.cpp") if shutil.which(n)), "")
    if cli:
        models = [m for d in WHISPER_DIRS if d.is_dir() for m in sorted(d.glob("ggml-*.bin"))]
        rank = lambda m: next((i for i, k in enumerate(("base", "small", "tiny", "medium", "large")) if k in m.name), 9)
        if models:
            return {"kind": "cli", "bin": cli, "model": str(sorted(models, key=rank)[0])}
    try:
        import importlib.util
        if importlib.util.find_spec("faster_whisper"):
            return {"kind": "python", "module": "faster_whisper"}
    except (ImportError, ValueError):
        pass
    return {}


def whisper_command(tool: dict, wav: str, base: str, language: str = "") -> list:
    """The command that writes `base`.srt from a 16 kHz mono WAV file."""
    if tool.get("kind") == "cli":
        return [tool["bin"], "-m", tool["model"], "-f", wav, "-osrt", "-of", base, "-l", language or "auto", "-ml", "42", "-sow"]
    code = ("import sys; from faster_whisper import WhisperModel as W; m = W('base', compute_type='int8'); "
            "segs, _ = m.transcribe(sys.argv[1], language=sys.argv[3] or None, vad_filter=True); "
            "f = lambda t: '%02d:%02d:%02d,%03d' % (t // 3600, t // 60 % 60, t % 60, round(t % 1 * 1000) % 1000); "
            "open(sys.argv[2] + '.srt', 'w').write('\\n'.join('%d\\n%s --> %s\\n%s\\n' % (n, f(s.start), f(s.end), s.text.strip()) for n, s in enumerate(segs, 1)))")
    import sys as _sys
    return [_sys.executable, "-c", code, wav, base, language]


# ------------------------------------------------------------------ round four: speed ramps and holds
RAMP_SMOOTH = 0.3            # seconds of footage a smooth change of speed takes on either side of where it's set
SPEED_CHOICES = [0.1, 0.25, 0.5, 1.0, 2.0, 4.0]
HOLD_LENGTH = 2.0


def ramped(c: dict) -> bool:
    return c.get("kind") == "media" and bool(c.get("ramp") or c.get("holds"))


def _run_len(s0: float, s1: float, v0: float, v1: float) -> float:
    """Seconds of film for the footage s0..s1 when the speed goes in a straight line from v0 to v1 across it."""
    ds = s1 - s0
    if ds <= 0:
        return 0.0
    if abs(v1 - v0) < 1e-9:
        return ds / v0
    return ds / (v1 - v0) * math.log(v1 / v0)


class Remap:
    """How a clip's footage is laid out in the film: speeds set from points in the footage on (gliding across
    each point when smooth) and frames held for a while. out(s) is the film's seconds from the footage's start
    to its second s; src(a) is the other way round. Only holds between the clip's in and out count."""

    def __init__(self, c: dict):
        base = max(0.05, min(16.0, float(c.get("speed") or 1.0)))
        pts = {}
        for s, v in c.get("ramp") or []:
            pts[round(max(0.0, float(s)), 4)] = max(0.05, min(16.0, float(v)))
        if 0.0 in pts:
            base = pts.pop(0.0)
        starts, speeds = [0.0] + sorted(pts), [base] + [pts[s] for s in sorted(pts)]
        n = len(starts)
        half = [0.0] * (n + 1)
        if c.get("rampSmooth", True):
            for k in range(1, n):
                if abs(speeds[k] - speeds[k - 1]) > 1e-9:
                    right = starts[k + 1] - starts[k] if k + 1 < n else 1e9
                    half[k] = max(0.0, min(RAMP_SMOOTH, 0.45 * (starts[k] - starts[k - 1]), 0.45 * right))
        runs, at = [], 0.0
        for k in range(n):
            end = starts[k + 1] - half[k + 1] if k + 1 < n else 1e9
            if end > at + 1e-9:
                runs.append((at, end, speeds[k], speeds[k]))
            if k + 1 < n:
                if half[k + 1] > 0:
                    runs.append((starts[k + 1] - half[k + 1], starts[k + 1] + half[k + 1], speeds[k], speeds[k + 1]))
                at = starts[k + 1] + half[k + 1]
        lo, hi = float(c.get("in", 0)), float(c.get("out", 1e9))
        holds = sorted((float(h), max(0.0, float(d))) for h, d in (c.get("holds") or []) if lo - 1e-6 <= float(h) < hi and float(d) > 0)
        self.starts, self.speeds = starts, speeds
        self.segs, a, i = [], 0.0, 0                  # (s0, s1, v0, v1, a0, a1); a hold has s0 == s1
        for s0, s1, v0, v1 in runs:
            cut = s0
            while i < len(holds) and holds[i][0] < s1:
                h, d = holds[i]
                if h > cut:
                    vc, vh = self._v(s0, s1, v0, v1, cut), self._v(s0, s1, v0, v1, h)
                    du = _run_len(cut, h, vc, vh)
                    self.segs.append((cut, h, vc, vh, a, a + du))
                    a, cut = a + du, h
                self.segs.append((h, h, 0.0, 0.0, a, a + d))
                a += d
                i += 1
            vc = self._v(s0, s1, v0, v1, cut)
            du = _run_len(cut, s1, vc, v1)
            self.segs.append((cut, s1, vc, v1, a, a + du))
            a += du

    @staticmethod
    def _v(s0, s1, v0, v1, s):
        return v0 if s1 <= s0 else v0 + (v1 - v0) * (s - s0) / (s1 - s0)

    def speed_at(self, s: float) -> float:
        for s0, s1, v0, v1, _, _ in self.segs:
            if s1 > s0 and s0 <= s < s1:
                return self._v(s0, s1, v0, v1, s)
        return self.speeds[-1]

    def out(self, s: float) -> float:
        if s <= 0:
            return s / self.speeds[0]
        for s0, s1, v0, v1, a0, a1 in self.segs:
            if s1 > s0 and s0 < s <= s1:
                return a0 + _run_len(s0, s, v0, self._v(s0, s1, v0, v1, s))
        return self.segs[-1][5]

    def src(self, a: float) -> float:
        if a <= 0:
            return a * self.speeds[0]
        for s0, s1, v0, v1, a0, a1 in self.segs:
            if a0 <= a < a1:
                if s1 <= s0:
                    return s0
                if abs(v1 - v0) < 1e-9:
                    return s0 + v0 * (a - a0)
                k = (v1 - v0) / (s1 - s0)
                return s0 + v0 * (math.exp(k * (a - a0)) - 1) / k
        return self.segs[-1][1]

    def time_map(self, frames: int, fps: int, longest: float) -> str:
        """For MLT's timeremap link: the footage's second to show at each of the film's frames, at every frame
        where the line bends (and every frame of a glide); straight in between."""
        want = {0, max(0, frames - 1)}
        for s0, s1, v0, v1, a0, a1 in self.segs:
            f0, f1 = math.ceil(a0 * fps - 1e-6), math.floor(a1 * fps - 1e-6)
            if f0 > frames:
                break
            want.update(f for f in (f0, f1, f1 + 1) if 0 <= f < frames)
            if s1 > s0 and abs(v1 - v0) > 1e-9:
                want.update(range(max(0, f0), min(frames, f1 + 1)))
        last = max(0.0, longest - 0.5 / max(1, fps))
        return ";".join(f"{f}={min(last, max(0.0, self.src(f / fps))):.5f}" for f in sorted(want))


def src_of(c: dict, u: float) -> float:
    """The footage's second shown `u` seconds into the clip (before or after it too)."""
    if ramped(c):
        r = Remap(c)
        return r.src(r.out(float(c["in"])) + u)
    return float(c["in"]) + u * float(c.get("speed") or 1.0)


def out_of(c: dict, s: float) -> float:
    """How many seconds into the clip the footage's second `s` is shown (where a held frame first shows)."""
    if ramped(c):
        r = Remap(c)
        return r.out(s) - r.out(float(c["in"]))
    return (s - float(c["in"])) / float(c.get("speed") or 1.0)


def speed_bands(c: dict) -> list:
    """The clip's stretches as [from, to, speed] in seconds into the clip; a held frame has speed 0."""
    if not ramped(c):
        return [[0.0, clip_len(c), float(c.get("speed") or 1.0)]]
    r = Remap(c)
    a_in, a_out = r.out(float(c["in"])), r.out(float(c["out"]))
    out = []
    for s0, s1, v0, v1, a0, a1 in r.segs:
        x0, x1 = max(a0, a_in), min(a1, a_out)
        if x1 - x0 > 1e-4:
            out.append([round(x0 - a_in, 4), round(x1 - a_in, 4), 0.0 if s1 <= s0 else round((v0 + v1) / 2, 3)])
    return out


# ------------------------------------------------------------------ round four: keying
def screen_colour(rgb: np.ndarray) -> str:
    """The colour of the green or blue screen in a picture (rows × columns × RGB): the middle of the pixels where
    green (or blue) stands well clear of the other two, whichever covers more."""
    px = rgb.reshape(-1, 3).astype(np.float32)
    r, g, b = px[:, 0], px[:, 1], px[:, 2]
    green = (g > 50) & (g > r * 1.25 + 10) & (g > b * 1.15 + 10)
    blue = (b > 50) & (b > r * 1.25 + 10) & (b > g * 1.1 + 10)
    pick = green if green.sum() >= blue.sum() else blue
    if pick.sum() < px.shape[0] * 0.02:
        return ""
    med = np.median(px[pick], axis=0)
    return "#%02X%02X%02X" % tuple(int(round(v)) for v in med)


def key_hue(colour: str) -> str:
    try:
        r, g, b = (int(colour[i:i + 2], 16) for i in (1, 3, 5))
    except (ValueError, TypeError):
        return "green"
    return "blue" if b > g else "green"


def frame_of(path: str, at: float, width: int = 320) -> np.ndarray:
    """One picture of a file at `at` seconds, `width` across, as rows × columns × RGB (or an empty array)."""
    try:
        info = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height", "-of", "json", path],
                              capture_output=True, text=True, timeout=20)
        s = (json.loads(info.stdout or "{}").get("streams") or [{}])[0]
        h = max(2, int(round(width * int(s.get("height") or 9) / max(1, int(s.get("width") or 16)) / 2)) * 2)
        raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{max(0.0, at):.3f}", "-i", path, "-frames:v", "1", "-vf", f"scale={width}:{h}",
                              "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True, timeout=60).stdout
    except (OSError, subprocess.SubprocessError, ValueError):
        return np.zeros((0, 0, 3), np.uint8)
    if len(raw) < width * h * 3:
        return np.zeros((0, 0, 3), np.uint8)
    return np.frombuffer(raw[:width * h * 3], np.uint8).reshape(h, width, 3)


SHAPES = {"oval": ("Oval", 0.3), "rect": ("Rectangle", 0.0), "diamond": ("Diamond", 0.9)}


# ------------------------------------------------------------------ round four: compound clips
def inner_view(root: dict, c: dict) -> dict:
    """A compound clip's insides as a project of their own: its tracks, clips and markers, with the film's media,
    bins and settings (shared, so media added inside are the film's)."""
    inner = c.setdefault("inner", {"tracks": [], "clips": [], "markers": []})
    v = {k: val for k, val in root.items() if k not in ("tracks", "clips", "markers", "name")}
    v.update(tracks=inner["tracks"], clips=inner["clips"], markers=inner.setdefault("markers", []), name=c.get("name") or "Compound clip")
    return v


def compound_content(c: dict) -> str:
    """"video" when anything inside is seen, else "audio"."""
    tracks = {t["id"]: t for t in (c.get("inner") or {}).get("tracks", [])}
    return "video" if any(tracks.get(x["track"], {}).get("kind") == "video" for x in (c.get("inner") or {}).get("clips", [])) else "audio"


# ------------------------------------------------------------------ round four: shots, beats, matching colour
def frames_between(path: str, start: float, end: float, width: int = 64, fps: float = 0) -> tuple:
    """Small pictures of a file from `start` to `end` (every frame, or `fps` a second) -> (frames, their times)."""
    try:
        info = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height,avg_frame_rate", "-of", "json", path],
                              capture_output=True, text=True, timeout=20)
        s = (json.loads(info.stdout or "{}").get("streams") or [{}])[0]
        a, b = (s.get("avg_frame_rate") or "30/1").split("/")
        rate = fps or (float(a) / float(b) if float(b) else 30.0)
        h = max(2, int(round(width * int(s.get("height") or 9) / max(1, int(s.get("width") or 16)) / 2)) * 2)
        raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{max(0.0, start):.3f}", "-i", path, "-t", f"{max(0.04, end - start):.3f}",
                              "-vf", f"fps={rate:.5f},scale={width}:{h}", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True, timeout=900).stdout
    except (OSError, subprocess.SubprocessError, ValueError, ZeroDivisionError):
        return np.zeros((0, 2, width, 3), np.uint8), np.zeros(0)
    n = len(raw) // (width * h * 3)
    frames = np.frombuffer(raw[:n * width * h * 3], np.uint8).reshape(n, h, width, 3)
    return frames, start + np.arange(n) / rate


def shot_changes(frames: np.ndarray, times: np.ndarray, least: float = 0.4) -> list:
    """Where the picture cuts to another shot: frames whose colours and layout both jump, well above the usual
    change between neighbouring frames there (so a busy shot doesn't count as a cut)."""
    if len(frames) < 3:
        return []
    f = frames.astype(np.float32)
    diff = np.abs(f[1:] - f[:-1]).mean(axis=(1, 2, 3)) / 255.0               # the layout moved
    hist = np.stack([np.stack([np.histogram(x[..., ch], bins=16, range=(0, 256))[0] for ch in range(3)]) for x in frames]).astype(np.float32)
    hist /= max(1.0, float(frames.shape[1] * frames.shape[2]))
    hd = np.abs(hist[1:] - hist[:-1]).sum(axis=(1, 2)) / 6.0                 # the colours changed (0..1)
    score = 0.5 * diff + 0.5 * hd
    out, last = [], -1e9
    for i, v in enumerate(score):
        around = np.concatenate([score[max(0, i - 15):i], score[i + 1:i + 16]])
        usual = float(np.median(around)) if around.size else 0.0
        if v > 0.12 and v > 4 * usual + 0.03 and times[i + 1] - last >= least:
            out.append(float(times[i + 1]))
            last = times[i + 1]
    return out


BEAT_BANDS = [(0, 120, 2.0), (120, 250, 1.5), (250, 500, 1.0), (500, 1000, 1.0), (1000, 2000, 0.8), (2000, 4000, 0.6), (4000, 22050, 0.5)]


def onset_envelope(x: np.ndarray, rate: int, hop: int = 128) -> np.ndarray:
    """How much new sound starts in each short moment: spectral flux of the log spectrum in bands, each band
    evened out on its own and the low ones counted more, so kicks and snares lead and hi-hats don't."""
    n = 1024
    if x.size < n * 2:
        return np.zeros(0)
    x = x.astype(np.float32) / 32768.0
    frames = np.lib.stride_tricks.sliding_window_view(x, n)[::hop] * np.hanning(n).astype(np.float32)
    mag = np.log1p(100 * np.abs(np.fft.rfft(frames, axis=1)))
    rise = np.maximum(0, np.diff(mag, axis=0))
    freqs = np.fft.rfftfreq(n, 1 / rate)
    k = max(1, int(rate / hop * 0.5))
    env = np.zeros(rise.shape[0], np.float32)
    for lo, hi, w in BEAT_BANDS:
        sel = (freqs >= lo) & (freqs < hi)
        if not sel.any():
            continue
        band = rise[:, sel].sum(axis=1)
        band = np.maximum(0, band - np.convolve(band, np.ones(2 * k + 1) / (2 * k + 1), mode="same"))   # take away the slow swell
        sd = float(band.std())
        if sd > 1e-9:
            env += w * band / sd
    env = np.concatenate([[0.0], env])
    sd = float(env.std()) or 1.0
    return env / sd


def beat_times(x: np.ndarray, rate: int, hop: int = 128) -> tuple:
    """The music's beat: (beats a minute, the beats in seconds). The tempo is the strongest repeat in the
    onsets between 70 and 180 a minute, leaning towards 120; the beats are then found by dynamic programming
    (Ellis 2007): each beat sits on a strong onset about one beat after the last."""
    env = onset_envelope(x, rate, hop)
    fr = rate / hop
    if env.size < fr * 4:
        return 0.0, []
    ac = np.correlate(env, env, mode="full")[env.size - 1:]
    lags = np.arange(int(fr * 60 / 180), int(fr * 60 / 70) + 1)
    lags = lags[lags < ac.size]
    bpms = 60 * fr / lags
    weight = np.exp(-0.5 * (np.log2(bpms / 120) / 0.9) ** 2)
    period = float(lags[np.argmax(ac[lags] * weight)])
    lo, hi = max(1, int(period * 0.9)), int(period * 1.1) + 1                # refine the period to a fraction of a frame
    best, bp = -1e9, period
    for p in np.linspace(lo, hi, 41):
        idx = (np.arange(0, env.size - 1, p)).astype(int)
        sc = max(env[np.clip(idx + o, 0, env.size - 1)].sum() for o in range(int(p)))
        if sc > best:
            best, bp = sc, p
    period = bp
    score, back = env.copy(), np.full(env.size, -1)
    a0, a1 = int(round(period * 0.5)), int(round(period * 2))
    for t in range(a1, env.size):
        prev = np.arange(t - a1, t - a0)
        pen = -100.0 * np.log((t - prev) / period) ** 2
        cand = score[prev] + pen
        j = int(np.argmax(cand))
        if cand[j] > 0:
            score[t] = env[t] + cand[j]
            back[t] = prev[j]
    t = int(np.argmax(score[-int(period * 2):])) + env.size - int(period * 2)
    beats = []
    while t >= 0:
        beats.append(t)
        t = int(back[t])
    beats = np.array(sorted(beats), float)
    if beats.size > 4:                                                         # the stretch before the first found beat
        first = beats[0] - period
        while first >= 0:
            beats = np.concatenate([[first], beats])
            first -= period
    times = beats / fr + (1024 / 2) / rate
    # The long window hears a beat early. Where does the sound actually jump, beat by beat? Move them all by the
    # usual difference (one shift for all, so the beat stays even).
    e = np.convolve(x.astype(np.float32) ** 2, np.ones(256) / 256, mode="same")[::32]
    de = np.diff(np.log(e + 1e-3))
    shifts = []
    for t in times:
        a, z = int((t - 0.03) * rate / 32), int((t + 0.12) * rate / 32)
        if 0 <= a < z < de.size:
            shifts.append((a + int(np.argmax(de[a:z]))) * 32 / rate - t)
    if len(shifts) >= 4:
        times = times + float(np.median(shifts))
    return round(60 * fr / period, 1), [round(float(t), 3) for t in times if t >= 0]


def _lab(rgb: np.ndarray) -> np.ndarray:
    """sRGB (0..1) to CIE Lab (D65)."""
    c = np.where(rgb <= 0.04045, rgb / 12.92, ((rgb + 0.055) / 1.055) ** 2.4)
    m = np.array([[0.4124564, 0.3575761, 0.1804375], [0.2126729, 0.7151522, 0.0721750], [0.0193339, 0.1191920, 0.9503041]])
    xyz = c @ m.T / np.array([0.95047, 1.0, 1.08883])
    f = np.where(xyz > 216 / 24389, np.cbrt(xyz), (24389 / 27 * xyz + 16) / 116)
    return np.stack([116 * f[..., 1] - 16, 500 * (f[..., 0] - f[..., 1]), 200 * (f[..., 1] - f[..., 2])], axis=-1)


def _rgb(lab: np.ndarray) -> np.ndarray:
    fy = (lab[..., 0] + 16) / 116
    fx, fz = fy + lab[..., 1] / 500, fy - lab[..., 2] / 200
    f = np.stack([fx, fy, fz], axis=-1)
    xyz = np.where(f ** 3 > 216 / 24389, f ** 3, (116 * f - 16) / (24389 / 27)) * np.array([0.95047, 1.0, 1.08883])
    m = np.array([[3.2404542, -1.5371385, -0.4985314], [-0.9692660, 1.8760108, 0.0415560], [0.0556434, -0.2040259, 1.0572252]])
    c = np.clip(xyz @ m.T, 0, 1)
    return np.clip(np.where(c <= 0.0031308, c * 12.92, 1.055 * np.power(c, 1 / 2.4) - 0.055), 0, 1)


def colour_stats(frames: np.ndarray) -> tuple:
    """Mean and spread of lightness and colour (Lab) over some pictures, leaving out clipped blacks and whites."""
    px = frames.reshape(-1, 3).astype(np.float32) / 255.0
    lum = px.mean(axis=1)
    px = px[(lum > 0.02) & (lum < 0.98)] if ((lum > 0.02) & (lum < 0.98)).sum() > 100 else px
    lab = _lab(px)
    return lab.mean(axis=0), lab.std(axis=0) + 1e-3


def match_cube(src: tuple, ref: tuple, path: str, size: int = 33, amount: float = 1.0) -> str:
    """A 3D LUT (.cube) that moves the colours of one shot to sit like another's (Reinhard's transfer in Lab:
    each of lightness and the two colour axes takes the other shot's average and spread)."""
    (ms, ss), (mr, sr) = src, ref
    scale = np.clip(sr / ss, 0.5, 2.0)
    g = np.linspace(0, 1, size)
    b_, g_, r_ = np.meshgrid(g, g, g, indexing="ij")                          # .cube: red changes fastest
    rgb = np.stack([r_, g_, b_], axis=-1).reshape(-1, 3)
    lab = _lab(rgb)
    moved = (lab - ms) * scale + mr
    out = _rgb(lab + (moved - lab) * max(0.0, min(1.0, amount)))
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as fh:
        fh.write(f"TITLE \"Clips colour match\"\nLUT_3D_SIZE {size}\n")
        fh.write("\n".join(f"{r:.5f} {gg:.5f} {bb:.5f}" for r, gg, bb in out) + "\n")
    return path


# ============================================================================================ to MLT
class Builder:
    """Writes the project as an MLT XML document at a given size (the viewer's or the export's)."""

    def __init__(self, p: dict, width: int, height: int, proxies: dict = None, font_for=None, has_cairo: bool = True, matte: str = "", pre: str = ""):
        self.p, self.W, self.H, self.fps = p, width, height, int(p.get("fps") or 30)
        self.pre = pre                                        # before every id, for a compound clip's insides
        self.matte = matte                                    # a clip shown alone as its see-through (white keeps, black goes)
        self.proxies, self.font_for, self.cairo = proxies or {}, font_for or (lambda fam: font_file(fam)), has_cairo
        self.out, self.ids = [], 0

    def f(self, seconds: float) -> int:
        return int(round(seconds * self.fps))

    @staticmethod
    def prop(name: str, value) -> str:
        return f'<property name={quoteattr(name)}>{escape(str(value))}</property>'

    def filt(self, service: str, props: dict, cin: int = None, cout: int = None) -> str:
        span = f' in="{cin}" out="{cout}"' if cin is not None else ""
        return f"<filter{span}>" + self.prop("mlt_service", service) + "".join(self.prop(k, v) for k, v in props.items()) + "</filter>"

    # ---------------------------------------------------------------- one clip's producer, with its filters
    def producer(self, c: dict, pid: str, upper: bool) -> tuple:
        """-> (xml, producer in frame, producer length in frames)."""
        p, fps = self.p, self.fps
        speed = max(0.1, min(16.0, float(c.get("speed") or 1.0)))
        length_f = max(1, self.f(clip_len(c)))
        props, filters = {}, []
        if c["kind"] == "title":
            props.update({"mlt_service": "color", "resource": "#00000000", "mlt_image_format": "rgba", "length": length_f + 2})
            pin, plen = 0, length_f + 2
            filters += self.title_filter(c)
        elif c["kind"] == "compound":                         # its insides, as a tractor of their own
            inner = Builder(inner_view(self.p, c), self.W, self.H, self.proxies, self.font_for, self.cairo, pre=f"{pid}_")
            filters = [f for f in self.picture_filters(c, upper) + self.sound_filters(c, 0, length_f) if f]
            pin = int(round(float(c["in"]) * fps))
            span = (pin, pin + length_f - 1)
            filters = [part for f in filters for part in f.split("\x00") if part]
            filters = [f.replace("<filter>", f'<filter in="{span[0]}" out="{span[1]}">', 1) for f in filters]
            parts, tractor, end = inner.tractor(pid, transparent=True, extra="".join(filters), at_least=pin + length_f)
            return "".join(parts) + tractor, pin, end
        else:
            m = media_of(p, c["media"])
            path = self.proxies.get(m.get("id"), m.get("path", ""))
            steady = float((c.get("effects") or {}).get("stabilise") or 0)
            if steady > 0.01 and m.get("kind") == "video" and stab_path(m.get("path", ""), steady).is_file():
                path = str(stab_path(m.get("path", ""), steady))      # the steadied copy (same length, same sound)
            track = track_of(p, c["track"])
            link = ""
            if m.get("kind") == "image":
                props.update({"mlt_service": "pixbuf", "resource": path, "ttl": 1, "length": length_f + 2, "aspect_ratio": 1})
                pin, plen = 0, length_f + 2
            elif ramped(c):                                   # speed ramps and holds: a chain through MLT's timeremap link
                r = Remap(c)
                longest = float(m.get("duration") or c["out"])
                plen = max(1, int(math.floor(r.out(longest) * fps)))
                pin = int(round(r.out(float(c["in"])) * fps))
                props.update({"mlt_service": "avformat-novalidate", "resource": path, "length": plen})
                link = ("<link>" + self.prop("mlt_service", "timeremap") + self.prop("time_map", r.time_map(plen, fps, longest))
                        + self.prop("pitch", 1 if c.get("keepPitch", True) else 0) + self.prop("image_mode", "nearest") + "</link>")
                if track.get("kind") == "audio" or c.get("soundOnly"):
                    props["video_index"] = -1
                heard = (track in sounding(p)) if track else bool(c.get("heard", True))
                if c.get("mute") or not m.get("audio") or not heard:
                    props["audio_index"] = -1
            else:
                media_f = max(1, int(math.floor(float(m.get("duration") or clip_len(c)) * fps / speed)))
                if abs(speed - 1.0) > 1e-3:
                    props.update({"mlt_service": "timewarp", "resource": f"{speed:g}:{path}", "warp_speed": f"{speed:g}", "warp_pitch": 1 if c.get("keepPitch", True) else 0})
                else:
                    props.update({"mlt_service": "avformat-novalidate", "resource": path})
                props["length"] = media_f
                pin, plen = int(round(c["in"] * fps / speed)), media_f
                if track.get("kind") == "audio" or c.get("soundOnly"):
                    props["video_index"] = -1
                heard = (track in sounding(p)) if track else bool(c.get("heard", True))
                if c.get("mute") or not m.get("audio") or not heard:
                    props["audio_index"] = -1
            filters += self.picture_filters(c, upper)
            filters += self.sound_filters(c, pin, length_f)
        span = (pin, pin + length_f - 1)
        filters = [part for f in filters if f for part in f.split("\x00") if part]
        filters = [f.replace("<filter>", f'<filter in="{span[0]}" out="{span[1]}">', 1) for f in filters]
        tag = "chain" if c["kind"] != "title" and link else "producer"
        xml = (f'<{tag} id="{pid}" in="0" out="{plen - 1}">' + "".join(self.prop(k, v) for k, v in props.items()) + (link if tag == "chain" else "")
               + "".join(filters) + f"</{tag}>")
        return xml, pin, plen

    def pframe(self, c: dict, s: float) -> int:
        """The producer's frame showing the footage's second `s` (speed, ramps and holds included)."""
        if ramped(c):
            return int(round(Remap(c).out(s) * self.fps))
        return int(round(s * self.fps / max(0.1, float(c.get("speed") or 1))))

    def title_filter(self, c: dict) -> list:
        st = c.get("style") or {}
        size = int(round(float(st.get("size", 54)) * self.H / 1080))
        place = st.get("place", "lower")
        align = st.get("align", "centre")
        margin = int(self.W * 0.06)
        x = {"left": str(margin), "right": f"w-text_w-{margin}"}.get(align, "(w-text_w)/2")
        y = {"top": "h*0.10", "centre": "(h-text_h)/2", "lower": "h*0.74", "bottom": "h*0.86-text_h"}.get(place, "h*0.74")
        props = {"av.text": c.get("text", "") or " ", "av.fontsize": size, "av.fontcolor": st.get("colour", "#FFFFFF"), "av.x": x, "av.y": y,
                 "av.expansion": "none", "av.line_spacing": int(size * 0.18), "av.fix_bounds": 1}
        fontfile = self.font_for(st.get("font", "Inter"))
        if fontfile:
            props["av.fontfile"] = fontfile
        if st.get("box"):
            props.update({"av.box": 1, "av.boxcolor": f"{st.get('boxColour', '#000000')}@{float(st.get('boxOpacity', 0.55)):.2f}", "av.boxborderw": int(size * 0.45)})
        if st.get("outline"):
            props.update({"av.borderw": max(1, int(size * float(st["outline"]) / 20)), "av.bordercolor": "black"})
        if st.get("shadow"):
            props.update({"av.shadowx": max(1, size // 22), "av.shadowy": max(1, size // 22), "av.shadowcolor": "black@0.6"})
        return [self.filt("avfilter.drawtext", props), self.transform_filter(c, True)]

    def picture_filters(self, c: dict, upper: bool) -> list:
        out = []
        m = media_of(self.p, c.get("media", ""))
        if m.get("kind") == "audio":
            return out
        crop = (c.get("transform") or {}).get("crop") or [0, 0, 0, 0]
        if any(crop):
            w, h = int(m.get("width") or self.W), int(m.get("height") or self.H)
            l, t, r, b = (max(0.0, min(0.45, float(v))) for v in crop)
            out.append(self.filt("crop", {"left": int(w * l), "right": int(w * r), "top": int(h * t), "bottom": int(h * b), "center": 0}))
        key = c.get("key") or {}
        if key.get("on"):                                    # green or blue screen
            colour = (key.get("colour") or "#1EC828").lstrip("#")[:6]
            out.append(self.filt("avfilter.chromakey", {"av.color": "0x" + colour, "av.similarity": f"{0.02 + 0.38 * float(key.get('strength', 0.35)):.3f}",
                                                        "av.blend": f"{0.3 * float(key.get('soft', 0.2)):.3f}"}))
            if float(key.get("spill", 0.5)) > 0.01:
                out.append(self.filt("avfilter.despill", {"av.type": key_hue("#" + colour), "av.mix": f"{float(key.get('spill', 0.5)):.2f}", "av.expand": 0}))
        shape = c.get("shape") or {}
        window = bool(shape.get("on")) and shape.get("use") == "colour"
        graded = len(out)
        col = c.get("colour") or {}
        if col.get("match") and os.path.isfile(col["match"]):     # matched to another shot, before any other grading
            out.append(self.filt("avfilter.lut3d", {"av.file": col["match"], "av.interp": "tetrahedral"}))
        if abs(float(col.get("exposure", 0))) > 1e-3:
            out.append(self.filt("avfilter.exposure", {"av.exposure": f"{float(col['exposure']):.3f}"}))
        con, sat = float(col.get("contrast", 1)), float(col.get("saturation", 1))
        if (c.get("effects") or {}).get("bw"):
            sat = 0.0
        if abs(con - 1) > 1e-3 or abs(sat - 1) > 1e-3:
            out.append(self.filt("avfilter.eq", {"av.contrast": f"{con:.3f}", "av.saturation": f"{sat:.3f}"}))
        temp = int(col.get("temperature", 6500))
        if abs(temp - 6500) > 50:
            out.append(self.filt("avfilter.colortemperature", {"av.temperature": temp, "av.mix": 1}))
        sh, mi, hi = wheel(col.get("shadows")), wheel(col.get("midtones")), wheel(col.get("highlights"))
        tint = float(col.get("tint", 0))
        if any(sh + mi + hi) or abs(tint) > 1e-3:
            mi = (mi[0] + tint * 0.15, mi[1] - tint * 0.3, mi[2] + tint * 0.15)
            out.append(self.filt("avfilter.colorbalance", {"av.rs": sh[0], "av.gs": sh[1], "av.bs": sh[2], "av.rm": round(mi[0], 4), "av.gm": round(mi[1], 4),
                                                           "av.bm": round(mi[2], 4), "av.rh": hi[0], "av.gh": hi[1], "av.bh": hi[2]}))
        if col.get("lut") and os.path.isfile(col["lut"]):
            out.append(self.filt("avfilter.lut3d", {"av.file": col["lut"], "av.interp": "tetrahedral"}))
        curves = {ch: pts for ch, pts in (col.get("curves") or {}).items() if ch in CURVE_CHANNELS and not curve_plain(pts)}
        if curves:
            out.append(self.filt("avfilter.curves", {CURVE_CHANNELS[ch]: curve_arg(pts) for ch, pts in curves.items()}))
        if window and len(out) > graded:                     # the grade only inside the shape (or outside it)
            out.insert(graded, self.filt("mask_start", {"filter": "frei0r.alphaspot", **{f"filter.{k}": v for k, v in self.shape_props(c, shape, masked=True).items()}}))
            out.append(self.filt("mask_apply", {"transition": "frei0r.cairoblend" if self.cairo else "affine"}))
        fx = c.get("effects") or {}
        steady = float(fx.get("stabilise") or 0)
        if steady > 0.01 and not stab_path(m.get("path", ""), steady).is_file():
            out.append(self.filt("avfilter.deshake", {"av.rx": 32, "av.ry": 32, "av.edge": "mirror"}))     # until the careful pass is done
        if float(fx.get("blur", 0)) > 0.01:
            out.append(self.filt("avfilter.gblur", {"av.sigma": f"{float(fx['blur']) * 30 * self.H / 1080:.2f}"}))
        if float(fx.get("sharpen", 0)) > 0.01:
            out.append(self.filt("avfilter.unsharp", {"av.la": f"{float(fx['sharpen']) * 2.5:.2f}", "av.lx": 5, "av.ly": 5}))
        if float(fx.get("vignette", 0)) > 0.01:
            out.append(self.filt("avfilter.vignette", {"av.angle": f"{0.2 + float(fx['vignette']) * 0.9:.3f}"}))
        if fx.get("flipH"):
            out.append(self.filt("avfilter.hflip", {}))
        if fx.get("flipV"):
            out.append(self.filt("avfilter.vflip", {}))
        if fx.get("videoNoise"):
            out.append(self.filt("avfilter.hqdn3d", {}))
        tr = c.get("tracking") or {}
        if tr.get("obscure") and tr.get("boxes"):
            W, H = self.W, self.H                              # MLT measures the area in the project's own size
            boxes = tr["boxes"]
            step = max(1, len(boxes) // 120)                   # a filter for each short stretch, the box moving across it
            lo, hi = self.pframe(c, float(c["in"])), self.pframe(c, float(c["out"])) - 1
            block = max(8, W // 40)
            rect = lambda q: f"{int(q[1] * W)}/{int(q[2] * H)}:{max(2, int(q[3] * W))}x{max(2, int(q[4] * H))}:{block}x{block}"
            pairs = list(zip(boxes[::step], boxes[step::step])) or [(boxes[0], boxes[0])]
            for k, (a, b) in enumerate(pairs):
                fa, fb = max(lo, self.pframe(c, a[0])), min(hi, self.pframe(c, b[0]) - (0 if k == len(pairs) - 1 else 1))
                if fb >= fa:
                    out.append(self.filt("obscure", {"start": rect(a), "end": rect(b)}, fa, fb))
        if shape.get("on") and shape.get("use", "cut") == "cut":   # see-through outside the shape
            out.append(self.filt("frei0r.alphaspot", self.shape_props(c, shape)))
        if self.matte and self.matte == c.get("id"):
            out.append(self.filt("avfilter.alphaextract", {}))
        out.append(self.transform_filter(c, upper))
        return [x for x in out if x]

    def shape_props(self, c: dict, shape: dict, masked: bool = False) -> dict:
        """frei0r's alphaspot for a clip's shape: where it is (following what was tracked, when asked), its size,
        softness and which side is kept. Inside mask_start, frames count from the producer's start, not the clip's."""
        inv = bool(shape.get("invert"))
        x, y = float(shape.get("x", 0.5)), float(shape.get("y", 0.5))
        props = {"0": SHAPES.get(shape.get("kind", "oval"), SHAPES["oval"])[1], "1": f"{x:.4f}", "2": f"{y:.4f}",
                 "3": f"{max(0.005, min(1.0, float(shape.get('w', 0.5)) / 2)):.4f}", "4": f"{max(0.005, min(1.0, float(shape.get('h', 0.5)) / 2)):.4f}",
                 "5": 0.5, "6": f"{max(0.0, min(1.0, float(shape.get('soft', 0.15)))) * 0.5:.4f}", "7": 1 if inv else 0, "8": 0 if inv else 1,
                 "9": 0.0 if masked else 0.5}                # write the mask; on the clip itself, keep the less see-through (a key stays)
        boxes = (c.get("tracking") or {}).get("boxes") or []
        if shape.get("follow") and boxes:
            dx = float(shape.get("dx", x - (boxes[0][1] + boxes[0][3] / 2)))       # how far from the thing it was put
            dy = float(shape.get("dy", y - (boxes[0][2] + boxes[0][4] / 2)))
            base = self.pframe(c, float(c["in"])) if masked else 0
            xs, ys, seen = [], [], set()
            for t, bx, by, bw, bh in boxes[::2]:
                f = base + int(round(out_of(c, t) * self.fps))
                if f in seen or f - base < 0:
                    continue
                seen.add(f)
                xs.append(f"{f}={max(0.0, min(1.0, bx + bw / 2 + dx)):.4f}")
                ys.append(f"{f}={max(0.0, min(1.0, by + bh / 2 + dy)):.4f}")
            if xs:
                props["1"], props["2"] = ";".join(xs), ";".join(ys)
        return props

    def transform_filter(self, c: dict, upper: bool) -> str:
        """Size, place, turn and see-through, with keyframes; fades are see-through on upper tracks, black on V1."""
        tr = c.get("transform") or {}
        W, H, fps, length = self.W, self.H, self.fps, clip_len(c)
        times = sorted({0.0} | {k[0] for prop in ("x", "y", "scale", "opacity") for k in (c.get("keys", {}).get(prop) or [])})
        times = dense_times(times, fps, c.get("ease", "linear"))
        fade_in, fade_out = float(c.get("fadeIn") or 0), float(c.get("fadeOut") or 0)
        if upper:
            times = sorted(set(times) | ({fade_in} if fade_in else set()) | ({max(0.0, length - fade_out), length} if fade_out else set()))

        def at(prop, base, t):
            keys = sorted(c.get("keys", {}).get(prop) or [])
            return base if not keys else eased_value(keys, t, c.get("ease", "linear"))
        plain = all(abs(at("scale", tr.get("scale", 1.0), t) - 1) < 1e-4 and abs(at("x", tr.get("x", 0), t)) < 1e-4 and abs(at("y", tr.get("y", 0), t)) < 1e-4
                    and abs(at("opacity", tr.get("opacity", 1.0), t) - 1) < 1e-4 for t in times) and abs(float(tr.get("rotation", 0))) < 1e-3
        if plain and not (upper and (fade_in or fade_out)) and not upper:
            return self.fade_black(c) if (fade_in or fade_out) else ""
        rects = []
        for t in times:
            s = at("scale", tr.get("scale", 1.0), t)
            o = at("opacity", tr.get("opacity", 1.0), t)
            if upper and fade_in and t < fade_in:
                o *= t / fade_in
            if upper and fade_out and t > length - fade_out:
                o *= max(0.0, (length - t) / fade_out)
            w, h = W * s, H * s
            x, y = (W - w) / 2 + at("x", tr.get("x", 0), t) * W, (H - h) / 2 + at("y", tr.get("y", 0), t) * H
            rects.append(f"{int(round(t * fps))}={x:.1f} {y:.1f} {w:.1f} {h:.1f} {max(0.0, min(1.0, o)):.3f}")
        props = {"background": "color:#00000000", "transition.rect": ";".join(rects), "transition.fill": 1, "transition.distort": 0,
                 "transition.valign": "middle", "transition.halign": "centre", "transition.threads": 0}
        if abs(float(tr.get("rotation", 0))) > 1e-3:
            props["transition.fix_rotate_x"] = f"{float(tr['rotation']):.2f}"
        out = self.filt("affine", props)
        if not upper and (fade_in or fade_out):
            out += "\x00" + self.fade_black(c)
        return out

    def fade_black(self, c: dict) -> str:
        n, fi, fo = max(1, self.f(clip_len(c))), self.f(float(c.get("fadeIn") or 0)), self.f(float(c.get("fadeOut") or 0))
        keys = (["0=0", f"{fi}=1"] if fi else ["0=1"]) + ([f"{max(fi, n - 1 - fo)}=1", f"{n - 1}=0"] if fo else [])
        return self.filt("brightness", {"level": ";".join(keys)})

    def sound_filters(self, c: dict, pin: int, n: int) -> list:
        m = media_of(self.p, c.get("media", ""))
        if not (m.get("audio") or c.get("kind") == "compound") or c.get("mute"):
            return []
        out = []
        fps, length = self.fps, clip_len(c)
        track = track_of(self.p, c["track"])
        gain = float(track.get("gain") or 0)                      # the mixer's fader for the whole track
        base = float(c.get("volume") or 0)
        keys = keyed(c, "volume", base)
        pts = {}
        if len(keys) > 1 and c.get("ease", "linear") != "linear":
            for t in dense_times([k[0] for k in keys], fps, c.get("ease")):
                pts[round(t, 4)] = eased_value(keys, t, c.get("ease"))
        for t, v in keys:
            pts[round(t, 4)] = v
        fi, fo = float(c.get("fadeIn") or 0), float(c.get("fadeOut") or 0)
        if fi:
            pts[0.0] = -60.0
            pts.setdefault(round(fi, 4), base)
        if fo:
            pts.setdefault(round(max(0.0, length - fo), 4), base)
            pts[round(length, 4)] = -60.0
        if self.p.get("duck") and track.get("role") == "music":
            by = float(self.p.get("duckBy", -12))
            for a, b in duck_spans(self.p):
                a_rel, b_rel = a - c["at"], b - c["at"]
                if b_rel <= 0 or a_rel >= length:
                    continue
                for t, v in ((a_rel - 0.4, base), (a_rel, base + by), (b_rel, base + by), (b_rel + 0.4, base)):
                    if 0 <= t <= length:
                        pts[round(t, 4)] = v
        if len(pts) > 1 or abs(base) > 1e-3 or abs(gain) > 1e-3:
            items = sorted(pts.items()) if pts else [(0.0, base)]
            out.append(self.filt("volume", {"level": ";".join(f"{int(round(t * fps))}={(v + gain if v > -59.9 else v):.2f}" for t, v in items)}))
        pan = max(-1.0, min(1.0, float(track.get("pan") or 0)))
        if abs(pan) > 0.01:
            out.append(self.filt("panner", {"channel": -1, "start": f"{(pan + 1) / 2:.3f}"}))
        if c.get("denoise"):
            out.append(self.filt("avfilter.afftdn", {"av.nr": 18, "av.nf": -35}))
        sfx = c.get("sound") or {}
        if sfx.get("voice"):                                   # a clear voice: no rumble, a little presence, even level
            out.append(self.filt("sox", {"effect": "highpass 85"}))       # MLT's own biquads pass sound through untouched;
            out.append(self.filt("sox", {"effect": "equalizer 3200 1q 3.5"}))   # SoX's work
            out.append(self.filt("avfilter.acompressor", {"av.threshold": 0.125, "av.ratio": 3, "av.attack": 15, "av.release": 180, "av.makeup": 2}))
        eq = sfx.get("eq") or {}
        if abs(float(eq.get("low", 0))) > 0.05:
            out.append(self.filt("sox", {"effect": f"bass {float(eq['low']):.1f} 120"}))
        if abs(float(eq.get("mid", 0))) > 0.05:
            out.append(self.filt("sox", {"effect": f"equalizer 1000 0.9q {float(eq['mid']):.1f}"}))
        if abs(float(eq.get("high", 0))) > 0.05:
            out.append(self.filt("sox", {"effect": f"treble {float(eq['high']):.1f} 6000"}))
        if sfx.get("comp"):
            amt = max(0.0, min(1.0, float(sfx["comp"])))
            out.append(self.filt("avfilter.acompressor", {"av.threshold": round(db_lin(-12 - 18 * amt), 4), "av.ratio": round(2 + amt * 6, 1),
                                                          "av.attack": 10, "av.release": 200, "av.makeup": round(1 + amt * 3, 2)}))
        if float(sfx.get("echo") or 0) > 0.01:
            amt = float(sfx["echo"])
            out.append(self.filt("avfilter.aecho", {"av.in_gain": 0.9, "av.out_gain": 0.85, "av.delays": "60|120", "av.decays": f"{0.25 * amt:.2f}|{0.15 * amt:.2f}"}))
        return out

    # ---------------------------------------------------------------- the whole thing
    def build(self, loudness: bool = False) -> str:
        p, fps = self.p, self.fps
        W, H = self.W, self.H
        g = math.gcd(W, H)
        head = (f'<?xml version="1.0" encoding="utf-8"?>\n<mlt LC_NUMERIC="C" version="7.0.0" title="{escape(p.get("name", ""))}" producer="main">'
                f'<profile description="clips" width="{W}" height="{H}" progressive="1" sample_aspect_num="1" sample_aspect_den="1" '
                f'display_aspect_num="{W // g}" display_aspect_den="{H // g}" frame_rate_num="{fps}" frame_rate_den="1" colorspace="709"/>')
        extra = self.filt("avfilter.loudnorm", {"av.I": -16, "av.TP": -1.5, "av.LRA": 11}) if loudness else ""
        parts, tractor, _ = self.tractor("main", extra=extra)
        return head + "".join(parts) + tractor + "</mlt>\n"

    def tractor(self, tid: str, transparent: bool = False, extra: str = "", at_least: int = 0) -> tuple:
        """The tracks, stacked: -> (what goes before it, the tractor itself, its length in frames). A compound
        clip's insides go on a see-through background, so what's under the clip shows where nothing is."""
        p, pre, W, H = self.p, self.pre, self.W, self.H
        end = max(1, self.f(total(p)) + 1, at_least)
        parts = [f'<producer id="{pre}black" in="0" out="{end - 1}">' + self.prop("mlt_service", "color") + self.prop("resource", "#00000000" if transparent else "#FF000000")
                 + self.prop("length", end) + self.prop("mlt_image_format", "rgba") + "</producer>",
                 f'<playlist id="{pre}background"><entry producer="{pre}black" in="0" out="{end - 1}"/></playlist>']
        videos = [t for t in p["tracks"] if t["kind"] == "video"]
        audios = [t for t in p["tracks"] if t["kind"] == "audio"]
        order = list(reversed(videos)) + audios                # V1 first above the background, then V2…, then audio
        track_ids = []
        for t in order:
            upper = t["kind"] == "video" and t["id"] != (videos[-1]["id"] if videos else "")
            pid_xml, play = self.playlist(t, upper)
            parts += pid_xml
            parts.append(play)
            track_ids.append(t)
        for snd in self.multicam_sound():                     # each multicam's sound, on its own track
            vt = {"id": snd["track"], "kind": "audio", "name": "multicam sound"}
            pid_xml, play = self.playlist(vt, False, [snd])
            parts += pid_xml
            parts.append(play)
            track_ids.append(vt)
        tr = [f'<tractor id="{tid}" in="0" out="{end - 1}"><track producer="{pre}background"/>']
        heard = [x["id"] for x in sounding(p)]
        heard += [f"mc_{c['id']}" for c in p.get("clips", []) if c.get("kind") == "multicam" and c["track"] in heard]
        for i, t in enumerate(track_ids, start=1):
            silent = t["id"] not in heard
            if t["kind"] == "audio":
                hide = ' hide="both"' if silent else ' hide="video"'
            else:
                hide = (' hide="both"' if silent else ' hide="video"') if t.get("hidden") else (' hide="audio"' if silent else "")
            tr.append(f'<track producer="{pre}pl_{t["id"]}"{hide}/>')
        for i, t in enumerate(track_ids, start=1):
            tr.append(f'<transition>{self.prop("mlt_service", "mix")}{self.prop("a_track", 0)}{self.prop("b_track", i)}{self.prop("always_active", 1)}{self.prop("sum", 1)}</transition>')
            if t["kind"] == "video":
                if self.cairo:
                    tr.append(f'<transition>{self.prop("mlt_service", "frei0r.cairoblend")}{self.prop("a_track", 0)}{self.prop("b_track", i)}{self.prop("always_active", 1)}</transition>')
                else:
                    tr.append(f'<transition>{self.prop("mlt_service", "affine")}{self.prop("a_track", 0)}{self.prop("b_track", i)}{self.prop("always_active", 1)}'
                              f'{self.prop("fill", 1)}{self.prop("distort", 0)}{self.prop("rect", f"0 0 {W} {H} 1")}</transition>')
        tr.append(extra + "</tractor>")
        return parts, "".join(tr), end

    def expand(self, clips: list) -> list:
        """Multicam clips become the pieces of each angle between its cuts (pictures only: their sound comes from
        one angle, on a track of its own)."""
        out = []
        for c in clips:
            if c.get("kind") != "multicam":
                out.append(c)
                continue
            angles = c.get("angles") or []
            cuts = sorted([float(t), int(a)] for t, a in (c.get("cuts") or [[c["in"], 0]]))
            a0, a1 = float(c["in"]), float(c["out"])
            bounds = [t for t, _ in cuts if a0 < t < a1]
            edges = [a0] + bounds + [a1]
            for k, (x0, x1) in enumerate(zip(edges, edges[1:])):
                if x1 - x0 < 1e-3:
                    continue
                angle = next((a for t, a in reversed(cuts) if t <= x0 + 1e-6), cuts[0][1] if cuts else 0)
                angle = max(0, min(len(angles) - 1, angle))
                piece = copy.deepcopy(c)
                piece.update(kind="media", id=f"{c['id']}_{k}", media=angles[angle]["media"], at=round(c["at"] + (x0 - a0), 4),
                             mute=True, transition=None, keys={})
                piece["in"], piece["out"] = round(x0 + float(angles[angle].get("offset", 0)), 4), round(x1 + float(angles[angle].get("offset", 0)), 4)
                for key in ("angles", "cuts", "audioAngle"):
                    piece.pop(key, None)
                out.append(piece)
        return out

    def multicam_sound(self) -> list:
        """One sound clip for each multicam clip, from its chosen angle, to go on a track of its own."""
        out = []
        heard_ids = [t["id"] for t in sounding(self.p)]
        for c in self.p.get("clips", []):
            if c.get("kind") != "multicam" or not c.get("angles"):
                continue
            k = max(0, min(len(c["angles"]) - 1, int(c.get("audioAngle", 0))))
            ang = c["angles"][k]
            snd = copy.deepcopy(c)
            snd.update(kind="media", id=f"{c['id']}_sound", media=ang["media"], track=f"mc_{c['id']}", soundOnly=True, heard=c["track"] in heard_ids,
                       transition=None, effects={}, colour={})
            snd["in"], snd["out"] = round(float(c["in"]) + float(ang.get("offset", 0)), 4), round(float(c["out"]) + float(ang.get("offset", 0)), 4)
            out.append(snd)
        return out

    def playlist(self, t: dict, upper: bool, clips: list = None) -> tuple:
        """One track: its clips' producers and the playlist placing them, with same-track transitions as small tractors."""
        clips = self.expand(on_track(self.p, t["id"])) if clips is None else clips
        if self.matte:
            clips = [c for c in clips if c["id"] == self.matte]
        xmls, entries, cursor = [], [], 0
        info = []
        for i, c in enumerate(clips):
            pid = f"{self.pre}p_{c['id']}"
            xml, pin, plen = self.producer(c, pid, upper)
            xmls.append(xml)
            info.append({"c": c, "pid": pid, "pin": pin, "plen": plen, "start": self.f(c["at"]), "n": max(1, self.f(clip_len(c)))})
        # how much each transition borrows from either side of its cut
        for i in range(len(info) - 1):
            a, b = info[i], info[i + 1]
            tr = a["c"].get("transition")
            a["h_after"] = 0
            if not tr or abs(a["start"] + a["n"] - b["start"]) > 1:
                continue
            want = max(2, self.f(float(tr.get("length", 1.0)))) // 2
            room_a = a["plen"] - (a["pin"] + a["n"])            # media after the cut on the left clip
            room_b = b["pin"]                                     # media before the cut on the right clip
            h = max(0, min(want, room_a, room_b, a["n"] // 2, b["n"] // 2))
            a["h_after"] = h
        for i, x in enumerate(info):
            c, h_before = x["c"], info[i - 1].get("h_after", 0) if i else 0
            h_after = x.get("h_after", 0)
            gap = x["start"] - cursor - (0 if not h_before else 0)
            if gap > 0 and not h_before:
                entries.append(f'<blank length="{gap}"/>')
                cursor += gap
            first = x["pin"] + h_before
            last = x["pin"] + x["n"] - 1 - h_after
            if last >= first:
                entries.append(f'<entry producer="{x["pid"]}" in="{first}" out="{last}"/>')
                cursor += last - first + 1
            if h_after:
                nxt = info[i + 1]
                kind = (c.get("transition") or {}).get("kind", "dissolve")
                luma = TRANSITIONS.get(kind, TRANSITIONS["dissolve"])[1]
                tid = f"{self.pre}tr_{c['id']}"
                L = 2 * h_after
                lp = {"mlt_service": "luma", "a_track": 0, "b_track": 1, "softness": 0.15}
                if luma and (LUMAS / luma).is_file():
                    lp["resource"] = str(LUMAS / luma)
                xmls.append(f'<tractor id="{tid}" in="0" out="{L - 1}">'
                            f'<track producer="{x["pid"]}" in="{x["pin"] + x["n"] - h_after}" out="{x["pin"] + x["n"] + h_after - 1}"/>'
                            f'<track producer="{nxt["pid"]}" in="{nxt["pin"] - h_after}" out="{nxt["pin"] + h_after - 1}"/>'
                            f'<transition in="0" out="{L - 1}">' + "".join(self.prop(k, v) for k, v in lp.items()) + "</transition>"
                            f'<transition in="0" out="{L - 1}">' + self.prop("mlt_service", "mix") + self.prop("a_track", 0) + self.prop("b_track", 1)
                            + self.prop("start", 0) + self.prop("end", 1) + "</transition></tractor>")
                entries.append(f'<entry producer="{tid}" in="0" out="{L - 1}"/>')
                cursor += L
        return xmls, f'<playlist id="{self.pre}pl_{t["id"]}">' + "".join(entries) + "</playlist>"


def melt_has(kind: str, name: str) -> bool:
    if not shutil.which("melt"):
        return False
    try:
        out = subprocess.run(["melt", "-query", kind], capture_output=True, text=True, timeout=20).stdout
    except (OSError, subprocess.SubprocessError):
        return False
    return f"- {name}\n" in out or out.rstrip().endswith(f"- {name}")


def export_command(project_file: str, target: str, preset: str, quality: str, width: int, height: int, fps: int, threads: int = 0) -> list:
    pr = PRESETS[preset]
    args = ["melt", project_file, "-progress", "-consumer", f"avformat:{target}"] + list(pr["args"])
    if pr.get("crf"):
        args.append(f"crf={pr['crf'].get(quality, list(pr['crf'].values())[1])}")
    if "vn=1" not in pr["args"]:
        g = math.gcd(width, height)                            # square pixels: given only a size, the consumer assumed PAL's 16:15
        args += [f"width={width}", f"height={height}", "sample_aspect_num=1", "sample_aspect_den=1", f"display_aspect_num={width // g}",
                 f"display_aspect_den={height // g}", f"frame_rate_num={fps}", "frame_rate_den=1"]
    args += [f"real_time=-{max(1, threads or min(8, os.cpu_count() or 2))}", "ar=48000", "channels=2"]
    return args


# ============================================================================================ the viewer
class Engine:
    """Plays the project through MLT's Python bindings: frames are pulled at the project's rate on a thread of their
    own (late ones are skipped), and the sound plays through MLT's audio output, started at the same moment."""

    def __init__(self, on_frame, on_end):
        self.on_frame, self.on_end = on_frame, on_end
        self.xml, self.size, self.prod, self.profile = "", (960, 540), None, None
        self.playing, self.pos, self.length, self.fps = False, 0, 1, 30
        self._thread, self._audio, self._audio_prod, self._lock = None, None, None, threading.Lock()
        if mlt is not None:
            mlt.Factory().init()

    @property
    def ok(self) -> bool:
        return mlt is not None

    def load(self, xml: str, size: tuple, fps: int) -> None:
        if mlt is None:
            return
        with self._lock:
            self.xml, self.size, self.fps = xml, size, fps
            self.profile = mlt.Profile()
            self.profile.set_width(size[0])
            self.profile.set_height(size[1])
            self.profile.set_frame_rate(fps, 1)
            self.profile.set_sample_aspect(1, 1)
            g = math.gcd(size[0], size[1])
            self.profile.set_display_aspect(size[0] // g, size[1] // g)
            self.profile.set_progressive(1)
            self.prod = mlt.Producer(self.profile, "xml-string", xml)
            self.length = max(1, self.prod.get_length() if self.prod and self.prod.is_valid() else 1)

    def image(self, n: int):
        """The frame at `n` as a QImage (or None)."""
        if mlt is None or not self.prod:
            return None
        with self._lock:
            self.prod.seek(max(0, min(n, self.length - 1)))
            frame = self.prod.get_frame()
            w, h = self.size
            data = frame.get_image(mlt.mlt_image_rgba, w, h)
        if not data:
            return None
        return QImage(bytes(data), w, h, w * 4, QImage.Format_RGBA8888).copy()

    def play(self, start: int) -> None:
        if mlt is None or not self.prod or self.playing:
            return
        self.playing, self.pos = True, max(0, min(start, self.length - 1))
        self._start_audio(self.pos)
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _start_audio(self, start: int) -> None:
        try:
            prod = mlt.Producer(self.profile, "xml-string", self.xml)
            prod.seek(start)
            cons = mlt.Consumer(self.profile, "sdl2_audio")
            if not cons.is_valid():
                return
            cons.set("terminate_on_pause", 0)
            cons.set("audio_buffer", 1024)
            cons.connect(prod)
            if cons.start() == 0:
                self._audio, self._audio_prod = cons, prod
        except Exception:
            self._audio = None

    def _run(self) -> None:
        t0, first = time.monotonic(), self.pos
        while self.playing:
            target = first + int((time.monotonic() - t0) * self.fps)
            if target >= self.length:
                self.playing = False
                self.on_end(self.length - 1)
                break
            img = self.image(target)
            self.pos = target
            if img is not None:
                self.on_frame(target, img)
            next_at = t0 + (target - first + 1) / self.fps
            wait = next_at - time.monotonic()
            if wait > 0:
                time.sleep(wait)
        self._stop_audio()

    def _stop_audio(self) -> None:
        if self._audio is not None:
            try:
                self._audio.stop()
            except Exception:
                pass
        self._audio, self._audio_prod = None, None

    def stop(self) -> int:
        self.playing = False
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=2)
        self._thread = None
        self._stop_audio()
        return self.pos


try:
    from PySide6.QtQuick import QQuickImageProvider

    class FrameProvider(QQuickImageProvider):
        """image://clips/<n>: the latest frame the viewer was given."""

        def __init__(self):
            super().__init__(QQuickImageProvider.Image)
            self.image = QImage(16, 9, QImage.Format_RGBA8888)
            self.image.fill(0)

        def requestImage(self, ident, size, requested):
            img = self.image
            if size is not None:
                try:
                    size.setWidth(img.width())
                    size.setHeight(img.height())
                except AttributeError:
                    pass
            return img
except ImportError:                                           # pragma: no cover
    FrameProvider = None


# ============================================================================================ the app
class Clips(QObject):
    changed = Signal()
    pickChanged = Signal()          # picking a clip mustn't rebuild the timeline (a drag that starts with the pick would break)
    frameChanged = Signal()
    said = Signal(str, bool)
    _back = Signal(object)
    _frame = Signal(int, QImage)

    def __init__(self, demo: bool = False, target=None, provider=None):
        super().__init__()
        self._back.connect(lambda fn: fn())
        self._frame.connect(self._got_frame)
        self._demo, self._provider = demo, provider
        self._file = STORE / "project.json"
        self._p = new_project()
        self._root, self._path = self._p, []                # the film, and the compound clips opened inside it
        self._undo, self._redo = [], []
        self._picked, self._head, self._frame_no = [], 0.0, 0
        self._zoom = 60.0                                   # pixels a second on the timeline
        self._thumbs, self._waves, self._proxies, self._proxying = {}, {}, {}, set()
        self._export = {"busy": False, "share": 0.0, "path": "", "proc": None}
        self._dirty_xml, self._xml_size = True, None
        self._cairo = melt_has("transitions", "frei0r.cairoblend") if not demo else True
        self._engine = Engine(lambda n, img: self._frame.emit(n, img), lambda n: self._back.emit(lambda: self._ended(n)))
        self._still = QTimer(self, singleShot=True, interval=60)
        self._still.timeout.connect(self._render_still)
        self._melt_busy = False
        self._steadying = {}                               # clip id -> share done (0..1), while a steadied copy is made
        self._mixing = None
        self._words = {"busy": False, "step": "", "proc": None}  # speech to captions
        self._matte = ""                                   # a clip shown alone as its matte, while keying
        if demo:
            self._demo_fill()
        else:
            self._load()
            if target:
                QTimer.singleShot(0, lambda: self.importFiles([str(target)]))
        self._root, self._path = self._p, []
        self._refresh_media()
        QTimer.singleShot(0, self._show_frame)

    # ---------------------------------------------------------------- keeping the project
    def _load(self) -> None:
        try:
            data = json.loads(self._file.read_text(encoding="utf-8"))
            self._p = migrate(data)
        except (OSError, ValueError, KeyError, TypeError):
            self._p = new_project()

    def _keep(self, undoable: bool = True) -> None:
        self._dirty_xml = True
        self._sync()
        if not self._demo:
            try:
                STORE.mkdir(parents=True, exist_ok=True)
                tmp = self._file.with_suffix(".saving")
                tmp.write_text(json.dumps(self._root), encoding="utf-8")
                os.replace(tmp, self._file)
            except OSError as e:
                self.said.emit(f"Couldn't save the project: {e.strerror or e}", True)
        self._picked = [x for x in self._picked if any(c["id"] == x for c in self._p["clips"])]
        self.changed.emit()
        self.pickChanged.emit()
        self._show_frame()

    def _before(self) -> None:
        self._mixing = None
        self._sync()
        self._undo.append((copy.deepcopy(self._root), list(self._path)))
        del self._undo[:-80]
        self._redo = []

    @Slot()
    def undo(self) -> None:
        if self._undo:
            self._sync()
            self._redo.append((copy.deepcopy(self._root), list(self._path)))
            self._root = self._undo.pop()[0]             # where the editing is stays put, as long as it still exists
            self._view()
            self._keep()

    @Slot()
    def redo(self) -> None:
        if self._redo:
            self._sync()
            self._undo.append((copy.deepcopy(self._root), list(self._path)))
            self._root = self._redo.pop()[0]             # where the editing is stays put, as long as it still exists
            self._view()
            self._keep()

    def _demo_fill(self) -> None:
        p = new_project("Tromsø, November")
        p["media"] = [
            {"id": "m1", "path": "/demo/harbour.mp4", "name": "Harbour at dawn.mp4", "kind": "video", "duration": 18.0, "width": 3840, "height": 2160, "fps": 30, "audio": True, "bin": "Footage"},
            {"id": "m2", "path": "/demo/ferry.mov", "name": "Ferry deck.mov", "kind": "video", "duration": 12.0, "width": 1920, "height": 1080, "fps": 30, "audio": True, "bin": "Footage"},
            {"id": "m3", "path": "/demo/market.mp4", "name": "Market stalls.mp4", "kind": "video", "duration": 22.0, "width": 1920, "height": 1080, "fps": 30, "audio": True, "bin": "Footage"},
            {"id": "m4", "path": "/demo/lights.mp4", "name": "Northern lights.mp4", "kind": "video", "duration": 30.0, "width": 3840, "height": 2160, "fps": 30, "audio": False, "bin": "Footage"},
            {"id": "m5", "path": "/demo/song.m4a", "name": "Fjord song.m4a", "kind": "audio", "duration": 96.0, "width": 0, "height": 0, "fps": 0, "audio": True, "bin": "Music"},
            {"id": "m6", "path": "/demo/voice.wav", "name": "Narration.wav", "kind": "audio", "duration": 14.0, "width": 0, "height": 0, "fps": 0, "audio": True, "bin": "Sound"},
            {"id": "m7", "path": "/demo/map.png", "name": "Route map.png", "kind": "image", "duration": 5.0, "width": 2000, "height": 1200, "fps": 0, "audio": False, "bin": "Footage"}]
        p["bins"] = ["Footage", "Music", "Sound"]
        c1 = blank_clip("c1", "m1", "v1", 0.0, 2.0, 8.0)
        c2 = blank_clip("c2", "m2", "v1", 6.0, 1.0, 7.5)
        c3 = blank_clip("c3", "m3", "v1", 12.5, 3.0, 10.0)
        c4 = blank_clip("c4", "m4", "v1", 19.5, 0.0, 12.0)
        c1["transition"] = {"kind": "dissolve", "length": 1.0}
        c2["transition"] = {"kind": "wipe-left", "length": 0.8}
        c1["fadeIn"], c4["fadeOut"] = 0.8, 1.5
        c3["colour"].update(temperature=5600, saturation=1.15, contrast=1.08)
        c4["speed"] = 0.75
        c4["out"] = 9.0
        pip = blank_clip("c5", "m7", "v2", 13.5, 0.0, 4.0)
        pip["transform"].update(scale=0.34, x=0.28, y=-0.26)
        pip["keys"] = {"opacity": [[0.0, 0.0], [0.5, 1.0]]}
        t1 = blank_title("c6", "v2", 1.0, 4.0, "Tromsø, November", "lower")
        music = blank_clip("c7", "m5", "a1", 0.0, 0.0, 31.5)
        music["fadeOut"], music["volume"] = 2.0, -6.0
        voice = blank_clip("c8", "m6", "a2", 7.0, 0.0, 9.0)
        p["clips"] = [c1, c2, c3, c4, pip, t1, music, voice]
        p["markers"] = [{"t": 12.5, "name": "Market", "colour": "#F5C542"}, {"t": 19.5, "name": "The lights", "colour": "#43D9B8"}]
        p["duck"], p["next"] = True, 9
        self._p = p
        self._picked = ["c3"]
        self._head = 14.2
        self._waves = {"m1": [abs(math.sin(i / 7)) * 0.6 for i in range(360)], "m2": [abs(math.sin(i / 5)) * 0.5 for i in range(240)],
                       "m3": [abs(math.sin(i / 9)) * 0.7 for i in range(440)], "m5": [0.35 + abs(math.sin(i / 11)) * 0.45 for i in range(1920)],
                       "m6": [abs(math.sin(i / 3)) * 0.8 if (i // 20) % 3 else 0.05 for i in range(280)]}

    # ---------------------------------------------------------------- media
    def _refresh_media(self) -> None:
        for m in self._p["media"]:
            if self._demo:
                continue
            mid = m["id"]
            if mid not in self._thumbs and m["kind"] in ("video", "image"):
                self._make_thumbs(m)
            if mid not in self._waves and m.get("audio"):
                self._make_wave(m)
            if mid not in self._proxies:
                try:
                    pp = proxy_path(m["path"])
                    if pp.exists():
                        self._proxies[mid] = str(pp)
                except OSError:
                    pass

    def _bg(self, work, then) -> None:
        def go():
            try:
                result = work()
            except Exception as e:                            # a broken file must not take the app down
                result = e
            self._back.emit(lambda: then(result))
        threading.Thread(target=go, daemon=True).start()

    def _make_thumbs(self, m: dict) -> None:
        folder = CACHE / "thumbs" / hashlib.sha1(m["path"].encode()).hexdigest()[:16]
        self._thumbs[m["id"]] = []

        def make():
            folder.mkdir(parents=True, exist_ok=True)
            got = []
            n = 1 if m["kind"] == "image" else 8
            for i in range(n):
                out = folder / f"{i}.jpg"
                if not out.exists():
                    t = 0 if m["kind"] == "image" else m["duration"] * (i + 0.5) / n
                    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{t:.2f}", "-i", m["path"], "-frames:v", "1", "-vf", "scale=-2:120", str(out)],
                                   capture_output=True, timeout=60)
                if out.exists():
                    got.append(QUrl.fromLocalFile(str(out)).toString())
            return got

        def done(got):
            if isinstance(got, list):
                self._thumbs[m["id"]] = got
                self.changed.emit()
        self._bg(make, done)

    def _make_wave(self, m: dict) -> None:
        cache = CACHE / "waves" / (hashlib.sha1(m["path"].encode()).hexdigest()[:16] + ".json")
        self._waves[m["id"]] = []

        def make():
            if cache.exists():
                return json.loads(cache.read_text())
            got = peaks(m["path"])
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps(got))
            return got

        def done(got):
            if isinstance(got, list):
                self._waves[m["id"]] = got
                self.changed.emit()
        self._bg(make, done)

    @Slot("QVariantList")
    def importFiles(self, paths: list) -> None:
        """Bring files into the library (each is read on a thread). Folders bring in what's inside them."""
        found = []
        for raw in paths:
            raw = str(raw)
            path = Path(QUrl(raw).toLocalFile() if raw.startswith("file:") else raw)
            if path.is_dir():
                found += sorted(q for q in path.iterdir() if q.suffix.lower() in VIDEO + AUDIO + IMAGE)
            elif path.is_file():
                found.append(path)
        known = {m["path"] for m in self._p["media"]}
        found = [f for f in found if str(f) not in known]
        if not found:
            return

        def look():
            out = []
            for f in found:
                try:
                    out.append((f, probe(str(f))))
                except ValueError as e:
                    out.append((f, str(e)))
            return out

        def done(result):
            if isinstance(result, Exception):
                self.said.emit(str(result), True)
                return
            self._before()
            added = 0
            for f, info in result:
                if isinstance(info, str):
                    self.said.emit(info, True)
                    continue
                bin_name = "Music" if info["kind"] == "audio" else "Footage"
                if bin_name not in self._p["bins"]:
                    self._p["bins"].append(bin_name)
                self._p["media"].append(dict(info, id=f"m{self._p['next']}", path=str(f), name=f.name, bin=bin_name))
                self._p["next"] += 1
                added += 1
            if added:
                self._refresh_media()
                self._keep()
                self.said.emit(f"Brought in {added} file{'s' if added != 1 else ''}", False)
        self._bg(look, done)

    @Slot(result="QVariantList")
    def mediaChoices(self) -> list:
        out = []
        for loc in (QStandardPaths.MoviesLocation, QStandardPaths.MusicLocation, QStandardPaths.PicturesLocation, QStandardPaths.DownloadLocation):
            folder = Path(QStandardPaths.writableLocation(loc) or "")
            if not folder.is_dir():
                continue
            for q in folder.rglob("*"):
                if q.suffix.lower() in VIDEO + AUDIO + IMAGE and q.is_file() and "/." not in str(q):
                    try:
                        out.append((q.stat().st_mtime, q))
                    except OSError:
                        pass
                if len(out) > 400:
                    break
        out.sort(reverse=True)
        known = {m["path"] for m in self._p["media"]}
        return [{"path": str(q), "name": q.name, "where": q.parent.name, "known": str(q) in known,
                 "kind": "video" if q.suffix.lower() in VIDEO else "audio" if q.suffix.lower() in AUDIO else "image"} for _, q in out[:120]]

    @Slot(str, str)
    def moveToBin(self, mid: str, bin_name: str) -> None:
        m = media_of(self._p, mid)
        if m and bin_name:
            self._before()
            if bin_name not in self._p["bins"]:
                self._p["bins"].append(bin_name)
            m["bin"] = bin_name
            self._keep()

    @Slot(str)
    def addBin(self, name: str) -> None:
        name = name.strip()
        if name and name not in self._p["bins"]:
            self._before()
            self._p["bins"].append(name)
            self._keep()

    @Slot(str, result=str)
    def removeMedia(self, mid: str) -> str:
        if any(c.get("media") == mid for c in self._p["clips"]):
            return "It's used on the timeline. Take it off there first."
        self._before()
        self._p["media"] = [m for m in self._p["media"] if m["id"] != mid]
        self._keep()
        return ""

    @Slot()
    def makeProxies(self) -> None:
        """Light copies of anything bigger than 1080p, made one after another in the background."""
        todo = [m for m in self._p["media"] if m["kind"] == "video" and max(m.get("width", 0), m.get("height", 0)) > 1920 and m["id"] not in self._proxies]
        if not todo:
            self.said.emit("Nothing needs a proxy: no media is bigger than 1080p.", False)
            return
        if self._demo:
            return
        self._proxying = {m["id"] for m in todo}
        self.changed.emit()

        def make():
            done_ids = []
            for m in todo:
                target = proxy_path(m["path"])
                target.parent.mkdir(parents=True, exist_ok=True)
                part = target.with_suffix(".part.mp4")
                r = subprocess.run(proxy_command(m["path"], part), capture_output=True, timeout=7200)
                if r.returncode == 0 and part.exists():
                    os.replace(part, target)
                    done_ids.append((m["id"], str(target)))
            return done_ids

        def done(result):
            self._proxying = set()
            if isinstance(result, list):
                for mid, path in result:
                    self._proxies[mid] = path
                self._dirty_xml = True
                self.said.emit(f"Made {len(result)} prox{'ies' if len(result) != 1 else 'y'}: editing 4K is now smooth", False)
                self._show_frame()
            self.changed.emit()
        self._bg(make, done)

    # ---------------------------------------------------------------- what QML sees
    def _face(self, c: dict) -> dict:
        if c.get("kind") == "multicam":                       # shown with its first angle's pictures and its sound
            ang = c.get("angles") or [{}]
            face = self._face(dict(c, kind="media", media=ang[min(len(ang) - 1, int(c.get("audioAngle", 0)))].get("media", "")))
            sp = float(c.get("speed") or 1)
            face.update(kind="multicam", name=f"Multicam · {len(ang)} angles", cuts=[[max(0.0, (cut[0] - c["in"]) / sp), cut[1]] for cut in sorted(c.get("cuts", []))], mediaKind="video")
            return face
        if c.get("kind") == "compound":                      # its first picture's thumbnails, its name and how many clips
            inner = (c.get("inner") or {}).get("clips") or []
            first = next((x for x in sorted(inner, key=lambda q: q["at"]) if media_of(self._p, x.get("media", "")).get("kind") in ("video", "image")), None)
            face = self._face(dict(c, kind="media", media=first["media"] if first else ""))
            face.update(kind="compound", name=f"{c.get('name') or 'Compound clip'} · {len(inner)} clip{'' if len(inner) == 1 else 's'}", mediaKind="compound", wave=[],
                        audio=any(media_of(self._p, x.get("media", "")).get("audio") for x in inner))
            return face
        m = media_of(self._p, c.get("media", ""))
        t = track_of(self._p, c["track"])
        thumbs = self._thumbs.get(m.get("id", ""), [])
        if len(thumbs) > 1 and m.get("duration") and c.get("kind") == "media":   # the pictures of the part used (trims, speeds, ramps)
            n, length, d = len(thumbs), clip_len(c), float(m["duration"])
            thumbs = [thumbs[max(0, min(n - 1, int(src_of(c, length * (k + 0.5) / n) / d * n)))] for k in range(n)]
        wave = self._waves.get(m.get("id", ""), [])
        if wave and m.get("duration"):
            per = len(wave) / m["duration"]
            a, b = int(c["in"] * per), int(c["out"] * per)
            step = max(1, (b - a) // 120)
            wave = [max(wave[i:i + step] or [0]) for i in range(a, b, step)][:200]
        tr = c.get("transition") or {}
        name = c.get("text", "") if c["kind"] == "title" else m.get("name", "?")
        return {"id": c["id"], "kind": c["kind"], "track": c["track"], "at": c["at"], "length": clip_len(c), "end": clip_end(c), "name": name,
                "media": c.get("media", ""), "mediaKind": "title" if c["kind"] == "title" else m.get("kind", ""), "thumbs": thumbs, "wave": wave,
                "speed": c.get("speed", 1.0), "mute": bool(c.get("mute")), "fadeIn": c.get("fadeIn", 0), "fadeOut": c.get("fadeOut", 0),
                "transition": tr.get("kind", ""), "transitionLength": tr.get("length", 0),
                "audio": bool(m.get("audio")) and not c.get("mute"), "keys": sum(len(v) for v in (c.get("keys") or {}).values()), "audioTrack": t.get("kind") == "audio",
                "bands": speed_bands(c) if ramped(c) else [], "keyed": bool((c.get("key") or {}).get("on")), "shaped": bool((c.get("shape") or {}).get("on")),
                "beats": beats_in(c)[:3000] if c.get("beats") else []}

    def _get_tracks(self) -> list:
        vids = [t for t in self._p["tracks"] if t["kind"] == "video"]
        auds = [t for t in self._p["tracks"] if t["kind"] == "audio"]
        return [dict(t, clips=[self._face(c) for c in on_track(self._p, t["id"])]) for t in vids + auds]

    def _get_media(self) -> list:
        used = {c.get("media") for c in self._p["clips"]}
        return [dict(m, thumb=(self._thumbs.get(m["id"]) or [""])[0], length=clock(m.get("duration", 0)), used=m["id"] in used,
                     proxy=m["id"] in self._proxies, proxying=m["id"] in self._proxying,
                     big=max(m.get("width", 0), m.get("height", 0)) > 1920) for m in self._p["media"]]

    def _get_clip(self) -> dict:
        if len(self._picked) != 1:
            return {}
        c = next((x for x in self._p["clips"] if x["id"] == self._picked[0]), None)
        if not c:
            return {}
        out = copy.deepcopy(c)
        if c.get("kind") == "multicam":
            ang = c.get("angles") or [{}]
            tau = float(c["in"]) + (self._head - c["at"]) * float(c.get("speed") or 1)
            showing = next((a for t, a in reversed(sorted(c.get("cuts") or [[0, 0]])) if t <= tau + 1e-6), 0)
            out["angleViews"] = [{"name": a.get("name", f"Angle {k + 1}"), "thumb": (self._thumbs.get(a.get("media", "")) or [""])[0], "offset": a.get("offset", 0)} for k, a in enumerate(ang)]
            out["showing"] = showing
            c = dict(c, media=ang[0].get("media", ""))
        m = media_of(self._p, c.get("media", ""))
        if c["kind"] == "compound":
            out.update(name=c.get("name") or "Compound clip", mediaKind="compound", length=clip_len(c), lengthText=clock(clip_len(c)),
                       sourceText=f"{clock(c['in'])}–{clock(c['out'])}", hasAudio=True, trackKind=track_of(self._p, c["track"]).get("kind", "video"),
                       keyTimes=sorted({k[0] for v in (c.get("keys") or {}).values() for k in v}), ease=c.get("ease", "linear"), sound={},
                       count=len((c.get("inner") or {}).get("clips") or []), inner=None,
                       shape=dict({"on": False, "kind": "oval", "x": 0.5, "y": 0.5, "w": 0.5, "h": 0.6, "soft": 0.15, "use": "cut", "invert": False}, **(c.get("shape") or {})))
            return out
        out.update(name=c.get("text", "") if c["kind"] == "title" else ("Multicam" if out.get("kind") == "multicam" else m.get("name", "")), mediaKind=m.get("kind", "title"), length=clip_len(c),
                   lengthText=clock(clip_len(c)), sourceText=f"{clock(c['in'])}–{clock(c['out'])}", hasAudio=bool(m.get("audio")),
                   trackKind=track_of(self._p, c["track"]).get("kind", "video"), keyTimes=sorted({k[0] for v in (c.get("keys") or {}).values() for k in v}),
                   ease=c.get("ease", "linear"), sound=c.get("sound") or {}, tracked=bool((c.get("tracking") or {}).get("boxes")),
                   obscure=bool((c.get("tracking") or {}).get("obscure")),
                   followable=[{"id": x["id"], "name": media_of(self._p, x.get("media", "")).get("name", "")} for x in self._p["clips"]
                               if x["id"] != c["id"] and (x.get("tracking") or {}).get("boxes") and x["at"] < clip_end(c) and c["at"] < clip_end(x)])
        if c.get("kind") == "media" and m.get("kind") == "video":
            out.update(self._ramp_view(c))
        if c.get("kind") == "media" and m.get("kind") in ("video", "image"):
            out["others"] = self._others(c)
        out.update(key=dict({"on": False, "colour": "#1EC828", "strength": 0.35, "soft": 0.2, "spill": 0.5}, **(c.get("key") or {})),
                   shape=dict({"on": False, "kind": "oval", "x": 0.5, "y": 0.5, "w": 0.5, "h": 0.6, "soft": 0.15, "use": "cut", "invert": False}, **(c.get("shape") or {})))
        return out

    def _angle_now(self) -> int:
        c = self._c(self._picked[0]) if len(self._picked) == 1 else None
        if not c or c.get("kind") != "multicam":
            return -1
        tau = float(c["in"]) + (self._head - c["at"]) * float(c.get("speed") or 1)
        return next((a for t, a in reversed(sorted(c.get("cuts") or [[0, 0]])) if t <= tau + 1e-6), 0)

    def _track_box(self) -> dict:
        """Where the picked clip's tracked thing is at the playhead (fractions of the picture)."""
        c = self._c(self._picked[0]) if len(self._picked) == 1 else None
        boxes = ((c or {}).get("tracking") or {}).get("boxes") or []
        if not boxes or not c["at"] - EPS <= self._head <= clip_end(c) + EPS:
            return {}
        tau = src_of(c, self._head - c["at"])
        if tau < boxes[0][0] - 0.05 or tau > boxes[-1][0] + 0.05:
            return {}
        b = min(boxes, key=lambda q: abs(q[0] - tau))
        return {"x": b[1], "y": b[2], "w": b[3], "h": b[4]}

    tracks = Property("QVariantList", _get_tracks, notify=changed)
    media = Property("QVariantList", _get_media, notify=changed)
    bins = Property("QStringList", lambda self: self._p["bins"], notify=changed)
    clip = Property("QVariantMap", _get_clip, notify=pickChanged)
    picked = Property("QStringList", lambda self: self._picked, notify=pickChanged)
    angleNow = Property(int, _angle_now, notify=frameChanged)
    trackBox = Property("QVariantMap", _track_box, notify=frameChanged)
    markers = Property("QVariantList", lambda self: sorted(self._p["markers"], key=lambda m: m["t"]), notify=changed)
    length = Property(float, lambda self: total(self._p), notify=changed)
    head = Property(float, lambda self: self._head, notify=frameChanged)
    headText = Property(str, lambda self: timecode(self._head, int(self._p.get("fps", 30))), notify=frameChanged)
    lengthText = Property(str, lambda self: timecode(total(self._p), int(self._p.get("fps", 30))), notify=changed)
    frame = Property(int, lambda self: self._frame_no, notify=frameChanged)
    playing = Property(bool, lambda self: self._engine.playing, notify=frameChanged)
    name = Property(str, lambda self: self._p.get("name", ""), notify=changed)
    size = Property(str, lambda self: self._p.get("size", "1080p"), notify=changed)
    sizes = Property("QVariantList", lambda self: [{"id": k, "name": v[2], "w": v[0], "h": v[1]} for k, v in SIZES.items()], constant=True)
    aspect = Property(float, lambda self: SIZES.get(self._p.get("size"), SIZES["1080p"])[0] / SIZES.get(self._p.get("size"), SIZES["1080p"])[1], notify=changed)
    fps = Property(int, lambda self: int(self._p.get("fps", 30)), notify=changed)
    rates = Property("QVariantList", lambda self: RATES, constant=True)
    duck = Property(bool, lambda self: bool(self._p.get("duck")), notify=changed)
    duckBy = Property(float, lambda self: float(self._p.get("duckBy", -12)), notify=changed)
    loudness = Property(bool, lambda self: bool(self._p.get("loudness")), notify=changed)
    zoom = Property(float, lambda self: self._zoom, notify=changed)
    canUndo = Property(bool, lambda self: bool(self._undo), notify=changed)
    canRedo = Property(bool, lambda self: bool(self._redo), notify=changed)
    transitions = Property("QVariantList", lambda self: [{"id": k, "name": v[0]} for k, v in TRANSITIONS.items()], constant=True)
    titleStyles = Property("QVariantList", lambda self: [{"id": k, "name": v["name"]} for k, v in TITLE_STYLES.items()], constant=True)
    presets = Property("QVariantList", lambda self: [{"id": k, "name": v["name"], "detail": v["detail"]} for k, v in PRESETS.items()], constant=True)
    exporting = Property(bool, lambda self: self._export["busy"], notify=changed)
    exportShare = Property(float, lambda self: self._export["share"], notify=changed)
    exported = Property(str, lambda self: self._export["path"], notify=changed)
    live = Property(bool, lambda self: self._engine.ok or self._demo, constant=True)
    hasMelt = Property(bool, lambda self: bool(shutil.which("melt")) or self._demo, constant=True)

    # ---------------------------------------------------------------- picking and the playhead
    @Slot(str, bool)
    def pick(self, cid: str, add: bool) -> None:
        if not cid:
            self._picked = []
        elif add:
            self._picked = [x for x in self._picked if x != cid] if cid in self._picked else self._picked + [cid]
        else:
            self._picked = [cid]
        self.pickChanged.emit()

    @Slot(float)
    def seek(self, t: float) -> None:
        was = self._engine.playing
        if was:
            self._engine.stop()
        self._head = max(0.0, min(t, total(self._p)))
        self.frameChanged.emit()
        self._show_frame()
        if was:
            self.play()

    @Slot(int)
    def step(self, frames: int) -> None:
        self.seek(self._head + frames / float(self._p.get("fps", 30)))

    @Slot(int)
    def jumpEdit(self, direction: int) -> None:
        """To the next or previous cut on any track (or marker)."""
        points = sorted({0.0, total(self._p)} | {c["at"] for c in self._p["clips"]} | {clip_end(c) for c in self._p["clips"]} | {m["t"] for m in self._p["markers"]})
        if direction > 0:
            nxt = next((x for x in points if x > self._head + 1e-3), self._head)
        else:
            nxt = next((x for x in reversed(points) if x < self._head - 1e-3), 0.0)
        self.seek(nxt)

    @Slot(float)
    def setZoom(self, z: float) -> None:
        self._zoom = max(4.0, min(400.0, z))
        self.changed.emit()

    # ---------------------------------------------------------------- the viewer
    def _xml(self, width: int, height: int, export: bool = False) -> str:
        if export:
            self._sync()
        return Builder(self._root if export else self._p, width, height, proxies={} if export else self._proxies, has_cairo=self._cairo,
                       matte="" if export else self._matte).build(loudness=export and self._p.get("loudness"))

    def _preview_size(self) -> tuple:
        W, H = SIZES.get(self._p.get("size"), SIZES["1080p"])[:2]
        scale = min(1.0, 960 / max(W, H))
        return max(2, int(W * scale) // 2 * 2), max(2, int(H * scale) // 2 * 2)

    def _ensure_engine(self) -> None:
        size = self._preview_size()
        if self._dirty_xml or self._xml_size != size:
            self._engine.load(self._xml(*size), size, int(self._p.get("fps", 30)))
            self._dirty_xml, self._xml_size = False, size

    def _show_frame(self) -> None:
        if not self._engine.playing:
            self._still.start()

    def _render_still(self) -> None:
        if self._demo or not self._p["clips"]:
            self._frame_no += 1
            self.frameChanged.emit()
            return
        n = int(round(self._head * int(self._p.get("fps", 30))))
        if self._engine.ok:
            self._ensure_engine()
            img = self._engine.image(n)
            if img is not None:
                self._got_frame(n, img)
            return
        if not shutil.which("melt") or self._melt_busy:
            return
        size = self._preview_size()
        xml, self._melt_busy = self._xml(*size), True
        work = CACHE / "still"

        def make():
            work.mkdir(parents=True, exist_ok=True)
            (work / "p.mlt").write_text(xml, encoding="utf-8")
            out = work / "frame.png"
            out.unlink(missing_ok=True)
            subprocess.run(["melt", str(work / "p.mlt"), f"in={n}", f"out={n}", "-consumer", f"avformat:{out}", "vcodec=png", "f=image2", "update=1", "an=1",
                            f"width={size[0]}", f"height={size[1]}", "sample_aspect_num=1", "sample_aspect_den=1"],
                           capture_output=True, timeout=60)
            return QImage(str(out)) if out.exists() else None

        def done(img):
            self._melt_busy = False
            if isinstance(img, QImage) and not img.isNull():
                self._got_frame(n, img)
        self._bg(make, done)

    def _got_frame(self, n: int, img: QImage) -> None:
        if self._provider is not None:
            self._provider.image = img
        if self._engine.playing:
            self._head = n / float(self._p.get("fps", 30))
        self._frame_no += 1
        self.frameChanged.emit()

    def _ended(self, n: int) -> None:
        self._head = n / float(self._p.get("fps", 30))
        self.frameChanged.emit()

    @Slot()
    def play(self) -> None:
        if self._demo or not self._engine.ok or not self._p["clips"]:
            if not self._engine.ok and not self._demo:
                self.said.emit("Playing needs MLT's Python bindings (python3-mlt). The viewer still shows each frame.", True)
            return
        self._ensure_engine()
        start = int(round(self._head * int(self._p.get("fps", 30))))
        if start >= self._engine.length - 1:
            start = 0
        self._engine.play(start)
        self.frameChanged.emit()

    @Slot()
    def pause(self) -> None:
        if self._engine.playing:
            n = self._engine.stop()
            self._head = n / float(self._p.get("fps", 30))
            self.frameChanged.emit()

    @Slot()
    def toggle(self) -> None:
        self.pause() if self._engine.playing else self.play()

    # ---------------------------------------------------------------- editing
    def _c(self, cid: str):
        return next((c for c in self._p["clips"] if c["id"] == cid), None)

    def _free_video_track(self, at: float, length: float, above: str = "v1") -> str:
        vids = [t for t in self._p["tracks"] if t["kind"] == "video"]      # top first
        for t in reversed(vids):
            if t["id"] != above and not t.get("locked") and t.get("role") != "captions" and fits(self._p, t["id"], at, length):
                return t["id"]
        new = {"id": f"v{len(vids) + 1}x{self._p['next']}", "kind": "video", "name": f"V{len(vids) + 1}", "hidden": False, "locked": False}
        self._p["next"] += 1
        self._p["tracks"].insert(0, new)
        return new["id"]

    @Slot(str, str, float, result=str)
    def place(self, mid: str, tid: str, at: float) -> str:
        """Put library item `mid` on track `tid` at `at` seconds (snapped). "" when done, else why not."""
        m = media_of(self._p, mid)
        if not m:
            return "That file isn't in the library."
        if not tid:
            tid = next((t["id"] for t in self._p["tracks"] if (t["kind"] == "audio") == (m["kind"] == "audio") and (m["kind"] == "audio" or t["id"] == "v1")), "")
            if tid:
                at = max([clip_end(c) for c in on_track(self._p, tid)] + [0.0]) if at < 0 else at
        t = track_of(self._p, tid)
        if not t:
            return "Pick a track."
        if t.get("locked"):
            return f"{t['name']} is locked."
        length = min(float(m.get("duration") or 5.0), 3600.0) if m["kind"] != "image" else 5.0
        c = blank_clip(f"c{self._p['next']}", mid, tid, 0.0, 0.0, length)
        if not accepts(t, c, m):
            return "Pictures and videos go on video tracks; sound goes on audio tracks." if t["kind"] == "audio" else "Sound files go on audio tracks."
        at = snap(self._p, max(0.0, at), 8.0 / self._zoom, playhead=self._head)
        if not fits(self._p, tid, at, length):
            later = max([clip_end(x) for x in on_track(self._p, tid) if clip_end(x) > at - EPS] + [at])
            if fits(self._p, tid, later, length):
                at = later
            else:
                return "There's no room there."
        self._before()
        c["at"] = round(at, 4)
        self._p["clips"].append(c)
        self._p["next"] += 1
        self._picked = [c["id"]]
        self._keep()
        return ""

    @Slot(str, str, float, result=bool)
    def move(self, cid: str, tid: str, at: float) -> bool:
        c = self._c(cid)
        t = track_of(self._p, tid)
        if not c or not t or t.get("locked") or track_of(self._p, c["track"]).get("locked"):
            return False
        if not accepts(t, c, media_of(self._p, c.get("media", ""))):
            return False
        at = snap(self._p, max(0.0, at), 8.0 / self._zoom, ignore=cid, playhead=self._head)
        if not fits(self._p, tid, at, clip_len(c), ignore=cid):
            end_snap = snap(self._p, at + clip_len(c), 8.0 / self._zoom, ignore=cid, playhead=self._head) - clip_len(c)
            if fits(self._p, tid, end_snap, clip_len(c), ignore=cid):
                at = end_snap
            else:
                return False
        if abs(c["at"] - at) < EPS and c["track"] == tid:
            return True
        self._before()
        c["at"], c["track"] = round(at, 4), tid
        if c.get("transition"):
            c["transition"] = None
        self._keep()
        return True

    @Slot(str, str, float, bool, result=bool)
    def trim(self, cid: str, edge: str, t: float, ripple: bool) -> bool:
        """Drag one end of a clip to timeline time `t`. With ripple on, what's after it on the track moves too."""
        c = self._c(cid)
        if not c or track_of(self._p, c["track"]).get("locked"):
            return False
        m = media_of(self._p, c.get("media", ""))
        longest = float(m.get("duration") or 3600) if m.get("kind") in ("video", "audio") else 3600.0
        if c.get("kind") == "compound":
            longest = total(c.get("inner") or {"clips": []})
        t = snap(self._p, t, 8.0 / self._zoom, ignore=cid, playhead=self._head)
        self._before()
        old_end = clip_end(c)
        if edge == "in":
            new_in = max(0.0, min(src_of(c, t - c["at"]), c["out"] - 0.1))
            new_len = clip_len(dict(c, **{"in": new_in}))
            new_at = old_end - new_len                       # the end stays put
            if new_at < 0 or not fits(self._p, c["track"], new_at, new_len, ignore=cid):
                self._undo.pop()
                return False
            c["at"], c["in"] = round(new_at, 4), round(new_in, 4)
        else:
            new_out = max(c["in"] + 0.1, min(src_of(c, t - c["at"]), longest))
            new_len = clip_len(dict(c, out=new_out))
            grow = new_len - clip_len(c)
            if not ripple and not fits(self._p, c["track"], c["at"], new_len, ignore=cid):
                self._undo.pop()
                return False
            c["out"] = round(new_out, 4)
            if ripple:
                for o in self._p["clips"]:
                    if o["track"] == c["track"] and o["id"] != cid and o["at"] >= old_end - EPS:
                        o["at"] = round(max(0.0, o["at"] + grow), 4)
        self._keep()
        return True

    @Slot(result=int)
    def cut(self) -> int:
        """Blade: cut the picked clips (or everything) at the playhead."""
        self._before()
        made = blade(self._p, self._head, self._picked or None)
        if not made:
            self._undo.pop()
            return 0
        self._keep()
        return len(made)

    @Slot(bool)
    def removePicked(self, ripple: bool) -> None:
        if not self._picked:
            return
        self._before()
        if ripple:
            ripple_delete(self._p, list(self._picked))
        else:
            self._p["clips"] = [c for c in self._p["clips"] if c["id"] not in self._picked]
        self._picked = []
        self._keep()

    @Slot()
    def duplicatePicked(self) -> None:
        made = []
        self._before()
        for cid in list(self._picked):
            c = self._c(cid)
            if not c:
                continue
            twin = copy.deepcopy(c)
            twin["id"] = f"c{self._p['next']}"
            self._p["next"] += 1
            at = clip_end(c)
            while not fits(self._p, c["track"], at, clip_len(c)):
                at = max(clip_end(x) for x in on_track(self._p, c["track"]) if clip_end(x) > at - EPS)
            twin["at"] = round(at, 4)
            twin["transition"] = None
            self._p["clips"].append(twin)
            made.append(twin["id"])
        if made:
            self._picked = made
            self._keep()
        else:
            self._undo.pop()

    @Slot(str, str, "QVariant")
    def set(self, cid: str, path: str, value) -> None:
        """Change one setting of a clip: "speed", "colour.exposure", "transform.scale", "style.size", "text"…"""
        c = self._c(cid)
        if not c:
            return
        if hasattr(value, "toVariant"):
            value = value.toVariant()
        self._before()
        node, parts = c, path.split(".")
        for key in parts[:-1]:
            node = node.setdefault(key, {})
        last = parts[-1]
        if path == "speed":
            value = max(0.1, min(16.0, float(value)))
            old_len = clip_len(c)
            new_len = clip_len(dict(c, speed=value))
            if new_len > old_len + EPS and not fits(self._p, c["track"], c["at"], new_len, ignore=cid):
                self._undo.pop()
                self.said.emit("Slower won't fit: something comes right after it on the track.", True)
                return
        if path == "length" and c["kind"] == "title":
            new = max(0.2, float(value))
            if not fits(self._p, c["track"], c["at"], new, ignore=cid):
                self._undo.pop()
                return
            c["out"] = round(c["in"] + new, 4)
            self._keep()
            return
        node[last] = value
        self._keep()

    @Slot(str, str, float)
    def setKey(self, cid: str, prop: str, value: float) -> None:
        """A keyframe for `prop` (opacity, scale, x, y, volume) at the playhead, inside the clip."""
        c = self._c(cid)
        if not c:
            return
        t = round(self._head - c["at"], 3)
        if t < -EPS or t > clip_len(c) + EPS:
            self.said.emit("Put the playhead over the clip first.", True)
            return
        self._before()
        keys = [k for k in c.setdefault("keys", {}).setdefault(prop, []) if abs(k[0] - t) > 0.02]
        keys.append([max(0.0, t), float(value)])
        c["keys"][prop] = sorted(keys)
        self._keep()

    @Slot(str, str)
    def clearKeys(self, cid: str, prop: str) -> None:
        c = self._c(cid)
        if c and (c.get("keys") or {}).get(prop):
            self._before()
            c["keys"].pop(prop, None)
            self._keep()

    @Slot(str, str, float, result=str)
    def setTransition(self, cid: str, kind: str, length: float) -> str:
        """A transition from clip `cid` into the one right after it on the same track ("" kind removes it)."""
        c = self._c(cid)
        if not c:
            return ""
        nxt = next((o for o in on_track(self._p, c["track"]) if abs(o["at"] - clip_end(c)) < 0.05), None)
        if kind and not nxt:
            return "A transition needs another clip right after this one, on the same track."
        self._before()
        length = max(0.2, min(4.0, length))
        c["transition"] = {"kind": kind, "length": length} if kind else None
        note = ""
        if kind and nxt:
            # a transition borrows footage from beyond the cut; where there isn't enough, the two clips overlap
            # instead (like Final Cut): each gives up the frames it lacks, and what follows on the track moves up
            def room_after(x):
                m = media_of(self._p, x.get("media", ""))
                return (float(m.get("duration") or 0) - x["out"]) / x.get("speed", 1.0) if m.get("kind") in ("video", "audio") else 99.0

            def room_before(x):
                m = media_of(self._p, x.get("media", ""))
                return x["in"] / x.get("speed", 1.0) if m.get("kind") in ("video", "audio") else 99.0
            half = length / 2
            need_a, need_b = max(0.0, half - room_after(c)), max(0.0, half - room_before(nxt))
            need_a, need_b = min(need_a, clip_len(c) / 2 - 0.05), min(need_b, clip_len(nxt) / 2 - 0.05)
            if need_a > 1e-3 or need_b > 1e-3:
                old_next_at = nxt["at"]
                c["out"] = round(c["out"] - need_a * c.get("speed", 1.0), 4)
                nxt["in"] = round(nxt["in"] + need_b * nxt.get("speed", 1.0), 4)
                shift = need_a + need_b                         # the right clip moves up by what the left gave up;
                for o in self._p["clips"]:                      # what follows it, by both
                    if o["track"] == c["track"] and o["at"] >= old_next_at - EPS:
                        o["at"] = round(max(0.0, o["at"] - (need_a if o is nxt else shift)), 4)
                note = f"The clips overlap by {shift:.1f} s to make the transition (there wasn't footage beyond the cut), so the film is that much shorter."
        self._keep()
        return note

    @Slot(str, float, result=str)
    def addTitle(self, style: str, at: float) -> str:
        at = self._head if at < 0 else at
        self._before()
        tid = self._free_video_track(at, 4.0)
        t = blank_title(f"c{self._p['next']}", tid, at, 4.0, "Your words here" if style != "caption" else "What's being said", style)
        self._p["next"] += 1
        self._p["clips"].append(t)
        self._picked = [t["id"]]
        self._keep()
        return t["id"]

    @Slot(str)
    def addTrack(self, kind: str) -> None:
        self._before()
        n = sum(1 for t in self._p["tracks"] if t["kind"] == kind) + 1
        tid = f"{kind[0]}{n}x{self._p['next']}"
        self._p["next"] += 1
        if kind == "video":
            self._p["tracks"].insert(0, {"id": tid, "kind": "video", "name": f"V{n}", "hidden": False, "locked": False})
        else:
            self._p["tracks"].append({"id": tid, "kind": "audio", "name": f"A{n}", "role": "", "muted": False, "locked": False})
        self._keep()

    @Slot(str, str, "QVariant")
    def setTrack(self, tid: str, key: str, value) -> None:
        t = track_of(self._p, tid)
        if t and key in ("name", "hidden", "locked", "muted", "role", "gain", "pan", "solo"):
            value = value.toVariant() if hasattr(value, "toVariant") else value
            if key == "gain":
                value = round(max(-60.0, min(12.0, float(value))), 1)
            elif key == "pan":
                value = round(max(-1.0, min(1.0, float(value))), 2)
            if not (key in ("gain", "pan") and self._undo and self._mixing == (tid, key)):   # one undo step for a whole drag of a fader
                self._before()
                self._mixing = (tid, key) if key in ("gain", "pan") else None
            t[key] = value
            self._keep()

    @Slot(str, result=str)
    def removeTrack(self, tid: str) -> str:
        if any(c["track"] == tid for c in self._p["clips"]):
            return "Take the clips off the track first."
        if tid == "v1":
            return "V1 is the main track; it stays."
        self._before()
        self._p["tracks"] = [t for t in self._p["tracks"] if t["id"] != tid]
        self._keep()
        return ""

    @Slot(str)
    def addMarker(self, name: str) -> None:
        self._before()
        self._p["markers"].append({"t": round(self._head, 3), "name": name or f"Marker {len(self._p['markers']) + 1}", "colour": "#F5C542"})
        self._keep()

    @Slot(float)
    def removeMarker(self, t: float) -> None:
        self._before()
        self._p["markers"] = [m for m in self._p["markers"] if abs(m["t"] - t) > 0.01]
        self._keep()

    @Slot(str, "QVariant")
    def setProject(self, key: str, value) -> None:
        if hasattr(value, "toVariant"):
            value = value.toVariant()
        if key not in ("name", "size", "fps", "duck", "duckBy", "loudness"):
            return
        if key == "size" and value not in SIZES:
            return
        if key == "fps" and int(value) not in RATES:
            return
        self._before()
        self._p[key] = value
        self._keep()

    @Slot()
    def startOver(self) -> None:
        self.pause()
        self._before()
        self._p = new_project()
        self._root, self._path = self._p, []
        self._picked, self._head = [], 0.0
        self._keep()

    # ---------------------------------------------------------------- looking closely
    @Slot(str, result=str)
    def scope(self, kind: str) -> str:
        """The frame under the playhead as a waveform, vectorscope or histogram picture (a file URL)."""
        if self._demo or self._provider is None or self._provider.image.isNull():
            return ""
        CACHE.mkdir(parents=True, exist_ok=True)
        src, out = CACHE / "scope-in.png", CACHE / f"scope-{kind}.png"
        self._provider.image.save(str(src))
        vf = {"waveform": "waveform=mode=column:display=overlay:intensity=0.3:graticule=green:flags=numbers,scale=480:240",
              "vectorscope": "format=yuv444p,vectorscope=mode=color3:graticule=green,scale=240:240",
              "histogram": "histogram=display_mode=overlay:levels_mode=linear,scale=480:240"}.get(kind)
        if not vf:
            return ""
        r = subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(src), "-vf", vf, "-frames:v", "1", "-update", "1", str(out)], capture_output=True, timeout=30)
        return QUrl.fromLocalFile(str(out)).toString() + f"?{time.time()}" if r.returncode == 0 and out.exists() else ""

    @Slot(result="QVariantList")
    def lutChoices(self) -> list:
        found = []
        for base in (Path.home() / "Videos" / "LUTs", Path.home() / "Downloads", Path.home() / "Documents", Path.home() / ".local/share/huginn/luts", Path("/usr/share/huginn/luts")):
            if base.is_dir():
                found += [{"path": str(q), "name": q.stem} for q in sorted(base.rglob("*.cube"))[:60]]
        return found



    # ---------------------------------------------------------------- round three: multicam
    _synced = Signal(object)

    @Slot()
    def makeMulticam(self) -> None:
        """The picked video clips (2 to 4, the same moment from different cameras) become one multicam clip, lined
        up by their sound. Then pick an angle at any moment (1 to 4 while playing) to cut to it."""
        clips = [c for c in self._p["clips"] if c["id"] in self._picked and c["kind"] == "media" and media_of(self._p, c["media"]).get("kind") == "video"]
        if not 2 <= len(clips) <= 4:
            self.said.emit("Pick 2 to 4 video clips of the same moment (Ctrl-click them).", True)
            return
        clips.sort(key=lambda c: (track_of(self._p, c["track"]).get("id") != "v1", c["at"]))
        if self._demo:
            offsets = [0.0] + [0.4 * k for k in range(1, len(clips))]
            self._made_multicam(clips, offsets)
            return
        self._busy_note = "Lining up the cameras by their sound…"
        self.said.emit(self._busy_note, False)
        paths = [media_of(self._p, c["media"])["path"] for c in clips]

        def work():
            base = sound_of(paths[0])
            offs = [0.0] + [audio_sync(base, sound_of(q), 8000) for q in paths[1:]]
            self._back.emit(lambda: self._made_multicam(clips, offs))
        threading.Thread(target=work, daemon=True).start()

    def _made_multicam(self, clips: list, offsets: list) -> None:
        first = clips[0]
        # angle k's own time = angle 0's time + offset k (offset from the sound: the same sound comes later by that much)
        angles = [{"media": c["media"], "offset": round(float(off), 3), "name": media_of(self._p, c["media"]).get("name", "")} for c, off in zip(clips, offsets)]
        lo = max(0.0, -min(a["offset"] for a in angles))
        hi = min(float(media_of(self._p, a["media"]).get("duration") or 0) - a["offset"] for a in angles)
        a0 = max(lo, float(first["in"]))
        a1 = max(a0 + 0.5, min(hi, float(first["out"])))
        self._before()
        ids = {c["id"] for c in clips}
        self._p["clips"] = [c for c in self._p["clips"] if c["id"] not in ids]
        mc = blank_clip(f"c{self._p['next']}", "", first["track"], first["at"], a0, a1)
        self._p["next"] += 1
        mc.update(kind="multicam", angles=angles, cuts=[[a0, 0]], audioAngle=0)
        self._p["clips"].append(mc)
        self._picked = [mc["id"]]
        self._keep()
        self.said.emit(f"A multicam clip with {len(angles)} angles. Pick an angle (1–{len(angles)}) at the playhead to cut to it.", False)

    @Slot(str, int)
    def cutTo(self, cid: str, angle: int) -> None:
        """From the playhead on (until the next cut), show this angle."""
        c = self._c(cid)
        if not c or c.get("kind") != "multicam" or not 0 <= angle < len(c.get("angles", [])):
            return
        if not c["at"] - EPS <= self._head <= clip_end(c) + EPS:
            self.said.emit("Put the playhead over the multicam clip.", True)
            return
        tau = round(float(c["in"]) + (self._head - c["at"]) * float(c.get("speed") or 1), 3)
        self._before()
        cuts = [cut for cut in c.get("cuts", []) if abs(cut[0] - tau) > 0.04]
        cuts.append([tau, int(angle)])
        cuts.sort()
        merged = []                                              # a cut to the angle already showing does nothing
        for cut in cuts:
            if merged and merged[-1][1] == cut[1]:
                continue
            merged.append(cut)
        c["cuts"] = merged
        self._keep()

    @Slot(str, int)
    def setSoundAngle(self, cid: str, angle: int) -> None:
        c = self._c(cid)
        if c and c.get("kind") == "multicam" and 0 <= angle < len(c.get("angles", [])):
            self._before()
            c["audioAngle"] = int(angle)
            self._keep()

    @Slot(str)
    def flatten(self, cid: str) -> None:
        """A multicam clip back into ordinary clips: the cuts as they are, and its sound as a clip on an audio track."""
        c = self._c(cid)
        if not c or c.get("kind") != "multicam":
            return
        b = Builder(self._p, 320, 180)
        pieces = b.expand([c])
        sound = next((x for x in b.multicam_sound() if x["id"] == f"{cid}_sound"), None)
        self._before()
        self._p["clips"] = [x for x in self._p["clips"] if x["id"] != cid]
        for k, piece in enumerate(pieces):
            piece["id"] = f"c{self._p['next']}"
            self._p["next"] += 1
            self._p["clips"].append(piece)
        if sound is not None:
            auds = [t for t in self._p["tracks"] if t["kind"] == "audio" and fits(self._p, t["id"], sound["at"], clip_len(sound))]
            if auds:
                tid = auds[0]["id"]
            else:
                self.addTrack("audio")
                self._undo.pop()
                tid = self._p["tracks"][-1]["id"]
            for key in ("soundOnly", "heard"):
                sound.pop(key, None)
            sound.update(id=f"c{self._p['next']}", track=tid, mute=False)
            self._p["next"] += 1
            self._p["clips"].append(sound)
        self._keep()

    # ---------------------------------------------------------------- round three: following something that moves
    @Slot(str, float, float, float, float)
    def trackMotion(self, cid: str, x: float, y: float, w: float, h: float) -> None:
        """Follow the box (fractions of the picture) from the playhead to the clip's end, in the background."""
        c = self._c(cid)
        if not c or c["kind"] != "media" or media_of(self._p, c["media"]).get("kind") != "video":
            self.said.emit("Pick a video clip, then draw a box round what to follow.", True)
            return
        m = media_of(self._p, c["media"])
        start = src_of(c, max(0.0, self._head - c["at"]))
        end = float(c["out"])
        if end - start < 0.2:
            return
        if self._demo:
            boxes = [[round(start + k * 0.1, 3), round(x + 0.01 * k, 4), round(y + 0.004 * k, 4), w, h] for k in range(int((end - start) * 10))]
            self._tracked(cid, boxes)
            return
        self.said.emit("Following it…", False)
        fps, W = 10, 320
        H = max(2, int(round(W * (m.get("height") or 9) / max(1, m.get("width") or 16) / 2)) * 2)

        def work():
            try:
                raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{start:.3f}", "-i", m["path"], "-t", f"{end - start:.3f}", "-vf", f"fps={fps},scale={W}:{H}",
                                      "-f", "rawvideo", "-pix_fmt", "gray", "-"], capture_output=True, timeout=600).stdout
                frames = [np.frombuffer(raw[k:k + W * H], np.uint8).reshape(H, W) for k in range(0, len(raw) - W * H + 1, W * H)]
                path = track_box(frames, (x * W, y * H, max(4, w * W), max(4, h * H)))
                boxes = [[round(start + k / fps, 3), round(bx / W, 4), round(by / H, 4), round(bw / W, 4), round(bh / H, 4)] for k, (bx, by, bw, bh) in enumerate(path)]
            except Exception as err:                         # noqa: BLE001
                boxes = err
            self._back.emit(lambda: self._tracked(cid, boxes))
        threading.Thread(target=work, daemon=True).start()

    def _tracked(self, cid: str, boxes) -> None:
        c = self._c(cid)
        if c is None:
            return
        if isinstance(boxes, Exception) or not boxes:
            self.said.emit(f"Couldn't follow it: {boxes}", True)
            return
        self._before()
        c["tracking"] = {"boxes": boxes, "obscure": bool((c.get("tracking") or {}).get("obscure"))}
        self._keep()
        self.said.emit(f"Followed it for {boxes[-1][0] - boxes[0][0]:.1f} s. Pixelate it, or make a title or picture follow it.", False)

    @Slot(str, bool)
    def setObscure(self, cid: str, on: bool) -> None:
        c = self._c(cid)
        if c and c.get("tracking"):
            self._before()
            c["tracking"]["obscure"] = bool(on)
            self._keep()

    @Slot(str, str)
    def follow(self, follower: str, cid: str) -> None:
        """Make a title or picture (on a track above) move with the tracked thing: keyframes for its place."""
        c, f = self._c(cid), self._c(follower)
        if not c or not f or not (c.get("tracking") or {}).get("boxes"):
            return
        self._before()
        xs, ys = [], []
        for t, bx, by, bw, bh in c["tracking"]["boxes"][::2]:
            at = c["at"] + out_of(c, t) - f["at"]                      # the follower's own time
            if -EPS <= at <= clip_len(f) + EPS:
                xs.append([round(at, 3), round(bx + bw / 2 - 0.5, 4)])
                ys.append([round(at, 3), round(by + bh / 2 - 0.5, 4)])
        f.setdefault("keys", {})["x"], f["keys"]["y"] = xs, ys
        self._keep()

    @Slot(str, result=str)
    def addFollower(self, cid: str) -> str:
        """A title that follows the tracked thing, on a track above."""
        c = self._c(cid)
        if not c or not (c.get("tracking") or {}).get("boxes"):
            return ""
        b = c["tracking"]["boxes"]
        at = c["at"] + out_of(c, b[0][0])
        length = out_of(c, b[-1][0]) - out_of(c, b[0][0])
        tid = self._free_video_track(at, length)
        self._before()
        t = blank_title(f"c{self._p['next']}", tid, at, length, "Here", "lower")
        self._p["next"] += 1
        t["style"].update(place="centre", align="centre", size=40, box=True)
        self._p["clips"].append(t)
        self._undo.pop()
        self.follow(t["id"], cid)
        self._picked = [t["id"]]
        self.pickChanged.emit()
        return t["id"]

    @Slot(str)
    def clearTracking(self, cid: str) -> None:
        c = self._c(cid)
        if c and c.get("tracking"):
            self._before()
            c.pop("tracking", None)
            self._keep()

    # ---------------------------------------------------------------- round two: the mixer's meters
    def _levels(self) -> dict:
        """How loud each track is right under the playhead, 0..1 on a −60…+6 dB scale (from the sound outlines,
        so it shows while scrubbing too), after the clip's volume and the track's fader."""
        out = {}
        heard = {t["id"] for t in sounding(self._p)}
        for t in self._p["tracks"]:
            level = 0.0
            if t["id"] in heard:
                for c in on_track(self._p, t["id"]):
                    if c["kind"] != "media" or c.get("mute") or not (c["at"] <= self._head < clip_end(c)):
                        continue
                    m = media_of(self._p, c["media"])
                    wave = self._waves.get(m.get("id", ""), [])
                    if not wave or not m.get("duration"):
                        continue
                    src = src_of(c, self._head - c["at"])
                    i = int(src * len(wave) / m["duration"])
                    peak = max(wave[max(0, i - 1):i + 2] or [0]) / 1.4
                    if peak <= 0:
                        continue
                    db = 20 * math.log10(peak) + float(c.get("volume") or 0) + float(t.get("gain") or 0)
                    level = max(level, max(0.0, min(1.0, (db + 60) / 66)))
            out[t["id"]] = round(level, 3)
        return out

    levels = Property("QVariantMap", _levels, notify=frameChanged)
    eases = Property("QVariantList", lambda self: [{"id": k, "name": v} for k, v in EASES.items()], constant=True)
    anySolo = Property(bool, lambda self: any(t.get("solo") for t in self._p["tracks"]), notify=changed)
    steadying = Property("QVariantMap", lambda self: dict(self._steadying), notify=changed)
    captions = Property("QVariantList", lambda self: [{"at": a, "end": b, "text": t} for a, b, t in captions_of(self._p)], notify=changed)
    hasCaptionTrack = Property(bool, lambda self: bool(caption_track(self._p)), notify=changed)
    words = Property("QVariantMap", lambda self: {"busy": self._words["busy"], "step": self._words["step"]}, notify=changed)

    @Slot("QVariantList", result="QVariantList")
    def curveSamples(self, points) -> list:
        return curve_samples(points.toVariant() if hasattr(points, "toVariant") else points)

    @Slot(result=str)
    def speechTool(self) -> str:
        """Which speech-to-text Clips would use, in words ("" when there's none)."""
        t = whisper_tool()
        if t.get("kind") == "cli":
            return f"whisper.cpp ({Path(t['model']).stem.replace('ggml-', '')} model)"
        return "faster-whisper" if t else ""

    # ---------------------------------------------------------------- round two: steadying shaky footage
    @Slot(str, float)
    def stabilise(self, cid: str, strength: float) -> None:
        """Steady a shaky clip. The preview steadies it roughly at once; a careful two-pass copy is made in the
        background and used as soon as it's ready (by the viewer and the export)."""
        c = self._c(cid)
        if not c or c["kind"] != "media":
            return
        m = media_of(self._p, c["media"])
        if m.get("kind") != "video":
            self.said.emit("Only video can be steadied.", True)
            return
        strength = round(max(0.0, min(1.0, float(strength))), 2)
        self._before()
        c.setdefault("effects", {})["stabilise"] = strength
        self._keep()
        if strength <= 0.01 or self._demo:
            return
        out = stab_path(m["path"], strength)
        if out.is_file() or cid in self._steadying:
            return
        if not shutil.which("ffmpeg"):
            self.said.emit("Careful steadying needs ffmpeg; the quick version is used meanwhile.", True)
            return
        STAB.mkdir(parents=True, exist_ok=True)
        trf = out.with_suffix(".trf")
        part = out.with_name(out.stem + ".part.mp4")
        detect, apply = stab_commands(m["path"], str(trf), str(part), strength)
        self._steadying[cid] = 0.0
        self.changed.emit()
        dur = max(0.1, float(m.get("duration") or 1))

        def run(args, share0, share1, then):
            proc = QProcess(self)
            proc.setProcessChannelMode(QProcess.MergedChannels)
            proc.setProperty("args", args)

            def read():
                text = bytes(proc.readAllStandardOutput()).decode(errors="replace")
                got = re.findall(r"out_time_ms=(\d+)", text)
                if got and cid in self._steadying:
                    self._steadying[cid] = round(share0 + (share1 - share0) * min(1.0, int(got[-1]) / 1e6 / dur), 3)
                    self.changed.emit()
            proc.readyReadStandardOutput.connect(read)
            proc.finished.connect(lambda code, _s: then(code))
            a = list(args)
            a[1:1] = ["-progress", "pipe:1", "-nostats"]
            proc.start(a[0], a[1:])

        def after_detect(code):
            if code != 0 or not trf.is_file():
                return failed()
            run(apply, 0.5, 1.0, after_apply)

        def after_apply(code):
            if code != 0 or not part.is_file() or part.stat().st_size == 0:
                return failed()
            os.replace(part, out)
            trf.unlink(missing_ok=True)
            self._steadying.pop(cid, None)
            self._dirty_xml = True
            self.said.emit(f"{m.get('name', 'The clip')} is steadied.", False)
            self.changed.emit()
            self._show_frame()

        def failed():
            self._steadying.pop(cid, None)
            part.unlink(missing_ok=True)
            self.said.emit("Couldn't steady it carefully (ffmpeg needs vid.stab); the quick version stays on.", True)
            self.changed.emit()
        run(detect, 0.0, 0.5, after_detect)

    # ---------------------------------------------------------------- round two: captions
    def _caption_track(self) -> str:
        t = caption_track(self._p)
        if t:
            return t["id"]
        tid = f"cap{self._p['next']}"
        self._p["next"] += 1
        self._p["tracks"].insert(0, {"id": tid, "kind": "video", "name": "Captions", "role": "captions", "hidden": False, "locked": False})
        return tid

    def _put_captions(self, items: list, replace: bool) -> int:
        tid = self._caption_track()
        if replace:
            self._p["clips"] = [c for c in self._p["clips"] if c["track"] != tid]
        n = 0
        for a, b, text in items:
            if b - a < 0.2 or not fits(self._p, tid, a, b - a):
                continue
            c = blank_title(f"c{self._p['next']}", tid, a, b - a, text, "caption")
            c["fadeIn"] = c["fadeOut"] = 0.0
            self._p["next"] += 1
            self._p["clips"].append(c)
            n += 1
        return n

    @Slot(result=str)
    def addCaption(self) -> str:
        """A new caption at the playhead, on the captions track (made when it isn't there yet)."""
        self._before()
        tid = self._caption_track()
        length = 2.5
        while length > 0.4 and not fits(self._p, tid, self._head, length):
            length -= 0.5
        if length <= 0.4:
            self._undo.pop()
            return "There's already a caption here."
        c = blank_title(f"c{self._p['next']}", tid, self._head, length, "What's being said", "caption")
        c["fadeIn"] = c["fadeOut"] = 0.0
        self._p["next"] += 1
        self._p["clips"].append(c)
        self._picked = [c["id"]]
        self._keep()
        return ""

    @Slot(result="QVariantList")
    def captionFiles(self) -> list:
        found, seen = [], set()
        for base in (Path.home() / "Videos", Path.home() / "Downloads", Path.home() / "Documents", Path.home() / "Desktop"):
            if not base.is_dir():
                continue
            for q in sorted(list(base.rglob("*.srt"))[:40] + list(base.rglob("*.vtt"))[:40], key=lambda q: -q.stat().st_mtime):
                if str(q) not in seen:
                    seen.add(str(q))
                    found.append({"path": str(q), "name": q.name, "where": str(q.parent).replace(str(Path.home()), "~")})
        return found[:60]

    @Slot(str, bool, result=str)
    def importCaptions(self, path: str, replace: bool = True) -> str:
        """Captions from an .srt or .vtt file onto the captions track. "" when done, else why not."""
        path = QUrl(path).toLocalFile() if path.startswith("file:") else path
        try:
            items = parse_captions(Path(path).read_text(encoding="utf-8", errors="replace"))
        except OSError as e:
            return f"Couldn't read it: {e.strerror or e}"
        if not items:
            return "No captions in that file."
        self._before()
        n = self._put_captions(items, replace)
        self._keep()
        self.said.emit(f"{n} caption{'s' if n != 1 else ''} from {Path(path).name}", False)
        return ""

    @Slot(str, result=str)
    def exportCaptions(self, kind: str) -> str:
        """The captions as a .srt or .vtt file in Videos/Clips. The path, or "" when there are none."""
        items = captions_of(self._p)
        if not items:
            self.said.emit("There are no captions yet.", True)
            return ""
        target = self._target(".vtt" if kind == "vtt" else ".srt")
        try:
            target.write_text(to_vtt(items) if kind == "vtt" else to_srt(items), encoding="utf-8")
        except OSError as e:
            self.said.emit(f"Couldn't save them: {e.strerror or e}", True)
            return ""
        self.said.emit(f"Saved {target.name} in Videos/Clips", False)
        return str(target)

    @Slot(str)
    def transcribe(self, language: str = "") -> None:
        """Captions from what's said: the film's sound, mixed down, through whisper (whisper.cpp or
        faster-whisper), all on this computer."""
        if self._words["busy"]:
            return
        if self._demo:
            self._before()
            self._put_captions([(7.2, 9.6, "We left Tromsø before it was light"), (9.8, 12.4, "and the harbour was still asleep."),
                                (12.8, 15.6, "By noon the market was full.")], True)
            self._keep()
            return
        tool = whisper_tool()
        if not tool:
            self.said.emit("Speech to text needs whisper.cpp with a model, or the faster-whisper package.", True)
            return
        if not shutil.which("melt") or not self._p["clips"]:
            self.said.emit("There's nothing to listen to yet." if shutil.which("melt") else "Listening needs melt (MLT).", True)
            return
        work = CACHE / "words"
        work.mkdir(parents=True, exist_ok=True)
        (work / "sound.mlt").write_text(self._xml(320, 180, export=True), encoding="utf-8")
        wav, base = work / "sound.wav", work / "words"
        for f in (wav, base.with_suffix(".srt")):
            f.unlink(missing_ok=True)
        steps = [("Listening to the film…", ["melt", str(work / "sound.mlt"), "-consumer", f"avformat:{wav}", "vn=1", "ar=16000", "ac=1", "acodec=pcm_s16le"]),
                 ("Writing down what's said…", whisper_command(tool, str(wav), str(base), language))]
        self._words.update(busy=True, step=steps[0][0])
        self.changed.emit()

        def next_step(k):
            if k >= len(steps):
                return finish()
            self._words["step"] = steps[k][0]
            self.changed.emit()
            proc = QProcess(self)
            proc.setProcessChannelMode(QProcess.MergedChannels)
            proc.setWorkingDirectory(str(work))
            self._words["proc"] = proc
            proc.finished.connect(lambda code, _s: next_step(k + 1) if code == 0 else fail(bytes(proc.readAll()).decode(errors="replace")))
            proc.start(steps[k][1][0], steps[k][1][1:])

        def fail(log):
            self._words.update(busy=False, step="", proc=None)
            last = [l for l in log.splitlines() if l.strip()][-1:] or ["it stopped"]
            self.said.emit("Couldn't write the captions: " + last[0][:140], True)
            self.changed.emit()

        def finish():
            self._words.update(busy=False, step="", proc=None)
            try:
                items = parse_captions(base.with_suffix(".srt").read_text(encoding="utf-8", errors="replace"))
            except OSError:
                items = []
            if not items:
                self.said.emit("No speech was heard.", True)
                self.changed.emit()
                return
            self._before()
            n = self._put_captions(items, True)
            self._keep()
            self.said.emit(f"{n} caption{'s' if n != 1 else ''} written. Check them: they can mishear names.", False)
        next_step(0)

    @Slot()
    def stopTranscribing(self) -> None:
        proc = self._words.get("proc")
        if proc is not None:
            proc.finished.disconnect()
            proc.kill()
        self._words.update(busy=False, step="", proc=None)
        self.changed.emit()

    # ---------------------------------------------------------------- making the video
    def _target(self, ext: str) -> Path:
        folder = Path(QStandardPaths.writableLocation(QStandardPaths.MoviesLocation) or Path.home() / "Videos") / "Clips"
        folder.mkdir(parents=True, exist_ok=True)
        base = re.sub(r"[\\/:*?\"<>|]+", " ", self._p.get("name") or "My Movie").strip() or "My Movie"
        out, n = folder / f"{base}{ext}", 2
        while out.exists():
            out, n = folder / f"{base} {n}{ext}", n + 1
        return out

    @Slot(str, str, str)
    def export(self, preset: str, quality: str, size: str) -> None:
        if preset not in PRESETS or self._export["busy"] or not self._p["clips"]:
            return
        if self._demo:
            self.said.emit("Making the video (demo)", False)
            return
        if not shutil.which("melt"):
            self.said.emit("Making the video needs melt (MLT's command line tool).", True)
            return
        missing = [m["name"] for m in self._p["media"] if m["kind"] != "title" and not Path(m["path"]).exists() and any(c.get("media") == m["id"] for c in self._p["clips"])]
        if missing:
            self.said.emit(f"{missing[0]} isn't where it was.", True)
            return
        W, H = SIZES.get(self._p.get("size"), SIZES["1080p"])[:2]
        if size in SIZES:
            W, H = SIZES[size][:2]
        elif size == "half":
            W, H = W // 2 // 2 * 2, H // 2 // 2 * 2
        target = self._target(PRESETS[preset]["ext"])
        part = target.with_name(f".{target.stem}.part{target.suffix}")
        work = CACHE / "export"
        work.mkdir(parents=True, exist_ok=True)
        (work / "project.mlt").write_text(self._xml(W, H, export=True), encoding="utf-8")
        args = export_command(str(work / "project.mlt"), str(part), preset, quality, W, H, int(self._p.get("fps", 30)))
        proc = QProcess(self)
        proc.setProcessChannelMode(QProcess.MergedChannels)
        self._export.update(busy=True, share=0.0, path="", proc=proc, target=str(target), part=str(part), log="")

        def read():
            text = bytes(proc.readAllStandardOutput()).decode(errors="replace")
            self._export["log"] = (self._export["log"] + text)[-4000:]
            got = re.findall(r"percentage:\s*(\d+)", text)
            if got:
                self._export["share"] = min(0.99, int(got[-1]) / 100)
                self.changed.emit()

        def finished(code, _status):
            self._export.update(busy=False, proc=None)
            if code == 0 and Path(part).exists() and Path(part).stat().st_size > 0:
                os.replace(part, target)
                self._export.update(share=1.0, path=str(target))
                items = captions_of(self._p)
                if items:                                   # the captions go alongside, for players and video sites
                    try:
                        target.with_suffix(".srt").write_text(to_srt(items), encoding="utf-8")
                    except OSError:
                        pass
                self.said.emit(f"Saved {target.name} in Videos/Clips" + (" with its captions (.srt)" if items else ""), False)
            else:
                Path(part).unlink(missing_ok=True)
                if not self._export.get("stopped"):
                    last = [l for l in self._export.get("log", "").splitlines() if l.strip() and "percentage" not in l][-1:] or ["it stopped"]
                    self.said.emit("The video couldn't be made: " + last[0][:160], True)
            self._export["stopped"] = False
            self.changed.emit()
        proc.readyReadStandardOutput.connect(read)
        proc.finished.connect(finished)
        proc.start(args[0], args[1:])
        self.changed.emit()

    @Slot()
    def stopExport(self) -> None:
        proc = self._export.get("proc")
        if proc is not None:
            self._export["stopped"] = True
            proc.kill()
            self.said.emit("Stopped.", False)

    @Slot()
    def showExported(self) -> None:
        import sys
        if self._export["path"]:
            QProcess.startDetached(sys.executable, [str(HERE / "huginn_app.py"), "files", str(Path(self._export["path"]).parent)])

    @Slot(result=str)
    def mltProject(self) -> str:
        """The project as MLT XML at full size (for Shotcut or Kdenlive, or for checking)."""
        W, H = SIZES.get(self._p.get("size"), SIZES["1080p"])[:2]
        return self._xml(W, H, export=True)

    @Slot(result=str)
    def saveMlt(self) -> str:
        """Save the project as an .mlt file beside the videos, which Shotcut opens too."""
        target = self._target(".mlt")
        try:
            target.write_text(self.mltProject(), encoding="utf-8")
        except OSError as e:
            return f"Couldn't save it: {e.strerror or e}"
        self.said.emit(f"Saved {target.name} in Videos/Clips (Shotcut opens it too)", False)
        return ""

    # ---------------------------------------------------------------- round four: speed ramps and holds
    def _grow(self, c: dict, change: dict) -> bool:
        """Change a clip's timing. When it gets longer than the room after it, what follows on its track moves along."""
        old_len, old_end = clip_len(c), clip_end(c)
        new_len = clip_len(dict(c, **change))
        self._before()
        c.update(change)
        if new_len > old_len + EPS and not fits(self._p, c["track"], c["at"], new_len, ignore=c["id"]):
            for o in self._p["clips"]:
                if o["track"] == c["track"] and o["id"] != c["id"] and o["at"] >= old_end - EPS:
                    o["at"] = round(o["at"] + new_len - old_len, 4)
            self.said.emit("What came after it on the track moved along to make room.", False)
        self._keep()
        return True

    def _rampable(self, cid: str):
        c = self._c(cid)
        if not c or c.get("kind") != "media" or media_of(self._p, c.get("media", "")).get("kind") != "video":
            return None
        return c

    @Slot(str, result=int)
    def splitSpeed(self, cid: str) -> int:
        """A new stretch of speed from the playhead on, at the speed it already had; returns its number."""
        c = self._rampable(cid)
        if not c:
            return -1
        u = self._head - c["at"]
        if u <= 0.05 or u >= clip_len(c) - 0.05:
            self.said.emit("Put the playhead inside the clip, where the speed should change.", True)
            return -1
        s = round(src_of(c, u), 4)
        r = Remap(c)
        k = max(i for i, x in enumerate(r.starts) if x <= s + 1e-9)
        pts = sorted([p for p in (c.get("ramp") or []) if abs(float(p[0]) - s) > 0.02] + [[s, r.speeds[k]]])
        self._before()
        c["ramp"] = pts
        c.setdefault("rampSmooth", True)
        self._keep()
        return 1 + [p[0] for p in pts].index(s)

    @Slot(str, int, float)
    def setSegmentSpeed(self, cid: str, k: int, speed: float) -> None:
        """Speed of one stretch (0: from the clip's start, or the whole clip when it has no ramp)."""
        c = self._rampable(cid)
        if not c:
            return
        speed = max(0.1, min(16.0, float(speed)))
        if k <= 0:
            self._grow(c, {"speed": speed})
            return
        pts = copy.deepcopy(sorted(c.get("ramp") or []))
        if k - 1 >= len(pts):
            return
        pts[k - 1][1] = speed
        self._grow(c, {"ramp": pts})

    @Slot(str, int)
    def removeSpeedChange(self, cid: str, k: int) -> None:
        """Take away where stretch k starts: it goes at the speed before it."""
        c = self._rampable(cid)
        pts = sorted((c or {}).get("ramp") or [])
        if c and 1 <= k <= len(pts):
            self._grow(c, {"ramp": pts[:k - 1] + pts[k:]})

    @Slot(str)
    def holdFrame(self, cid: str) -> None:
        """Hold the picture under the playhead for two seconds (longer if there's one there already)."""
        c = self._rampable(cid)
        if not c:
            return
        u = self._head - c["at"]
        if u < 0 or u > clip_len(c):
            self.said.emit("Put the playhead on the picture to hold.", True)
            return
        s = round(min(src_of(c, u), float(c["out"]) - 0.5 / int(self._p.get("fps", 30))), 4)
        holds = copy.deepcopy(c.get("holds") or [])
        near = next((h for h in holds if abs(float(h[0]) - s) < 0.02), None)
        if near:
            near[1] = round(float(near[1]) + HOLD_LENGTH, 3)
        else:
            holds.append([s, HOLD_LENGTH])
        self._grow(c, {"holds": sorted(holds)})

    @Slot(str, int, float)
    def setHold(self, cid: str, k: int, seconds: float) -> None:
        c = self._rampable(cid)
        holds = copy.deepcopy(sorted((c or {}).get("holds") or []))
        if not c or not 0 <= k < len(holds):
            return
        if seconds < 0.05:
            del holds[k]
        else:
            holds[k][1] = round(min(60.0, float(seconds)), 3)
        self._grow(c, {"holds": holds})

    @Slot(str)
    def clearRamp(self, cid: str) -> None:
        c = self._c(cid)
        if c and (c.get("ramp") or c.get("holds")):
            self._grow(c, {"ramp": [], "holds": []})

    def _ramp_view(self, c: dict) -> dict:
        """The Speed tab's view of a clip: its stretches and held frames, in seconds into the clip."""
        r = Remap(c)
        lo, hi = float(c["in"]), float(c["out"])
        segs, here = [], 0
        u = self._head - c["at"]
        for k, start in enumerate(r.starts):
            end = r.starts[k + 1] if k + 1 < len(r.starts) else 1e9
            if end <= lo or start >= hi:
                continue
            a, b = out_of(c, max(start, lo)), out_of(c, min(end, hi))
            segs.append({"k": k, "from": round(a, 3), "to": round(b, 3), "speed": r.speeds[k]})
            if a - EPS <= u:
                here = k
        holds = [{"k": k, "at": round(out_of(c, float(h)), 3), "length": float(d)} for k, (h, d) in enumerate(sorted(c.get("holds") or []))
                 if lo - 1e-6 <= float(h) < hi]
        return {"segments": segs, "holdsView": holds, "segmentHere": here, "ramped": ramped(c), "rampSmooth": c.get("rampSmooth", True)}

    # ---------------------------------------------------------------- round four: keying and shapes
    def _clip_point(self, c: dict, fx: float, fy: float) -> tuple:
        """A point on the film's picture (fractions) as a point on the clip's own picture, undoing its size and place."""
        tr = c.get("transform") or {}
        s = max(0.05, float(tr.get("scale", 1.0)))
        return (max(0.0, min(1.0, (fx - 0.5 - float(tr.get("x", 0))) / s + 0.5)), max(0.0, min(1.0, (fy - 0.5 - float(tr.get("y", 0))) / s + 0.5)))

    def _keyable(self, cid: str):
        c = self._c(cid)
        if not c or c.get("kind") != "media" or media_of(self._p, c.get("media", "")).get("kind") not in ("video", "image"):
            return None
        return c

    def _set_key(self, cid: str, colour: str) -> None:
        c = self._c(cid)
        if not c:
            return
        self._before()
        key = c.setdefault("key", {})
        key.update(on=True, colour=colour)
        for k, v in (("strength", 0.35), ("soft", 0.2), ("spill", 0.5)):
            key.setdefault(k, v)
        self._keep()
        self.said.emit(f"Keyed out {'blue' if key_hue(colour) == 'blue' else 'green'} ({colour}).", False)

    @Slot(str)
    def findKey(self, cid: str) -> None:
        """Find the screen's colour in the picture under the playhead and key it out."""
        c = self._keyable(cid)
        if not c:
            return
        if self._demo:
            self._set_key(cid, "#1EC828")
            return
        m = media_of(self._p, c["media"])
        at = src_of(c, max(0.0, min(clip_len(c), self._head - c["at"])))

        def work():
            colour = screen_colour(frame_of(m["path"], at if m.get("kind") == "video" else 0))
            self._back.emit(lambda: self._set_key(cid, colour) if colour else self.said.emit("No green or blue screen found in this picture: pick its colour instead.", True))
        threading.Thread(target=work, daemon=True).start()

    @Slot(str, float, float)
    def pickKeyColour(self, cid: str, fx: float, fy: float) -> None:
        """Key out the colour at a point of the picture (a small patch's middle, so noise doesn't decide)."""
        c = self._keyable(cid)
        if not c:
            return
        if self._demo:
            self._set_key(cid, "#1EC828")
            return
        m = media_of(self._p, c["media"])
        at = src_of(c, max(0.0, min(clip_len(c), self._head - c["at"])))
        px, py = self._clip_point(c, fx, fy)

        def work():
            f = frame_of(m["path"], at if m.get("kind") == "video" else 0)
            colour = ""
            if f.size:
                h, w = f.shape[:2]
                x, y = int(px * (w - 1)), int(py * (h - 1))
                patch = f[max(0, y - 3):y + 4, max(0, x - 3):x + 4].reshape(-1, 3)
                colour = "#%02X%02X%02X" % tuple(int(v) for v in np.median(patch, axis=0))
            self._back.emit(lambda: self._set_key(cid, colour) if colour else self.said.emit("Couldn't read the picture there.", True))
        threading.Thread(target=work, daemon=True).start()

    @Slot(str, bool)
    def showMatte(self, cid: str, on: bool) -> None:
        self._matte = cid if on else ""
        self._dirty_xml = True
        self.changed.emit()
        self._show_frame()

    @Slot(str, bool)
    def setShape(self, cid: str, on: bool) -> None:
        c = self._keyable(cid) or (self._c(cid) if (self._c(cid) or {}).get("kind") == "compound" else None)
        if not c:
            return
        self._before()
        sh = c.setdefault("shape", {})
        for k, v in (("kind", "oval"), ("x", 0.5), ("y", 0.5), ("w", 0.5), ("h", 0.6), ("soft", 0.15), ("use", "cut"), ("invert", False)):
            sh.setdefault(k, v)
        sh["on"] = bool(on)
        self._keep()

    @Slot(str, float, float, float, float)
    def placeShape(self, cid: str, x: float, y: float, w: float, h: float) -> None:
        """Where the shape is and how big (fractions of the clip's picture), from dragging it in the viewer."""
        c = self._c(cid)
        if not c or not c.get("shape"):
            return
        self._before()
        sh = c["shape"]
        sh.update(x=round(max(0.0, min(1.0, x)), 4), y=round(max(0.0, min(1.0, y)), 4), w=round(max(0.02, min(2.0, w)), 4), h=round(max(0.02, min(2.0, h)), 4))
        if sh.get("follow"):
            self._anchor_shape(c)
        self._keep()

    def _anchor_shape(self, c: dict) -> None:
        """Remember how far the shape is from the tracked thing, as seen at the playhead."""
        boxes = (c.get("tracking") or {}).get("boxes") or []
        if not boxes:
            return
        tau = src_of(c, self._head - c["at"])
        b = min(boxes, key=lambda q: abs(q[0] - tau))
        sh = c["shape"]
        sh["dx"], sh["dy"] = round(float(sh.get("x", 0.5)) - (b[1] + b[3] / 2), 4), round(float(sh.get("y", 0.5)) - (b[2] + b[4] / 2), 4)

    @Slot(str, bool)
    def followShape(self, cid: str, on: bool) -> None:
        c = self._c(cid)
        if not c or not c.get("shape"):
            return
        if on and not (c.get("tracking") or {}).get("boxes"):
            self.said.emit("Follow something first (Effects), then the shape can go with it.", True)
            return
        self._before()
        c["shape"]["follow"] = bool(on)
        if on:
            self._anchor_shape(c)
        self._keep()

    def _shape_now(self) -> dict:
        """The picked clip's shape as it is under the playhead (where it's followed to), for the viewer."""
        c = self._c(self._picked[0]) if len(self._picked) == 1 else None
        sh = dict((c or {}).get("shape") or {})
        if not sh.get("on"):
            return {}
        boxes = (c.get("tracking") or {}).get("boxes") or []
        if sh.get("follow") and boxes and "dx" in sh:
            tau = src_of(c, self._head - c["at"])
            b = min(boxes, key=lambda q: abs(q[0] - tau))
            sh["x"], sh["y"] = b[1] + b[3] / 2 + float(sh["dx"]), b[2] + b[4] / 2 + float(sh["dy"])
        return sh

    shapeNow = Property("QVariantMap", _shape_now, notify=frameChanged)
    matte = Property(str, lambda self: self._matte, notify=changed)
    speedChoices = Property("QVariantList", lambda self: SPEED_CHOICES, constant=True)
    shapes = Property("QVariantList", lambda self: [{"id": k, "name": v[0]} for k, v in SHAPES.items()], constant=True)

    # ---------------------------------------------------------------- round four: compound clips
    def _sync(self) -> None:
        """Put what's being edited inside a compound clip back into it, then let each compound clip on the way out
        follow its insides' length (unless its end was trimmed), moving what comes after it along if it grew."""
        if not self._path:
            self._root = self._p
            return
        level, chain = self._root, []
        for cid in self._path:
            c = next((x for x in level["clips"] if x["id"] == cid), None)
            if c is None:
                break
            chain.append((level, c))
            level = inner_view(self._root, c)
        if len(chain) != len(self._path):
            return
        _, deepest = chain[-1]
        deepest["inner"] = {"tracks": self._p["tracks"], "clips": self._p["clips"], "markers": self._p["markers"]}
        if self._p.get("name") and self._p["name"] != deepest.get("name"):     # renamed from inside
            deepest["name"] = self._p["name"]
        for k, v in self._p.items():                       # media, bins, settings and the id counter are the film's
            if k not in ("tracks", "clips", "markers", "name"):
                self._root[k] = v
        for container, c in reversed(chain):
            was, now = float(c.get("innerLength", c["out"])), total(inner_view(self._root, c))
            if abs(now - was) < 1e-4:
                continue
            old_len, old_end = clip_len(c), clip_end(c)
            c["out"] = round(now if abs(float(c["out"]) - was) < 1e-3 else min(float(c["out"]), now), 4)
            c["in"] = round(max(0.0, min(float(c["in"]), float(c["out"]) - 0.1)), 4)
            c["innerLength"] = round(now, 4)
            grow = clip_len(c) - old_len
            if grow > EPS and not fits(container, c["track"], c["at"], clip_len(c), ignore=c["id"]):
                for o in container["clips"]:
                    if o["track"] == c["track"] and o["id"] != c["id"] and o["at"] >= old_end - EPS:
                        o["at"] = round(o["at"] + grow, 4)

    def _view(self) -> None:
        """Make self._p the level being edited: the film, or the insides of the compound clips on the path."""
        p, path = self._root, []
        for cid in self._path:
            c = next((x for x in p["clips"] if x["id"] == cid and x.get("kind") == "compound"), None)
            if c is None:
                break
            path.append(cid)
            p = inner_view(self._root, c)
        self._path, self._p = path, p

    @Slot(result=str)
    def makeCompound(self) -> str:
        """The picked clips become one compound clip, which can be opened and edited like a film of its own."""
        picked = [c for c in self._p["clips"] if c["id"] in self._picked]
        if not picked:
            return "Pick the clips to put together first."
        if any(track_of(self._p, c["track"]).get("locked") for c in picked):
            return "Some of them are on a locked track."
        start = min(c["at"] for c in picked)
        end = max(clip_end(c) for c in picked)
        used = {c["track"] for c in picked}
        tracks = [copy.deepcopy(t) for t in self._p["tracks"] if t["id"] in used]
        for t in tracks:
            t["locked"] = False
        vids = [t for t in tracks if t["kind"] == "video" and t.get("role") != "captions"]
        target = vids[-1]["id"] if vids else tracks[0]["id"]            # the lowest picture track it came from
        self._before()
        inner_clips = []
        for c in picked:
            x = copy.deepcopy(c)
            x["at"] = round(c["at"] - start, 4)
            inner_clips.append(x)
        self._p["clips"] = [c for c in self._p["clips"] if c["id"] not in self._picked]
        n = sum(1 for c in self._p["clips"] if c.get("kind") == "compound") + 1
        comp = blank_clip(f"c{self._p['next']}", "", target, start, 0.0, end - start)
        self._p["next"] += 1
        comp.update(kind="compound", name=f"Compound clip {n}", inner={"tracks": tracks, "clips": inner_clips, "markers": []}, innerLength=round(end - start, 4))
        comp.pop("media", None)
        if not fits(self._p, target, start, end - start):
            if compound_content(comp) == "video":
                target = self._free_video_track(start, end - start, above=target)
            else:
                self._p["clips"] += picked
                self._undo.pop()
                return "There's something else on that track meanwhile: pick it too, or move it."
        comp["track"] = target
        self._p["clips"].append(comp)
        self._picked = [comp["id"]]
        self._keep()
        return ""

    @Slot(str)
    def openCompound(self, cid: str) -> None:
        c = self._c(cid)
        if not c or c.get("kind") != "compound":
            return
        self.pause()
        self._sync()
        self._head = max(0.0, self._head - c["at"] + float(c["in"]))
        self._path.append(cid)
        self._view()
        self._picked = []
        self._matte = ""
        self._keep(False)

    @Slot()
    def closeCompound(self) -> None:
        if not self._path:
            return
        self.pause()
        self._sync()
        cid = self._path.pop()
        self._view()
        c = self._c(cid)
        if c:
            self._head = max(0.0, c["at"] + self._head - float(c["in"]))
            self._picked = [cid]
        self._keep(False)

    @Slot(str)
    def breakApart(self, cid: str) -> None:
        """A compound clip back into its clips, on the tracks they came from (or free ones), trimmed as it was."""
        c = self._c(cid)
        if not c or c.get("kind") != "compound":
            return
        inside = copy.deepcopy(inner_view(self._root, c))
        inside["next"] = self._p["next"]
        lo, hi = float(c["in"]), float(c["out"])
        blade(inside, lo)
        blade(inside, hi)
        keep = [x for x in inside["clips"] if x["at"] >= lo - 1e-3 and clip_end(x) <= hi + 1e-3]
        self._before()
        self._p["next"] = inside["next"]
        self._p["clips"] = [x for x in self._p["clips"] if x["id"] != cid]
        made = []
        for x in sorted(keep, key=lambda q: q["at"]):
            kind = track_of(inside, x["track"]).get("kind", "video")
            x["at"] = round(c["at"] + x["at"] - lo, 4)
            x["id"] = f"c{self._p['next']}"
            self._p["next"] += 1
            ours = track_of(self._p, x["track"])
            if not (ours and ours["kind"] == kind and not ours.get("locked") and fits(self._p, ours["id"], x["at"], clip_len(x))):
                if kind == "video":
                    x["track"] = self._free_video_track(x["at"], clip_len(x), above="")
                else:
                    free = next((t["id"] for t in self._p["tracks"] if t["kind"] == "audio" and not t.get("locked") and fits(self._p, t["id"], x["at"], clip_len(x))), "")
                    if not free:
                        free = f"a{sum(1 for t in self._p['tracks'] if t['kind'] == 'audio') + 1}x{self._p['next']}"
                        self._p["next"] += 1
                        self._p["tracks"].append({"id": free, "kind": "audio", "name": "Sound", "role": "", "muted": False, "locked": False})
                    x["track"] = free
            self._p["clips"].append(x)
            made.append(x["id"])
        for mk in inside.get("markers") or []:
            if lo <= mk["t"] <= hi:
                self._p["markers"].append(dict(mk, t=round(c["at"] + mk["t"] - lo, 3)))
        self._picked = made
        self._keep()

    path = Property("QVariantList", lambda self: [{"id": "", "name": self._root.get("name") or "Film"}] + [{"id": cid, "name": n} for cid, n in self._path_names()], notify=changed)
    inside = Property(bool, lambda self: bool(self._path), notify=changed)

    def _path_names(self) -> list:
        out, p = [], self._root
        for cid in self._path:
            c = next((x for x in p["clips"] if x["id"] == cid), None)
            if not c:
                break
            out.append((cid, c.get("name") or "Compound clip"))
            p = inner_view(self._root, c)
        return out

    # ---------------------------------------------------------------- round four: shots, beats, matching colour
    @Slot(str)
    def cutAtShots(self, cid: str) -> None:
        """Find where the footage cuts to another shot and cut the clip there (a long recording, a finished film)."""
        c = self._c(cid)
        m = media_of(self._p, (c or {}).get("media", ""))
        if not c or c.get("kind") != "media" or m.get("kind") != "video":
            self.said.emit("Pick a video clip to find its shots.", True)
            return
        lo, hi = float(c["in"]), float(c["out"])
        if self._demo:
            self._shots_found(cid, [lo + (hi - lo) * k / 3 for k in (1, 2)])
            return
        self.said.emit("Looking for the shots…", False)

        def work():
            found, at = [], lo
            while at < hi:                                  # two minutes at a time, a second overlapping
                frames, times = frames_between(m["path"], max(lo, at - 1.0), min(hi, at + 120.0), 48)
                found += [t for t in shot_changes(frames, times) if not found or t - found[-1] > 0.3]
                at += 120.0
            self._back.emit(lambda: self._shots_found(cid, found))
        threading.Thread(target=work, daemon=True).start()

    def _shots_found(self, cid: str, cuts: list) -> None:
        c = self._c(cid)
        if not c:
            return
        times = sorted({round(c["at"] + out_of(c, s), 3) for s in cuts if float(c["in"]) < s < float(c["out"])})
        times = [t for t in times if c["at"] + 0.1 < t < clip_end(c) - 0.1]
        if not times:
            self.said.emit("It's one shot all the way through: nothing to cut.", False)
            return
        self._before()
        for t in reversed(times):
            blade(self._p, t, [cid])
        self._keep()
        self.said.emit(f"Cut into {len(times) + 1} shots.", False)

    @Slot(str)
    def markBeats(self, cid: str) -> None:
        """Mark the beat of a clip's music along the timeline, so cuts can snap to it."""
        c = self._c(cid)
        m = media_of(self._p, (c or {}).get("media", ""))
        if not c or c.get("kind") != "media" or not m.get("audio"):
            self.said.emit("Pick a clip with music in it.", True)
            return
        lo, hi = float(c["in"]), float(c["out"])
        if self._demo:
            self._beats_found(cid, 120.0, [lo + 0.5 * k for k in range(int((hi - lo) * 2))])
            return
        self.said.emit("Listening for the beat…", False)

        def work():
            rate = 11025
            try:
                raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{lo:.3f}", "-i", m["path"], "-t", f"{hi - lo:.3f}", "-vn", "-ac", "1", "-ar", str(rate),
                                      "-f", "s16le", "-"], capture_output=True, timeout=600).stdout
                bpm, beats = beat_times(np.frombuffer(raw[:len(raw) // 2 * 2], np.int16), rate)
            except (OSError, subprocess.SubprocessError):
                bpm, beats = 0.0, []
            self._back.emit(lambda: self._beats_found(cid, bpm, [lo + b for b in beats]))
        threading.Thread(target=work, daemon=True).start()

    def _beats_found(self, cid: str, bpm: float, beats: list) -> None:
        c = self._c(cid)
        if not c:
            return
        if not beats:
            self.said.emit("Couldn't hear a steady beat in it.", True)
            return
        self._before()
        c["beats"], c["bpm"] = [round(float(b), 3) for b in beats], bpm      # in the footage's own time: they go where the clip goes
        self._keep()
        n = sum(1 for b in beats if float(c["in"]) <= b < float(c["out"]))
        self.said.emit(f"{bpm:g} beats a minute: {n} beats marked. Cuts and clips snap to them.", False)

    @Slot(str)
    def clearBeats(self, cid: str) -> None:
        c = self._c(cid)
        if c and c.get("beats"):
            self._before()
            c.pop("beats", None)
            c.pop("bpm", None)
            self._keep()

    def _sample_frames(self, c: dict, n: int = 6) -> np.ndarray:
        m = media_of(self._p, c.get("media", ""))
        if m.get("kind") == "image":
            f = frame_of(m["path"], 0, 128)
            return f[None] if f.size else np.zeros((0, 2, 2, 3), np.uint8)
        lo, hi = float(c["in"]), float(c["out"])
        frames, _ = frames_between(m["path"], lo, hi, 128, fps=max(0.2, n / max(0.2, hi - lo)))
        return frames

    @Slot(str, str)
    def matchColour(self, cid: str, ref: str) -> None:
        """Make a clip's colours sit like another shot's (its lightness and colour, average and spread)."""
        c, r = self._c(cid), self._c(ref)
        if not c or not r or cid == ref:
            return
        if any(x.get("kind") != "media" or media_of(self._p, x.get("media", "")).get("kind") not in ("video", "image") for x in (c, r)):
            self.said.emit("Both need to be pictures.", True)
            return
        if self._demo:
            self._matched(cid, ref, "")
            return
        self.said.emit("Matching the colour…", False)
        target = CACHE / "matched" / f"{cid}-{hashlib.sha1(json.dumps([c.get('media'), c['in'], c['out'], r.get('media'), r['in'], r['out']]).encode()).hexdigest()[:10]}.cube"

        def work():
            a, b = self._sample_frames(c), self._sample_frames(r)
            path = match_cube(colour_stats(a), colour_stats(b), str(target)) if len(a) and len(b) else ""
            self._back.emit(lambda: self._matched(cid, ref, path))
        threading.Thread(target=work, daemon=True).start()

    def _matched(self, cid: str, ref: str, path: str) -> None:
        c, r = self._c(cid), self._c(ref)
        if not c:
            return
        if not path and not self._demo:
            self.said.emit("Couldn't read the pictures to match.", True)
            return
        self._before()
        c.setdefault("colour", {}).update(match=path, matchTo=ref)
        self._keep()
        self.said.emit(f"Matched to {media_of(self._p, (r or {}).get('media', '')).get('name', 'the other shot')}. Grade on top of it as usual.", False)

    @Slot(str)
    def clearMatch(self, cid: str) -> None:
        c = self._c(cid)
        if c and (c.get("colour") or {}).get("match") is not None:
            self._before()
            c["colour"].pop("match", None)
            c["colour"].pop("matchTo", None)
            self._keep()

    def _others(self, c: dict) -> list:
        """Other picture clips to match this one to, nearest first."""
        out = [x for x in self._p["clips"] if x["id"] != c["id"] and x.get("kind") == "media" and media_of(self._p, x.get("media", "")).get("kind") in ("video", "image")]
        out.sort(key=lambda x: abs(x["at"] - c["at"]))
        return [{"id": x["id"], "name": media_of(self._p, x["media"]).get("name", ""), "at": clock(x["at"])} for x in out[:8]]

    def leaving(self) -> None:
        self._engine.stop()
        proc = self._export.get("proc")
        if proc is not None:
            proc.kill()
