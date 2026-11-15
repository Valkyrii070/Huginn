#!/usr/bin/env python3
"""Record the screen to a video file, the way a Wayland desktop allows it.

    huginn_screencast.py /path/to/output.webm

It asks the desktop's own "share your screen" service (the xdg-desktop-portal ScreenCast interface) for a screen or
a window; the desktop shows its picker, so you choose what is recorded and nothing is captured behind your back. The
picture stream it hands back (PipeWire) is written to the file by GStreamer. Prints STARTED when recording begins;
stop it with Ctrl+C or SIGTERM, and the file is finished properly. Prints ERROR: … and exits 1 when it can't.

Records what the computer is playing too, unless --no-sound is given (and carries on silently if sound can't be
captured). Needs: python3-gi, xdg-desktop-portal with a backend for the desktop, PipeWire, and
gstreamer1.0-pipewire with gstreamer1.0-plugins-good (VP8, WebM, PulseAudio) and -base (Opus); H.264 in MP4 is used
instead when x264 is there.
"""
import os
import shutil
import signal
import subprocess
import sys
import uuid


def pipeline(fd: int, node: int, target: str, sound: bool = False) -> list:
    """The GStreamer command that turns the screen's stream (and, with `sound`, what the computer is playing) into a
    video file. The sound is whatever comes out of the speakers ("the monitor of the default output"), not the microphone."""
    mp4 = target.endswith(".mp4")
    video = ["pipewiresrc", f"fd={fd}", f"path={node}", "do-timestamp=true", "keepalive-time=1000", "!", "videorate", "!", "videoconvert", "!", "queue", "!"]
    video += ["x264enc", "speed-preset=veryfast", "tune=zerolatency", "bitrate=6000", "!", "video/x-h264,profile=main", "!"] if mp4 else \
             ["vp8enc", "deadline=1", "cpu-used=8", "target-bitrate=6000000", "keyframe-max-dist=60", "!"]
    out = ["gst-launch-1.0", "-e", "mp4mux" if mp4 else "webmmux", "name=mux", "!", "filesink", f"location={target}"] + video + ["queue", "!", "mux."]
    if sound:
        out += ["pulsesrc", "device=@DEFAULT_MONITOR@", "do-timestamp=true", "!", "audioconvert", "!", "audioresample", "!", "opusenc", "bitrate=128000", "!", "queue", "!", "mux."]
    return out


