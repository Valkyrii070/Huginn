"""Privacy & Security test for safari_browser.py: drives the real flows against local HTTP and
HTTPS servers (self-signed certificate) and prints PASS/FAIL per check.
Runs headless by default; set QT_QPA_PLATFORM=windows to run it on screen on Windows."""
import json
import os
import ssl
import sys
import tempfile
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if not sys.platform.startswith("win"):
    os.environ.setdefault("QTWEBENGINE_DISABLE_SANDBOX", "1")
    os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--no-sandbox --disable-gpu")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import safari_browser as sb  # noqa: E402
from PySide6.QtCore import QSettings, QTimer, QUrl  # noqa: E402
from PySide6.QtNetwork import QNetworkCookie  # noqa: E402
from PySide6.QtWidgets import QDialog  # noqa: E402

# Throwaway self-signed certificate for a local test server (never trusted, never used elsewhere).
TEST_CERT = '''-----BEGIN CERTIFICATE-----
MIIDHzCCAgegAwIBAgIULDx3nDHRG8Lb87RRcBnAFGVqqpcwDQYJKoZIhvcNAQEL
BQAwFDESMBAGA1UEAwwJbG9jYWxob3N0MB4XDTI2MTEwODIyNDgyNFoXDTQ2MTEw
MzIyNDgyNFowFDESMBAGA1UEAwwJbG9jYWxob3N0MIIBIjANBgkqhkiG9w0BAQEF
AAOCAQ8AMIIBCgKCAQEAurR31nBPwJchohvStsPG7BXFMoJJKnehF47MeGSKv1v8
Xzd8DKQRFn91UwSSqVxhQfqoXOEVusZpM3jF7oWgeq8eEKP6XIQkvwPtQI8MYlBp
/Aqe4KzoY4JRiYu7asr7Pm7AYLBYtycj8Wpe9qnTer2v8ngt4kkExJCLpXD7ppPI
gsc+w3Sa5b3rWrdr7cUAp6zfdHcRp+CJOscjRzmtTD5YDP2jn+oP6H3SnwFL8deJ
i8GECvldL2MxnAG6eFdFmvFqLARcvWLP9hcEtOU+QnCtjB9bucBLXN49pRiT72WG
nnPTcv4M9Ip/UDikG4GlxYErR6Li/R5Mxy9VyZS0GwIDAQABo2kwZzAdBgNVHQ4E
FgQUK3Lz0EUZYtTgeuJBMF/8JQ0ckiMwHwYDVR0jBBgwFoAUK3Lz0EUZYtTgeuJB
MF/8JQ0ckiMwDwYDVR0TAQH/BAUwAwEB/zAUBgNVHREEDTALgglsb2NhbGhvc3Qw
DQYJKoZIhvcNAQELBQADggEBAJiQ0GV2jR6vqTTtuIbRPoFSQ/aFVG00K6nNfZhB
V2A+jJLJtt68h9Ailsh895MTUgRdSzsEKGqpcsMruTGLfD0LJPRzYbzZamv7SPl7
+DRKWdT3prM71KnXBrnEuPYcH0V0PcNaSbYJ0O2BbWPwG8gbZX3hClSR0Jr5j3c/
HIAVHhqsm8O4lnfQfY0rw/RoPlNRVudOx9wPmMNcsB3+f+FlK9ECr8BgYxCQ91V4
CQeqIfqRy8PdTRVaEte/FtP71iLGrcX50r5oVi/2K7e4v3kSJQA360AJvkkvz+DZ
FsVUQNmGreJ/sDWzZ2mqv0zSfKo1Cbh3tkHPCq0LGpJ407U=
-----END CERTIFICATE-----
'''
TEST_KEY = '''-----BEGIN PRIVATE KEY-----
MIIEvAIBADANBgkqhkiG9w0BAQEFAASCBKYwggSiAgEAAoIBAQC6tHfWcE/AlyGi
G9K2w8bsFcUygkkqd6EXjsx4ZIq/W/xfN3wMpBEWf3VTBJKpXGFB+qhc4RW6xmkz
eMXuhaB6rx4Qo/pchCS/A+1AjwxiUGn8Cp7grOhjglGJi7tqyvs+bsBgsFi3JyPx
al72qdN6va/yeC3iSQTEkIulcPumk8iCxz7DdJrlvetat2vtxQCnrN90dxGn4Ik6
xyNHOa1MPlgM/aOf6g/ofdKfAUvx14mLwYQK+V0vYzGcAbp4V0Wa8WosBFy9Ys/2
FwS05T5CcK2MH1u5wEtc3j2lGJPvZYaec9Ny/gz0in9QOKQbgaXFgStHouL9HkzH
L1XJlLQbAgMBAAECggEAQ6lcVp/MH0EGBNAtfGOV5v/6v5O8vUGuZTGwgx74s2G8
I6uhbplUwgD9/VCGcA8VBgq3UjWWIOJ/xJILtSXDI0LsU96BQF75TCo5pHBS7hwz
VI5qxoSTEWDseLrleE3IYHdVi5TNCc8K9RX2BVFFXVF5/pa0FjIdIrk5ioLYCCUe
haDuZ4dMRkyQ04Jmkkj0v/EDEDZgkQLIs50ps5n5P4af+6IBBG5xh7QTdlZT73ED
XwexWvFQU42Mmu3LxJpmBILvKNjlhxDPgcEYD+ee1byPbdfjMoE1qHe/6hiPxGtB
qS0KQjGheYznjZ8V3oX3pO0uSbZPgcTtLtuM08VP5QKBgQDtFca/9TCKU3EFAQ/S
DxB+8aUQMIMRJ+F7b0HJt/3aklxLMqG6B0qjIrFsQmJXwxekdkLuZ9v5YMiV/dBL
gcwVEmSXiuEYo0IlsnHHv1pzntUwSJeCpeYQblPFGT2JpC4ePagmPfxMzhadaYeS
s6qC2WzhVEX3bYdMZn5qvGziXQKBgQDJmbqOqAEvVTl4RY+KxbhAfXjD4tZmjHlq
wdZyDoMnJ+RZ80u14Axhyv4davFVKUeqZ3XnS5hchEUTuFaD+MzQhHyuBvraQWQN
iRo6GPAATA7wOwy+ZsCqraNI5pBv0Dshg56XBDv8d0n6ofRLgzWVSRn7rT2uWmMF
iEHbjbN41wKBgGHb6jSTlRyTgoQJQyl2VF3BiltbWs47AuQ7MRF9I4gTf4r+dCjg
F5usl0VTRVpqSZj1w3y6W97cZw8aO97ezYkpFWJDzdOol4YN2M8VGdW9isuqOveP
WJ4Rm/wwBemJXgvXcU+PqFNfgZAp3e7cwBXQfxOnAFY33G/ZonaWHe91AoGACvqN
N1Gc5uf8PjmDjKoh05lBp2FGDcWeoxq1Q/bYW5yHigJ+4AO4iObWGeIGDH44Aeaq
fBMY1Aj7/gvu4jb9aGmepJeKt7IR8c7Cl+FdyJZbxedhVUkhOupD1yd/PCeZ4MRb
MZwwbBpO9BA3zpjxpRSbDqKrlkAj3lxCQeOgn3cCgYAXEaeRhwXs5g+qW/LISXmD
sZfW6OFP6Xz7yt2X5b82BVgHhsqx7zBZAL2O/KyfGJV0Ati3tEXReloDRbSidVC+
UinN8tRAf+lPZtExL8h9VoBCmHq4QZigGhxrxsyP/Q40IMuqWdbg0BM3HD1t96Vs
Zo4PJStexN3pfiL0ydS2ig==
-----END PRIVATE KEY-----
'''

