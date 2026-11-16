"""Tempo's plugins: the LV2 effects and instruments Linux's audio world shares (LSP, Calf, x42, ZAM, Dragonfly and
whatever else is installed), found through lilv and run block by block inside Tempo's engine.

    host         what plugins may ask of a host: URIDs (map and unmap), options (the sample rate, block sizes, the
                 size of event buffers), bounded block lengths and a worker. A worker's jobs are done between blocks:
                 fine, as Tempo draws its sound ahead of the sound card rather than on its clock.
    effects      stereo in and out. A mono plugin runs twice, left and right; extra inputs (sidechains) hear silence
                 and extra outputs are left out.
    instruments  MIDI in through an atom sequence. Like Tempo's own instruments, a region is drawn to sound in one
                 pass (with the instrument's tail), and a note at a time for the keyboard.
    controls     every control input with its range, steps, switches and named values (what plugins hide from a
                 host's own controls stays hidden); presets (LV2 presets of port values).

A plugin that's gone (uninstalled, or a project from another computer) is passed through, and says so.
"""
import ctypes
import json
import os
import struct
import threading
from ctypes import CFUNCTYPE, POINTER, Structure, c_char_p, c_float, c_int, c_int32, c_uint32, c_void_p, cast, pointer
from pathlib import Path

import numpy as np

def _import_lilv():
    """lilv's Python side opens "liblilv-0.so", which only the development package provides: given the library itself."""
    real = ctypes.CDLL

    def cdll(name, *a, **k):
        return real("liblilv-0.so.0" if name == "liblilv-0.so" else name, *a, **k)
    ctypes.CDLL = cdll
    try:
        import lilv as module
        return module
    except Exception:                               # noqa: BLE001  (not installed: no plugins, everything else works)
        return None
    finally:
        ctypes.CDLL = real


lilv = _import_lilv()


def _quiet_exit():
    """At exit Python frees lilv's objects in no particular order, the world before what points into it, and the
    process crashes on its way out. Nothing needs freeing then: lilv's own clean-ups are switched off."""
    if lilv is None:
        return
    for name in dir(lilv):
        cls = getattr(lilv, name)
        if isinstance(cls, type) and "__del__" in cls.__dict__:
            cls.__del__ = lambda self: None


if lilv is not None:
    import atexit
    atexit.register(_quiet_exit)

SR = 48000
MAX_BLOCK = 4096
SEQ_BYTES = 1 << 16
CACHE = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "huginn" / "tempo"

LV2 = "http://lv2plug.in/ns/lv2core#"
ATOM = "http://lv2plug.in/ns/ext/atom#"
URID_MAP, URID_UNMAP = "http://lv2plug.in/ns/ext/urid#map", "http://lv2plug.in/ns/ext/urid#unmap"
OPTIONS = "http://lv2plug.in/ns/ext/options#options"
BUF = "http://lv2plug.in/ns/ext/buf-size#"
WORKER_SCHEDULE, WORKER_IFACE = "http://lv2plug.in/ns/ext/worker#schedule", "http://lv2plug.in/ns/ext/worker#interface"
MIDI_EVENT = "http://lv2plug.in/ns/ext/midi#MidiEvent"
PPROPS = "http://lv2plug.in/ns/ext/port-props#"
PSET = "http://lv2plug.in/ns/ext/presets#"
RDFS_LABEL = "http://www.w3.org/2000/01/rdf-schema#label"
# What a plugin may require and still be run here. (isLive and hardRTCapable describe the plugin, not the host.)
SUPPORTED = {URID_MAP, URID_UNMAP, OPTIONS, BUF + "boundedBlockLength", WORKER_SCHEDULE, LV2 + "isLive", LV2 + "hardRTCapable",
             LV2 + "inPlaceBroken"}


