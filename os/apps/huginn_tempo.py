"""Tempo: make music. Tracks of instruments, drummers and recordings, loops to start from, a piano roll and a
drum grid to write in, a mixer with effects, and export to share. The sound comes from huginn_tempo_engine.

A song is a folder in Music/Tempo (Name.tempo) holding project.json and the recordings it uses (audio/), so it
can be copied whole. Tempo saves as you go; undo goes back step by step.

Playing: a thread draws the song a block ahead into a queue; the window's timer feeds the queue to the sound card
(Qt Multimedia, 48 kHz float stereo), mixing in whatever is being played live on the keyboard just before it goes
out, so live notes answer quickly. Without a sound card the clock still runs (and the meters move).
Recording: notes from the on-screen keyboard, the computer keyboard (musical typing) or a MIDI keyboard (raw ALSA
MIDI devices, /dev/snd/midiC*D*), and sound from the microphone.
"""
import copy
import json
import os
import re
import threading
import time
import uuid
from collections import deque
from pathlib import Path

import numpy as np
from PySide6.QtCore import Property, QByteArray, QObject, QStandardPaths, QTimer, QUrl, Signal, Slot

import huginn_tempo_engine as se

try:
    from PySide6.QtMultimedia import QAudioFormat, QAudioSink, QAudioSource, QMediaDevices
except ImportError:                                           # no Qt Multimedia: the clock runs silently
    QAudioSink = None

STATE = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share") / "huginn" / "tempo" / "state.json"
OLD_STATE = STATE.parent.parent / "studio" / "state.json"     # from when Tempo was called Studio
COLOURS = {"instrument": "#4FA3FF", "drummer": "#FFC53D", "audio": "#3DDC84", "loop": "#B57BFF", "stack": "#FF8A5B"}
TEMPLATES = {
    "empty": ("Empty Song", "Start with one instrument.", [("instrument", "grand", "Piano")]),
    "songwriter": ("Songwriter", "Piano, bass and a drummer: write a song.", [("instrument", "grand", "Piano"), ("instrument", "fingered", "Bass"), ("drummer", "drums", "Drummer")]),
    "beat": ("Beat Maker", "Electronic drums, bass, a pad and a lead.", [("drummer", "electronic", "Beat"), ("instrument", "bass", "Bass"), ("instrument", "pad", "Pad"), ("instrument", "lead", "Lead")]),
    "band": ("Band", "Drums, bass, guitar and organ.", [("drummer", "drums", "Drums"), ("instrument", "fingered", "Bass"), ("instrument", "guitar", "Guitar"), ("instrument", "organ", "Organ")]),
    "voice": ("Voice and Podcast", "Two microphones and music underneath.", [("audio", "", "Voice 1"), ("audio", "", "Voice 2"), ("instrument", "pad", "Music bed")]),
}
QWERTY = {"a": 0, "w": 1, "s": 2, "e": 3, "d": 4, "f": 5, "t": 6, "g": 7, "y": 8, "h": 9, "u": 10, "j": 11, "k": 12, "o": 13, "l": 14, "p": 15, ";": 16}


def parse_midi_bytes(state: dict, data: bytes) -> list:
    """Raw MIDI bytes (from a keyboard) -> [("on", pitch, vel) | ("off", pitch, 0)], keeping running status."""
    out = []
    for b in data:
        if b & 0x80:
            if b >= 0xF8:                                     # clock and other real-time bytes come between anything
                continue
            state["status"], state["data"] = b, []
            continue
        st = state.get("status", 0)
        if not st:
            continue
        state.setdefault("data", []).append(b)
        need = 1 if st & 0xF0 in (0xC0, 0xD0) else 2
        if len(state["data"]) >= need:
            d = state["data"]
            state["data"] = []
            if st & 0xF0 == 0x90 and d[1] > 0:
                out.append(("on", d[0], d[1]))
            elif st & 0xF0 == 0x80 or (st & 0xF0 == 0x90 and d[1] == 0):
                out.append(("off", d[0], 0))
    return out


def sound_server() -> bool:
    """Is there a sound server to talk to? (Asking Qt Multimedia without one can crash it.)"""
    run = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
    return any(os.path.exists(os.path.join(run, s)) for s in ("pipewire-0", "pulse/native"))