RESULTS, ERRORS, REQUESTS = [], [], []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail and not cond else ""), flush=True)


sys.excepthook = lambda t, v, tb: ERRORS.append("".join(traceback.format_exception(t, v, tb)))

# ---- local web servers ------------------------------------------------------------------
PAGES = {
    "/gpc": "<script>document.title = 'gpc:' + navigator.globalPrivacyControl</script>",
    "/geo": "<script>navigator.geolocation.getCurrentPosition(p => document.title = 'pos', "
            "e => document.title = 'geo-err')</script>",
    "/notify": "<script>Notification.requestPermission().then(r => document.title = 'notify:' + r)</script>",
    "/clip": "<script>navigator.clipboard.readText().then(t => document.title = 'clip:ok', "
             "e => document.title = 'clip:' + e.name + ':' + e.message)</script>",
    "/cookie": "<script>document.cookie = 'first=1; max-age=3600'; document.title = 'cookie'</script>",
    "/download": "<a id=a href='/setup.exe'>get</a>",
}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        REQUESTS.append((self.path, self.headers.get("Sec-GPC")))
        path = self.path.split("?")[0]
        headers = [("Content-Type", "text/html; charset=utf-8")]
        if path in ("/setup.exe", "/notes.txt"):
            body = b"MZ not really a program"
            headers = [("Content-Type", "application/octet-stream"),
                       ("Content-Disposition", f'attachment; filename="{path[1:]}"')]
        else:
            body = (f"<html><head><title>{path.strip('/') or 'home'}</title></head><body>"
                    f"{PAGES.get(path, 'ok')}</body></html>").encode()
        self.send_response(200)
        for k, v in headers:
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