# ------------------------------------------------------------------------------------------------- the host's side
MapFn = CFUNCTYPE(c_uint32, c_void_p, c_char_p)
UnmapFn = CFUNCTYPE(c_void_p, c_void_p, c_uint32)
ScheduleFn = CFUNCTYPE(c_int, c_void_p, c_uint32, c_void_p)
RespondFn = CFUNCTYPE(c_int, c_void_p, c_uint32, c_void_p)
WorkFn = CFUNCTYPE(c_int, c_void_p, RespondFn, c_void_p, c_uint32, c_void_p)
WorkResponseFn = CFUNCTYPE(c_int, c_void_p, c_uint32, c_void_p)
EndRunFn = CFUNCTYPE(c_int, c_void_p)


class UridMap(Structure):
    _fields_ = [("handle", c_void_p), ("map", MapFn)]


class UridUnmap(Structure):
    _fields_ = [("handle", c_void_p), ("unmap", UnmapFn)]


class Option(Structure):
    _fields_ = [("context", c_uint32), ("subject", c_uint32), ("key", c_uint32), ("size", c_uint32), ("type", c_uint32), ("value", c_void_p)]


class WorkerSchedule(Structure):
    _fields_ = [("handle", c_void_p), ("schedule_work", ScheduleFn)]


class WorkerIface(Structure):
    _fields_ = [("work", WorkFn), ("work_response", WorkResponseFn), ("end_run", EndRunFn)]


class _Host:
    """One lilv world and the features every plugin gets. lilv isn't safe from several threads: `lock`."""

    def __init__(self):
        self.lock = threading.RLock()
        self.world = None
        self.uris: dict[str, int] = {}
        self.names: dict[int, ctypes.Array] = {}
        self._map = MapFn(self._do_map)
        self._unmap = UnmapFn(self._do_unmap)
        self.map_s = UridMap(None, self._map)
        self.unmap_s = UridUnmap(None, self._unmap)
        self._vals = {}
        opts = [("maxBlockLength", MAX_BLOCK, "Int"), ("minBlockLength", 1, "Int"), ("nominalBlockLength", 1024, "Int"),
                ("sequenceSize", SEQ_BYTES, "Int")]
        entries = []
        for key, v, kind in opts:
            val = c_int32(v)
            self._vals[key] = val
            entries.append(Option(0, 0, self.urid(BUF + key), 4, self.urid(ATOM + kind), cast(pointer(val), c_void_p)))
        rate = c_float(SR)
        self._vals["rate"] = rate
        entries.append(Option(0, 0, self.urid("http://lv2plug.in/ns/ext/parameters#sampleRate"), 4, self.urid(ATOM + "Float"), cast(pointer(rate), c_void_p)))
        entries.append(Option(0, 0, 0, 0, 0, None))
        self.options = (Option * len(entries))(*entries)

    def _do_map(self, _handle, uri) -> int:
        return self.urid(uri.decode("utf-8") if uri else "")

    def _do_unmap(self, _handle, urid) -> int:
        buf = self.names.get(int(urid))
        return ctypes.addressof(buf) if buf is not None else 0

    def urid(self, uri: str) -> int:
        u = self.uris.get(uri)
        if u is None:
            u = self.uris[uri] = len(self.uris) + 1
            self.names[u] = ctypes.create_string_buffer(uri.encode("utf-8"))
        return u

    def loaded(self):
        """The world, with every installed plugin's description read (a second or two, once)."""
        if lilv is None:
            return None
        with self.lock:
            if self.world is None:
                w = lilv.World()
                w.load_all()
                self.world = w
            return self.world

    def node(self, uri: str):
        return self.loaded().new_uri(uri)


HOST = _Host()


def available() -> bool:
    return lilv is not None


def _plugins() -> dict:
    w = HOST.loaded()
    return {str(p.get_uri()): p for p in w.get_all_plugins()} if w is not None else {}


def _ports(p) -> list:
    """Each port: (index, symbol, "audio" | "control" | "atom" | "cv" | "other", is input, the lilv port)."""
    w = HOST.loaded()
    audio, control, atom, cv, inp = (w.new_uri(LV2 + "AudioPort"), w.new_uri(LV2 + "ControlPort"), w.new_uri(ATOM + "AtomPort"),
                                     w.new_uri(LV2 + "CVPort"), w.new_uri(LV2 + "InputPort"))
    out = []
    for i in range(p.get_num_ports()):
        port = p.get_port_by_index(i)
        kind = "audio" if port.is_a(audio) else "control" if port.is_a(control) else "atom" if port.is_a(atom) else "cv" if port.is_a(cv) else "other"
        out.append((i, str(port.get_symbol()), kind, port.is_a(inp), port))
    return out