def main() -> int:
    args = [a for a in sys.argv[1:] if a != "--no-sound"]
    if len(args) != 1:
        print("ERROR: say where to save the recording.", flush=True)
        return 1
    target, want_sound = args[0], "--no-sound" not in sys.argv[1:]
    if not shutil.which("gst-launch-1.0"):
        print("ERROR: GStreamer isn't installed, so the screen can't be recorded.", flush=True)
        return 1
    try:
        import gi
        gi.require_version("Gio", "2.0")
        from gi.repository import Gio, GLib
    except (ImportError, ValueError):
        print("ERROR: the part that talks to the desktop (python3-gi) isn't installed.", flush=True)
        return 1
    try:
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    except GLib.Error:
        print("ERROR: couldn't reach the desktop session.", flush=True)
        return 1
    name, path, iface = "org.freedesktop.portal.Desktop", "/org/freedesktop/portal/desktop", "org.freedesktop.portal.ScreenCast"
    sender = bus.get_unique_name().lstrip(":").replace(".", "_")
    loop, state = GLib.MainLoop(), {"session": "", "gst": None, "code": 1}

    def fail(why: str) -> None:
        print("ERROR: " + why, flush=True)
        loop.quit()

    def ask(method: str, args: tuple, then) -> None:
        """Call the portal; `then(results)` runs when the desktop (and you, at its picker) have answered."""
        token = "huginn" + uuid.uuid4().hex[:10]
        request = f"{path}/request/{sender}/{token}"
        sub = [0]

        def answered(_bus, _sender, _path, _iface, _signal, params):
            bus.signal_unsubscribe(sub[0])
            code, results = params.unpack()
            if code != 0:
                fail("Nothing was chosen to record." if code == 1 else "The desktop wouldn't share the screen.")
            else:
                then(results)
        sub[0] = bus.signal_subscribe(name, "org.freedesktop.portal.Request", "Response", request, None, Gio.DBusSignalFlags.NONE, answered)
        options = dict(args[-1], handle_token=GLib.Variant("s", token))
        try:
            bus.call_sync(name, path, iface, method, GLib.Variant(SIGNATURES[method], args[:-1] + (options,)), None, Gio.DBusCallFlags.NONE, 30000, None)
        except GLib.Error as err:
            bus.signal_unsubscribe(sub[0])
            fail("This desktop has no screen-sharing service: " + err.message[:120])

    SIGNATURES = {"CreateSession": "(a{sv})", "SelectSources": "(oa{sv})", "Start": "(osa{sv})"}

    def created(results):
        state["session"] = results["session_handle"]
        ask("SelectSources", (state["session"], {"types": GLib.Variant("u", 3), "multiple": GLib.Variant("b", False), "cursor_mode": GLib.Variant("u", 2)}), lambda _r: ask("Start", (state["session"], "", {}), started))

    def started(results):
        streams = results.get("streams") or []
        if not streams:
            fail("The desktop shared nothing.")
            return
        node = streams[0][0]
        try:
            reply, fds = bus.call_with_unix_fd_list_sync(name, path, iface, "OpenPipeWireRemote", GLib.Variant("(oa{sv})", (state["session"], {})), None, Gio.DBusCallFlags.NONE, 30000, None, None)
            fd = fds.get(reply.unpack()[0])
        except GLib.Error as err:
            fail("Couldn't open the screen's stream: " + err.message[:120])
            return
        os.makedirs(os.path.dirname(target) or ".", exist_ok=True)
        state.update(fd=fd, node=node)
        launch(want_sound)
        print("STARTED", flush=True)
        GLib.timeout_add(500, watch)

    def launch(sound: bool) -> None:
        import time
        state.update(sound=sound, since=time.monotonic())
        state["gst"] = subprocess.Popen(pipeline(state["fd"], state["node"], target, sound), pass_fds=[state["fd"]], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)

    def watch() -> bool:
        gst = state["gst"]
        if gst is not None and gst.poll() is not None:              # the recorder ended by itself: the window closed, or it broke
            import time
            err = (gst.stderr.read() or "").strip().splitlines()
            if gst.returncode != 0 and state.get("sound") and not state.get("stopping") and time.monotonic() - state["since"] < 4:
                print("NOTE: the computer's sound couldn't be recorded, so this video is silent.", flush=True)
                try:
                    os.unlink(target)
                except OSError:
                    pass
                launch(False)                                      # the picture is what matters: carry on without sound
                return True
            state["code"] = 0 if gst.returncode == 0 else 1
            if gst.returncode != 0:
                print("ERROR: the recording stopped: " + (err[-1][:160] if err else "no reason given"), flush=True)
            loop.quit()
            return False
        return True

    def stop(*_args) -> bool:
        gst = state["gst"]
        if gst is None:
            loop.quit()
        elif gst.poll() is None:
            state["stopping"] = True
            gst.send_signal(signal.SIGINT)                          # with -e this ends the file properly
        return True

    for sig in (signal.SIGINT, signal.SIGTERM):
        GLib.unix_signal_add(GLib.PRIORITY_HIGH, sig, stop)
    ask("CreateSession", ({"session_handle_token": GLib.Variant("s", "huginn" + uuid.uuid4().hex[:10])},), created)
    loop.run()
    gst = state["gst"]
    if gst is not None:
        try:
            gst.wait(timeout=10)
            state["code"] = 0 if gst.returncode == 0 else state["code"]
        except subprocess.TimeoutExpired:
            gst.kill()
    return state["code"]


if __name__ == "__main__":
    sys.exit(main())