tmp = tempfile.mkdtemp(prefix="safariqt-sec-")
with open(os.path.join(tmp, "c.pem"), "w") as f:
    f.write(TEST_CERT)
with open(os.path.join(tmp, "k.pem"), "w") as f:
    f.write(TEST_KEY)
http_srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
https_srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
ctx.load_cert_chain(os.path.join(tmp, "c.pem"), os.path.join(tmp, "k.pem"))
https_srv.socket = ctx.wrap_socket(https_srv.socket, server_side=True)
for srv in (http_srv, https_srv):
    threading.Thread(target=srv.serve_forever, daemon=True).start()
HP, SP = http_srv.server_address[1], https_srv.server_address[1]

import socket  # noqa: E402
black_hole = socket.socket()                     # accepts connections, never answers
black_hole.bind(("127.0.0.1", 0))
black_hole.listen(8)
HOLD = []
threading.Thread(target=lambda: [HOLD.append(black_hole.accept()) for _ in iter(int, 1)], daemon=True).start()
BP = black_hole.getsockname()[1]
H = f"http://localhost:{HP}"
S = f"https://localhost:{SP}"

# ---- the browser ----------------------------------------------------------------------------
SETTINGS_NAME = "SafariQtSecurity"
raw = QSettings(sb.ORG_NAME, SETTINGS_NAME)
raw.clear()
raw.setValue("httpsMode", "sideways")          # junk must fall back to defaults
raw.setValue("warnDownloads", "maybe")
raw.sync()
app = sb.create_application([sys.argv[0]])
w = sb.create_browser(app, persistent=False, settings_name=SETTINGS_NAME)
w.add_tab(QUrl(sb.START_URL))
w.resize(1100, 720)
w.show()

DIALOGS = []
dialog_answer = {"code": QDialog.DialogCode.Accepted, "text": None, "block": False}


def fake_run_dialog(dialog):
    """Records the sheet instead of showing it, and answers like a user would."""
    DIALOGS.append({"title": dialog.title_label.text(), "message": dialog.message_label.text(),
                    "has_cancel": dialog.cancel_button is not None,
                    "has_block": hasattr(dialog, "block_checkbox"),
                    "ok": dialog.ok_button.text(), "danger": dialog.ok_button.objectName() == "DangerButton"})
    if dialog_answer["text"] is not None and hasattr(dialog, "prompt_field"):
        dialog.prompt_field.setText(dialog_answer["text"])
    if dialog_answer["block"] and hasattr(dialog, "block_checkbox"):
        dialog.block_checkbox.setChecked(True)
    if hasattr(dialog, "range_combo") and dialog_answer.get("range"):
        combo = dialog.range_combo
        combo.setCurrentIndex(combo.findData(dialog_answer["range"]))
    return dialog_answer["code"]


SAVED = []
w.run_dialog = fake_run_dialog
w.ask_save_path = lambda suggested: (SAVED.append(suggested), os.path.join(tmp, os.path.basename(suggested)))[1]

steps = []


def step(ms):
    def deco(fn):
        steps.append((ms, fn))
        return fn
    return deco


def view():
    return w.current_view()


def history_urls(v):
    return [item.url().toString() for item in v.page().history().items()]


class FakeInfo:
    def __init__(self, url, main=True, method=b"GET", redirect=False, first=""):
        self._u, self._f = QUrl(url), QUrl(first or url)
        self.main, self.method, self.is_redirect = main, method, redirect
        self.headers, self.redirected_to, self.blocked = {}, None, False

    def requestUrl(self):
        return self._u

    def firstPartyUrl(self):
        return self._f

    def resourceType(self):
        RT = sb.QWebEngineUrlRequestInfo.ResourceType
        return RT.ResourceTypeMainFrame if self.main else RT.ResourceTypeImage

    def requestMethod(self):
        return self.method

    def navigationType(self):
        NT = sb.QWebEngineUrlRequestInfo.NavigationType
        return NT.NavigationTypeRedirect if self.is_redirect else NT.NavigationTypeTyped

    def setHttpHeader(self, k, v):
        self.headers[bytes(k)] = bytes(v)

    def redirect(self, url):
        self.redirected_to = QUrl(url)

    def block(self, b):
        self.blocked = b


class FakeCookieRequest:
    def __init__(self, third):
        self.thirdParty = third