def _describe(uri: str, p) -> dict | None:
    """What the browser needs to know of a plugin, or None if it can't be run here."""
    required = {str(n) for n in p.get_required_features()}
    if required - SUPPORTED:
        return None
    w = HOST.loaded()
    midi = w.new_uri(MIDI_EVENT)
    ports = _ports(p)
    if any(k == "other" for _i, _s, k, _in, _p in ports):
        return None
    ins = sum(1 for _i, _s, k, i, _p in ports if k == "audio" and i)
    outs = sum(1 for _i, _s, k, i, _p in ports if k == "audio" and not i)
    takes_midi = any(k == "atom" and i and port.supports_event(midi) for _i, _s, k, i, port in ports)
    cls = p.get_class()
    category = str(cls.get_label()) if cls is not None else ""
    instrument = "Instrument" in category or (takes_midi and ins == 0)
    if outs == 0 or (not instrument and ins == 0):
        return None
    if instrument and outs > 2:                       # a kit with a pair of outputs per drum: its stereo one is there
        return None
    if "Analyser" in category:                        # meters and scopes: nothing to hear, nothing to see here
        return None
    path_t = w.new_uri(ATOM + "Path")
    for prm in w.find_nodes(p.get_uri(), w.new_uri("http://lv2plug.in/ns/ext/patch#writable"), None):
        if w.get(prm, w.new_uri("http://www.w3.org/2000/01/rdf-schema#range"), None) == path_t:
            return None                               # needs a file of its own (a sampler, an impulse response) first
    lib = p.get_library_uri()                         # (lilv's nodes won't be taken as true or false)
    lib = str(lib) if lib is not None else ""
    if lib.startswith("file://") and _links_toolkit(lib[7:]):
        return None
    author = p.get_author_name()
    return {"uri": uri, "name": str(p.get_name()), "kind": "instrument" if instrument else "effect",
            "category": category.replace(" Plugin", "") or ("Instrument" if instrument else "Effect"),
            "author": str(author) if author is not None else "", "ins": ins, "outs": outs}


def _links_toolkit(path: str) -> bool:
    """Does a plugin's sound engine bring a toolkit (Qt, GTK) into Tempo? Qt's would fight Tempo's own Qt."""
    try:
        data = Path(path).read_bytes()
    except OSError:
        return False
    return any(t in data for t in (b"libQt5Core.so", b"libQt6Core.so", b"libQtCore.so", b"libgtk-3.so", b"libgtk-x11-2.0.so"))


def _stamp() -> str:
    dirs = [Path(d) for d in (os.environ.get("LV2_PATH") or f"{Path.home()}/.lv2:/usr/local/lib/lv2:/usr/lib/lv2").split(":")]
    return "|".join(f"{d}:{int(d.stat().st_mtime)}:{len(list(d.iterdir()))}" for d in dirs if d.is_dir())


def catalogue(refresh: bool = False) -> list:
    """Every plugin that can run here, kept between starts (until something is installed or removed). Found by a
    scan in a process of its own, as other studios do: each plugin is started and played a moment, and one that
    crashes, or makes nothing but noise or silence where numbers should be, is left out without taking Tempo down."""
    if lilv is None:
        return []
    stamp = _stamp()
    cache = CACHE / "plugins.json"
    if not refresh:
        try:
            saved = json.loads(cache.read_text())
            if saved.get("stamp") == stamp:
                return saved["plugins"]
        except (OSError, ValueError, KeyError):
            pass
    import subprocess
    import sys
    import tempfile
    CACHE.mkdir(parents=True, exist_ok=True)
    found, broken = [], []
    with tempfile.TemporaryDirectory() as tmp:
        out, progress = Path(tmp) / "found.jsonl", Path(tmp) / "trying"
        for _attempt in range(40):                    # each round past the plugin that took the last one down
            progress.write_text("")
            try:
                done = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--scan", str(out), str(progress), json.dumps(broken)],
                                      timeout=300, capture_output=True).returncode == 0
            except subprocess.TimeoutExpired:
                done = False
            if done:
                break
            culprit = progress.read_text().strip()
            if not culprit or culprit in broken:
                break
            broken.append(culprit)
        if out.exists():
            for line in out.read_text().splitlines():
                try:
                    found.append(json.loads(line))
                except ValueError:
                    pass
    seen = set()
    found = [d for d in found if not (d["uri"] in seen or seen.add(d["uri"]))]
    found.sort(key=lambda d: (d["kind"], d["name"].lower()))
    try:
        cache.write_text(json.dumps({"stamp": stamp, "plugins": found, "broken": broken}))
    except OSError:
        pass
    return found


