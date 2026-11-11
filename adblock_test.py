"""Ad-blocking test for safari_browser.py: the filter engine, network blocking and element
hiding on local pages, the YouTube defence against a fake YouTube (www.youtube.com is
mapped to a local server), list downloads, and per-site / global switches.
Prints PASS/FAIL per check. Runs headless by default."""
import json
import os
import sys
import tempfile
import threading
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
P = None
# The local server doubles as the browser's HTTP proxy, so made-up hosts like news.example
# and www.youtube.com (over http) reach it without any DNS. Started further down; the port
# is reserved here because Chromium reads its switches when the app starts.
import socket  # noqa: E402
_probe = socket.socket()
_probe.bind(("127.0.0.1", 0))
P = _probe.getsockname()[1]
_probe.close()
flags = f"--proxy-server=http://127.0.0.1:{P}"
if not sys.platform.startswith("win"):
    os.environ.setdefault("QTWEBENGINE_DISABLE_SANDBOX", "1")
    flags = "--no-sandbox --disable-gpu " + flags
os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = flags
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import safari_browser as sb  # noqa: E402
from PySide6.QtCore import QSettings, QTimer, QUrl  # noqa: E402

RESULTS, ERRORS, REQUESTS = [], [], []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail and not cond else ""), flush=True)


sys.excepthook = lambda t, v, tb: ERRORS.append("".join(traceback.format_exception(t, v, tb)))

TEST_LIST = r"""[Adblock Plus 2.0]
! Title: SafariQt test list
||ads.example^$third-party
/ad-banner-
@@||news.example/images/ad-banner-ok.gif
/api/track?$xmlhttprequest
||cdn.example^$domain=other.example
##.ad-slot
###sponsored-box
##.keep-me
news.example##.promo-strip
news.example#@#.keep-me
@@||allowed.example^$document
@@||generic.example^$generichide
||popup.example^$popup
||csp.example/x.js$csp=script-src 'none'
||bad.example^
||bad.example^$badfilter
/banner\d+\.gif/
||case.example/Ad.js$match-case
||imp.example^$important
@@||imp.example^
/ads/*$script,~third-party
||doc.example^$document
example.org##+js(set-constant, x, 1)
example.org##.thing:has-text(Sponsored)
"""

YT_PLAYER = {"videoDetails": {"videoId": "abc"}, "adPlacements": [{"x": 1}], "playerAds": [1], "adSlots": [2]}
YT_PAGE = """<!doctype html><html><head><title>Fake YouTube</title></head><body>
<script>var ytInitialPlayerResponse = {"videoDetails":{"videoId":"abc"},"adPlacements":[{"a":1}],"playerAds":[1],
"adSlots":[2],"auxiliaryUi":{"messageRenderers":{"enforcementMessageViewModel":{"x":1}}}};</script>
<script>
window.results = {};
var r = ytInitialPlayerResponse;
results.initial = [r.adPlacements === undefined, r.playerAds === undefined, r.adSlots === undefined,
                   !!r.videoDetails, !r.auxiliaryUi.messageRenderers.enforcementMessageViewModel];
var parsed = JSON.parse('{"playerResponse":{"adPlacements":[1],"videoDetails":{}},"other":1}');
results.parse = [parsed.playerResponse.adPlacements === undefined, parsed.other === 1];
results.native = Function.prototype.toString.call(JSON.parse).indexOf('[native code]') >= 0;
fetch('/youtubei/v1/player?key=1', {method: 'POST', body: '{}'}).then(x => x.json()).then(j =>
  results.fetchJson = [j.adPlacements === undefined, j.playerAds === undefined, !!j.videoDetails]);
fetch('/youtubei/v1/player?key=2', {method: 'POST', body: '{}'}).then(x => x.text()).then(t =>
  results.fetchText = [t.indexOf('"adPlacements"') < 0, t.indexOf('videoDetails') >= 0]);
var x = new XMLHttpRequest(); x.open('POST', '/youtubei/v1/next');
x.onload = () => results.xhr = [x.responseText.indexOf('"adSlots"') < 0, x.responseText.indexOf('videoDetails') >= 0];
x.send('{}');
fetch('/other/data.json').then(x => x.json()).then(j => results.unrelated = j.adPlacements !== undefined);
fetch('/api/stats/ads?ver=2').then(() => results.statsAds = 'loaded', () => results.statsAds = 'blocked');
</script>
<div id="movie_player" class="html5-video-player"><video></video>
<button class="ytp-ad-skip-button" onclick="window.skipClicked = (window.skipClicked || 0) + 1">Skip</button></div>
<ytd-popup-container><tp-yt-paper-dialog id="wall"><ytd-enforcement-message-view-model>Ad blockers violate
YouTube's Terms of Service</ytd-enforcement-message-view-model></tp-yt-paper-dialog></ytd-popup-container>
<tp-yt-iron-overlay-backdrop id="backdrop" opened></tp-yt-iron-overlay-backdrop>
<ytd-ad-slot-renderer id="feedad">AD</ytd-ad-slot-renderer><div id="masthead-ad">AD</div>
<ytd-rich-item-renderer id="video1">a real video</ytd-rich-item-renderer>
</body></html>"""