# ---- pure functions -------------------------------------------------------------------------
@step(1500)
def pure():
    prefs = sb.load_privacy_prefs(QSettings(sb.ORG_NAME, SETTINGS_NAME))
    check("junk https mode -> default", prefs["httpsMode"] == "upgrade", prefs["httpsMode"])
    check("junk bool -> False", prefs["warnDownloads"] is False)
    QSettings(sb.ORG_NAME, SETTINGS_NAME).setValue("warnDownloads", True)
    w.set_privacy_pref("warnDownloads", True)

    strip = lambda u: (sb.strip_tracking_params(QUrl(u)) or QUrl("none")).toString()   # noqa: E731
    check("strip utm/fbclid keeps others + fragment",
          strip("https://a.com/p?utm_source=x&id=5&FBCLID=1#top") == "https://a.com/p?id=5#top",
          strip("https://a.com/p?utm_source=x&id=5&FBCLID=1#top"))
    check("strip all params drops '?'", strip("https://a.com/?utm_medium=mail") == "https://a.com/")
    check("no tracking params -> None", sb.strip_tracking_params(QUrl("https://a.com/?q=a%26b&page=2")) is None)
    check("encoded values survive stripping",
          strip("https://a.com/s?q=a%26b%3Dc&gclid=9") == "https://a.com/s?q=a%26b%3Dc",
          strip("https://a.com/s?q=a%26b%3Dc&gclid=9"))

    up = lambda u: sb.should_upgrade_to_https(QUrl(u))                                    # noqa: E731
    check("upgrade public http", up("http://example.com/x"))
    check("no upgrade: https / localhost / IP / port / intranet",
          not any(up(u) for u in ("https://example.com", "http://localhost/", "http://192.168.1.1/",
                                  "http://example.com:8080/", "http://router/", "http://nas.local/",
                                  "http://dev.test/", "http://[::1]/")))

    disp = lambda u: sb.display_text_for(QUrl(u))                                         # noqa: E731
    check("homograph: all-Cyrillic 'apple' shown as xn--", disp("https://xn--80ak6aa92e.com/") == "xn--80ak6aa92e.com",
          disp("https://xn--80ak6aa92e.com/"))
    check("homograph: mixed-script 'paypal' shown as xn--", disp("https://xn--pypal-4ve.com/") == "xn--pypal-4ve.com",
          disp("https://xn--pypal-4ve.com/"))
    check("real IDN münchen.de stays readable", disp("https://xn--mnchen-3ya.de/") == "münchen.de")
    check("Japanese IDN stays readable", disp("https://xn--r8jz45g.jp/") == "例え.jp")
    check("edit text shows xn-- for spoofs",
          "xn--80ak6aa92e.com" in sb.edit_text_for(QUrl("https://xn--80ak6aa92e.com/login")))
    check("not-secure label for accepted certificates",
          sb.display_text_for(QUrl("https://bad.example/"), True) == "Not Secure — bad.example")

    check("dangerous downloads", sb.is_dangerous_download("Setup.EXE") and sb.is_dangerous_download("a.ps1")
          and not sb.is_dangerous_download("photo.jpg") and not sb.is_dangerous_download("exe"))
    motw = sb.mark_of_the_web(QUrl("https://u:p@cdn.example.com/a.exe"), QUrl("https://example.com/dl"))
    check("mark of the web: zone 3, no credentials",
          motw.startswith("[ZoneTransfer]\r\nZoneId=3\r\n") and "HostUrl=https://cdn.example.com/a.exe" in motw
          and "u:p" not in motw and "ReferrerUrl=https://example.com/dl" in motw, motw)
    check("mark of the web without urls (private)", sb.mark_of_the_web(None, None) == "[ZoneTransfer]\r\nZoneId=3\r\n")

    now = time.time()
    hour, today, yday = (sb.history_cutoff(k, now) for k in ("hour", "today", "yesterday"))
    check("history periods ordered", yday < today <= now and abs(now - 3600 - hour) < 1 and now - yday <= 2 * 86400 + 3600)
    check("'all' period is None", sb.history_cutoff("all") is None)

    g = w.guard
    info = FakeInfo("https://shop.example/item?utm_campaign=x&ref=5")
    g.interceptRequest(info)
    check("guard strips tracking params on navigation",
          info.redirected_to is not None and info.redirected_to.toString() == "https://shop.example/item?ref=5")
    check("guard sends Sec-GPC", info.headers.get(b"Sec-GPC") == b"1")
    sub = FakeInfo("https://cdn.example/pixel.gif?utm_source=x", main=False)
    g.interceptRequest(sub)
    check("subresources aren't rewritten", sub.redirected_to is None)
    post = FakeInfo("http://example.com/form", method=b"POST")
    g.interceptRequest(post)
    check("POST isn't upgraded", post.redirected_to is None)
    info = FakeInfo("http://news.example.com/story")
    g.interceptRequest(info)
    check("guard upgrades http to https", info.redirected_to is not None
          and info.redirected_to.toString() == "https://news.example.com/story")
    check("upgrade remembered for fallback", g.was_upgraded(QUrl("https://news.example.com/story")))
    back = FakeInfo("http://news.example.com/story", redirect=True)
    g.interceptRequest(back)
    check("https->http redirect: site allowed over http", back.redirected_to is None
          and "news.example.com" in g.http_allowed)
    again = FakeInfo("http://news.example.com/other")
    g.interceptRequest(again)
    check("http-only site isn't upgraded again", again.redirected_to is None)
    check("bare host key matches WebEngine's form", g._key(QUrl("https://a.com")) == g._key(QUrl("https://a.com/")))
    check("third-party cookies refused", not g.allow_cookie(FakeCookieRequest(True)))
    check("first-party cookies allowed", g.allow_cookie(FakeCookieRequest(False)))
    w.set_privacy_pref("preventTracking", False)
    check("tracking off allows third-party cookies", g.allow_cookie(FakeCookieRequest(True)))
    w.set_privacy_pref("preventTracking", True)
    w.set_privacy_pref("httpsMode", "off")
    info = FakeInfo("http://news2.example.com/")
    g.interceptRequest(info)
    check("https mode off: no upgrade", info.redirected_to is None)
    w.set_privacy_pref("httpsMode", "upgrade")
    check("secure DNS accepted", sb.apply_secure_dns("quad9") and sb.apply_secure_dns("off"))
    sb.apply_secure_dns("quad9")


