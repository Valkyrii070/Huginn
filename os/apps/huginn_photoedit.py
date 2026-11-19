"""Editing in Photos: crop, straighten, turn and flip; light; colour; detail; and filters.

Edits never wear a picture down. The first time a picture is edited its original is put aside in
~/.local/share/huginn/photos/originals, and the edit itself is kept as a handful of numbers in photos.json; the file
you see in Pictures is the original with those numbers applied. Editing again starts from the original with the
numbers as they were, and "Revert to Original" puts the original back.

The picture on screen while you edit is a smaller copy, worked out in a moment; Done applies the same numbers to the
full-size original (numpy and Pillow do the work).
"""
import hashlib
import json
import math
import os
import shutil
import threading
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter, ImageOps

DATA_HOME = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share") / "huginn"
ORIGINALS = DATA_HOME / "photos" / "originals"
PREVIEW_SIDE = 1400
EDITABLE = (".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff")

# Every setting, its range and its resting value. Light and colour go from -1 to 1; detail from 0 to 1.
SLIDERS = {"exposure": (-1, 1, 0), "brightness": (-1, 1, 0), "contrast": (-1, 1, 0), "highlights": (-1, 1, 0), "shadows": (-1, 1, 0),
           "blacks": (-1, 1, 0), "saturation": (-1, 1, 0), "vibrance": (-1, 1, 0), "warmth": (-1, 1, 0), "tint": (-1, 1, 0),
           "sharpen": (0, 1, 0), "vignette": (0, 1, 0), "grain": (0, 1, 0), "fade": (0, 1, 0), "straighten": (-45, 45, 0), "amount": (0, 1, 1)}
FILTERS = {
    "none": {},
    "vivid": {"saturation": 0.3, "vibrance": 0.25, "contrast": 0.15},
    "warm": {"warmth": 0.45, "saturation": 0.1, "fade": 0.05},
    "cool": {"warmth": -0.45, "tint": -0.05, "contrast": 0.05},
    "mono": {"mono": 1, "contrast": 0.15},
    "noir": {"mono": 1, "contrast": 0.45, "blacks": -0.2, "vignette": 0.45},
    "fade": {"fade": 0.18, "contrast": -0.2, "saturation": -0.2},
    "film": {"fade": 0.08, "warmth": 0.15, "grain": 0.35, "contrast": 0.1, "saturation": -0.05},
    "dramatic": {"contrast": 0.35, "shadows": 0.25, "highlights": -0.35, "saturation": -0.1, "vignette": 0.3},
    "sepia": {"mono": 1, "sepia": 1, "contrast": 0.05, "fade": 0.06},
    "golden": {"warmth": 0.3, "exposure": 0.08, "highlights": -0.2, "saturation": 0.15, "vignette": 0.15},
}
FILTER_NAMES = {"none": "Original", "vivid": "Vivid", "warm": "Warm", "cool": "Cool", "mono": "Mono", "noir": "Noir", "fade": "Fade",
                "film": "Film", "dramatic": "Dramatic", "sepia": "Sepia", "golden": "Golden Hour"}
RATIOS = {"free": 0, "original": -1, "square": 1, "4:3": 4 / 3, "3:2": 3 / 2, "16:9": 16 / 9, "5:4": 5 / 4, "9:16": 9 / 16}


def blank() -> dict:
    """An edit that changes nothing."""
    out = {k: v[2] for k, v in SLIDERS.items()}
    out.update(filter="none", crop=[0.0, 0.0, 1.0, 1.0], turns=0, flip=False, ratio="free")
    return out


def tidy(edit: dict) -> dict:
    out = blank()
    for k, (lo, hi, _) in SLIDERS.items():
        try:
            out[k] = max(lo, min(hi, float(edit.get(k, out[k]))))
        except (TypeError, ValueError):
            pass
    out["filter"] = edit.get("filter") if edit.get("filter") in FILTERS else "none"
    crop = edit.get("crop")
    if isinstance(crop, (list, tuple)) and len(crop) == 4:
        x, y, w, h = (max(0.0, min(1.0, float(v))) for v in crop)
        w, h = max(0.02, min(w, 1 - x)), max(0.02, min(h, 1 - y))
        out["crop"] = [x, y, w, h]
    out["turns"] = int(edit.get("turns", 0)) % 4
    out["flip"] = bool(edit.get("flip"))
    out["ratio"] = edit.get("ratio") if edit.get("ratio") in RATIOS else "free"
    return out


