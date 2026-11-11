"""Checks which video/audio formats the browser engine can play. Invisible (no window).

    python\\python.exe engine\\codec_check.py            (from the SafariQt folder)

Besides asking the engine (canPlayType / MediaSource), it really plays a 4-second H.264 + AAC
clip and decodes its sound, because "maybe" answers can't be trusted on their own.
Prints a table and a final line  CODEC_RESULT {...json...}.
Exit code 0 = H.264 and AAC really play; 1 = they don't; 2 = the check couldn't run."""
import argparse
import base64
import json
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
HERE = Path(__file__).resolve().parent

TYPES = {
    "H.264 (MP4)": 'video/mp4; codecs="avc1.4D401E"',
    "AAC (MP4 audio)": 'audio/mp4; codecs="mp4a.40.2"',
    "H.264 + AAC": 'video/mp4; codecs="avc1.4D401E, mp4a.40.2"',
    "MP3": "audio/mpeg",
    "HEVC / H.265": 'video/mp4; codecs="hvc1.1.6.L93.B0"',
    "VP9 (WebM)": 'video/webm; codecs="vp9"',
    "AV1 (MP4)": 'video/mp4; codecs="av01.0.05M.08"',
    "Opus": 'audio/webm; codecs="opus"',
}

PAGE = """<!doctype html><html><body><video id="v" muted playsinline width="320" height="240"></video>
<script>
(async function () {
  const TYPES = __TYPES__, MIME = __MIME__;
  const out = {types: {}, play: {}, decode: {}};
  const probe = document.createElement('video');
  for (const [name, type] of Object.entries(TYPES)) {
    out.types[name] = [probe.canPlayType(type) || 'no',
                       window.MediaSource && MediaSource.isTypeSupported(type) ? 'yes' : 'no'];
  }
  const bytes = Uint8Array.from(atob(__CLIP__), c => c.charCodeAt(0));
  const v = document.getElementById('v');
  v.addEventListener('error', () => { out.play.error = v.error ? v.error.code + ' ' + (v.error.message || '') : 'error'; });
  v.src = URL.createObjectURL(new Blob([bytes], {type: MIME}));
  try { await v.play(); } catch (e) { out.play.playError = String(e); }
  await new Promise(r => setTimeout(r, 3000));
  out.play.currentTime = v.currentTime;
  out.play.width = v.videoWidth;
  out.play.height = v.videoHeight;
  out.play.readyState = v.readyState;
  if ('webkitVideoDecodedByteCount' in v) out.play.videoBytes = v.webkitVideoDecodedByteCount;
  if ('webkitAudioDecodedByteCount' in v) out.play.audioBytes = v.webkitAudioDecodedByteCount;
  try { out.play.frames = v.getVideoPlaybackQuality().totalVideoFrames; } catch (e) {}
  try {
    const ctx = new OfflineAudioContext(2, 44100, 44100);
    const audio = await ctx.decodeAudioData(bytes.buffer.slice(0));
    out.decode.duration = audio.duration;
    out.decode.channels = audio.numberOfChannels;
  } catch (e) { out.decode.error = String(e && e.message || e); }
  window.__result = out;
})();
</script></body></html>"""


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--clip", default=str(HERE / "codec_test.mp4"),
                        help="clip to play (default: the H.264/AAC test clip)")
    args = parser.parse_args()
    clip = Path(args.clip)
    mime = "video/webm" if clip.suffix == ".webm" else "video/mp4"

    from PySide6.QtCore import QTimer, QUrl
    from PySide6.QtWebEngineCore import (QWebEnginePage, QWebEngineProfile, QWebEngineSettings,
                                         qWebEngineChromiumVersion, qWebEngineVersion)
    from PySide6.QtWebEngineWidgets import QWebEngineView
    from PySide6.QtWidgets import QApplication

    app = QApplication(sys.argv[:1])
    profile = QWebEngineProfile()                         # off the record: touches no browser data
    profile.settings().setAttribute(QWebEngineSettings.WebAttribute.PlaybackRequiresUserGesture, False)
    page = QWebEnginePage(profile)
    view = QWebEngineView()
    view.setPage(page)
    view.resize(400, 300)
    view.show()
    html = (PAGE.replace("__TYPES__", json.dumps(TYPES)).replace("__MIME__", json.dumps(mime))
            .replace("__CLIP__", json.dumps(base64.b64encode(clip.read_bytes()).decode())))
    page.setHtml(html, QUrl("https://codec-check.invalid/"))
    state = {"tries": 0, "result": None}

    def poll():
        def got(value):
            if value:
                state["result"] = json.loads(value)
                app.quit()
            elif state["tries"] > 50:
                app.quit()
            else:
                state["tries"] += 1
                QTimer.singleShot(500, poll)
        page.runJavaScript("window.__result ? JSON.stringify(window.__result) : ''", 0, got)

    QTimer.singleShot(1500, poll)
    app.exec()
    result = state["result"]
    engine = f"Qt WebEngine {qWebEngineVersion()} (Chromium {qWebEngineChromiumVersion()})"
    view.setPage(None)
    del page

    if not result:
        print("CODEC_RESULT " + json.dumps({"ok": False, "engine": engine, "summary": "page did not report back"}))
        return 2
    types, play, decode = result["types"], result["play"], result["decode"]
    print(engine)
    print(f"{'format':<18}{'plain playback':<16}streaming (MSE)")
    for name, (plain, mse) in types.items():
        print(f"{name:<18}{plain:<16}{mse}")
    played = (not play.get("error") and play.get("width") == 320 and play.get("height") == 240
              and play.get("currentTime", 0) > 0.5)
    decoded = decode.get("duration", 0) > 3.5
    asked = types["H.264 (MP4)"][0] == "probably" and types["AAC (MP4 audio)"][0] == "probably"
    print(f"real playback of {clip.name}: {'yes' if played else 'no'} {json.dumps(play)}")
    print(f"sound decoded: {'yes' if decoded else 'no'} {json.dumps(decode)}")
    is_h264 = mime == "video/mp4"
    ok = played and decoded and (asked or not is_h264)
    if is_h264:
        summary = "H.264 and AAC play" if ok else \
            f"H.264/AAC not playable (engine says H.264 '{types['H.264 (MP4)'][0]}', AAC '{types['AAC (MP4 audio)'][0]}')"
    else:
        summary = f"{clip.name} plays" if ok else f"{clip.name} does not play"
    print("CODEC_RESULT " + json.dumps({"ok": ok, "engine": engine, "summary": summary, "types": types,
                                        "play": play, "decode": decode}))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