# ---- link stripping + GPC over the network --------------------------------------------------
@step(300)
def nav_strip():
    view().setUrl(QUrl(f"{H}/page?utm_source=news&id=5&fbclid=abc"))


@step(2500)
def nav_strip_check():
    check("tracking params removed before loading", view().url().toString() == f"{H}/page?id=5",
          view().url().toString())
    hits = [r for r in REQUESTS if r[0].startswith("/page")]
    check("server never saw the tracking params", hits and all("utm_" not in p and "fbclid" not in p for p, _ in hits))
    check("server got Sec-GPC: 1", hits and hits[-1][1] == "1")
    view().setUrl(QUrl(f"{H}/gpc"))


@step(2000)
def gpc_js():
    check("navigator.globalPrivacyControl is true", view().title() == "gpc:true", view().title())
    w.set_privacy_pref("globalPrivacyControl", False)
    check("GPC script removed when off", not w.profile.scripts().find(sb.GPC_SCRIPT_NAME))
    w.set_privacy_pref("globalPrivacyControl", True)
    check("GPC script back on", bool(w.profile.scripts().find(sb.GPC_SCRIPT_NAME)))
    view().setUrl(QUrl(f"{H}/cookie"))


@step(2000)
def cookies():
    names = {bytes(c.name()).decode() for c in w.cookies.cookies.values()}
    check("first-party cookie stored (and mirrored)", "first" in names, names)


# ---- certificate warning ---------------------------------------------------------------------
@step(200)
def cert_go():
    view().setUrl(QUrl(f"{S}/secret"))


@step(2500)
def cert_warning():
    v = view()
    check("bad certificate: warning shown", v.warning is not None and v.warning["kind"] == "certificate"
          and w.warning_panel.isVisible(), str(v.warning))
    check("warning covers the page card", w.warning_panel.geometry() == w.tabs.card_rect())
    check("address says Not Secure", w.address.edit.text().startswith("Not Secure"), w.address.edit.text())
    check("server never received the request", not any(p == "/secret" for p, _ in REQUESTS))
    check("warning page not added to history", not any(e["url"].startswith(S) for e in w.store.history))
    w.warning_panel.details_button.click()
    check("details reveal 'visit anyway'", w.warning_panel.details_label.isVisible()
          and w.warning_panel.proceed_button.isVisible())
    w.warning_panel.proceed_button.click()


@step(2500)
def cert_proceeded():
    v = view()
    check("visit anyway loads the page", v.title() == "secret" and v.warning is None, v.title())
    check("still marked Not Secure after accepting", w.address.edit.text().startswith("Not Secure"),
          w.address.edit.text())
    view().setUrl(QUrl(f"{H}/page"))


@step(1500)
def cert_back_prep():
    view().setUrl(QUrl(f"https://127.0.0.1:{SP}/other"))       # different host: not excepted


@step(2500)
def cert_back():
    check("second bad host warns too", view().warning is not None)
    w.warning_panel.back_button.click()


@step(2000)
def cert_back_done():
    check("Go Back returns to the previous page", view().url().toString() == f"{H}/page" and view().warning is None,
          view().url().toString())
    check("panel hidden after going back", not w.warning_panel.isVisible())