def is_blank(edit: dict) -> bool:
    e, b = tidy(edit), blank()
    return all(e[k] == b[k] for k in b if k not in ("ratio", "amount"))


# ------------------------------------------------------------------------------------------- the picture's shape
def inscribed(w: float, h: float, degrees: float) -> float:
    """How much a w×h picture turned by `degrees` must shrink so no empty corner shows."""
    t = abs(math.radians(degrees))
    if t < 1e-6:
        return 1.0
    c, s = math.cos(t), math.sin(t)
    return min(w / (w * c + h * s), h / (w * s + h * c))


def shape(img: Image.Image, edit: dict, crop: bool = True) -> Image.Image:
    """Quarter turns and the mirror, then straightening (trimmed so no empty corner shows), then the crop."""
    if edit["turns"]:
        img = img.transpose([None, Image.Transpose.ROTATE_270, Image.Transpose.ROTATE_180, Image.Transpose.ROTATE_90][edit["turns"]])
    if edit["flip"]:
        img = ImageOps.mirror(img)
    angle = edit["straighten"]
    if abs(angle) > 0.01:
        w, h = img.size
        k = inscribed(w, h, angle)
        img = img.rotate(-angle, resample=Image.Resampling.BICUBIC, expand=False)
        cw, ch = w * k, h * k
        img = img.crop((round((w - cw) / 2), round((h - ch) / 2), round((w + cw) / 2), round((h + ch) / 2)))
    if crop:
        x, y, cw, ch = edit["crop"]
        if (x, y, cw, ch) != (0.0, 0.0, 1.0, 1.0):
            w, h = img.size
            box = (round(x * w), round(y * h), round((x + cw) * w), round((y + ch) * h))
            if box[2] - box[0] >= 2 and box[3] - box[1] >= 2:
                img = img.crop(box)
    return img


# ------------------------------------------------------------------------------------------- light and colour
def combined(edit: dict) -> dict:
    """The sliders with the filter's own values added (scaled by the filter's amount)."""
    out = dict(edit)
    preset, amount = FILTERS.get(edit.get("filter", "none"), {}), edit.get("amount", 1.0)
    for k, v in preset.items():
        if k in ("mono", "sepia"):
            out[k] = v * amount
        else:
            out[k] = out.get(k, 0) + v * amount
    return out