def _probe(d: dict) -> bool:
    """Start the plugin and play it a moment: silence, then a tone (or two notes); everything it gives back must be a
    number."""
    t = np.arange(2048) / SR
    if d["kind"] == "instrument":
        a = render_notes(d["uri"], {}, [[0.0, 0.08, 60, 100], [0.0, 0.08, 38, 100], [0.08, 0.08, 64, 90]], 0.2, tail=0.1)
        return bool(np.isfinite(a).all()) and float(np.abs(a).max()) > 1e-4      # and it makes a sound
    fx = Effect(d["uri"], {})
    if fx.missing:
        return False
    try:
        x = np.zeros((4096, 2), np.float32)
        x[2048:] = (np.sin(2 * np.pi * 440 * t) * 0.3).astype(np.float32)[:, None]
        y = np.concatenate([fx._run(x[a:a + 1024]) for a in range(0, 4096, 1024)])
        return bool(np.isfinite(y).all())
    finally:
        fx.close()


def _scan(out: str, progress: str, broken: list) -> None:
    """(In its own process.) Each plugin that might run, tried; those that play are written out one per line."""
    done = set()
    if os.path.exists(out):
        for line in Path(out).read_text().splitlines():
            try:
                done.add(json.loads(line)["uri"])
            except (ValueError, KeyError):
                pass
    tried = Path(out + ".tried")
    if tried.exists():
        done |= set(tried.read_text().split())
    with HOST.lock:
        plugins = _plugins()
    for uri, p in sorted(plugins.items()):
        if uri in done or uri in broken:
            continue
        Path(progress).write_text(uri)
        with open(tried, "a") as f:
            f.write(uri + "\n")
        try:
            d = _describe(uri, p)
            if d and _probe(d):
                with open(out, "a") as f:
                    f.write(json.dumps(d) + "\n")
        except Exception:                             # noqa: BLE001  (a plugin that won't play is left out)
            pass
    Path(progress).write_text("")


def _num(node, fallback: float = 0.0) -> float:
    """A node as a number: floats, whole numbers and true/false alike (lilv's Python only takes floats)."""
    if node is None:
        return fallback
    if node.is_float() or node.is_int():
        return float(lilv.c.node_as_float(node.node))
    if node.is_bool():
        return 1.0 if lilv.c.node_as_bool(node.node) else 0.0
    try:
        return float(str(node))
    except ValueError:
        return fallback


def _scale_points(port) -> list:
    """(value, label) pairs. (Read through lilv's C calls: its Python wrapper frees them before they can be read.)"""
    c = lilv.c
    pts = c.port_get_scale_points(port.plugin.plugin, port.port)
    out = []
    if pts:
        it = c.scale_points_begin(pts)
        while not c.scale_points_is_end(pts, it):
            sp = c.scale_points_get(pts, it)
            out.append((float(c.node_as_float(c.scale_point_get_value(sp))), c.node_as_string(c.scale_point_get_label(sp)).decode("utf-8")))
            it = c.scale_points_next(pts, it)
        c.scale_points_free(pts)
    return sorted(out)