# ---- https upgrade fallback (simulated: the http server can't speak TLS) ---------------------
@step(200)
def fallback_go():
    w.guard.upgraded[w.guard._key(QUrl(f"https://localhost:{HP}/plain"))] = QUrl(f"{H}/plain")
    view().setUrl(QUrl(f"https://localhost:{HP}/plain"))


@step(3500)
def fallback_check():
    v = view()
    check("failed https falls back to http", v.url().toString() == f"{H}/plain", v.url().toString())
    check("error page replaced in history", not any(u.startswith(f"https://localhost:{HP}") for u in history_urls(v)),
          history_urls(v))
    w.guard.http_allowed.clear()
    w.set_privacy_pref("httpsMode", "strict")
    w.guard.upgraded[w.guard._key(QUrl(f"https://localhost:{HP}/strict"))] = QUrl(f"{H}/strict")
    v.setUrl(QUrl(f"https://localhost:{HP}/strict"))


@step(3000)
def strict_check():
    v = view()
    check("strict mode warns instead of falling back", v.warning is not None and v.warning["kind"] == "insecure"
          and w.warning_panel.proceed_button.isVisible(), str(v.warning))
    w.warning_panel.proceed_button.click()


@step(3000)
def strict_continue():
    check("continue loads the http site", view().url().toString() == f"{H}/strict", view().url().toString())
    w.set_privacy_pref("httpsMode", "upgrade")
    sb.HTTPS_UPGRADE_TIMEOUT_MS = 2500
    w.guard.upgraded[w.guard._key(QUrl(f"https://localhost:{BP}/hang"))] = QUrl(f"{H}/hang-ok")
    view().setUrl(QUrl(f"https://localhost:{BP}/hang"))


@step(1200)
def hang_waiting():
    check("silent https port: still waiting at first", view().loading)


@step(3500)
def hang_fell_back():
    check("silent https port: falls back after the timeout", view().url().toString() == f"{H}/hang-ok",
          view().url().toString())
    check("timed-out attempt not left in history", not any(f":{BP}/" in u for u in history_urls(view())),
          history_urls(view()))
    w.guard.http_allowed.clear()
    sb.HTTPS_UPGRADE_TIMEOUT_MS = 6000


# ---- permissions -----------------------------------------------------------------------------
@step(200)
def perm_go():
    view().setUrl(QUrl(f"{H}/geo"))


@step(2500)
def perm_prompt():
    p = w.permission_prompt
    text = p.text_label.text()
    check("location prompt shown", p.isVisible() and f"localhost:{HP}" in text and "location" in text, text)
    card = w.tabs.card_rect()
    check("prompt sits inside the page card", card.contains(p.geometry().topLeft()) and p.geometry().right() <= card.right() + 1)
    p.allow_button.click()


@step(1500)
def perm_granted():
    check("prompt closes after answering", not w.permission_prompt.isVisible())
    stored = [(p.permissionType().name, p.state()) for p in w.stored_permissions()]
    check("allow is remembered", ("Geolocation", sb.QWebEnginePermission.State.Granted) in stored, stored)
    for p in w.stored_permissions():
        w.forget_permission(p)
    check("forgetting removes it", not w.stored_permissions())
    view().setUrl(QUrl(f"{H}/notify"))


@step(2500)
def notify():
    check("notifications refused quietly", view().title() == "notify:denied" and not w.permission_prompt.isVisible(),
          view().title())
    check("notification refusal not stored", not w.stored_permissions())
    w.add_tab(QUrl(f"{H}/geo?bg=1"), background=True)


@step(2500)
def background_prompt():
    check("background tab's request waits", not w.permission_prompt.isVisible())
    w.select_tab(w.tabs.count() - 1)


@step(1500)
def background_prompt_shown():
    check("switching to it shows the prompt", w.permission_prompt.isVisible()
          and "location" in w.permission_prompt.text_label.text(), w.permission_prompt.text_label.text())
    w.permission_prompt.deny_button.click()


@step(1500)
def denied():
    check("deny answered", view().title() == "geo-err", view().title())
    check("settings list shows the decision", any(p.permissionType().name == "Geolocation"
                                                   and p.state() == sb.QWebEnginePermission.State.Denied
                                                   for p in w.stored_permissions()))
    check("reset for the site", w.reset_site_permissions(view().url()) == 1 and not w.stored_permissions())
    w.activateWindow()
    view().setFocus()
    view().setUrl(QUrl(f"{H}/clip"))


@step(2500)
def clipboard():
    text = w.permission_prompt.text_label.text()
    if "not focused" in view().title() or "NotAllowed" in view().title():
        print("NOTE clipboard check skipped: this platform gives the page no keyboard focus", flush=True)
    else:
        check("clipboard prompt (focused tab)", w.permission_prompt.isVisible() and "copy" in text,
              f"{text} / {view().title()}")
    w.permission_prompt.deny_button.click()
    w.reset_site_permissions(view().url())
    w.close_current_tab()