def tone(rgb: np.ndarray, e: dict, seed: int = 7) -> np.ndarray:
    """Light and colour on a float picture (values 0..1, shape h×w×3). Returns the same shape, clipped to 0..1."""
    x = rgb.astype(np.float32, copy=True)
    if e.get("exposure"):
        x *= 2.0 ** (e["exposure"] * 1.5)
    lum = x @ np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)
    if e.get("highlights") or e.get("shadows"):
        L = np.clip(lum, 0, 1)[..., None]
        if e.get("shadows"):
            mask = (1 - L) ** 2
            x = x + e["shadows"] * 0.6 * mask * (np.sqrt(np.clip(x, 0, None)) - x) if e["shadows"] > 0 else x * (1 + e["shadows"] * 0.6 * mask)
        if e.get("highlights"):
            mask, h = L ** 2, e["highlights"]
            x = x + h * 0.45 * mask * (1 - x) if h > 0 else x * (1 + h * 0.45 * mask)
    if e.get("brightness"):
        x = np.clip(x, 0, None) ** (2.0 ** (-e["brightness"] * 0.9))
    if e.get("contrast"):
        k = 1 + e["contrast"] * (0.9 if e["contrast"] > 0 else 0.7)
        x = (x - 0.5) * k + 0.5
    if e.get("blacks"):
        b = e["blacks"] * 0.12
        x = (x + b) / (1 + b) if b > 0 else (x + b) / (1 + b)
    lum = (x @ np.array([0.2126, 0.7152, 0.0722], dtype=np.float32))[..., None]
    if e.get("saturation") or e.get("vibrance"):
        sat = 1 + e.get("saturation", 0)
        if e.get("vibrance"):
            spread = (x.max(axis=2, keepdims=True) - x.min(axis=2, keepdims=True))
            sat = sat + e["vibrance"] * (1 - np.clip(spread * 1.6, 0, 1))
        x = lum + (x - lum) * sat
    if e.get("warmth") or e.get("tint"):
        w, t = e.get("warmth", 0) * 0.12, e.get("tint", 0) * 0.08
        x = x * np.array([1 + w + t * 0.5, 1 - t, 1 - w + t * 0.5], dtype=np.float32)
    if e.get("mono"):
        m = min(1.0, e["mono"])
        grey = (x @ np.array([0.3, 0.59, 0.11], dtype=np.float32))[..., None]
        if e.get("sepia"):
            grey = grey * np.array([1.07, 0.96, 0.78], dtype=np.float32)
        x = x * (1 - m) + grey * m
    if e.get("fade"):
        f = e["fade"] * 0.35
        x = x * (1 - f) + f * 0.5 + f * 0.25 * (0.5 - x)
    h, w = x.shape[:2]
    if e.get("vignette"):
        yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
        r = np.sqrt(((xx - w / 2) / (w / 2)) ** 2 + ((yy - h / 2) / (h / 2)) ** 2) / math.sqrt(2)
        x = x * (1 - e["vignette"] * 0.75 * np.clip((r - 0.35) / 0.65, 0, 1) ** 1.6)[..., None]
    if e.get("grain"):
        noise = np.random.default_rng(seed).normal(0, 1, (h, w, 1)).astype(np.float32)
        x = x + noise * e["grain"] * 0.06
    return np.clip(x, 0, 1)


def render(img: Image.Image, edit: dict, crop: bool = True) -> Image.Image:
    """The whole edit on one picture (any size). Keeps transparency in PNGs."""
    edit = tidy(edit)
    img = ImageOps.exif_transpose(img)
    alpha = img.getchannel("A") if img.mode in ("RGBA", "LA") else None
    img = shape(img.convert("RGB"), edit, crop)
    if alpha is not None:
        alpha = shape(alpha, edit, crop)
    e = combined(edit)
    if any(e.get(k) for k in ("exposure", "brightness", "contrast", "highlights", "shadows", "blacks", "saturation", "vibrance", "warmth", "tint", "mono", "fade", "vignette", "grain")):
        arr = np.asarray(img, dtype=np.float32) / 255.0
        img = Image.fromarray((tone(arr, e) * 255 + 0.5).astype(np.uint8), "RGB")
    if e.get("sharpen"):
        side = max(img.size)
        img = img.filter(ImageFilter.UnsharpMask(radius=max(1.0, side / 1400), percent=int(e["sharpen"] * 160), threshold=2))
    if alpha is not None:
        img.putalpha(alpha)
    return img


def auto_enhance(img: Image.Image) -> dict:
    """A good starting point: exposure and contrast from the picture's own levels, a touch of colour."""
    small = ImageOps.exif_transpose(img).convert("L")
    small.thumbnail((400, 400))
    a = np.asarray(small, dtype=np.float32) / 255.0
    lo, mid, hi = np.percentile(a, [1, 50, 99])
    out = {"exposure": float(np.clip((0.45 - mid) * 1.4, -0.6, 0.6)), "contrast": float(np.clip((0.85 - (hi - lo)) * 0.8, -0.2, 0.4)),
           "shadows": float(np.clip((0.12 - lo) * 3, 0, 0.4)), "highlights": float(np.clip((0.96 - hi) * -4, -0.5, 0)), "vibrance": 0.15}
    return {k: round(v, 3) for k, v in out.items()}


# ------------------------------------------------------------------------------------------- keeping originals and edits
def original_of(path: str) -> Path:
    digest = hashlib.sha1(os.path.realpath(path).encode()).hexdigest()[:20]
    return ORIGINALS / (digest + Path(path).suffix.lower())