def controls(uri: str) -> list:
    """A plugin's knobs: [{symbol, name, min, max, default, toggle, integer, log, choices: [[value, label]]}]."""
    with HOST.lock:
        p = _plugins().get(uri)
        if p is None:
            return []
        w = HOST.loaded()
        props = {k: w.new_uri(v) for k, v in (("toggled", LV2 + "toggled"), ("integer", LV2 + "integer"), ("enum", LV2 + "enumeration"),
                                                 ("log", PPROPS + "logarithmic"), ("hidden", PPROPS + "notOnGUI"))}
        out = []
        for _i, sym, kind, is_in, port in _ports(p):
            if kind != "control" or not is_in or port.has_property(props["hidden"]):
                continue
            dflt, lo, hi = port.get_range()
            lo, hi = _num(lo, 0.0), _num(hi, 1.0)
            dflt = _num(dflt, lo)
            choices = _scale_points(port) if port.has_property(props["enum"]) else []
            out.append({"symbol": sym, "name": str(port.get_name()), "min": lo, "max": hi, "default": min(hi, max(lo, dflt)),
                        "toggle": port.has_property(props["toggled"]), "integer": port.has_property(props["integer"]) or bool(choices),
                        "log": port.has_property(props["log"]) and lo > 0, "choices": [[v, label] for v, label in choices]})
        return out


def presets(uri: str) -> list:
    """The plugin's own presets: [{"name", "values": {symbol: value}}]."""
    with HOST.lock:
        p = _plugins().get(uri)
        if p is None:
            return []
        w = HOST.loaded()
        port_p, sym_p, val_p, label = w.new_uri(LV2 + "port"), w.new_uri(LV2 + "symbol"), w.new_uri(PSET + "value"), w.new_uri(RDFS_LABEL)
        out = []
        for preset in p.get_related(w.new_uri(PSET + "Preset")):
            w.load_resource(preset)
            name = w.get(preset, label, None)
            values = {}
            for pn in w.find_nodes(preset, port_p, None):
                s, v = w.get(pn, sym_p, None), w.get(pn, val_p, None)
                if s is not None and v is not None:
                    values[str(s)] = _num(v)
            if values:
                out.append({"name": str(name) if name is not None else str(preset).rsplit("#", 1)[-1], "values": values})
        out.sort(key=lambda d: d["name"].lower())
        return out