class Player:
    """The sound going out: blocks from the mixer thread, live notes added at the last moment."""

    def __init__(self, owner: "Tempo"):
        self.owner = owner
        self.queue = deque()
        self.lock = threading.Lock()
        self.thread = None
        self.running = False
        self.sink = None
        self.io = None
        self.written = 0                 # frames handed to the sound card since start
        self.marks = deque()             # (written frame where a block starts, song frame it holds, frames)
        self.clock0 = 0.0
        self.live = []                   # [{"id", "audio", "pos", "release"}]
        self.device = False
        if QAudioSink is not None and sound_server():
            try:
                self.device = QMediaDevices.defaultAudioOutput() is not None and not QMediaDevices.defaultAudioOutput().isNull()
            except Exception:                                 # noqa: BLE001  (no sound system at all)
                self.device = False
        self.timer = QTimer(owner, interval=10)
        self.timer.timeout.connect(self._feed)
        self.timer.start()

    def start(self, project: dict, audio_dir: Path, at_frame: int, cycle, metronome: bool, count_in: int) -> None:
        self.stop()
        self.queue.clear()
        self.marks.clear()
        self.written = 0
        self.running = True
        snap = json.loads(json.dumps(project))
        tm, mm = se.TempoMap(snap), se.MeterMap(snap)
        click_hi = (np.sin(2 * np.pi * 1760 * np.arange(1600) / se.SR) * np.exp(-np.arange(1600) / 300)).astype(np.float32) * 0.5
        click_lo = (np.sin(2 * np.pi * 1320 * np.arange(1600) / se.SR) * np.exp(-np.arange(1600) / 300)).astype(np.float32) * 0.35
        # the click: each beat of the signature (quarters in 4/4, eighths in 6/8), higher on a bar's first, where the
        # tempo map puts it; the count-in in the signature and tempo where playing starts
        start_beat = tm.beat(at_frame / se.SR)
        sig0 = mm.sig_at(start_beat)
        unit = int(se.beats_to_s(4.0 / int(sig0[1]), tm.tempo_at(start_beat)) * se.SR)
        lead = count_in * int(sig0[0]) * unit
        counting = [(at_frame - lead + i * unit, i % int(sig0[0]) == 0) for i in range(count_in * int(sig0[0]))]
        clicks = []                                    # the song's own, from the start (a cycle comes round again)
        for b, _n, sig in mm.bars(se.song_length(snap) + 64):
            for j in range(int(sig[0])):
                clicks.append((int(tm.seconds(b + j * 4.0 / int(sig[1])) * se.SR), j == 0))
        clicks.sort()
        count_at, click_at = [c[0] for c in counting], [c[0] for c in clicks]

        def work():
            m = se.Mixer(snap, audio_dir)
            m.seek(at_frame)
            song = at_frame - lead                             # the count-in plays before the song starts
            counting_in = lead > 0
            import bisect

            def click(block, marks, at, s0, s1):
                for i in range(bisect.bisect_left(at, s0), bisect.bisect_left(at, s1)):
                    f, first = marks[i]
                    c = click_hi if first else click_lo
                    k = f - song
                    e = min(len(block), k + len(c))
                    block[k:e] += c[:e - k, None]
            while self.running:
                if len(self.queue) > 10:
                    time.sleep(0.004)
                    continue
                if counting_in:                                # silence and the count-in's clicks, ending right where the song starts
                    n = min(se.BLOCK, at_frame - song)
                    block = np.zeros((n, 2), np.float32)
                    click(block, counting, count_at, song, song + n)
                else:
                    n = se.BLOCK
                    block = m.render(n)
                    if metronome:                              # higher on the bar's first beat
                        click(block, clicks, click_at, song, song + n)
                levels = dict(m.levels)
                start = song
                song += n
                if counting_in and song >= at_frame:
                    counting_in = False
                if cycle and song >= cycle[1] > cycle[0] and start < cycle[1]:   # round again
                    m.seek(cycle[0])
                    song = cycle[0]
                with self.lock:
                    self.queue.append((start, block, levels))
        self.thread = threading.Thread(target=work, daemon=True)
        self.thread.start()
        if self.device:
            fmt = QAudioFormat()
            fmt.setSampleRate(se.SR)
            fmt.setChannelCount(2)
            fmt.setSampleFormat(QAudioFormat.SampleFormat.Float)
            self.sink = QAudioSink(QMediaDevices.defaultAudioOutput(), fmt, self.owner)
            self.sink.setBufferSize(se.BLOCK * 8 * 6)
            self.io = self.sink.start()
        self.clock0 = time.monotonic()

    def stop(self) -> None:
        self.running = False
        if self.thread is not None:
            self.thread.join(timeout=1.0)
            self.thread = None
        if self.sink is not None:
            self.sink.stop()
            self.sink = None
            self.io = None

    def played_frames(self) -> int:
        if self.sink is not None:
            buffered = (self.sink.bufferSize() - self.sink.bytesFree()) // 8
            return max(0, self.written - buffered)
        return int((time.monotonic() - self.clock0) * se.SR)

    def song_frame(self) -> int:
        played = self.played_frames()
        for w0, song0, n in self.marks:
            if w0 <= played < w0 + n:
                return song0 + (played - w0)
        return self.marks[-1][1] + self.marks[-1][2] if self.marks else 0

    def _mix_live(self, block: np.ndarray) -> np.ndarray:
        n = len(block)
        for v in list(self.live):
            a, p = v["audio"], v["pos"]
            piece = a[p:p + n]
            block[:len(piece)] += piece[:, None] if piece.ndim == 1 else piece
            v["pos"] += n
            if v["pos"] >= len(a):
                self.live.remove(v)
        return block

    def _feed(self) -> None:
        """Hand blocks to the sound card while it has room (or at the clock's pace when there's none)."""
        if self.running:
            want = (self.sink.bytesFree() // (se.BLOCK * 8)) if self.sink is not None else \
                max(0, (self.played_frames() + se.BLOCK * 3 - self.written) // se.BLOCK)
            for _ in range(int(want)):
                with self.lock:
                    item = self.queue.popleft() if self.queue else None
                if item is None:
                    break
                start, block, levels = item
                block = self._mix_live(block)
                if self.io is not None:
                    self.io.write(QByteArray(np.clip(block, -1, 1).astype(np.float32).tobytes()))
                self.marks.append((self.written, start, len(block)))
                while len(self.marks) > 64:
                    self.marks.popleft()
                self.written += len(block)
                self.owner._levels = levels
        elif self.live:                                       # only live notes: a sink of their own
            if self.sink is None and self.device:
                fmt = QAudioFormat()
                fmt.setSampleRate(se.SR)
                fmt.setChannelCount(2)
                fmt.setSampleFormat(QAudioFormat.SampleFormat.Float)
                self.sink = QAudioSink(QMediaDevices.defaultAudioOutput(), fmt, self.owner)
                self.sink.setBufferSize(se.BLOCK * 8 * 3)
                self.io = self.sink.start()
            if self.sink is not None:
                while self.live and self.sink.bytesFree() >= se.BLOCK * 8:
                    self.io.write(QByteArray(np.clip(self._mix_live(np.zeros((se.BLOCK, 2), np.float32)), -1, 1).tobytes()))
            else:
                for v in list(self.live):                     # nowhere to play: let the notes run out
                    v["pos"] += se.BLOCK
                    if v["pos"] >= len(v["audio"]):
                        self.live.remove(v)

    def play_live(self, vid: str, audio: np.ndarray) -> None:
        self.live.append({"id": vid, "audio": audio, "pos": 0})

    def release_live(self, vid: str, frames: int) -> None:
        for v in self.live:
            if v["id"] == vid:
                end = min(len(v["audio"]), v["pos"] + frames)
                a = v["audio"][:end].copy()
                n = end - v["pos"]
                if n > 0:
                    a[v["pos"]:end] *= np.linspace(1, 0, n, dtype=np.float32)[:, None] if a.ndim == 2 else np.linspace(1, 0, n, dtype=np.float32)
                v["audio"] = a

    def stop_live(self, prefix: str = "") -> None:
        self.live = [v for v in self.live if prefix and not v["id"].startswith(prefix)]


class Tempo(QObject):
    changed = Signal()
    clockChanged = Signal()
    pluginsChanged = Signal()
    said = Signal(str, bool)
    _midi_in = Signal(str, int, int)
    _back = Signal(object)

    def __init__(self, demo: bool = False):
        super().__init__()
        self._demo = demo
        self._p = None
        self._folder = None
        self._undo, self._redo, self._coalesce = [], [], None
        self._pos = 0.0                                       # the playhead, in beats
        self._playing = False
        self._recording = False
        self._rec = None
        self._levels = {}
        self._sel_track, self._sel_region = "", ""
        self._held = {}
        self._player = Player(self)
        self._save_timer = QTimer(self, singleShot=True, interval=700)
        self._save_timer.timeout.connect(self._write)
        self._clock = QTimer(self, interval=33)
        self._clock.timeout.connect(self._tick)
        self._clock.start()
        self._midi_in.connect(self._midi_event)
        self._back.connect(lambda fn: fn())
        self._midi_threads = []
        self._mic = None
        self._plugins, self._plugin_state = [], "finding" if se.lv2 is not None and se.lv2.available() else "none"
        self._plugin_controls = {}
        if self._plugin_state == "finding":
            threading.Thread(target=self._find_plugins, daemon=True).start()
        if demo:
            self._demo_song()
        else:
            last = ""
            try:
                last = json.loads((STATE if STATE.exists() else OLD_STATE).read_text(encoding="utf-8")).get("last", "")
            except (OSError, ValueError):
                pass
            root = self._root()
            if last.endswith(".studio") and not Path(last).exists():   # moved when Studio became Tempo
                last = str(root / Path(last).with_suffix(".tempo").name)
            if last and (Path(last) / "project.json").exists():
                self.openProject(last)
            self._listen_midi()

    # ---------------------------------------------------------------- songs on disk
    def _root(self) -> Path:
        music = Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.MusicLocation) or Path.home() / "Music")
        root = music / "Tempo"
        old = music / "Studio"                                 # Tempo was called Studio: bring its songs along once
        if not root.exists() and old.is_dir() and any(old.glob("*.studio")):
            try:
                old.rename(root)
                for d in root.glob("*.studio"):
                    d.rename(d.with_suffix(".tempo"))
            except OSError:
                return old
        return root

    def _write(self) -> None:
        if self._demo or self._folder is None or self._p is None:
            return
        try:
            self._folder.mkdir(parents=True, exist_ok=True)
            tmp = self._folder / "project.json.saving"
            tmp.write_text(json.dumps(self._p), encoding="utf-8")
            os.replace(tmp, self._folder / "project.json")
            STATE.parent.mkdir(parents=True, exist_ok=True)
            STATE.write_text(json.dumps({"last": str(self._folder)}), encoding="utf-8")
        except OSError as e:
            self.said.emit(f"Couldn't save the song: {e.strerror or e}", True)

    def _keep(self) -> None:
        self._save_timer.start()
        if self._playing:                                    # the song being played follows edits
            self._restart_player()
        self.changed.emit()
        self.clockChanged.emit()                             # the display too (bar.beat, tempo and signature here)

    def _before(self, coalesce=None) -> None:
        if coalesce is not None and coalesce == self._coalesce and self._undo:
            return
        self._coalesce = coalesce
        self._undo.append(copy.deepcopy(self._p))
        del self._undo[:-100]
        self._redo = []

    def _id(self, prefix: str) -> str:
        return prefix + uuid.uuid4().hex[:8]

    @Slot(result="QVariantList")
    def templates(self) -> list:
        return [{"id": k, "name": v[0], "about": v[1]} for k, v in TEMPLATES.items()]

    @Slot(str, str)
    def newProject(self, template: str, name: str) -> None:
        name = (name or "").strip() or "My Song"
        name = re.sub(r"\s+", " ", re.sub(r"[\\/:*?\"<>|]+", " ", name)).strip() or "My Song"
        p = {"version": 1, "name": name, "tempo": 110, "sig": [4, 4], "key": 0, "mode": "major", "metronome": False, "countIn": 1,
             "cycle": {"on": False, "start": 0, "end": 16}, "tracks": [], "regions": [], "master": {"volume": 0, "room": 1.8, "effects": []}}
        self._p = p
        for kind, inst, tname in TEMPLATES.get(template, TEMPLATES["empty"])[2]:
            self._add_track(kind, inst, tname)
        if template not in ("empty", "voice"):                # something to hear straight away
            for t in self._p["tracks"]:
                if t["kind"] == "drummer":
                    self._p["regions"].append(self._drummer_region(t, 0, 16))
        if not self._demo:
            root = self._root()
            root.mkdir(parents=True, exist_ok=True)
            folder, n = root / f"{name}.tempo", 2
            while folder.exists():
                folder, n = root / f"{name} {n}.tempo", n + 1
            self._folder = folder
            (folder / "audio").mkdir(parents=True, exist_ok=True)
            self._p["name"] = folder.stem
        self._undo, self._redo, self._pos = [], [], 0.0
        self._sel_track = self._p["tracks"][0]["id"] if self._p["tracks"] else ""
        self._sel_region = ""
        self._write()
        self.changed.emit()
        self.clockChanged.emit()

    @Slot(str)
    def openProject(self, path: str) -> None:
        path = QUrl(path).toLocalFile() if path.startswith("file:") else path
        try:
            self._p = json.loads((Path(path) / "project.json").read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            self.said.emit(f"Couldn't open that song: {e}", True)
            return
        self._folder = Path(path)
        self._undo, self._redo, self._pos = [], [], 0.0
        self._sel_track = self._p["tracks"][0]["id"] if self._p.get("tracks") else ""
        self._sel_region = ""
        self._write()
        self.changed.emit()
        self.clockChanged.emit()

    @Slot(result="QVariantList")
    def songs(self) -> list:
        root = self._root()
        if self._demo:
            return [{"path": "/demo/Northern Lights.tempo", "name": "Northern Lights", "when": "Today, 09:12", "tracks": 6},
                    {"path": "/demo/Fjord Morning.tempo", "name": "Fjord Morning", "when": "Yesterday", "tracks": 4},
                    {"path": "/demo/Raven Beat.tempo", "name": "Raven Beat", "when": "10 Nov", "tracks": 5}]
        out = []
        if root.is_dir():
            for d in sorted(root.glob("*.tempo"), key=lambda q: -q.stat().st_mtime):
                try:
                    p = json.loads((d / "project.json").read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    continue
                out.append({"path": str(d), "name": d.stem, "when": time.strftime("%-d %b, %H:%M", time.localtime(d.stat().st_mtime)), "tracks": len(p.get("tracks", []))})
        return out

    @Slot(str)
    def rename(self, name: str) -> None:
        name = re.sub(r"\s+", " ", re.sub(r"[\\/:*?\"<>|]+", " ", name or "")).strip()
        if not name or self._p is None:
            return
        if not self._demo and self._folder is not None:
            target = self._folder.with_name(f"{name}.tempo")
            if target.exists():
                self.said.emit("There's a song with that name already.", True)
                return
            os.replace(self._folder, target)
            self._folder = target
        self._p["name"] = name
        self._keep()

    # ---------------------------------------------------------------- what the window sees
    def _track_view(self, t: dict) -> dict:
        regions = []
        for r in self._p.get("regions", []):
            if r["track"] != t["id"]:
                continue
            v = {"id": r["id"], "start": r["start"], "length": r["length"], "loops": int(r.get("loops", 1)), "kind": r.get("kind", "midi"),
                 "name": r.get("name") or t["name"], "muted": bool(r.get("muted")), "takes": len(r.get("takes") or []), "take": int(r.get("take", 0)),
                 "comp": r.get("comp") or []}
            if r.get("kind") == "audio":
                v.update(gain=float(r.get("gain", 0)), fadeIn=float(r.get("fadeIn", 0)), fadeOut=float(r.get("fadeOut", 0)), reverse=bool(r.get("reverse")),
                         transpose=float(r.get("transpose", 0)), follow=bool(r.get("follow")))
                v["peaks"] = self._peaks(r, r.get("file", ""), max(16, int(r["length"] * 8))) or r.get("demoPeaks", [])
            else:
                notes = r.get("notes") or []
                v["notes"] = [[n["t"], n["d"], n["p"]] for n in notes[:600]]
                ps = [n["p"] for n in notes] or [60]
                v["low"], v["high"] = min(ps), max(ps)
            regions.append(v)
        inst = se.settings(t.get("instrument") or {"id": "grand"})
        members = [o["id"] for o in self._p.get("tracks", []) if o.get("output") == t["id"]] if t["kind"] == "stack" else []
        summary = [[r["start"], r["length"] * max(1, int(r.get("loops", 1)))] for r in self._p.get("regions", []) if r["track"] in members]
        name = inst.get("name", "")
        if inst.get("engine") == "sampler":
            name = f"Sampler · {inst.get('sound') or 'drop a sound'}"
        return {**{k: v for k, v in t.items() if k not in ("automation",)}, "regions": regions, "instName": name if t["kind"] != "stack" else f"{len(members)} tracks",
                "family": self._plugin_family(t.get("instrument") or {}) or inst.get("family", ""), "automation": t.get("automation") or {}, "colour": t.get("colour") or COLOURS.get(t["kind"], "#4FA3FF"),
                "output": t.get("output", ""), "members": members, "summary": summary, "open": t.get("open", True), "lane": t.get("lane", "volume"),
                "midiFx": t.get("midiFx") or {}, "outputName": (self._t(t.get("output", "")) or {}).get("name", ""),
                "hidden": bool(t.get("output") and not (self._t(t["output"]) or {}).get("open", True))}

    def _peaks(self, r: dict, file: str, count: int) -> list:
        """A recording's shape as the region plays it: from its offset, reversed, and stretched to the tempo."""
        if self._demo:
            return []
        path = file
        if self._folder and not os.path.isabs(path):
            path = str(self._folder / path)
        a = se.load_audio(path)
        if not a.size:
            return []
        if r.get("reverse"):
            a = a[::-1]
        tempo = float(self._p.get("tempo", 120))
        ratio = float(r.get("srcTempo") or tempo) / tempo if r.get("follow") else 1.0
        off = int(float(r.get("offset", 0)) * se.SR)
        seg = a[off:off + int(se.beats_to_s(float(r["length"]), tempo) * se.SR / ratio)]
        return se.peaks(seg, count) if seg.size else []

    hasSong = Property(bool, lambda self: self._p is not None, notify=changed)
    song = Property("QVariantMap", lambda self: {k: v for k, v in (self._p or {}).items() if k not in ("tracks", "regions")}, notify=changed)
    tracks = Property("QVariantList", lambda self: [self._track_view(t) for t in (self._p or {}).get("tracks", [])], notify=changed)
    position = Property(float, lambda self: self._pos, notify=clockChanged)
    playing = Property(bool, lambda self: self._playing, notify=changed)
    recording = Property(bool, lambda self: self._recording, notify=changed)
    levels = Property("QVariantMap", lambda self: self._levels, notify=clockChanged)
    selectedTrack = Property(str, lambda self: self._sel_track, notify=changed)
    selectedRegion = Property(str, lambda self: self._sel_region, notify=changed)
    canUndo = Property(bool, lambda self: bool(self._undo), notify=changed)
    canRedo = Property(bool, lambda self: bool(self._redo), notify=changed)
    hasSound = Property(bool, lambda self: self._player.device, constant=True)
    noteNames = Property("QVariantList", lambda self: [se.note_name(p) for p in range(128)], constant=True)
    drumNames = Property("QVariantMap", lambda self: {str(k): v for k, v in se.DRUM_NAMES.items()}, constant=True)
    kitRows = Property("QVariantList", lambda self: se.KIT_ROWS, constant=True)
    effectKinds = Property("QVariantList", lambda self: [{"id": k, "name": v[0], "defaults": v[2]} for k, v in se.EFFECTS.items()], constant=True)

    @Property("QVariantList", constant=True)
    def instruments(self):
        return [{"id": k, "name": v["name"], "family": v["family"], "kit": v.get("engine") == "kit"} for k, v in se.INSTRUMENTS.items() if k != "sampler"]

    @Property("QVariantList", constant=True)
    def loops(self):
        return [{"id": i, "name": n, "family": f, "instrument": inst, "bars": b} for i, n, f, inst, _s, b in se.LOOPS]

    @Property(str, notify=clockChanged)
    def clock(self):
        """Bar.beat as the display shows it, and the time."""
        if self._p is None:
            return "1.1"
        bar, beat = self._mm().where(self._pos)
        return f"{bar}.{beat}"

    @Property(str, notify=clockChanged)
    def time(self):
        if self._p is None:
            return "0:00.0"
        s = self._tm().seconds(self._pos)
        return f"{int(s // 60)}:{s % 60:04.1f}"

    @Property(float, notify=changed)
    def length(self):
        return se.song_length(self._p or {})

    def _t(self, tid: str) -> dict:
        return next((t for t in (self._p or {}).get("tracks", []) if t["id"] == tid), None)

    def _r(self, rid: str) -> dict:
        return next((r for r in (self._p or {}).get("regions", []) if r["id"] == rid), None)

    @Slot(str, result="QVariantMap")
    def region(self, rid: str) -> dict:
        """One region with its notes, for the editors."""
        r = self._r(rid)
        if not r:
            return {}
        t = self._t(r["track"]) or {}
        kit = se.settings(t.get("instrument") or {}).get("engine") == "kit"
        views = []
        for k, tk in enumerate(r.get("takes") or []):            # each take, small, for picking and comping
            if r.get("kind") == "audio":
                views.append({"name": tk.get("name", f"Take {k + 1}"), "peaks": self._peaks(r, tk.get("file", ""), max(16, int(r["length"] * 8))) or tk.get("demoPeaks", [])})
            else:
                ns = tk.get("notes") or []
                ps = [n["p"] for n in ns] or [60]
                views.append({"name": tk.get("name", f"Take {k + 1}"), "notes": [[n["t"], n["d"], n["p"]] for n in ns], "low": min(ps), "high": max(ps)})
        return {**r, "notes": [dict(n, i=i) for i, n in enumerate(r.get("notes") or [])], "kit": kit, "trackKind": t.get("kind", ""),
                "colour": self._track_view(t)["colour"] if t else "", "takeViews": views, "comp": r.get("comp") or [], "take": int(r.get("take", 0)),
                "span": self._tm().clock(float(r["start"]))(float(r["length"]))}

    @Slot(str, result="QVariantList")
    def smartControls(self, tid: str) -> list:
        t = self._t(tid)
        if not t:
            return []
        inst = t.get("instrument") or {}
        if inst.get("id") == "plugin":                        # a plugin instrument: its first dozen knobs
            params = inst.get("params") or {}
            return [{"key": "param:" + c["symbol"], "name": c["name"], "low": c["min"], "high": c["max"], "value": float(params.get(c["symbol"], c["default"]))}
                    for c in self.pluginControls(inst.get("uri", "")) if not c["toggle"] and not c["choices"]][:12]
        s = se.settings(t.get("instrument") or {})
        out = []
        for key, name, lo, hi in se.SMART.get(s.get("engine", "sub"), []):
            if key.startswith("bar"):
                value = float(s.get(key, (s.get("bars") or [0] * 8)[int(key[3:])]))
            else:
                value = float(s.get(key, {"tune": 0, "decay": 1, "punch": 0.5, "tone": 0}.get(key, lo)))
            out.append({"key": key, "name": name, "low": lo, "high": hi, "value": value})
        return out

    # ---------------------------------------------------------------- the song's settings
    @Slot(str, "QVariant")
    def setSong(self, key: str, value) -> None:
        if self._p is None:
            return
        value = value.toVariant() if hasattr(value, "toVariant") else value
        if key == "tempo":
            value = round(max(40.0, min(240.0, float(value))), 1)
        elif key == "key":
            value = int(value) % 12
        elif key == "mode":
            if value not in ("major", "minor"):
                return
        elif key == "sig":
            value = [int(value[0]), int(value[1])]
        elif key not in ("metronome", "countIn", "cycle"):
            return
        self._before(("song", key))
        self._p[key] = value
        if key in ("key", "mode", "sig"):                    # loops and drummers follow the song
            self._refresh_generated()
        self._keep()
        self.clockChanged.emit()

    @Slot(str, "QVariant")
    def setMaster(self, key: str, value) -> None:
        if self._p is None:
            return
        self._before(("master", key))
        self._p.setdefault("master", {})[key] = float(value) if not isinstance(value, (list, dict)) else value
        self._keep()

    # ---------------------------------------------------------------- tempo and time-signature changes
    @Property(float, notify=clockChanged)
    def tempoNow(self):
        """The tempo where the playhead is (the song's own tempo when it never changes)."""
        return round(self._tm().tempo_at(self._pos), 1) if self._p else 120.0

    @Property("QVariantList", notify=clockChanged)
    def sigNow(self):
        return list(self._mm().sig_at(self._pos)) if self._p else [4, 4]

    @Slot(float, float, result="QVariantList")
    def bars(self, b0: float, b1: float) -> list:
        """The bar lines between two beats: [beat, its number, its signature where it changes (else "")]."""
        if self._p is None:
            return []
        out, last = [], None
        for b, n, sig in self._mm().bars(max(0.0, b1)):
            mark = f"{sig[0]}/{sig[1]}" if (last is not None and list(sig) != last) else ""
            last = list(sig)
            if b >= b0 - 1e-6:
                out.append([b, n, mark])
        return out

    @Slot(float, float, int, result="QVariantList")
    def tempoCurve(self, b0: float, b1: float, steps: int) -> list:
        """[beat, bpm] along the song, for drawing the tempo line."""
        if self._p is None or steps < 2:
            return []
        tm = self._tm()
        pts = sorted({max(0.0, b0 + (b1 - b0) * k / (steps - 1)) for k in range(steps)} | {p[0] for p in tm.pts if b0 <= p[0] <= b1}
                     | {p[0] - 1e-4 for p in tm.pts if b0 <= p[0] - 1e-4 <= b1})
        return [[b, round(tm.tempo_at(b), 2)] for b in pts]

    @Slot(float)
    def setTempoHere(self, bpm: float) -> None:
        """The tempo display: changes the tempo playing where the playhead is (a change's, or the song's own)."""
        changes = (self._p or {}).get("tempoChanges") or []
        here = [i for i, c in enumerate(changes) if float(c["beat"]) <= self._pos + 1e-6]
        if here:
            self.setTempoChange(here[-1], "bpm", bpm)
        else:
            self.setSong("tempo", bpm)

    @Slot(float, result=int)
    def addTempoChange(self, beat: float) -> int:
        """A tempo change at a beat (the nearest), at the tempo already there; its place in the list."""
        if self._p is None:
            return -1
        beat = round(max(1.0, float(beat)))
        changes = self._p.setdefault("tempoChanges", [])
        if any(abs(float(c["beat"]) - beat) < 1e-6 for c in changes):
            return next(i for i, c in enumerate(changes) if abs(float(c["beat"]) - beat) < 1e-6)
        self._before()
        changes.append({"beat": beat, "bpm": round(self._tm().tempo_at(beat), 1), "glide": False})
        changes.sort(key=lambda c: float(c["beat"]))
        self._keep()
        return next(i for i, c in enumerate(changes) if abs(float(c["beat"]) - beat) < 1e-6)

    @Slot(int, str, "QVariant")
    def setTempoChange(self, index: int, key: str, value) -> None:
        changes = (self._p or {}).get("tempoChanges") or []
        if not 0 <= index < len(changes) or key not in ("bpm", "beat", "glide"):
            return
        value = value.toVariant() if hasattr(value, "toVariant") else value
        self._before(("tempoChange", index, key))
        c = changes[index]
        if key == "bpm":
            c["bpm"] = round(max(20.0, min(400.0, float(value))), 1)
        elif key == "glide":
            c["glide"] = bool(value)
        else:
            beat = round(max(1.0, float(value)) * 4) / 4      # moved along: on a sixteenth, never onto another change
            if not any(abs(float(o["beat"]) - beat) < 1e-6 for o in changes if o is not c):
                c["beat"] = beat
                changes.sort(key=lambda x: float(x["beat"]))
        self._keep()

    @Slot(int)
    def removeTempoChange(self, index: int) -> None:
        changes = (self._p or {}).get("tempoChanges") or []
        if 0 <= index < len(changes):
            self._before()
            changes.pop(index)
            self._keep()

    @Slot(float, int, int)
    def setSignatureAt(self, beat: float, num: int, den: int) -> None:
        """The time signature from the bar a beat is in onwards (the song's own from the first bar)."""
        if self._p is None or not (1 <= int(num) <= 32 and int(den) in (1, 2, 4, 8, 16, 32)):
            return
        at = self._bar_at(max(0.0, float(beat)))
        self._before()
        if at < 1e-6:
            self._p["sig"] = [int(num), int(den)]
        else:
            changes = [c for c in self._p.get("sigChanges") or [] if abs(float(c["beat"]) - at) > 1e-6]
            changes.append({"beat": at, "sig": [int(num), int(den)]})
            self._p["sigChanges"] = sorted(changes, key=lambda c: float(c["beat"]))
        self._keep()

    @Slot(float)
    def removeSignatureAt(self, beat: float) -> None:
        changes = (self._p or {}).get("sigChanges") or []
        keep = [c for c in changes if abs(float(c["beat"]) - float(beat)) > 1e-6]
        if len(keep) != len(changes):
            self._before()
            self._p["sigChanges"] = keep
            self._keep()

    # ---------------------------------------------------------------- tracks
    def _add_track(self, kind: str, inst: str, name: str = "") -> dict:
        inst = inst or {"audio": "", "drummer": "drums"}.get(kind, "grand")
        info = se.INSTRUMENTS.get(inst, {})
        t = {"id": self._id("t"), "kind": kind, "name": name or (info.get("name") if kind != "audio" else "Audio"),
             "instrument": {"id": inst} if inst else {}, "volume": -3.0, "pan": 0.0, "mute": False, "solo": False, "arm": False,
             "reverb": 0.15 if kind != "drummer" else 0.08, "echo": 0.0, "effects": [{"kind": "eq", "params": {}, "on": True}, {"kind": "comp", "params": {}, "on": kind != "instrument"}],
             "automation": {}}
        if kind == "drummer":
            t["drummer"] = {"style": "pop" if inst != "electronic" else "house", "complexity": 0.5, "loudness": 0.55, "fills": 0.4}
        self._p["tracks"].append(t)
        return t

    @Slot(str, str, result=str)
    def addTrack(self, kind: str, inst: str) -> str:
        if self._p is None:
            return ""
        self._before()
        t = self._add_track(kind, inst)
        if kind == "drummer":
            self._p["regions"].append(self._drummer_region(t, 0, max(8, int(se.song_length(self._p) // int(self._p["sig"][0])) or 8)))
        self._sel_track = t["id"]
        self._keep()
        return t["id"]

    @Slot(str)
    def removeTrack(self, tid: str) -> None:
        self._before()
        for o in self._p["tracks"]:                            # taking a stack away keeps its tracks
            if o.get("output") == tid:
                o.pop("output", None)
            for f in o.get("effects", []):                    # and nothing listens for a track that's gone
                if (f.get("params") or {}).get("key") == tid:
                    f["params"].pop("key")
        self._p["tracks"] = [t for t in self._p["tracks"] if t["id"] != tid]
        self._p["regions"] = [r for r in self._p["regions"] if r["track"] != tid]
        if self._sel_track == tid:
            self._sel_track = self._p["tracks"][0]["id"] if self._p["tracks"] else ""
        self._keep()

    @Slot(str, int)
    def moveTrack(self, tid: str, to: int) -> None:
        tr = self._p["tracks"]
        i = next((k for k, t in enumerate(tr) if t["id"] == tid), -1)
        if i >= 0 and 0 <= to < len(tr) and to != i:
            self._before()
            tr.insert(to, tr.pop(i))
            self._keep()

    @Slot(str, str, "QVariant")
    def setTrack(self, tid: str, key: str, value) -> None:
        t = self._t(tid)
        if not t or key not in ("name", "volume", "pan", "mute", "solo", "arm", "reverb", "echo", "colour", "lane", "open"):
            return
        value = value.toVariant() if hasattr(value, "toVariant") else value
        if key == "volume":
            value = round(max(-60.0, min(6.0, float(value))), 1)
        elif key == "pan":
            value = round(max(-1.0, min(1.0, float(value))), 2)
        elif key in ("reverb", "echo"):
            value = round(max(0.0, min(1.0, float(value))), 2)
        self._before(("track", tid, key) if key in ("volume", "pan", "reverb", "echo") else None)
        t[key] = value
        if key == "arm" and value:                           # one armed track at a time, like a tape machine
            for o in self._p["tracks"]:
                if o is not t:
                    o["arm"] = False
        self._keep()

    @Slot(str)
    def selectTrack(self, tid: str) -> None:
        self._sel_track = tid
        self.changed.emit()

    @Slot(str, str)
    def setInstrument(self, tid: str, inst: str) -> None:
        t = self._t(tid)
        if not t or inst not in se.INSTRUMENTS:
            return
        self._before()
        t["instrument"] = {"id": inst}
        if t["kind"] == "audio":
            t["kind"] = "instrument"
        if t["name"] in [v["name"] for v in se.INSTRUMENTS.values()] or not t["name"]:
            t["name"] = se.INSTRUMENTS[inst]["name"]
        self._keep()

    @Slot(str, str, float)
    def setSmart(self, tid: str, key: str, value: float) -> None:
        t = self._t(tid)
        if not t:
            return
        if key.startswith("param:"):                         # a plugin instrument's knob
            self.setPluginParam(tid, -1, key[6:], value)
            return
        self._before(("smart", tid, key))
        t.setdefault("instrument", {"id": "grand"})[key] = round(float(value), 4)
        self._keep()

    @Slot(str, str)
    def addEffect(self, tid: str, kind: str) -> None:
        t = self._t(tid) if tid != "master" else self._p.setdefault("master", {})
        if t is None or kind not in se.EFFECTS:
            return
        self._before()
        t.setdefault("effects", []).append({"kind": kind, "params": {}, "on": True})
        self._keep()

    @Slot(str, int, str, "QVariant")
    def setEffect(self, tid: str, index: int, key: str, value) -> None:
        t = self._t(tid) if tid != "master" else self._p.get("master", {})
        fx = (t or {}).get("effects", [])
        if not 0 <= index < len(fx):
            return
        value = value.toVariant() if hasattr(value, "toVariant") else value
        self._before(("fx", tid, index, key))
        if key == "on":
            fx[index]["on"] = bool(value)
        else:
            fx[index].setdefault("params", {})[key] = value
        self._keep()

    @Slot(str, int)
    def removeEffect(self, tid: str, index: int) -> None:
        t = self._t(tid) if tid != "master" else self._p.get("master", {})
        if t and 0 <= index < len(t.get("effects", [])):
            self._before()
            t["effects"].pop(index)
            auto = {}
            for k, v in (t.get("automation") or {}).items():    # lines drawn for it go; later effects' lines move up
                b = k.split(".")
                if len(b) == 3 and b[0] == "fx" and b[1].isdigit():
                    i = int(b[1])
                    if i == index:
                        continue
                    if i > index:
                        k = f"fx.{i - 1}.{b[2]}"
                auto[k] = v
            t["automation"] = auto
            if t.get("lane", "").startswith("fx."):
                t["lane"] = "volume"
            self._keep()

    @Slot(str, result="QVariantList")
    def effectsOf(self, tid: str) -> list:
        t = self._t(tid) if tid != "master" else (self._p or {}).get("master", {})
        out = []
        for f in (t or {}).get("effects", []):
            if f["kind"] == "plugin":
                params = {c["symbol"]: c["default"] for c in self.pluginControls(f.get("uri", ""))}
                params.update(f.get("params") or {})
                info = self._plugin_info(f.get("uri", ""))
                out.append({"kind": "plugin", "name": f.get("name") or info.get("name", "Plugin"), "on": f.get("on", True), "params": params,
                            "uri": f.get("uri", ""), "category": info.get("category", ""), "author": info.get("author", ""),
                            "missing": self._plugin_state == "ready" and not info})
                continue
            params = dict(se.EFFECTS.get(f["kind"], ("", None, {}))[2])
            params.update(f.get("params") or {})
            out.append({"kind": f["kind"], "name": se.EFFECTS.get(f["kind"], ("?",))[0], "on": f.get("on", True), "params": params})
        return out

    # ---------------------------------------------------------------- plugins (LV2: huginn_tempo_lv2)
    def _find_plugins(self) -> None:
        """(A thread.) What's installed, from the list kept between starts or a fresh scan when something changed."""
        try:
            found = se.lv2.catalogue()
            se.lv2.HOST.loaded()                               # read once now, so the first plugin played doesn't wait
        except Exception:                                     # noqa: BLE001
            found = []

        def done():
            self._plugins, self._plugin_state = found, "ready"
            self.pluginsChanged.emit()
            self.changed.emit()
        self._back.emit(done)

    plugins = Property("QVariantList", lambda self: self._plugins, notify=pluginsChanged)
    pluginState = Property(str, lambda self: self._plugin_state, notify=pluginsChanged)

    @Property("QVariantList", notify=pluginsChanged)
    def pluginInstruments(self):
        return [{"id": "plugin:" + d["uri"], "uri": d["uri"], "name": d["name"], "family": "Plugins", "kit": "drum" in d["name"].lower() or "percussion" in d["name"].lower()}
                for d in self._plugins if d["kind"] == "instrument"]

    @staticmethod
    def _plugin_family(inst: dict) -> str:
        """A plugin instrument's family: a kit's is Drums (written in the drum grid, General MIDI's drum notes), else Plugins."""
        if inst.get("id") != "plugin":
            return ""
        name = (inst.get("name") or "").lower()
        return "Drums" if "drum" in name or "percussion" in name else "Plugins"

    @Slot(str, int, result="QVariantMap")
    def pluginValues(self, tid: str, index: int) -> dict:
        """Where a plugin's knobs are now: an effect's (its place) or the instrument's (-1), defaults filled in."""
        t = self._t(tid) if tid != "master" else (self._p or {}).get("master", {})
        if not t:
            return {}
        target = t.get("instrument") if index < 0 else ((t.get("effects") or [])[index] if 0 <= index < len(t.get("effects") or []) else None)
        if not target:
            return {}
        out = {c["symbol"]: c["default"] for c in self.pluginControls(target.get("uri", ""))}
        out.update(target.get("params") or {})
        return out

    def _plugin_info(self, uri: str) -> dict:
        return next((d for d in self._plugins if d["uri"] == uri), {})

    @Slot(str, result="QVariantList")
    def pluginControls(self, uri: str) -> list:
        if not uri or se.lv2 is None or self._plugin_state != "ready":
            return []
        if uri not in self._plugin_controls:
            try:
                self._plugin_controls[uri] = se.lv2.controls(uri)
            except Exception:                                 # noqa: BLE001
                self._plugin_controls[uri] = []
        return self._plugin_controls[uri]

    @Slot(str, result="QVariantList")
    def pluginPresets(self, uri: str) -> list:
        if not uri or se.lv2 is None or self._plugin_state != "ready":
            return []
        try:
            return [d["name"] for d in se.lv2.presets(uri)]
        except Exception:                                     # noqa: BLE001
            return []

    @Slot(str, str)
    def addPlugin(self, tid: str, uri: str) -> None:
        """A plugin effect at the end of a track's (or a stack's, or the master's) effects."""
        t = self._t(tid) if tid != "master" else self._p.setdefault("master", {})
        info = self._plugin_info(uri)
        if t is None or not info or info["kind"] != "effect":
            return
        self._before()
        t.setdefault("effects", []).append({"kind": "plugin", "uri": uri, "name": info["name"], "params": {}, "on": True})
        self._keep()

    @Slot(str, str)
    def usePluginInstrument(self, tid: str, uri: str) -> None:
        t = self._t(tid)
        info = self._plugin_info(uri)
        if not t or not info or info["kind"] != "instrument":
            return
        self._before()
        old = (t.get("instrument") or {}).get("name") or se.INSTRUMENTS.get((t.get("instrument") or {}).get("id", ""), {}).get("name", "")
        t["instrument"] = {"id": "plugin", "uri": uri, "name": info["name"], "params": {}}
        if t["kind"] == "audio":
            t["kind"] = "instrument"
        if not t.get("name") or t["name"] == old or t["name"] in [v["name"] for v in se.INSTRUMENTS.values()]:
            t["name"] = info["name"]
        self._keep()

    @Slot(str, int, str, "QVariant")
    def setPluginParam(self, tid: str, index: int, symbol: str, value) -> None:
        """A plugin's knob: an effect's (its place in the list) or the instrument's (-1)."""
        value = value.toVariant() if hasattr(value, "toVariant") else value
        try:
            value = float(value)
        except (TypeError, ValueError):
            return
        if index >= 0:
            t = self._t(tid) if tid != "master" else (self._p or {}).get("master", {})
            fx = (t or {}).get("effects", [])
            if 0 <= index < len(fx):
                fx[index].pop("preset", None)                  # turned by hand: no longer the preset as it came
            self.setEffect(tid, index, symbol, value)
            return
        t = self._t(tid)
        if not t or (t.get("instrument") or {}).get("id") != "plugin":
            return
        self._before(("plugin", tid, symbol))
        t["instrument"].setdefault("params", {})[symbol] = value
        t["instrument"].pop("preset", None)
        self._keep()

    @Slot(str, int, result=str)
    def pluginPreset(self, tid: str, index: int) -> str:
        """The preset a plugin is set to, as long as no knob has been turned since."""
        t = self._t(tid) if tid != "master" else (self._p or {}).get("master", {})
        if not t:
            return ""
        target = t.get("instrument") if index < 0 else ((t.get("effects") or [])[index] if 0 <= index < len(t.get("effects") or []) else None)
        return (target or {}).get("preset", "")

    @Slot(str, int, str)
    def applyPluginPreset(self, tid: str, index: int, name: str) -> None:
        t = self._t(tid) if tid != "master" else (self._p or {}).get("master", {})
        if not t:
            return
        target = t.get("instrument") if index < 0 else (t.get("effects") or [None] * (index + 1))[index]
        if not target or (index < 0 and target.get("id") != "plugin") or (index >= 0 and target.get("kind") != "plugin"):
            return
        preset = next((d for d in se.lv2.presets(target.get("uri", "")) if d["name"] == name), None)
        if preset is None:
            return
        self._before()
        target["params"] = dict(preset["values"])
        target["preset"] = name
        self._keep()

    def _param_range(self, t: dict, param: str):
        """[low, high, name, unit, value now] for a knob that can be drawn over time, or None."""
        fixed = {"volume": [-60, 6, "Volume", "dB", float(t.get("volume", 0))], "pan": [-1, 1, "Pan", "", float(t.get("pan", 0))],
                 "reverb": [0, 1, "Reverb send", "", float(t.get("reverb", 0))], "echo": [0, 1, "Echo send", "", float(t.get("echo", 0))]}
        if param in fixed:
            return fixed[param]
        bits = param.split(".")
        if len(bits) == 3 and bits[0] == "fx" and bits[1].isdigit():
            fx = t.get("effects", [])
            i = int(bits[1])
            if 0 <= i < len(fx) and fx[i]["kind"] == "plugin":
                c = next((c for c in self.pluginControls(fx[i].get("uri", "")) if c["symbol"] == bits[2]), None)
                if c:
                    return [c["min"], c["max"], f"{fx[i].get('name', 'Plugin')} · {c['name']}", "", float((fx[i].get("params") or {}).get(bits[2], c["default"]))]
                return None
            if 0 <= i < len(fx):
                rng = se.PARAM_RANGES.get(fx[i]["kind"], {}).get(bits[2])
                if rng:
                    params = dict(se.EFFECTS[fx[i]["kind"]][2])
                    params.update(fx[i].get("params") or {})
                    return [rng[0], rng[1], f"{se.EFFECTS[fx[i]['kind']][0]} · {se.PARAM_NAMES.get(bits[2], bits[2])}", rng[2], float(params.get(bits[2], rng[0]))]
        return None

    @Slot(str, result="QVariantList")
    def automatable(self, tid: str) -> list:
        """Every knob of a track that can be drawn over time, for the lane's menu."""
        t = self._t(tid)
        if not t:
            return []
        params = ["volume", "pan", "reverb", "echo"]
        for i, f in enumerate(t.get("effects", [])):
            if f["kind"] == "plugin":                         # a plugin's knobs (not its switches or lists), the first 48
                params += [f"fx.{i}.{c['symbol']}" for c in self.pluginControls(f.get("uri", "")) if not c["toggle"] and not c["choices"]][:48]
            else:
                params += [f"fx.{i}.{k}" for k in se.PARAM_RANGES.get(f["kind"], {})]
        out = []
        for prm in params:
            rng = self._param_range(t, prm)
            if rng is None:
                continue
            lo, hi, name, unit, value = rng
            out.append({"param": prm, "name": name, "low": lo, "high": hi, "unit": unit, "value": value, "drawn": bool((t.get("automation") or {}).get(prm))})
        return out

    @Slot(str, str, "QVariantList")
    def setAutomation(self, tid: str, param: str, points) -> None:
        t = self._t(tid)
        if not t or self._param_range(t, param) is None:
            return
        pts = points.toVariant() if hasattr(points, "toVariant") else points
        lo, hi = self._param_range(t, param)[:2]
        self._before(("auto", tid, param))
        clean = sorted([[round(max(0.0, float(a)), 3), round(max(lo, min(hi, float(b))), 3)] for a, b in pts])
        if clean:
            t.setdefault("automation", {})[param] = clean
        else:
            (t.get("automation") or {}).pop(param, None)
        self._keep()


    # ================================================================ the pro pass
    # ---- audio regions: gain, fades, reverse, transpose, following the tempo
    @Slot(str, str, "QVariant")
    def setRegion(self, rid: str, key: str, value) -> None:
        r = self._r(rid)
        if not r:
            return
        value = value.toVariant() if hasattr(value, "toVariant") else value
        audio_keys = ("gain", "fadeIn", "fadeOut", "reverse", "transpose", "follow")
        if key not in ("name", "muted") + audio_keys or (key in audio_keys and r.get("kind") != "audio"):
            return
        tempo = self._tm().tempo_at(float(r["start"]))
        span = self._tm().clock(float(r["start"]))(float(r["length"]))
        self._before(("region", rid, key))
        if key == "gain":
            value = round(max(-30.0, min(12.0, float(value))), 1)
        elif key in ("fadeIn", "fadeOut"):
            value = round(max(0.0, min(span, float(value))), 3)
        elif key == "transpose":
            value = round(max(-24.0, min(24.0, float(value))), 2)
        elif key in ("reverse", "follow", "muted"):
            value = bool(value)
            if key == "follow" and value:
                r.setdefault("srcTempo", tempo)
        else:
            value = str(value)[:60]
        r[key] = value
        self._keep()

    # ---- takes: every pass round the cycle while recording, and comps cut from them
    def _take_wrap(self) -> None:
        """The cycle went round while recording: what was played becomes a take, and the next pass starts."""
        rec = self._rec
        cyc = (self._p or {}).get("cycle") or {}
        if not rec or not cyc.get("on"):
            return
        c0, c1 = float(cyc["start"]), float(cyc["end"])
        for p in list(self._held):                           # notes held across the turn end with the pass
            start, vel = self._held[p]
            rec["notes"].append({"t": start, "d": max(1 / 32, c1 - start), "p": p, "v": vel})
            self._held[p] = (c0, vel)
        rec.setdefault("passes", []).append(rec["notes"])
        rec["notes"] = []

    def _finish_takes(self, rec: dict) -> bool:
        """Several passes round the cycle: one region over the cycle with a take for each pass (the last one
        playing). Gives False when there's only one pass, for the usual recording."""
        cyc = self._p.get("cycle") or {}
        if not cyc.get("on"):
            return False
        c0, c1 = float(cyc["start"]), float(cyc["end"])
        length = c1 - c0
        if rec["kind"] == "notes":
            passes = [ps for ps in rec.get("passes", []) + [rec["notes"]] if ps]
            if len(passes) < 2:
                return False
            takes = [{"name": f"Take {k + 1}", "notes": [dict(n, t=round(n["t"] - c0, 4)) for n in ps if c0 - 1e-6 <= n["t"] < c1]} for k, ps in enumerate(passes)]
            self._before()
            self._p["regions"].append({"id": self._id("r"), "track": rec["track"], "start": c0, "length": length, "kind": "midi", "name": "Takes",
                                       "notes": copy.deepcopy(takes[-1]["notes"]), "takes": takes, "take": len(takes) - 1})
            self._keep()
            self.said.emit(f"{len(takes)} takes. Pick the best, or comp the best parts of each.", False)
            return True
        data = rec.get("audio")
        if data is None:
            return False
        tm = self._tm()
        first = int((tm.seconds(c1) - tm.seconds(float(rec["start"]))) * se.SR)   # the first pass may start partway round
        span = int((tm.seconds(c0 + length) - tm.seconds(c0)) * se.SR)
        if len(data) < first + span // 2:
            return False
        pieces = []
        lead = int((tm.seconds(float(rec["start"])) - tm.seconds(c0)) * se.SR)
        pieces.append(np.concatenate([np.zeros((max(0, lead), 2), np.float32), data[:first]]))
        k = first
        while k + se.SR // 10 < len(data):
            pieces.append(data[k:k + span])
            k += span
        folder = (self._folder / "audio") if self._folder else Path("/tmp")
        folder.mkdir(parents=True, exist_ok=True)
        takes = []
        for n, piece in enumerate(pieces):
            fname = f"take-{n + 1}-{uuid.uuid4().hex[:6]}.wav"
            se.write_wav(str(folder / fname), piece, 24)
            takes.append({"name": f"Take {n + 1}", "file": f"audio/{fname}" if self._folder else str(folder / fname)})
        self._before()
        self._p["regions"].append({"id": self._id("r"), "track": rec["track"], "start": c0, "length": length, "kind": "audio", "name": "Takes",
                                   "file": takes[-1]["file"], "offset": 0.0, "gain": 0.0, "srcTempo": tempo, "takes": takes, "take": len(takes) - 1})
        self._keep()
        self.said.emit(f"{len(takes)} takes. Pick the best, or comp the best parts of each.", False)
        return True

    def _apply_comp(self, r: dict) -> None:
        if r.get("kind") == "audio" or not r.get("comp"):
            return
        notes = []                                           # MIDI comps are put together straight away
        for b0, b1, k in r["comp"]:
            notes += [copy.deepcopy(n) for n in r["takes"][k].get("notes", []) if b0 - 1e-6 <= n["t"] < b1]
        r["notes"] = sorted(notes, key=lambda n: (n["t"], n["p"]))

    @Slot(str, int)
    def chooseTake(self, rid: str, k: int) -> None:
        r = self._r(rid)
        if not r or not 0 <= k < len(r.get("takes") or []):
            return
        self._before()
        r["take"] = int(k)
        r.pop("comp", None)
        if r.get("kind") == "audio":
            r["file"] = r["takes"][k]["file"]
        else:
            r["notes"] = copy.deepcopy(r["takes"][k].get("notes", []))
        self._keep()

    @Slot(str, float, float, int)
    def compTake(self, rid: str, b0: float, b1: float, k: int) -> None:
        """Use take k from b0 to b1 (beats into the region): swipe across the best bit of each take."""
        r = self._r(rid)
        if not r or not 0 <= k < len(r.get("takes") or []):
            return
        length = float(r["length"])
        b0, b1 = sorted((max(0.0, min(length, round(float(b0) * 16) / 16)), max(0.0, min(length, round(float(b1) * 16) / 16))))
        if b1 - b0 < 1 / 16:
            return
        self._before()
        comp = r.get("comp") or [[0.0, length, int(r.get("take", 0))]]
        out = []
        for a, b, t in comp:                                  # cut the range out of what's there, then put it in
            if b <= b0 or a >= b1:
                out.append([a, b, t])
                continue
            if a < b0:
                out.append([a, b0, t])
            if b > b1:
                out.append([b1, b, t])
        out.append([b0, b1, int(k)])
        out.sort()
        merged = []
        for seg in out:
            if merged and merged[-1][2] == seg[2] and abs(merged[-1][1] - seg[0]) < 1e-6:
                merged[-1][1] = seg[1]
            else:
                merged.append(seg)
        r["comp"] = merged
        self._apply_comp(r)
        self._keep()

    @Slot(str)
    def flattenTakes(self, rid: str) -> None:
        """Keep what plays now (the take or the comp) and let the other takes go."""
        r = self._r(rid)
        if not r or not r.get("takes"):
            return
        self._before()
        if r.get("kind") == "audio" and r.get("comp"):
            m = se.Mixer({"tempo": self._p["tempo"], "tempoChanges": self._p.get("tempoChanges") or [], "tracks": [], "regions": []}, self._folder)
            audio = m._region_audio({}, dict(r, follow=False, reverse=False, transpose=0, gain=0, fadeIn=0, fadeOut=0))
            folder = (self._folder / "audio") if self._folder else Path("/tmp")
            fname = f"comp-{uuid.uuid4().hex[:6]}.wav"
            se.write_wav(str(folder / fname), audio, 24)
            r["file"], r["offset"] = (f"audio/{fname}" if self._folder else str(folder / fname)), 0.0
        for key in ("takes", "take", "comp"):
            r.pop(key, None)
        self._keep()

    # ---- track stacks and sidechain
    @Slot("QVariantList", result=str)
    def makeStack(self, tids) -> str:
        """The tracks given play into a new stack (a bus with its own effects and fader), shown above them."""
        tids = tids.toVariant() if hasattr(tids, "toVariant") else list(tids)
        members = [t for t in self._p["tracks"] if t["id"] in tids and t["kind"] != "stack"]
        if not members:
            return ""
        self._before()
        stack = {"id": self._id("t"), "kind": "stack", "name": "Stack", "instrument": {}, "volume": 0.0, "pan": 0.0, "mute": False, "solo": False,
                 "arm": False, "reverb": 0.0, "echo": 0.0, "effects": [{"kind": "eq", "params": {}, "on": True}, {"kind": "comp", "params": {"ratio": 2, "threshold": -14}, "on": True}],
                 "automation": {}, "open": True}
        first = min(self._p["tracks"].index(t) for t in members)
        rest = [t for t in self._p["tracks"] if t not in members]
        at = len([t for t in self._p["tracks"][:first] if t not in members])
        for t in members:
            t["output"] = stack["id"]
        self._p["tracks"] = rest[:at] + [stack] + members + rest[at:]
        self._sel_track = stack["id"]
        self._keep()
        return stack["id"]

    @Slot(str, str)
    def setOutput(self, tid: str, sid: str) -> None:
        """Send a track into a stack ("" for straight to the master), moving it under the stack."""
        t = self._t(tid)
        if not t or t["kind"] == "stack" or (sid and (self._t(sid) or {}).get("kind") != "stack"):
            return
        self._before()
        if sid:
            t["output"] = sid
            tr = self._p["tracks"]
            tr.remove(t)
            pos = tr.index(self._t(sid)) + 1
            while pos < len(tr) and tr[pos].get("output") == sid:
                pos += 1
            tr.insert(pos, t)
        else:
            t.pop("output", None)
        self._keep()

    @Slot(str, str)
    def duckUnder(self, tid: str, key: str) -> None:
        """This track dips whenever the `key` track plays (a compressor listening to it): the bass under the kick."""
        t, k = self._t(tid), self._t(key)
        if not t or not k or tid == key:
            return
        self._before()
        t.setdefault("effects", []).append({"kind": "comp", "on": True, "params": {"key": key, "threshold": -32, "ratio": 8, "attack": 0.003, "release": 0.16, "makeup": 0}})
        self._keep()
        self.said.emit(f"{t['name']} dips whenever {k['name']} plays.", False)

    @Property("QVariantList", notify=changed)
    def stacks(self):
        return [{"id": t["id"], "name": t["name"]} for t in (self._p or {}).get("tracks", []) if t["kind"] == "stack"]

    # ---- the sampler and drum pads
    def _bring_in(self, url) -> tuple:
        """A sound file from a drop (or path) copied into the song's folder: (path in the song, its audio)."""
        path = url.toLocalFile() if hasattr(url, "toLocalFile") else (str(url)[7:] if str(url).startswith("file://") else str(url))
        a = se.load_audio(path)
        if not a.size:
            self.said.emit(f"{Path(path).name} isn't a sound Tempo can read.", True)
            return "", None
        if self._folder is None:
            return path, a
        (self._folder / "audio").mkdir(parents=True, exist_ok=True)
        fname = f"{re.sub(r'[^A-Za-z0-9]+', '-', Path(path).stem).strip('-')[:30] or 'sound'}-{uuid.uuid4().hex[:6]}.wav"
        se.write_wav(str(self._folder / "audio" / fname), a, 24)
        return f"audio/{fname}", a

    @Slot(str, "QVariant", result=str)
    def makeSampler(self, tid: str, url) -> str:
        """Play a sound across the keys: on this track (or a new one). Its own note is heard, so it stays in tune."""
        if self._p is None:
            return ""
        rel, a = self._bring_in(url)
        if not rel:
            return ""
        root = se.detect_pitch(a.mean(axis=1))
        name = Path(url.toLocalFile() if hasattr(url, "toLocalFile") else str(url)).stem[:24]
        self._before()
        t = self._t(tid)
        if t is None or t["kind"] in ("stack", "drummer"):
            t = self._add_track("instrument", "sampler", name)
        t["kind"] = "instrument" if t["kind"] == "audio" else t["kind"]
        t["instrument"] = {"id": "sampler", "file": rel, "root": round(root) if root else 60, "sound": name,
                           "mode": "oneshot" if len(a) < se.SR * 0.6 else "held"}
        self._sel_track = t["id"]
        self._keep()
        self.said.emit(f"Heard {name} as {se.note_name(round(root))}{round(root) // 12 - 1}: it plays in tune across the keys." if root
                       else f"{name} has no clear note: it plays as C3 at its own pitch.", False)
        return t["id"]

    @Slot(str, int, "QVariant")
    def setPad(self, tid: str, pitch: int, url) -> None:
        """A sound of your own on one drum of a kit."""
        t = self._t(tid)
        if not t or se.settings(t.get("instrument") or {}).get("engine") != "kit":
            return
        rel, _a = self._bring_in(url)
        if not rel:
            return
        self._before()
        t.setdefault("instrument", {"id": "drums"}).setdefault("pads", {})[str(int(pitch))] = rel
        self._keep()

    @Slot(str, int)
    def clearPad(self, tid: str, pitch: int) -> None:
        t = self._t(tid)
        pads = ((t or {}).get("instrument") or {}).get("pads") or {}
        if str(pitch) in pads:
            self._before()
            pads.pop(str(pitch))
            self._keep()

    @Slot(str, str, float)
    def setSampler(self, tid: str, key: str, value: float) -> None:
        t = self._t(tid)
        if t and key in ("root",) and (t.get("instrument") or {}).get("id") == "sampler":
            self._before(("sampler", tid, key))
            t["instrument"][key] = int(max(0, min(127, round(float(value)))))
            self._keep()

    @Slot(str, str)
    def setSamplerMode(self, tid: str, mode: str) -> None:
        t = self._t(tid)
        if t and mode in ("held", "oneshot") and (t.get("instrument") or {}).get("id") == "sampler":
            self._before()
            t["instrument"]["mode"] = mode
            self._keep()

    # ---- MIDI effects
    @Slot(str, str, str, "QVariant")
    def setMidiFx(self, tid: str, which: str, key: str, value) -> None:
        """The arpeggiator ("arp": on, mode, rate, octaves, gate) or chord trigger ("chord": on, shape)."""
        t = self._t(tid)
        if not t or which not in ("arp", "chord") or t["kind"] in ("audio", "stack"):
            return
        value = value.toVariant() if hasattr(value, "toVariant") else value
        if key == "on":
            value = bool(value)
        elif key == "mode" and value not in se.ARP_MODES:
            return
        elif key == "shape" and value not in list(se.CHORD_SHAPES) + ["key"]:
            return
        elif key in ("rate", "gate"):
            value = max(0.0625 if key == "rate" else 0.05, min(1.0, float(value)))
        elif key == "octaves":
            value = int(max(1, min(4, int(value))))
        self._before(("mfx", tid, which, key))
        fx = t.setdefault("midiFx", {}).setdefault(which, {"on": False} if which == "chord" else {"on": False, "mode": "up", "rate": 0.25, "octaves": 1, "gate": 0.8})
        if which == "chord":
            fx.setdefault("shape", "major")
        fx[key] = value
        self._keep()

    arpModes = Property("QVariantList", lambda self: [{"id": k, "name": v} for k, v in se.ARP_MODES.items()], constant=True)
    chordShapes = Property("QVariantList", lambda self: [{"id": k, "name": n} for k, n in (("major", "Major"), ("minor", "Minor"), ("seventh", "Seventh"),
                                                                                            ("sus", "Suspended"), ("power", "Power"), ("octaves", "Octaves"), ("key", "In the key"))], constant=True)

    # ---- the arrangement: Intro, Verse, Chorus…
    @Property("QVariantList", notify=changed)
    def sections(self):
        return sorted((self._p or {}).get("sections", []), key=lambda x: x["start"])

    @Slot(str, float, float, result=str)
    def addSection(self, name: str, start: float, length: float) -> str:
        if self._p is None:
            return ""
        start = self._bar_round(max(0.0, float(start)))
        length = max(self._bar_len(start), self._bar_round(start + float(length)) - start)
        taken = sorted(self._p.get("sections", []), key=lambda x: x["start"])
        for sec in taken:                                     # sections don't overlap: start after one this falls in
            if sec["start"] <= start < sec["start"] + sec["length"]:
                start = sec["start"] + sec["length"]
        nxt = next((x["start"] for x in taken if x["start"] > start), None)
        if nxt is not None:
            length = min(length, nxt - start)
        if length < 1:
            return ""
        names = ["Intro", "Verse", "Chorus", "Verse", "Chorus", "Bridge", "Chorus", "Outro"]
        self._before()
        sec = {"id": self._id("s"), "name": name or names[min(len(taken), len(names) - 1)], "start": start, "length": length}
        self._p.setdefault("sections", []).append(sec)
        self._keep()
        return sec["id"]

    def _sec(self, sid: str) -> dict:
        return next((x for x in (self._p or {}).get("sections", []) if x["id"] == sid), None)

    @Slot(str, str, "QVariant")
    def setSection(self, sid: str, key: str, value) -> None:
        sec = self._sec(sid)
        if not sec or key not in ("name", "length"):
            return
        value = value.toVariant() if hasattr(value, "toVariant") else value
        self._before(("section", sid, key))
        if key == "length":
            value = max(self._bar_len(sec["start"]), self._bar_round(sec["start"] + float(value)) - sec["start"])
            nxt = min([x["start"] for x in self._p["sections"] if x["start"] > sec["start"]] or [1e9])
            value = min(value, nxt - sec["start"])
        else:
            value = str(value).strip()[:24] or sec["name"]
        sec[key] = value
        self._keep()

    @Slot(str)
    def removeSection(self, sid: str) -> None:
        """Just the marker: the music stays."""
        if self._sec(sid):
            self._before()
            self._p["sections"] = [x for x in self._p["sections"] if x["id"] != sid]
            self._keep()

    def _shift_from(self, at: float, by: float) -> None:
        """Everything from `at` on moves by `by` beats: regions, automation points, sections and the cycle."""
        for r in self._p["regions"]:
            if r["start"] >= at - 1e-6:
                r["start"] = round(r["start"] + by, 4)
        for t in self._p["tracks"]:
            for prm, pts in (t.get("automation") or {}).items():
                t["automation"][prm] = [[round(a + by, 3) if a >= at - 1e-6 else a, b] for a, b in pts]
        for x in self._p.get("sections", []):
            if x["start"] >= at - 1e-6:
                x["start"] = round(x["start"] + by, 4)

    @Slot(str, result=str)
    def duplicateSection(self, sid: str) -> str:
        """The section again, straight after it: everything after moves along to make room."""
        sec = self._sec(sid)
        if not sec:
            return ""
        a, n = sec["start"], sec["length"]
        inside = [r for r in self._p["regions"] if a - 1e-6 <= r["start"] < a + n - 1e-6]
        self._before()
        self._shift_from(a + n, n)
        for r in inside:
            c = copy.deepcopy(r)
            c["id"] = self._id("r")
            c["start"] = round(r["start"] + n, 4)
            self._p["regions"].append(c)
        for t in self._p["tracks"]:                            # its automation too
            for prm, pts in (t.get("automation") or {}).items():
                t["automation"][prm] = sorted(pts + [[round(x + n, 3), y] for x, y in pts if a <= x < a + n])
        copy_sec = {"id": self._id("s"), "name": sec["name"], "start": a + n, "length": n}
        self._p["sections"].append(copy_sec)
        self._keep()
        return copy_sec["id"]

    @Slot(str)
    def deleteSection(self, sid: str) -> None:
        """The section and its music go, and the rest of the song closes up."""
        sec = self._sec(sid)
        if not sec:
            return
        a, n = sec["start"], sec["length"]
        self._before()
        self._p["regions"] = [r for r in self._p["regions"] if not (a - 1e-6 <= r["start"] < a + n - 1e-6)]
        for t in self._p["tracks"]:
            for prm, pts in (t.get("automation") or {}).items():
                t["automation"][prm] = [[x, y] for x, y in pts if not (a <= x < a + n)]
        self._p["sections"] = [x for x in self._p["sections"] if x["id"] != sid]
        self._shift_from(a + n, -n)
        self._keep()

    @Slot(str, int)
    def moveSection(self, sid: str, to: int) -> None:
        """Put the section at another place in the order of sections (its music goes with it)."""
        secs = sorted(self._p.get("sections", []), key=lambda x: x["start"])
        sec = self._sec(sid)
        if not sec or not 0 <= to < len(secs) or secs.index(sec) == to:
            return
        a, n = sec["start"], sec["length"]
        moving = [r for r in self._p["regions"] if a - 1e-6 <= r["start"] < a + n - 1e-6]
        autos = {t["id"]: {prm: [[x - a, y] for x, y in pts if a <= x < a + n]} for t in self._p["tracks"] for prm, pts in (t.get("automation") or {}).items()}
        self._before()
        others = [x for x in secs if x is not sec]
        # take it out, close the gap, then open a gap where it goes
        self._p["regions"] = [r for r in self._p["regions"] if r not in moving]
        for t in self._p["tracks"]:
            for prm, pts in (t.get("automation") or {}).items():
                t["automation"][prm] = [[x, y] for x, y in pts if not (a <= x < a + n)]
        self._p["sections"] = others
        self._shift_from(a + n, -n)
        target = others[to]["start"] if to < len(others) else max([x["start"] + x["length"] for x in others] or [0])
        self._shift_from(target, n)
        for r in moving:
            r["start"] = round(target + (r["start"] - a), 4)
            self._p["regions"].append(r)
        for t in self._p["tracks"]:
            for prm, pts in autos.get(t["id"], {}).items():
                if pts:
                    t.setdefault("automation", {})[prm] = sorted((t.get("automation") or {}).get(prm, []) + [[round(x + target, 3), y] for x, y in pts])
        sec["start"] = target
        self._p["sections"].append(sec)
        self._keep()

    # ---------------------------------------------------------------- regions
    def _drummer_region(self, t: dict, start: float, bars: int) -> dict:
        d = t.get("drummer") or {}
        bpb = max(1, int(round(self._bar_len(start))))        # the drummer plays the bars where it is
        notes = se.drummer(d.get("style", "pop"), float(d.get("complexity", 0.5)), float(d.get("loudness", 0.5)), bars, bpb,
                           float(d.get("fills", 0.4)), seed=int(start) + 11)
        return {"id": self._id("r"), "track": t["id"], "start": float(start), "length": float(bars * bpb), "kind": "drummer", "notes": notes,
                "name": d.get("style", "pop").title()}

    def _refresh_generated(self) -> None:
        for r in self._p["regions"]:
            t = self._t(r["track"])
            if r.get("kind") == "drummer" and t:
                fresh = self._drummer_region(t, r["start"], max(1, int(round(r["length"] / self._bar_len(r["start"])))))
                r["notes"] = fresh["notes"]
            elif r.get("loop"):
                bpb = max(1, int(round(self._bar_len(r["start"]))))
                r["notes"] = se.loop_notes(r["loop"], int(self._p.get("key", 0)), self._p.get("mode", "major"), bpb)

    @Slot(str, str, "QVariant")
    def setDrummer(self, tid: str, key: str, value) -> None:
        t = self._t(tid)
        if not t or t["kind"] != "drummer":
            return
        value = value.toVariant() if hasattr(value, "toVariant") else value
        self._before(("drummer", tid, key))
        t.setdefault("drummer", {})[key] = value if key == "style" else round(max(0.0, min(1.0, float(value))), 3)
        self._refresh_generated()
        self._keep()

    @Slot(str, float, float, result=str)
    def addRegion(self, tid: str, start: float, length: float) -> str:
        t = self._t(tid)
        if not t or t["kind"] == "audio":
            return ""
        self._before()
        start = self._bar_at(max(0.0, float(start)))
        bpb = self._bar_len(start)
        r = self._drummer_region(t, start, max(1, int(round(length / bpb)))) if t["kind"] == "drummer" else \
            {"id": self._id("r"), "track": tid, "start": start, "length": float(max(bpb, length)), "kind": "midi", "notes": []}
        self._p["regions"].append(r)
        self._sel_region, self._sel_track = r["id"], tid
        self._keep()
        return r["id"]

    @Slot(str, str, float, result=str)
    def addLoop(self, loop_id: str, tid: str, start: float) -> str:
        """A loop at `start` on a track (a new track for it when tid is empty or the track holds something else)."""
        lp = next((x for x in se.LOOPS if x[0] == loop_id), None)
        if lp is None or self._p is None:
            return ""
        _, name, fam, inst, _style, bars = lp
        self._before()
        t = self._t(tid)
        kit = se.INSTRUMENTS[inst].get("engine") == "kit"
        if t is None or t["kind"] == "audio" or (se.settings(t.get("instrument") or {}).get("engine") == "kit") != kit:
            t = self._add_track("instrument", inst, name)
        at = self._bar_at(max(0.0, float(start)))
        bpb = max(1, int(round(self._bar_len(at))))
        notes = se.loop_notes(loop_id, int(self._p.get("key", 0)), self._p.get("mode", "major"), bpb)
        r = {"id": self._id("r"), "track": t["id"], "start": at, "length": float(bars * bpb), "kind": "midi",
             "notes": notes, "loop": loop_id, "name": name}
        self._p["regions"].append(r)
        self._sel_track, self._sel_region = t["id"], r["id"]
        self._keep()
        return r["id"]

    @Slot(str)
    def previewLoop(self, loop_id: str) -> None:
        """Hear a loop on its own (again stops it)."""
        if any(v["id"].startswith("preview") for v in self._player.live):
            self._player.stop_live("preview")
            return
        lp = next((x for x in se.LOOPS if x[0] == loop_id), None)
        if lp is None:
            return
        tempo = float((self._p or {}).get("tempo", 110))
        bpb = int(((self._p or {}).get("sig") or [4])[0])
        r = {"notes": se.loop_notes(loop_id, int((self._p or {}).get("key", 0)), (self._p or {}).get("mode", "major"), bpb), "length": lp[5] * bpb}
        audio = se.render_midi_region(r, {"id": lp[3]}, tempo)
        self._player.play_live("preview", audio * 0.8)

    @Slot(str, str, float)
    def moveRegion(self, rid: str, tid: str, start: float) -> None:
        r = self._r(rid)
        t = self._t(tid) or self._t(r["track"] if r else "")
        if not r or not t:
            return
        if t["kind"] == "stack":
            self.said.emit("A stack holds tracks, not regions: put it on one of its tracks.", True)
            return
        if (t["kind"] == "audio") != (r.get("kind") == "audio"):
            self.said.emit("Recordings go on audio tracks, notes on instrument tracks.", True)
            return
        self._before()
        r["track"], r["start"] = t["id"], round(max(0.0, float(start)) * 4) / 4
        self._keep()

    @Slot(str, float)
    def resizeRegion(self, rid: str, length: float) -> None:
        r = self._r(rid)
        if r:
            self._before(("resize", rid))
            r["length"] = max(0.25, round(float(length) * 4) / 4)
            if r.get("kind") == "drummer":
                t = self._t(r["track"])
                r["notes"] = self._drummer_region(t, r["start"], max(1, int(round(r["length"] / self._bar_len(r["start"])))))["notes"]
            self._keep()

    @Slot(str, int)
    def setLoops(self, rid: str, n: int) -> None:
        r = self._r(rid)
        if r:
            self._before(("loops", rid))
            r["loops"] = max(1, min(64, int(n)))
            self._keep()

    @Slot(str, float, result=str)
    def splitRegion(self, rid: str, at: float) -> str:
        """Cut a region in two at song time `at` (beats)."""
        r = self._r(rid)
        if not r or not r["start"] < at < r["start"] + r["length"]:
            return ""
        self._before()
        cut = at - r["start"]
        b = copy.deepcopy(r)
        b["id"] = self._id("r")
        b["start"], b["length"] = at, r["length"] - cut
        r["length"] = cut
        if r.get("kind") == "audio":
            b["offset"] = float(r.get("offset", 0)) + self._tm().clock(float(r["start"]))(cut)
        else:
            notes = r.get("notes") or []
            r["notes"] = [n for n in notes if n["t"] < cut]
            b["notes"] = [dict(n, t=n["t"] - cut) for n in notes if n["t"] >= cut]
        b.pop("loop", None)
        r.pop("loop", None)
        self._p["regions"].append(b)
        self._keep()
        return b["id"]

    @Slot(str, result=str)
    def duplicateRegion(self, rid: str) -> str:
        r = self._r(rid)
        if not r:
            return ""
        self._before()
        b = copy.deepcopy(r)
        b["id"] = self._id("r")
        b["start"] = r["start"] + r["length"] * max(1, int(r.get("loops", 1)))
        self._p["regions"].append(b)
        self._sel_region = b["id"]
        self._keep()
        return b["id"]

    @Slot(str)
    def removeRegion(self, rid: str) -> None:
        if self._r(rid):
            self._before()
            self._p["regions"] = [r for r in self._p["regions"] if r["id"] != rid]
            if self._sel_region == rid:
                self._sel_region = ""
            self._keep()

    @Slot(str)
    def selectRegion(self, rid: str) -> None:
        self._sel_region = rid
        r = self._r(rid)
        if r:
            self._sel_track = r["track"]
        self.changed.emit()

    # ---- notes (the piano roll and the drum grid)
    def _notes(self, rid: str):
        r = self._r(rid)
        if r is None or r.get("kind") == "audio":
            return None, None
        if r.get("kind") == "drummer":                       # editing a drummer's part makes it yours
            r["kind"] = "midi"
        r.pop("loop", None)
        return r, r.setdefault("notes", [])

    @Slot(str, float, int, float, int, result=int)
    def addNote(self, rid: str, t: float, pitch: int, d: float, vel: int) -> int:
        self._before()
        r, notes = self._notes(rid)
        if r is None:
            self._undo.pop()
            return -1
        notes.append({"t": round(max(0.0, float(t)), 4), "d": round(max(1 / 16, float(d)), 4), "p": int(pitch) & 0x7F, "v": max(1, min(127, int(vel)))})
        self._keep()
        self._audition(r["track"], int(pitch), int(vel))
        return len(notes) - 1

    @Slot(str, int, float, int)
    def moveNote(self, rid: str, i: int, t: float, pitch: int) -> None:
        self._before(("note", rid, i, "move"))
        r, notes = self._notes(rid)
        if notes is None or not 0 <= i < len(notes):
            return
        changed_pitch = notes[i]["p"] != int(pitch)
        notes[i]["t"], notes[i]["p"] = round(max(0.0, float(t)), 4), int(pitch) & 0x7F
        self._keep()
        if changed_pitch:
            self._audition(r["track"], int(pitch), notes[i].get("v", 100))

    @Slot(str, int, float)
    def resizeNote(self, rid: str, i: int, d: float) -> None:
        self._before(("note", rid, i, "size"))
        r, notes = self._notes(rid)
        if notes is not None and 0 <= i < len(notes):
            notes[i]["d"] = round(max(1 / 32, float(d)), 4)
            self._keep()

    @Slot(str, int, int)
    def setVelocity(self, rid: str, i: int, vel: int) -> None:
        self._before(("note", rid, i, "vel"))
        r, notes = self._notes(rid)
        if notes is not None and 0 <= i < len(notes):
            notes[i]["v"] = max(1, min(127, int(vel)))
            self._keep()

    @Slot(str, int)
    def removeNote(self, rid: str, i: int) -> None:
        self._before()
        r, notes = self._notes(rid)
        if notes is not None and 0 <= i < len(notes):
            notes.pop(i)
            self._keep()

    @Slot(str, int, int)
    def toggleStep(self, rid: str, pitch: int, step: int) -> None:
        """The drum grid: a sixteenth note on or off."""
        self._before()
        r, notes = self._notes(rid)
        if r is None:
            return
        t = step / 4
        hit = next((k for k, n in enumerate(notes) if n["p"] == pitch and abs(n["t"] - t) < 1e-3), -1)
        if hit >= 0:
            notes.pop(hit)
        else:
            notes.append({"t": t, "d": 0.25, "p": int(pitch), "v": 100})
            self._audition(r["track"], int(pitch), 100)
        self._keep()

    @Slot(str, float, float)
    def quantize(self, rid: str, grid: float, strength: float = 1.0) -> None:
        self._before()
        r, notes = self._notes(rid)
        if notes is None or grid <= 0:
            return
        for n in notes:
            q = round(n["t"] / grid) * grid
            n["t"] = round(n["t"] + (q - n["t"]) * max(0.0, min(1.0, strength)), 4)
        self._keep()

    @Slot(str, int)
    def transpose(self, rid: str, semis: int) -> None:
        self._before()
        r, notes = self._notes(rid)
        if notes is not None:
            for n in notes:
                n["p"] = max(0, min(127, n["p"] + int(semis)))
            self._keep()

    # ---------------------------------------------------------------- the transport
    def _frame(self, beats: float) -> int:
        return int(self._tm().seconds(beats) * se.SR)

    def _tm(self) -> "se.TempoMap":
        return se.TempoMap(self._p or {})

    def _mm(self) -> "se.MeterMap":
        return se.MeterMap(self._p or {})

    def _bar_len(self, at: float = 0.0) -> float:
        """A bar's length in beats (quarter notes) where `at` is."""
        mm = self._mm()
        return mm.bar_len(mm.sig_at(at))

    def _bar_starts(self, upto: float) -> list:
        return [b for b, _n, _s in self._mm().bars(max(0.0, upto) + 64)]

    def _bar_at(self, beat: float) -> float:
        """The start of the bar a beat is in."""
        return max([b for b in self._bar_starts(beat) if b <= beat + 1e-6] or [0.0])

    def _bar_round(self, beat: float) -> float:
        """The bar line nearest a beat."""
        return min(self._bar_starts(beat + 32), key=lambda b: abs(b - beat))

    def _bar_after(self, beat: float) -> float:
        """The first bar line after a beat."""
        return next((b for b in self._bar_starts(beat + 32) if b > beat + 1e-6), beat + self._bar_len(beat))

    def _bars_span(self, start: float, bars: int) -> float:
        """How many beats `bars` bars take from a bar line."""
        starts = [b for b in self._bar_starts(start + bars * 8 + 32) if b >= start - 1e-6]
        return (starts[bars] if len(starts) > bars else start + bars * self._bar_len(start)) - start

    def _restart_player(self) -> None:
        cyc = self._p.get("cycle") or {}
        cycle = (self._frame(cyc["start"]), self._frame(cyc["end"])) if cyc.get("on") else None
        self._player.start(self._p, self._folder, self._frame(self._pos), cycle, bool(self._p.get("metronome")) or self._recording, 0)

    @Slot()
    def play(self) -> None:
        if self._p is None or self._playing:
            return
        self._playing = True
        cyc = self._p.get("cycle") or {}
        cycle = (self._frame(cyc["start"]), self._frame(cyc["end"])) if cyc.get("on") else None
        self._player.start(self._p, self._folder, self._frame(self._pos), cycle, bool(self._p.get("metronome")), 0)
        self.changed.emit()

    @Slot()
    def stop(self) -> None:
        if self._recording:
            self._finish_recording()
        if self._playing:
            self._pos = self._tm().beat(self._player.song_frame() / se.SR)
            self._player.stop()
            self._playing = False
        self._levels = {}
        self.changed.emit()
        self.clockChanged.emit()

    @Slot()
    def toggle(self) -> None:
        self.stop() if self._playing else self.play()

    @Slot(float)
    def seek(self, beats: float) -> None:
        was = self._playing
        if was:
            self._player.stop()
            self._playing = False
        self._pos = max(0.0, float(beats))
        if was:
            self.play()
        self.clockChanged.emit()

    @Slot()
    def toStart(self) -> None:
        self.seek(0.0)

    def _tick(self) -> None:
        if self._playing and self._p is not None:
            f = self._player.song_frame()
            if f >= 0:
                was = self._pos
                self._pos = self._tm().beat(f / se.SR)
                if self._recording and self._pos < was - 0.5 and (self._p.get("cycle") or {}).get("on"):
                    self._take_wrap()                          # round the cycle: the next take
            if not self._recording and not (self._p.get("cycle") or {}).get("on") and self._pos > se.song_length(self._p) + 4 and not self._held:
                self.stop()
                return
            self.clockChanged.emit()

    # ---------------------------------------------------------------- playing live and recording
    def _target_track(self) -> dict:
        t = self._t(self._sel_track)
        if t is None or t["kind"] == "audio":
            t = next((x for x in self._p.get("tracks", []) if x["kind"] != "audio"), None)
        return t

    def _audition(self, tid: str, pitch: int, vel: int) -> None:
        t = self._t(tid)
        if t is None or self._playing:
            return
        a = se.instrument_note(t.get("instrument") or {"id": "grand"}, pitch, vel, 0.35, self._folder)
        g = 10 ** (float(t.get("volume", 0)) / 20)
        self._player.play_live(f"aud{pitch}", a * g * 0.9)

    @Slot(int, int)
    def noteOn(self, pitch: int, vel: int) -> None:
        if self._p is None:
            return
        t = self._target_track()
        if t is None or pitch in self._held:
            return
        chord = (t.get("midiFx") or {}).get("chord") or {}
        if chord.get("on"):                                  # the chord trigger plays live too
            ps = [n["p"] for n in se.apply_midi_fx([{"t": 0, "d": 1, "p": pitch, "v": vel}], {"chord": chord}, 1, int(self._p.get("key", 0)), self._p.get("mode", "major"))]
            parts = [se.instrument_note(t.get("instrument") or {"id": "grand"}, q, vel, 6.0, self._folder) for q in ps]
            n = max(len(x) for x in parts)
            stereo = any(x.ndim == 2 for x in parts)          # a plugin plays in stereo
            a = np.zeros((n, 2) if stereo else n, np.float32)
            for x in parts:
                a[:len(x)] += (x if x.ndim == 2 or not stereo else x[:, None]) * 0.7
        else:
            a = se.instrument_note(t.get("instrument") or {"id": "grand"}, pitch, vel, 6.0, self._folder)
        g = 10 ** (float(t.get("volume", 0)) / 20)
        self._player.play_live(f"key{pitch}", a * g * 0.9)
        self._held[pitch] = (self._pos, vel)

    @Slot(int)
    def noteOff(self, pitch: int) -> None:
        held = self._held.pop(pitch, None)
        t = self._target_track()
        rel = float(se.settings((t or {}).get("instrument") or {}).get("release", 0.3)) if t else 0.3
        self._player.release_live(f"key{pitch}", int(rel * se.SR))
        if held and self._recording and self._rec and self._rec.get("kind") == "notes":
            start, vel = held
            self._rec["notes"].append({"t": start, "d": max(1 / 32, self._pos - start), "p": pitch, "v": vel})

    @Slot(str, result=int)
    def keyPitch(self, key: str) -> int:
        """Musical typing: A W S E D F T G Y H U J K O L P ; play a scale from C (octave from the window)."""
        return QWERTY.get(key.lower(), -1)

    @Slot()
    def record(self) -> None:
        """Record onto the armed track (or the selected one): notes for instruments, sound for audio tracks. A bar of
        clicks counts you in."""
        if self._p is None or self._recording:
            return
        t = next((x for x in self._p["tracks"] if x.get("arm")), None) or self._t(self._sel_track)
        if t is None:
            self.said.emit("Add a track to record onto.", True)
            return
        self._recording = True
        self._rec = {"track": t["id"], "start": self._pos, "kind": "sound" if t["kind"] == "audio" else "notes", "notes": [], "bytes": bytearray(),
                     "countIn": 0 if self._playing else int(self._p.get("countIn", 1)) * self._bar_len(self._pos)}
        if self._rec["kind"] == "sound":
            self._start_mic()
        if not self._playing:
            self._playing = True
            cyc = self._p.get("cycle") or {}
            cycle = (self._frame(cyc["start"]), self._frame(cyc["end"])) if cyc.get("on") else None
            self._player.start(self._p, self._folder, self._frame(self._pos), cycle, True, int(self._p.get("countIn", 1)))
        self.changed.emit()

    def _start_mic(self) -> None:
        if QAudioSink is None or self._demo or not sound_server():
            if not self._demo:
                self.said.emit("No sound system to record from.", True)
            return
        try:
            dev = QMediaDevices.defaultAudioInput()
            if dev.isNull():
                self.said.emit("No microphone was found.", True)
                return
            fmt = QAudioFormat()
            fmt.setSampleRate(se.SR)
            fmt.setChannelCount(1)
            fmt.setSampleFormat(QAudioFormat.SampleFormat.Float)
            self._mic = QAudioSource(dev, fmt, self)
            io = self._mic.start()
            io.readyRead.connect(lambda: self._rec and self._rec["bytes"].extend(bytes(io.readAll())))
        except Exception as e:                               # noqa: BLE001
            self.said.emit(f"Couldn't use the microphone: {e}", True)

    def _finish_recording(self) -> None:
        rec, self._rec = self._rec, None
        self._recording = False
        if self._mic is not None:
            self._mic.stop()
            self._mic = None
        if not rec:
            return
        for p in list(self._held):                           # notes still held end where the recording ends
            start, vel = self._held.pop(p)
            rec["notes"].append({"t": start, "d": max(1 / 32, self._pos - start), "p": p, "v": vel})
        if rec["kind"] == "sound":                            # the count-in was recorded too: skip it
            data = np.frombuffer(bytes(rec["bytes"])[:len(rec["bytes"]) // 4 * 4], np.float32)
            lead = int(rec.get("countIn", 0) * se.beats_to_s(1, self._tm().tempo_at(float(rec.get("start", 0)))) * se.SR)
            rec["audio"] = np.repeat(data[lead:, None], 2, axis=1)
        if self._finish_takes(rec):
            return
        start = self._bar_at(max(0.0, float(rec["start"])))
        end = max(self._pos, rec["start"] + 0.25)
        length = max(self._bar_len(start), self._bar_after(end) - start)
        if rec["kind"] == "notes":
            if not rec["notes"]:
                return
            self._before()
            notes = [dict(n, t=round(n["t"] - start, 4)) for n in rec["notes"] if n["t"] >= start]
            self._p["regions"].append({"id": self._id("r"), "track": rec["track"], "start": start, "length": length, "kind": "midi", "notes": notes, "name": "Recording"})
            self._keep()
            self.said.emit(f"Recorded {len(notes)} note{'s' if len(notes) != 1 else ''}.", False)
        else:
            data = rec["audio"]
            if len(data) < se.SR // 10:
                return
            self._add_audio_region(rec["track"], data, rec["start"], "Recording")

    def _add_audio_region(self, tid: str, audio: np.ndarray, start: float, name: str) -> str:
        folder = (self._folder / "audio") if self._folder else Path("/tmp")
        folder.mkdir(parents=True, exist_ok=True)
        fname = f"{re.sub(r'[^A-Za-z0-9]+', '-', name).strip('-') or 'sound'}-{uuid.uuid4().hex[:6]}.wav"
        se.write_wav(str(folder / fname), audio, 24)
        tm = self._tm()
        tempo = tm.tempo_at(float(start))
        self._before()
        r = {"id": self._id("r"), "track": tid, "start": round(float(start), 4),
             "length": round(tm.beat(tm.seconds(float(start)) + len(audio) / se.SR) - float(start), 4), "kind": "audio",
             "file": f"audio/{fname}" if self._folder else str(folder / fname), "offset": 0.0, "gain": 0.0, "name": name, "srcTempo": tempo}
        self._p["regions"].append(r)
        self._keep()
        return r["id"]

    def _listen_midi(self) -> None:
        """Every MIDI keyboard plugged in (raw ALSA MIDI devices), read in the background."""
        for dev in sorted(Path("/dev/snd").glob("midiC*D*")) if Path("/dev/snd").is_dir() else []:
            def work(path=str(dev)):
                state = {}
                try:
                    with open(path, "rb", buffering=0) as fh:
                        while True:
                            data = fh.read(64)
                            if not data:
                                break
                            for kind, pitch, vel in parse_midi_bytes(state, data):
                                self._midi_in.emit(kind, pitch, vel)
                except OSError:
                    return
            th = threading.Thread(target=work, daemon=True)
            th.start()
            self._midi_threads.append(th)

    def _midi_event(self, kind: str, pitch: int, vel: int) -> None:
        if kind == "on":
            self.noteOn(pitch, vel)
        else:
            self.noteOff(pitch)

    @Property("QVariantList", constant=True)
    def midiInputs(self):
        if self._demo:
            return ["Arturia KeyStep 37"]
        names = []
        for card in sorted(Path("/proc/asound").glob("card*")) if Path("/proc/asound").is_dir() else []:
            if list(card.glob("midi*")):
                try:
                    names.append((card / "id").read_text().strip())
                except OSError:
                    pass
        return names

    # ---------------------------------------------------------------- bringing things in, sending things out
    @Slot("QVariantList")
    def importFiles(self, urls) -> None:
        urls = urls.toVariant() if hasattr(urls, "toVariant") else urls
        for u in urls:
            if hasattr(u, "toLocalFile"):
                path = u.toLocalFile()
            else:
                path = QUrl(str(u)).toLocalFile() if str(u).startswith("file:") else str(u)
            low = path.lower()
            if low.endswith((".mid", ".midi")):
                self.importMidi(path)
            else:
                a = se.load_audio(path)
                if a.size == 0:
                    self.said.emit(f"{Path(path).name} isn't a sound Tempo can read.", True)
                    continue
                if self._p is None:
                    self.newProject("empty", Path(path).stem)
                self._before()
                t = self._add_track("audio", "", Path(path).stem[:24])
                self._undo.pop()
                self._add_audio_region(t["id"], a, self._pos, Path(path).stem)

    @Slot(str)
    def importMidi(self, path: str) -> None:
        try:
            song = se.read_midi(Path(path).read_bytes())
        except (OSError, ValueError, IndexError) as e:
            self.said.emit(f"Couldn't read that MIDI file: {e}", True)
            return
        if self._p is None:
            self.newProject("empty", Path(path).stem)
            self._p["tracks"] = []
            self._p["tempo"] = round(song["tempo"], 1)
            # a new song from the file: its tempo and time-signature changes too
            self._p["sig"] = [int(song["sig"][0]), int(song["sig"][1])]
            self._p["tempoChanges"] = song.get("tempoChanges") or []
            self._p["sigChanges"] = song.get("sigChanges") or []
        self._before()
        gm = {0: "grand", 1: "bright", 4: "epiano", 16: "organ", 25: "guitar", 33: "fingered", 38: "bass", 48: "strings", 61: "brass", 81: "lead", 89: "pad"}
        for tr in song["tracks"]:
            drums = tr["channel"] == 9
            nearest = gm[min(gm, key=lambda k: abs(k - tr["program"]))]
            inst = "drums" if drums else gm.get(tr["program"], nearest)
            t = self._add_track("instrument", inst, tr["name"] or se.INSTRUMENTS[inst]["name"])
            end = max(a + d for a, d, _p, _v in tr["notes"])
            bars = [b for b, _n, _s in self._mm().bars(end + 64)]
            length = next((b for b in bars if b > end), end)
            self._p["regions"].append({"id": self._id("r"), "track": t["id"], "start": 0.0, "length": length, "kind": "midi", "name": tr["name"] or "MIDI",
                                       "notes": [{"t": round(a, 4), "d": round(d, 4), "p": p, "v": v} for a, d, p, v in tr["notes"]]})
        self._keep()
        self.said.emit(f"Brought in {len(song['tracks'])} track{'s' if len(song['tracks']) != 1 else ''} from {Path(path).name}.", False)

    def _exports(self) -> Path:
        d = Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.MusicLocation) or Path.home() / "Music") / "Tempo Exports"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _free(self, folder: Path, base: str, ext: str) -> Path:
        out, n = folder / f"{base}{ext}", 2
        while out.exists():
            out, n = folder / f"{base} {n}{ext}", n + 1
        return out

    @Slot(str, result=str)
    def export(self, kind: str) -> str:
        """The song as a file in Music/Tempo Exports: wav, flac, mp3, ogg or m4a; "stems" (a WAV per track, in a
        folder) or "midi"."""
        if self._p is None or not self._p.get("regions"):
            self.said.emit("There's nothing to export yet.", True)
            return ""
        name = self._p.get("name", "Song")
        if self._demo:
            self.said.emit(f"Exported {name}.{kind}", False)
            return ""
        folder = self._exports()
        if kind == "midi":
            tracks, names = [], []
            for k, t in enumerate(self._p["tracks"]):
                notes = [(r["start"] + n["t"] + rep * r["length"], n["d"], n["p"], n.get("v", 100)) for r in self._p["regions"] if r["track"] == t["id"] and r.get("kind") != "audio"
                         for rep in range(int(r.get("loops", 1))) for n in r.get("notes") or [] if n["t"] < r["length"]]
                if notes:
                    kit = se.settings(t.get("instrument") or {}).get("engine") == "kit"
                    tracks.append({"channel": 9 if kit else min(15, len(tracks) + (1 if len(tracks) >= 9 else 0)), "program": se.INSTRUMENTS.get((t.get("instrument") or {}).get("id"), {}).get("program", 0), "notes": notes})
                    names.append(t["name"])
            target = self._free(folder, name, ".mid")
            target.write_bytes(se.write_midi(tracks, float(self._p["tempo"]), tuple(self._p["sig"]), names=names, project=self._p))
            self.said.emit(f"Saved {target.name} in Music/Tempo Exports", False)
            return str(target)
        self.said.emit("Exporting…", False)
        snap = json.loads(json.dumps(self._p))
        folder_in = self._folder

        def work():
            try:
                if kind == "stems":
                    out_dir = self._free(folder, f"{name} stems", "")
                    out_dir.mkdir(parents=True)
                    for t in snap["tracks"]:
                        if any(r["track"] == t["id"] for r in snap["regions"]):
                            safe = re.sub(r"[\\/:*?<>|]+", " ", t["name"]).strip() or t["id"]
                            se.write_wav(str(out_dir / f"{safe}.wav"), se.render_song(snap, folder_in, tracks=[t["id"]]), 24)
                    result = (str(out_dir), f"Saved the stems in Music/Tempo Exports/{out_dir.name}")
                else:
                    audio = se.render_song(snap, folder_in)
                    target = self._free(folder, name, "." + kind)
                    if kind == "wav":
                        se.write_wav(str(target), audio, 24)
                        good = True
                    else:
                        good = se.encode(audio, str(target), kind)
                    result = (str(target), f"Saved {target.name} in Music/Tempo Exports") if good else ("", "Couldn't make that kind of file (it needs ffmpeg).")
            except Exception as e:                           # noqa: BLE001
                result = ("", f"Couldn't export: {e}")
            self._back.emit(lambda: self._exported(result))
        threading.Thread(target=work, daemon=True).start()
        return "…"

    def _exported(self, result) -> None:
        self._last_export = result[0]
        self.said.emit(result[1], not result[0])
        self.changed.emit()

    lastExport = Property(str, lambda self: getattr(self, "_last_export", ""), notify=changed)

    # ---------------------------------------------------------------- undo
    @Slot()
    def undo(self) -> None:
        if self._undo:
            self._redo.append(copy.deepcopy(self._p))
            self._p = self._undo.pop()
            self._coalesce = None
            self._keep()

    @Slot()
    def redo(self) -> None:
        if self._redo:
            self._undo.append(copy.deepcopy(self._p))
            self._p = self._redo.pop()
            self._coalesce = None
            self._keep()

    def leaving(self) -> None:
        self._player.stop()
        self._save_timer.stop()
        self._write()

    # ---------------------------------------------------------------- the demo
    def _demo_song(self) -> None:
        self.newProject("songwriter", "Northern Lights")
        p = self._p
        p["tempo"], p["key"], p["mode"] = 96, 9, "minor"
        piano, bass, drums = p["tracks"]
        piano["volume"], bass["volume"] = -4.0, -5.0
        self._p["regions"] = []
        self._p["regions"].append({"id": "rd", "track": drums["id"], "start": 0.0, "length": 32.0, "kind": "drummer", "name": "Pop",
                                   "notes": se.drummer("pop", 0.55, 0.6, 8)})
        for k, (lp, tr, at) in enumerate((("keys-ballad", piano, 0), ("keys-ballad", piano, 16), ("bass-root", bass, 0), ("bass-walk", bass, 16))):
            r = {"id": f"rl{k}", "track": tr["id"], "start": float(at), "length": 16.0, "kind": "midi", "loop": lp, "name": "Verse" if at == 0 else "Chorus",
                 "notes": se.loop_notes(lp, 9, "minor")}
            self._p["regions"].append(r)
        pad = self._add_track("instrument", "pad", "Aurora Pad")
        pad["reverb"], pad["volume"] = 0.45, -8.0
        self._p["regions"].append({"id": "rp", "track": pad["id"], "start": 16.0, "length": 16.0, "kind": "midi", "loop": "pad-warm", "name": "Swell",
                                   "notes": se.loop_notes("pad-warm", 9, "minor")})
        lead = self._add_track("instrument", "lead", "Hook")
        lead["echo"], lead["volume"] = 0.25, -9.0
        lead["effects"].append({"kind": "delay", "params": {"time": 0.75}, "on": True})
        self._p["regions"].append({"id": "rh", "track": lead["id"], "start": 24.0, "length": 8.0, "kind": "midi", "name": "Hook",
                                   "notes": se.loop_notes("lead-hook", 9, "minor")[:12]})
        voice = self._add_track("audio", "", "Vocals")
        rng = np.random.default_rng(3)
        env = np.abs(np.sin(np.linspace(0, 40, 220))) * (0.4 + 0.6 * rng.random(220))
        takes = []
        for k in range(3):                                     # three takes, comped from the first and the last
            e2 = np.abs(np.sin(np.linspace(k, 40 + k * 3, 220))) * (0.35 + 0.65 * rng.random(220))
            takes.append({"name": f"Take {k + 1}", "file": f"/demo/vocals-{k + 1}.wav", "demoPeaks": [round(float(x), 3) for x in e2]})
        self._p["regions"].append({"id": "rv", "track": voice["id"], "start": 8.0, "length": 20.0, "kind": "audio", "file": "/demo/vocals.wav", "name": "Vocal takes",
                                   "demoPeaks": [round(float(x), 3) for x in env], "takes": takes, "take": 2, "comp": [[0.0, 8.0, 2], [8.0, 14.0, 0], [14.0, 20.0, 2]],
                                   "srcTempo": 96, "fadeIn": 0.4, "fadeOut": 1.2})
        bass["automation"] = {"volume": [[0, -12], [8, -5], [24, -5], [32, -2]]}
        # the pro bits: sections, a stack for the rhythm section, the bass ducking under the kick, a filter sweep
        p["sections"] = [{"id": "s1", "name": "Verse", "start": 0.0, "length": 16.0}, {"id": "s2", "name": "Chorus", "start": 16.0, "length": 16.0}]
        bass["effects"].append({"kind": "comp", "on": True, "params": {"key": drums["id"], "threshold": -32, "ratio": 8, "attack": 0.003, "release": 0.16, "makeup": 0}})
        lead["effects"].append({"kind": "filter", "params": {"cutoff": 600, "res": 1.4}, "on": True})
        lead["automation"] = {"fx.3.cutoff": [[24, 500], [28, 7000], [31, 2500]]}
        lead["lane"] = "fx.3.cutoff"
        lead["midiFx"] = {"arp": {"on": False, "mode": "up", "rate": 0.25, "octaves": 2, "gate": 0.8}}
        stack = {"id": "tstack", "kind": "stack", "name": "Rhythm", "instrument": {}, "volume": -1.0, "pan": 0.0, "mute": False, "solo": False, "arm": False,
                 "reverb": 0.05, "echo": 0.0, "effects": [{"kind": "eq", "params": {"low": 2}, "on": True}, {"kind": "comp", "params": {"ratio": 2, "threshold": -14}, "on": True}],
                 "automation": {}, "open": True}
        bass["output"], drums["output"] = stack["id"], stack["id"]
        tr = p["tracks"]
        tr.insert(tr.index(bass), stack)
        self._sel_track, self._sel_region = piano["id"], "rl1"
        self._pos = 17.5
        self._undo = []