def save_edit(path: str, edit: dict, as_copy: str = "") -> str:
    """Apply the edit to the full-size original and write it. Returns the file written."""
    keep = original_of(path)
    if not as_copy and not keep.exists():
        keep.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, keep)                                    # the first edit: put the original aside
    source = keep if keep.exists() else Path(path)
    with Image.open(source) as img:
        exif = img.info.get("exif")
        icc = img.info.get("icc_profile")
        out = render(img, edit)
    target = Path(as_copy or path)
    suffix = target.suffix.lower()
    kw = {}
    if suffix in (".jpg", ".jpeg"):
        out = out.convert("RGB")
        kw = {"quality": 94, "subsampling": 1, "optimize": True}
    elif suffix == ".webp":
        kw = {"quality": 94}
    if exif and suffix in (".jpg", ".jpeg", ".webp", ".png"):
        try:                                                        # turned upright already: say so in the EXIF
            from PIL import Image as _I
            ex = _I.Exif()
            ex.load(exif)
            ex[0x0112] = 1
            kw["exif"] = ex.tobytes()
        except Exception:                                           # noqa: BLE001
            pass
    if icc:
        kw["icc_profile"] = icc
    part = target.with_name(f".{target.name}.saving{suffix}")
    out.save(part, **kw)
    os.replace(part, target)
    return str(target)


def revert(path: str) -> bool:
    keep = original_of(path)
    if not keep.exists():
        return False
    part = Path(path).with_name(f".{Path(path).name}.reverting")
    shutil.copy2(keep, part)
    os.replace(part, path)
    keep.unlink()
    return True


class Session:
    """One picture being edited: a small copy to work on, and the numbers so far (with undo)."""

    def __init__(self, path: str, edit: dict = None):
        self.path = path
        keep = original_of(path)
        with Image.open(keep if keep.exists() else path) as img:
            img = ImageOps.exif_transpose(img)
            self.size = img.size
            self.small = img.convert("RGBA" if img.mode in ("RGBA", "LA", "P") else "RGB")
            self.small.thumbnail((PREVIEW_SIDE, PREVIEW_SIDE), Image.Resampling.LANCZOS)
        self.thumb = self.small.copy()
        self.thumb.thumbnail((220, 220))
        self.edit = tidy(edit or {})
        self.history, self.future = [], []
        self.lock = threading.Lock()
        self._cache = {}

    def mark(self) -> None:
        """Remember how things are now, as one step to undo (before a slider is dragged)."""
        with self.lock:
            self.history.append(dict(self.edit))
            self.history = self.history[-80:]
            self.future = []

    def change(self, record: bool = True, **kw) -> None:
        with self.lock:
            if record:
                self.history.append(dict(self.edit))
                self.history = self.history[-80:]
                self.future = []
            self.edit = tidy({**self.edit, **kw})
            self._cache.clear()

    def undo(self) -> bool:
        with self.lock:
            if not self.history:
                return False
            self.future.append(self.edit)
            self.edit = self.history.pop()
            self._cache.clear()
            return True

    def redo(self) -> bool:
        with self.lock:
            if not self.future:
                return False
            self.history.append(self.edit)
            self.edit = self.future.pop()
            self._cache.clear()
            return True

    def plain(self) -> Image.Image:
        """The picture as it came, for comparing."""
        return self.small

    def preview(self, crop: bool = True) -> Image.Image:
        with self.lock:
            edit = dict(self.edit)
            hit = self._cache.get(crop)
        if hit is not None:
            return hit
        out = render(self.small, edit, crop)
        with self.lock:
            if edit == self.edit:
                self._cache[crop] = out
        return out

    def filter_thumb(self, name: str) -> Image.Image:
        edit = dict(self.edit, filter=name, amount=1.0)
        return render(self.thumb, edit)

    def shape_size(self) -> tuple:
        """The size of the picture after turning and straightening, before the crop (for the crop frame's ratios)."""
        w, h = self.size
        if self.edit["turns"] % 2:
            w, h = h, w
        k = inscribed(w, h, self.edit["straighten"])
        return w * k, h * k


def load_edits(file: Path) -> dict:
    try:
        return json.loads(file.read_text(encoding="utf-8")).get("edits", {})
    except (OSError, ValueError, AttributeError):
        return {}