# ------------------------------------------------------------------------------------------------- running one
class _Instance:
    """One running copy of a plugin with every port connected: audio and CV to float buffers, controls to single
    floats, atom ports to event sequences."""

    def __init__(self, p, params: dict):
        self.jobs: list[bytes] = []
        self.responses: list[bytes] = []
        self._schedule_fn = ScheduleFn(self._schedule)
        self._respond_fn = RespondFn(self._respond)
        self.sched = WorkerSchedule(None, self._schedule_fn)
        feats = [lilv.LV2_Feature(URID_MAP.encode(), cast(pointer(HOST.map_s), c_void_p)),
                 lilv.LV2_Feature(URID_UNMAP.encode(), cast(pointer(HOST.unmap_s), c_void_p)),
                 lilv.LV2_Feature(OPTIONS.encode(), cast(HOST.options, c_void_p)),
                 lilv.LV2_Feature((BUF + "boundedBlockLength").encode(), None),
                 lilv.LV2_Feature(WORKER_SCHEDULE.encode(), cast(pointer(self.sched), c_void_p))]
        self._feats = feats
        self._feat_arr = (POINTER(lilv.LV2_Feature) * (len(feats) + 1))(*[pointer(f) for f in feats], None)
        self.inst = lilv.Instance(p, SR, self._feat_arr)
        if not self.inst.instance:
            raise RuntimeError("the plugin wouldn't start")
        self.desc = self.inst.get_descriptor()
        self.handle = self.inst.get_handle()
        self.audio_in, self.audio_out, self.atom_in, self.atom_out, self.midi_in = [], [], [], [], None
        self.controls: dict[str, np.ndarray] = {}
        self.defaults: dict[str, float] = {}
        self._keep = []
        w = HOST.loaded()
        midi = w.new_uri(MIDI_EVENT)
        for i, sym, kind, is_in, port in _ports(p):
            if kind == "audio" or kind == "cv":
                buf = np.zeros(MAX_BLOCK, np.float32)
                if kind == "audio":
                    (self.audio_in if is_in else self.audio_out).append(buf)
                self._connect(i, buf.ctypes.data)
                self._keep.append(buf)
            elif kind == "control":
                dflt, lo, hi = port.get_range()
                v = _num(dflt, _num(lo, 0.0))
                buf = np.array([v], np.float32)
                if is_in:
                    self.controls[sym] = buf
                    self.defaults[sym] = v
                self._connect(i, buf.ctypes.data)
                self._keep.append(buf)
            elif kind == "atom":
                buf = ctypes.create_string_buffer(SEQ_BYTES)
                if is_in:
                    self.atom_in.append(buf)
                    if self.midi_in is None and port.supports_event(midi):
                        self.midi_in = buf
                else:
                    self.atom_out.append(buf)
                self._connect(i, ctypes.addressof(buf))
                self._keep.append(buf)
        self.set(params)
        iface = self.inst.get_extension_data(WORKER_IFACE)
        self.worker = cast(iface, POINTER(WorkerIface)).contents if iface else None
        self.seq_t, self.chunk_t, self.midi_t = HOST.urid(ATOM + "Sequence"), HOST.urid(ATOM + "Chunk"), HOST.urid(MIDI_EVENT)
        self.inst.activate()

    def _connect(self, index: int, address: int) -> None:
        self.desc.connect_port(self.handle, index, c_void_p(address))

    def _schedule(self, _handle, size, data) -> int:
        self.jobs.append(ctypes.string_at(data, size))
        return 0

    def _respond(self, _handle, size, data) -> int:
        self.responses.append(ctypes.string_at(data, size))
        return 0

    def set(self, params: dict) -> None:
        for k, v in (params or {}).items():
            buf = self.controls.get(k)
            if buf is not None:
                try:
                    buf[0] = float(v)
                except (TypeError, ValueError):
                    pass

    def run(self, n: int, events: list = None) -> None:
        """One run of n frames (n ≤ MAX_BLOCK); events: (frame, bytes of a MIDI message) for the MIDI input."""
        for buf in self.atom_in:
            body = b""
            if buf is self.midi_in and events:
                for frame, msg in events:
                    ev = struct.pack("<qII", int(frame), len(msg), self.midi_t) + msg
                    body += ev + b"\0" * (-len(ev) % 8)
                    if len(body) > SEQ_BYTES - 64:
                        break
            struct.pack_into("<IIII", buf, 0, 8 + len(body), self.seq_t, 0, 0)
            if body:
                ctypes.memmove(ctypes.addressof(buf) + 16, body, len(body))
        for buf in self.atom_out:
            struct.pack_into("<II", buf, 0, SEQ_BYTES - 8, self.chunk_t)
        self.inst.run(n)
        if self.worker is not None and self.jobs:
            jobs, self.jobs = self.jobs, []
            for job in jobs:
                b = ctypes.create_string_buffer(job, len(job))
                self.worker.work(self.handle, self._respond_fn, None, len(job), ctypes.addressof(b))
            responses, self.responses = self.responses, []
            for r in responses:
                b = ctypes.create_string_buffer(r, len(r))
                self.worker.work_response(self.handle, len(r), ctypes.addressof(b))
            if self.worker.end_run:
                self.worker.end_run(self.handle)

    def close(self) -> None:
        try:
            self.inst.deactivate()
        except Exception:                             # noqa: BLE001
            pass


def _make(uri: str, params: dict) -> _Instance | None:
    with HOST.lock:
        p = _plugins().get(uri)
        return _Instance(p, params) if p is not None else None