# ---- page dialogs ----------------------------------------------------------------------------
@step(500)
def dialogs():
    DIALOGS.clear()
    view().setUrl(QUrl(f"{H}/page"))


@step(1500)
def dialogs_run():
    dialog_answer.update(code=QDialog.DialogCode.Accepted, text="typed", block=False)
    view().page().runJavaScript("alert('hello <b>x</b>'); JSON.stringify([confirm('sure?'), prompt('name?', 'def')])",
                                0, lambda r: DIALOGS.append({"result": r}))


@step(1500)
def dialogs_check():
    titles = [d.get("title") for d in DIALOGS if "title" in d]
    check("dialogs name the site", titles and all(t == f"localhost:{HP} says" for t in titles), titles)
    check("page text shown literally", DIALOGS[0]["message"] == "hello <b>x</b>")
    check("alert has no Cancel, confirm does", not DIALOGS[0]["has_cancel"] and DIALOGS[1]["has_cancel"])
    check("second dialog offers blocking", DIALOGS[1]["has_block"] and not DIALOGS[0]["has_block"])
    check("confirm/prompt answers reach the page", DIALOGS[-1].get("result") == '[true,"typed"]', DIALOGS[-1])
    DIALOGS.clear()
    dialog_answer.update(block=True)
    view().page().runJavaScript("for (let i = 0; i < 6; i++) alert(i); 'done'", 0,
                                lambda r: DIALOGS.append({"result": r}))


@step(1500)
def dialogs_blocked():
    shown = [d for d in DIALOGS if "title" in d]
    check("dialog loop stopped after blocking", len(shown) == 1 and DIALOGS[-1].get("result") == "done", len(shown))
    dialog_answer.update(block=False)
    view().setUrl(QUrl(f"{H}/page?again=1"))


@step(1500)
def dialogs_reset():
    DIALOGS.clear()
    view().page().runJavaScript("alert('new page')", 0, lambda r: None)


@step(800)
def dialogs_reset_check():
    check("a new page may show dialogs again", any(d.get("message") == "new page" for d in DIALOGS))
    DIALOGS.clear()
    bg = w.add_tab(QUrl(f"{H}/page"), background=True)
    QTimer.singleShot(1500, lambda: bg.page().runJavaScript("alert('from background')", 0, lambda r: None))


@step(2500)
def background_dialog():
    check("background tabs can't pop dialogs", not any(d.get("message") == "from background" for d in DIALOGS))


# ---- downloads ---------------------------------------------------------------------------------
@step(200)
def dl_go():
    DIALOGS.clear()
    dialog_answer.update(code=QDialog.DialogCode.Rejected)
    view().setUrl(QUrl(f"{H}/setup.exe"))


@step(2000)
def dl_cancelled():
    check("app download asks first", DIALOGS and DIALOGS[0]["danger"] and "setup.exe" in DIALOGS[0]["message"], DIALOGS)
    check("declining cancels it", not os.path.exists(os.path.join(tmp, "setup.exe")) and not SAVED)
    DIALOGS.clear()
    dialog_answer.update(code=QDialog.DialogCode.Accepted)
    view().setUrl(QUrl(f"{H}/setup.exe?2"))


@step(2500)
def dl_done():
    path = os.path.join(tmp, "setup.exe")
    check("accepted download saved", os.path.exists(path))
    if sb.IS_WINDOWS:
        try:
            with open(path + ":Zone.Identifier", encoding="ascii") as f:
                zone = f.read()
        except OSError as e:
            zone = repr(e)
        check("Mark of the Web written (SmartScreen)", "ZoneId=3" in zone and f"/setup.exe" in zone, zone)
    DIALOGS.clear()
    view().setUrl(QUrl(f"{H}/notes.txt"))


@step(2000)
def dl_plain():
    check("ordinary files don't warn", not DIALOGS and os.path.exists(os.path.join(tmp, "notes.txt")), DIALOGS)


# ---- private browsing ---------------------------------------------------------------------------
STATE = {}


@step(200)
def private_open():
    STATE["history"] = len(w.store.history)
    p = w.open_private_window()
    STATE["p"] = p
    check("private window is off the record", p.private and p.profile.isOffTheRecord())
    check("private address field styled", p.address.edit.property("private") is True
          and p.address.page_glyph == "private")
    check("shares Favorites", p.store is w.store)
    html_text = sb.render_start_page(p.theme, p.store, True, None, private=True)
    check("private start page explains itself, no Frequently Visited",
          "Private Browsing is on" in html_text and "Frequently Visited" not in html_text)
    p.current_view().setUrl(QUrl(f"{H}/page?private=1"))