def news_page(port):
    return f"""<!doctype html><html><head><title>News</title></head><body>
<script>window.flags = {{}};</script>
<script src="http://ads.example/ads/banner.js"></script>
<script src="/ads/first.js"></script>
<img id="banner" src="/images/ad-banner-1.gif" onload="flags.banner='loaded'" onerror="flags.banner='blocked'">
<img id="bannerok" src="/images/ad-banner-ok.gif" onload="flags.bannerok='loaded'" onerror="flags.bannerok='blocked'">
<img id="photo" src="/images/photo.png" onload="flags.photo='loaded'" onerror="flags.photo='blocked'">
<img id="regex" src="/img/banner42.gif" onload="flags.regex='loaded'" onerror="flags.regex='blocked'">
<img id="adsimg" src="/ads/pic.png" onload="flags.adsimg='loaded'" onerror="flags.adsimg='blocked'">
<img id="cdn" src="http://cdn.example/lib.png" onload="flags.cdn='loaded'" onerror="flags.cdn='blocked'">
<img id="bad" src="http://bad.example/x.png" onload="flags.bad='loaded'" onerror="flags.bad='blocked'">
<img id="imp" src="http://imp.example/x.png" onload="flags.imp='loaded'" onerror="flags.imp='blocked'">
<script src="http://case.example/Ad.js"></script>
<script src="http://case.example/ad.js"></script>
<script>
var xh = new XMLHttpRequest(); xh.open('GET', '/api/track?x=1');
xh.onload = () => flags.xhr = 'loaded'; xh.onerror = () => flags.xhr = 'blocked'; xh.send();
fetch('/api/track?x=2').then(() => flags.fetchTrack = 'loaded', () => flags.fetchTrack = 'blocked');
fetch('/api/data').then(() => flags.fetchData = 'loaded', () => flags.fetchData = 'blocked');
</script>
<div class="ad-slot" id="adslot">AD</div><div id="sponsored-box">AD</div><div class="promo-strip" id="promo">AD</div>
<div class="keep-me" id="keep">keep</div><div class="article" id="article">Story</div>
</body></html>"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, body, ctype="text/html; charset=utf-8", extra=()):
        data = body.encode() if isinstance(body, str) else body
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        for k, v in extra:
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        self.rfile.read(length)
        REQUESTS.append(("POST",) + self._target())
        self._send(json.dumps(YT_PLAYER), "application/json")

    def _target(self):
        """(host, path) whether asked directly or as a proxy (absolute URL)."""
        if self.path.startswith("http://"):
            from urllib.parse import urlsplit
            parts = urlsplit(self.path)
            return parts.hostname or "", parts.path + ("?" + parts.query if parts.query else "")
        return (self.headers.get("Host") or "").split(":")[0], self.path

    def do_GET(self):
        host, path = self._target()
        REQUESTS.append(("GET", host, path))
        png = bytes.fromhex("89504e470d0a1a0a0000000d4948445200000001000000010806000000"
                            "1f15c4890000000d49444154789c6360000002000105fe02fea70000000049454e44ae426082")
        if path.endswith((".png", ".gif")):
            return self._send(png, "image/png")
        if path.endswith(".js"):
            return self._send(f"window.loaded_{host.split('.')[0]}_{os.path.basename(path).split('.')[0]} = true;",
                              "application/javascript")
        if path == "/other/data.json":
            return self._send(json.dumps({"adPlacements": [1]}), "application/json")
        if path.startswith("/api/"):
            return self._send("{}", "application/json")
        if path.startswith("/lists/easylist.txt"):
            return self._send("[Adblock Plus 2.0]\n! served list\n||served-rule.example^\n" + "! pad\n" * 3000)
        if path.startswith("/lists/portal"):
            return self._send("<html>Please log in to the Wi-Fi</html>" + " " * 20000)
        if host == "www.youtube.com":
            return self._send(YT_PAGE)
        if path == "/csp":
            return self._send(news_page(P), extra=[("Content-Security-Policy", "style-src 'self'")])
        return self._send(news_page(P))


server = ThreadingHTTPServer(("127.0.0.1", P), Handler)
threading.Thread(target=server.serve_forever, daemon=True).start()

SETTINGS_NAME = "SafariQtAdblock"
QSettings(sb.ORG_NAME, SETTINGS_NAME).clear()
QSettings(sb.ORG_NAME, SETTINGS_NAME).setValue("httpsMode", "off")   # plain http through the test proxy
app = sb.create_application([sys.argv[0]])
w = sb.create_browser(app, persistent=False, settings_name=SETTINGS_NAME)
w.add_tab(QUrl(sb.START_URL))
w.resize(1100, 720)
w.show()
adblock = w.guard.adblock
STATE = {}
steps = []


def step(ms):
    def deco(fn):
        steps.append((ms, fn))
        return fn
    return deco


def view():
    return w.current_view()


def js(code, key):
    STATE.pop(key, None)
    view().page().runJavaScript(code, 0, lambda r: STATE.__setitem__(key, r))


# ---- the engine on its own ------------------------------------------------------------------
@step(800)
def engine_unit():
    e = sb.FilterEngine()
    e.add_text(TEST_LIST)
    T = sb.AD_TYPES

    def m(url, site, kind="script", third=None):
        host = QUrl(url).host()
        if third is None:
            third = sb.registrable_domain(host) != sb.registrable_domain(site)
        return e.match(url, host, site, T[kind], third) is not None
    check("third-party host rule blocks", m("http://ads.example/x.js", "news.example"))
    check("...but not first-party", not m("http://ads.example/x.js", "ads.example"))
    check("token rule blocks", m("http://news.example/images/ad-banner-1.gif", "news.example", "image"))
    check("exception rule allows", not m("http://news.example/images/ad-banner-ok.gif", "news.example", "image"))
    check("type option: xhr only", m("http://x.example/api/track?a", "x.example", "xmlhttprequest")
          and not m("http://x.example/api/track?a", "x.example", "image"))
    check("domain= option", m("http://cdn.example/a.js", "other.example") and not m("http://cdn.example/a.js", "news.example"))
    check("regex filter", m("http://x.example/img/banner42.gif", "x.example", "image")
          and not m("http://x.example/img/bannerx.gif", "x.example", "image"))
    check("match-case", m("http://case.example/Ad.js", "x.example") and not m("http://case.example/ad.js", "x.example"))
    check("$important beats exceptions", m("http://imp.example/x.png", "x.example", "image"))
    check("badfilter disables a rule", not m("http://bad.example/x.png", "x.example", "image"))
    check("~third-party + type", m("http://news.example/ads/first.js", "news.example")
          and not m("http://news.example/ads/pic.png", "news.example", "image"))
    check("$popup / $csp rules skipped", not m("http://popup.example/", "x.example", "subdocument")
          and not m("http://csp.example/x.js", "x.example"))
    check("$document block rule never blocks a page", not m("http://doc.example/", "doc.example", "document"))
    check("page exception ($document)", e.page_flags("http://allowed.example/", "allowed.example") & sb.PAGE_DOCUMENT)
    check("page exception ($generichide)", e.page_flags("http://generic.example/a", "generic.example") & sb.PAGE_GENERICHIDE)
    css = e.css_for("news.example")
    check("css: generic + specific", ".ad-slot" in css and "#sponsored-box" in css and ".promo-strip" in css)
    check("css: #@# exception honoured", ".keep-me" not in css and ".keep-me" in e.css_for("other.example"))
    check("css: no generic with $generichide", ".ad-slot" not in e.css_for("generic.example", generic=False))
    check("scriptlets and procedural filters skipped", "has-text" not in e.css_for("example.org") and e.skipped >= 3)
    grouped = sb.hiding_css([".a", "#b", "div[x]", ".9bad"])
    check("simple selectors grouped, others alone", grouped.startswith(".a,#b{") and "div[x]{" in grouped
          and ".9bad{" in grouped)
    adblock.load_text(TEST_LIST)
    view().setUrl(QUrl(f"http://news.example/news"))


# ---- network blocking + element hiding on a page ----------------------------------------------
@step(3000)
def news_check():
    js("JSON.stringify({flags: window.flags, adsjs: !!window.loaded_ads_banner, firstads: !!window.loaded_news_first, "
       "caseUpper: !!window.loaded_case_Ad, caseLower: !!window.loaded_case_ad, "
       "hidden: ['adslot','sponsored-box','promo','keep','article'].map(i => getComputedStyle(document.getElementById(i)).display)})",
       "news")


@step(800)
def news_results():
    r = json.loads(STATE.get("news") or "{}")
    f = r.get("flags", {})
    check("third-party ad script blocked", r.get("adsjs") is False, r)
    check("first-party /ads/ script blocked", r.get("firstads") is False)
    check("ad image blocked, exception image loads", f.get("banner") == "blocked" and f.get("bannerok") == "loaded", f)
    check("ordinary image loads", f.get("photo") == "loaded")
    check("regex rule blocks on a real page", f.get("regex") == "blocked")
    check("image under /ads/ allowed ($script only)", f.get("adsimg") == "loaded")
    check("domain= rule doesn't apply here", f.get("cdn") == "loaded")
    check("badfilter'd host loads", f.get("bad") == "loaded")
    check("important rule wins", f.get("imp") == "blocked")
    check("match-case on a real page", r.get("caseUpper") is False and r.get("caseLower") is True, r)
    check("tracking XHR + fetch blocked, others fine", f.get("xhr") == "blocked" and f.get("fetchTrack") == "blocked"
          and f.get("fetchData") == "loaded", f)
    hidden = r.get("hidden", [])
    check("ads hidden, content and exceptions shown", hidden == ["none", "none", "none", "block", "block"], hidden)
    check("blocked requests counted for the site", w.guard.ads_blocked.get("news.example", 0) >= 5,
          dict(w.guard.ads_blocked))
    check("blocked requests never reached the server",
          not any(p.startswith(("/images/ad-banner-1", "/api/track", "/img/banner42")) for _, _, p in REQUESTS))
    view().setUrl(QUrl(f"http://news.example/csp"))


@step(2500)
def csp_check():
    js("getComputedStyle(document.getElementById('adslot')).display", "csp")


@step(600)
def csp_result():
    check("hiding works despite a strict style CSP", STATE.get("csp") == "none", STATE.get("csp"))
    view().setUrl(QUrl(f"http://allowed.example/news"))


@step(2500)
def allowed_site():
    js("JSON.stringify({adsjs: !!window.loaded_ads_banner, slot: getComputedStyle(document.getElementById('adslot')).display})",
       "allowed")


@step(600)
def allowed_result():
    r = json.loads(STATE.get("allowed") or "{}")
    check("$document exception: nothing blocked or hidden", r.get("adsjs") is True and r.get("slot") == "block", r)
    view().setUrl(QUrl(f"http://www.youtube.com/watch?v=abc"))


# ---- YouTube ------------------------------------------------------------------------------------
@step(3000)
def youtube_data():
    js("JSON.stringify(window.results)", "yt")


@step(700)
def youtube_results():
    r = json.loads(STATE.get("yt") or "{}")
    check("ytInitialPlayerResponse: ads + wall data removed, video kept", r.get("initial") == [True] * 5, r.get("initial"))
    check("JSON.parse pruned (playerResponse.adPlacements)", r.get("parse") == [True, True], r.get("parse"))
    check("patched JSON.parse still looks native", r.get("native") is True)
    check("fetch().json() of /youtubei/v1/player pruned", r.get("fetchJson") == [True, True, True], r.get("fetchJson"))
    check("fetch().text() neutered", r.get("fetchText") == [True, True], r.get("fetchText"))
    check("XHR /youtubei/v1/next neutered", r.get("xhr") == [True, True], r.get("xhr"))
    check("unrelated JSON untouched", r.get("unrelated") is True, r.get("unrelated"))
    check("YouTube ad-stats request blocked", r.get("statsAds") == "blocked", r.get("statsAds"))
    ev = view().youtube_events
    check("removals reported to the browser", ev["pruned"] >= 4 and ev["wall"] >= 1, dict(ev))
    js("JSON.stringify({wall: !!document.getElementById('wall'), backdrop: !!document.getElementById('backdrop'), "
       "feed: getComputedStyle(document.getElementById('feedad')).display, "
       "mast: getComputedStyle(document.getElementById('masthead-ad')).display, "
       "video: getComputedStyle(document.getElementById('video1')).display})", "dom")


@step(600)
def youtube_dom():
    r = json.loads(STATE.get("dom") or "{}")
    check("anti-adblock wall removed", r.get("wall") is False and r.get("backdrop") is False, r)
    check("feed + masthead ads hidden, videos shown", r.get("feed") == "none" and r.get("mast") == "none"
          and r.get("video") != "none", r)
    js("var v = document.querySelector('#movie_player video'); v.muted = false; v.playbackRate = 1; "
       "document.getElementById('movie_player').classList.add('ad-showing'); 1", "adon")


@step(900)
def ad_playing():
    js("var v = document.querySelector('#movie_player video'); JSON.stringify([v.muted, v.playbackRate, window.skipClicked || 0])",
       "during")


@step(500)
def ad_playing_check():
    r = json.loads(STATE.get("during") or "[]")
    check("leftover ad: muted, 16x and Skip pressed", r[:2] == [True, 16] and (r[2] if len(r) > 2 else 0) >= 1, r)
    js("document.getElementById('movie_player').classList.remove('ad-showing'); 1", "adoff")


@step(900)
def ad_done():
    js("var v = document.querySelector('#movie_player video'); JSON.stringify([v.muted, v.playbackRate])", "after")


@step(500)
def ad_done_check():
    check("after the ad: sound and speed restored", json.loads(STATE.get("after") or "[]") == [False, 1],
          STATE.get("after"))
    check("skipped ad reported", view().youtube_events["skipped"] >= 1)
    w.set_site_ad_blocking("www.youtube.com", False)          # reloads the page


@step(3000)
def youtube_allowlisted():
    check("per-site switch removes the YouTube script", not w.profile.scripts().find(sb.ADBLOCK_YOUTUBE_NAME))
    js("JSON.stringify(window.results && window.results.initial)", "ytoff")


@step(600)
def youtube_allowlisted_check():
    check("YouTube left alone when turned off for it",
          json.loads(STATE.get("ytoff") or "null") == [False, False, False, True, False], STATE.get("ytoff"))
    w.set_site_ad_blocking("www.youtube.com", True)
    check("switching back re-installs it", bool(w.profile.scripts().find(sb.ADBLOCK_YOUTUBE_NAME)))
    w.set_privacy_pref("blockAds", False)
    view().setUrl(QUrl(f"http://news.example/news"))


@step(2500)
def global_off():
    js("JSON.stringify({adsjs: !!window.loaded_ads_banner, slot: getComputedStyle(document.getElementById('adslot')).display})",
       "off")


@step(600)
def global_off_check():
    r = json.loads(STATE.get("off") or "{}")
    check("Block ads off: nothing blocked or hidden", r.get("adsjs") is True and r.get("slot") == "block", r)
    check("Block ads off: YouTube script removed", not w.profile.scripts().find(sb.ADBLOCK_YOUTUBE_NAME))
    w.set_privacy_pref("blockAds", True)
    p = w.open_private_window()
    STATE["p"] = p
    check("private windows share the engine", p.guard.adblock is adblock)
    p.current_view().setUrl(QUrl(f"http://news.example/news"))


@step(2500)
def private_check():
    STATE["p"].current_view().page().runJavaScript("!!window.loaded_ads_banner", 0, lambda r: STATE.__setitem__("pads", r))


@step(600)
def private_result():
    check("ads blocked in private windows too", STATE.get("pads") is False, STATE.get("pads"))
    STATE["p"].close()
    # list downloads, from the local server instead of the internet
    STATE["lists"] = dict(sb.FILTER_LISTS)
    sb.FILTER_LISTS.clear()
    sb.FILTER_LISTS["easylist"] = ("EasyList", (f"http://127.0.0.1:{P}/lists/portal",
                                                f"http://127.0.0.1:{P}/lists/easylist.txt"))
    adblock.directory = tempfile.mkdtemp(prefix="safariqt-filters-")
    adblock.update(force=True)
    check("download in progress shows in settings", adblock.downloading and "Downloading" in adblock.status_text())


@step(3000)
def downloaded():
    path = adblock.list_path("easylist")
    ok = os.path.exists(path) and "served-rule.example" in open(path, encoding="utf-8").read()
    check("captive-portal page rejected, mirror used", ok)
    m = adblock.engine.match("http://served-rule.example/x.js", "served-rule.example", "news.example",
                             sb.AD_TYPES["script"], True)
    check("downloaded list parsed in the background and used", m is not None and not adblock.loading)
    check("status shows the update", "updated just now" in adblock.status_text(), adblock.status_text())
    sb.FILTER_LISTS["easylist"] = ("EasyList", (f"http://127.0.0.1:{P}/lists/portal",))
    adblock.update(force=True)


@step(2500)
def failed_download():
    path = adblock.list_path("easylist")
    check("failed update keeps the old list", "served-rule.example" in open(path, encoding="utf-8").read())
    check("failed update explained", "Couldn't download EasyList" in adblock.status_text(), adblock.status_text())
    sb.FILTER_LISTS.clear()
    sb.FILTER_LISTS.update(STATE["lists"])
    d = w.show_privacy_settings()
    check("settings show the filter lists", "EasyList" in d.filter_status.text()
          and "rules" in d.filter_status.text() and "blockAds" in d.switches, d.filter_status.text())
    d.close()


def run(i=0):
    if i >= len(steps):
        finish()
        return
    ms, fn = steps[i]

    def go():
        try:
            fn()
        except Exception:
            check(f"step {fn.__name__} raised", False, traceback.format_exc())
        run(i + 1)
    QTimer.singleShot(ms, go)


def finish():
    passed = sum(1 for _, ok, _ in RESULTS if ok)
    print(f"\n{passed} passed, {len(RESULTS) - passed} failed, {len(ERRORS)} uncaught errors", flush=True)
    for e in ERRORS:
        print("UNCAUGHT:", e, flush=True)
    QSettings(sb.ORG_NAME, SETTINGS_NAME).clear()
    w.close()
    QTimer.singleShot(300, app.quit)


run()
app.exec()
import shiboken6  # noqa: E402
for extra in w.all_windows()[1:]:
    shiboken6.delete(extra)
shiboken6.delete(w)
server.shutdown()