class Effect:
    """A plugin as one of a track's effects: stereo in, stereo out, its knobs set (and drawn over time) by name."""

    def __init__(self, uri: str, params: dict):
        self.uri = uri
        self.p = dict(params or {})
        self.parts: list[_Instance] = []
        self.missing = False
        try:
            first = _make(uri, self.p)
        except Exception:                             # noqa: BLE001
            first = None
        if first is None:
            self.missing = True
            self.defaults = {}
            return
        self.parts = [first]
        if len(first.audio_in) == 1 and len(first.audio_out) == 1:     # mono: one for each side
            self.parts.append(_make(uri, self.p))
        self.defaults = dict(first.defaults)

    def set(self, params: dict) -> None:
        self.p = dict(params)
        for part in self.parts:
            part.set(params)

    def run(self, x: np.ndarray) -> np.ndarray:
        if self.missing or not len(x):
            return x
        out = np.empty_like(x)
        for a in range(0, len(x), MAX_BLOCK):
            b = min(len(x), a + MAX_BLOCK)
            out[a:b] = self._run(x[a:b])
        if not np.isfinite(out).all():                 # a plugin gone wrong is heard as silence, never as noise
            out = np.nan_to_num(out, nan=0.0, posinf=0.0, neginf=0.0)
        return out

    def _run(self, x: np.ndarray) -> np.ndarray:
        n = len(x)
        if len(self.parts) == 2:
            res = np.empty((n, 2), np.float32)
            for side, part in enumerate(self.parts):
                part.audio_in[0][:n] = x[:, side]
                part.run(n)
                res[:, side] = part.audio_out[0][:n]
            return res
        part = self.parts[0]
        ins = part.audio_in
        if len(ins) == 1:
            ins[0][:n] = x.mean(axis=1)
        elif len(ins) >= 2:
            ins[0][:n], ins[1][:n] = x[:, 0], x[:, 1]
            for extra in ins[2:]:
                extra[:n] = 0.0
        part.run(n)
        outs = part.audio_out
        if len(outs) == 1:
            return np.repeat(outs[0][:n, None], 2, axis=1)
        return np.stack([outs[0][:n], outs[1][:n]], axis=1)

    def close(self) -> None:
        for part in self.parts:
            part.close()


def render_notes(uri: str, params: dict, notes: list, seconds: float, tail: float = 2.0, controls: list = None) -> np.ndarray:
    """An instrument playing notes ([start s, length s, pitch, velocity]) from silence: stereo float32, with its tail
    (cut where it has died away). `controls`: other MIDI to send, [(seconds, message)] (pedal, bends, mod wheel)."""
    inst = _make(uri, params)
    if inst is None:
        return np.zeros((int(seconds * SR), 2), np.float32)
    try:
        evs = []
        for start, length, pitch, vel in notes:
            on = max(0, int(start * SR))
            evs.append((on, 1, bytes([0x90, int(pitch) & 127, max(1, min(127, int(vel)))])))
            evs.append((on + max(1, int(length * SR)), 0, bytes([0x80, int(pitch) & 127, 0])))
        for at, msg in controls or []:                # controllers before notes at the same moment
            evs.append((max(0, int(at * SR)), -1, bytes(msg)))
        evs.sort(key=lambda e: (e[0], e[1]))           # at the same moment, a note ends before the next begins
        total = int((seconds + tail) * SR)
        out = np.zeros((total, 2), np.float32)
        k, block = 0, 1024
        for _ in range(8):                            # a moment of silence first: kits load their sounds as they start
            inst.run(block)
        for s0 in range(0, total, block):
            n = min(block, total - s0)
            mine = []
            while k < len(evs) and evs[k][0] < s0 + n:
                mine.append((evs[k][0] - s0, evs[k][2]))
                k += 1
            inst.run(n, mine)
            outs = inst.audio_out
            out[s0:s0 + n, 0] = outs[0][:n]
            out[s0:s0 + n, 1] = outs[1][:n] if len(outs) > 1 else outs[0][:n]
        # the tail: cut once it's quiet for good
        end = int(seconds * SR)
        loud = np.nonzero(np.abs(out[end:]).max(axis=1) > 1e-4)[0]
        cut = end + (int(loud[-1]) + 1 if len(loud) else 0)
        return out[:max(1, cut)]
    finally:
        inst.close()


if __name__ == "__main__":
    import sys
    if len(sys.argv) >= 5 and sys.argv[1] == "--scan":
        _scan(sys.argv[2], sys.argv[3], json.loads(sys.argv[4]))