@step(2500)
def private_check():
    p = STATE["p"]
    check("private visit not in history", len(w.store.history) == STATE["history"]
          and not any("private=1" in e["url"] for e in w.store.history))
    check("private window title", "Private Browsing" in p.windowTitle(), p.windowTitle())
    check("settings reach private windows too", p in w.all_windows())
    w.set_privacy_pref("stripTrackingParams", False)
    check("private guard follows settings", p.guard.strip_links is False)
    w.set_privacy_pref("stripTrackingParams", True)
    STATE["profile_alive"] = True
    p.profile.destroyed.connect(lambda *_: STATE.update(profile_alive=False))
    p.close()


@step(1500)
def private_closed():
    check("closing deletes the window and its profile", w.all_windows() == [w] and not STATE["profile_alive"])


# ---- settings dialog ------------------------------------------------------------------------------
@step(200)
def settings_dialog():
    d = w.show_privacy_settings()
    STATE["d"] = d
    check("settings has all switches", set(d.switches) == {"preventTracking", "stripTrackingParams",
                                                           "globalPrivacyControl", "warnDownloads", "blockAds",
                                                           "rejectCookieBanners", "fingerprintProtection",
                                                           "clearCookiesOnQuit", "searchSuggestions",
                                                           "rememberPages"})
    d.switches["warnDownloads"].click()
    check("switch saves + applies", w.prefs["warnDownloads"] is False
          and QSettings(sb.ORG_NAME, SETTINGS_NAME).value("warnDownloads") in (False, "false"))
    d.switches["warnDownloads"].click()
    combo = d.combos["httpsMode"]
    combo.setCurrentIndex(combo.findData("strict"))
    check("combo applies https mode", w.guard.https_mode == "strict")
    combo.setCurrentIndex(combo.findData("upgrade"))
    d.show_page(1)
    check("permissions page lists none", d.permission_list.count() == 1)
    d.close()


# ---- clear history ranges ---------------------------------------------------------------------------
@step(500)
def clear_ranges():
    now = time.time()
    w.store.history = [
        {"title": "recent", "url": "https://recent.example/", "time": now - 600},
        {"title": "older", "url": "https://older.example/", "time": now - 3 * 3600},
        {"title": "ancient", "url": "https://ancient.example/", "time": now - 5 * 86400},
    ]
    for domain in ("recent.example", "older.example"):
        cookie = QNetworkCookie(b"sid", b"1")
        cookie.setDomain(domain)
        cookie.setPath("/")
        w.profile.cookieStore().setCookie(cookie, QUrl(f"https://{domain}/"))


@step(1200)
def clear_hour():
    before = {c.domain() for c in w.cookies.cookies.values()}
    STATE["before"] = before
    dialog_answer.update(code=QDialog.DialogCode.Accepted, range="hour")
    w.show_clear_history_dialog()


@step(1200)
def clear_hour_check():
    urls = [e["url"] for e in w.store.history]
    check("last hour: only recent history removed", urls == ["https://older.example/", "https://ancient.example/"], urls)
    domains = {c.domain() for c in w.cookies.cookies.values()}
    before = {d.lstrip(".") for d in STATE["before"]}
    domains = {d.lstrip(".") for d in domains}
    check("last hour: that site's cookies removed, others kept",
          "recent.example" in before and "recent.example" not in domains and "older.example" in domains,
          (before, domains))
    dialog_answer.update(range="all")
    w.show_clear_history_dialog()


@step(1500)
def clear_all_check():
    check("all history removed", w.store.history == [])
    check("all cookies removed", not w.cookies.cookies, list(w.cookies.cookies))
    check("off-the-record profile schedules no disk wipe",
          QSettings(sb.ORG_NAME, SETTINGS_NAME).value("pendingSiteDataWipe") is None)
    store_dir = tempfile.mkdtemp(prefix="safariqt-wipe-")
    for name in ("Local Storage", "IndexedDB", "Cookies"):
        os.makedirs(os.path.join(store_dir, name), exist_ok=True) if name != "Cookies" else open(
            os.path.join(store_dir, name), "w").close()
    sb.wipe_site_data(store_dir)
    left = sorted(os.listdir(store_dir))
    check("site data wipe keeps cookies file for the API, removes storage", left == ["Cookies"], left)


# ---- run ----------------------------------------------------------------------------------------------
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
    failed = len(RESULTS) - passed
    print(f"\n{passed} passed, {failed} failed, {len(ERRORS)} uncaught errors", flush=True)
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
http_srv.shutdown()
https_srv.shutdown()
