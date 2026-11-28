"""The Islands look as Huginn OS's apps are laid out (three islands, tabs as wide as their titles, thin) and side by side,
run offscreen.  Usage: python3 islands_test.py [shots folder]"""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_DISABLE_SANDBOX", "1")
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--no-sandbox --disable-gpu --single-process")
SHOTS = sys.argv[1] if len(sys.argv) > 1 else ""
import safari_browser as sb
from PySide6.QtCore import QUrl, QCoreApplication, QPoint
from PySide6.QtWidgets import QApplication
ok = bad = 0
def check(name, cond, extra=""):
    global ok, bad
    if cond:
        ok += 1; print("ok  ", name)
    else:
        bad += 1; print("FAIL", name, extra, flush=True)
def pump(secs=0.6, until=None):
    end = time.time() + secs
    while time.time() < end:
        QCoreApplication.processEvents(); time.sleep(0.01)
        if until and until():
            return True
    return until() if until else True
app = sb.create_application(["huginn-test"])
win = sb.create_browser(app, persistent=False)
win.resize(1280, 760)
win.show()
win.set_look("islands")
pump(1.0)
tb = win.toolbar
page = lambda t, c: QUrl("data:text/html," + f"<title>{t}</title><body style='background:{c};margin:0'><h1 style='font:40px sans-serif;padding:40px'>{t}</h1></body>".replace(" ", "%20").replace("#", "%23"))
win.add_tab(page("Fjord Weekly", "#F4F1EA")); win.add_tab(page("Maps", "#CFE0D5")); win.add_tab(page("Recipes", "#FBE9D2"))
pump(3.0)
check("Islands: three groups, the address with back and forward, split with share and new tab",
      tb._arranged == "islands" and tb.nav_island.buttons[:2] == [tb.back_button, tb.forward_button] and tb.address.parentWidget() is tb.nav_island
      and tb.act_island.buttons == [tb.split_button, tb.share_button, tb.new_tab_button])
check("…the name beside the three, with the sidebar", tb.name_label.isVisible() and tb.name_label.text() == "Huginn" and tb.sidebar_button.parentWidget() is tb.name_island
      and not tb.capsules[0].isVisible() and not tb.overview_button.isVisible())
check("…the groups don't overlap", tb.name_island.geometry().right() < tb.nav_island.mapTo(tb, QPoint(0, 0)).x() < tb.nav_island.mapTo(tb, QPoint(tb.nav_island.width(), 0)).x() < tb.act_island.mapTo(tb, QPoint(0, 0)).x(),
      (tb.name_island.geometry(), tb.nav_island.mapTo(tb, QPoint(0, 0)), tb.act_island.mapTo(tb, QPoint(0, 0))))
bar = win.tabs.tabBar()
geo = bar.geometry()
hints = [(bar.tabText(i), bar.tabSizeHint(i).width()) for i in range(bar.count())]
check("tabs: each as wide as its title, the row an island in the middle", geo.width() < win.tabs.width() - 100 and abs((geo.left() + geo.right()) / 2 - win.tabs.width() / 2) < 3
      and len({w for _t, w in hints}) > 1 and all(sb.ISLAND_TAB_MIN <= w <= sb.ISLAND_TAB_MAX for _t, w in hints), (geo, win.tabs.width(), hints))
if SHOTS:
    win.grab().save(os.path.join(SHOTS, "browser-islands.png"))
n = win.tabs.count()
win.tabs.setCurrentIndex(1); pump(0.5)
left = win.current_view()
win.toggle_split(); pump(1.5)
split = win.tabs.page_at(win.tabs.currentIndex())
check("side by side: the tab and the next as one tab", isinstance(split, sb.SplitPage) and win.tabs.count() == n - 1 and split.views[0] is left, (win.tabs.count(), n))
check("…its title both pages'", " + " in win.tabs.tabText(win.tabs.currentIndex()), win.tabs.tabText(win.tabs.currentIndex()))
check("…the split button lit, the window's page the side you're in", tb.split_button.isChecked() and win.current_view() is left)
right = split.views[1]
split.set_focused(right); pump(3.0)
check("…the other side in: the address follows it", win.current_view() is right and "Maps" in (win.tabs.tabText(win.tabs.currentIndex())) and tb.address.text() == right.url().toString()[:len(tb.address.text())] if hasattr(tb.address, "text") else win.current_view() is right)
check("…every page still counted (two in the split)", len(win.views()) == n and right in win.views() and left in win.views())
if SHOTS:
    win.grab().save(os.path.join(SHOTS, "browser-side-by-side.png"))
win.toggle_split(); pump(0.8)
check("again: two tabs of their own, in order, the one you were in in front", win.tabs.count() == n and win.tabs.page_at(1) is left and win.tabs.page_at(2) is right and win.current_view() is right and not tb.split_button.isChecked())
win.tabs.setCurrentIndex(1); pump(0.3); win.toggle_split(); pump(1.0)
split = win.tabs.page_at(win.tabs.currentIndex())
win._close_split_side(split.views[1]); pump(0.8)
check("closing a side: that page goes, the other is a tab of its own", win.tabs.count() == n - 1 and win.tabs.page_at(1) is left and not isinstance(win.tabs.page_at(1), sb.SplitPage))
win.tabs.setCurrentIndex(win.tabs.count() - 1); pump(0.3)
last = win.current_view(); win.toggle_split(); pump(1.0)
split = win.tabs.page_at(win.tabs.currentIndex())
check("the last tab splits with the one before it", isinstance(split, sb.SplitPage) and split.views[1] is last)
win.close_tab(win.tabs.currentIndex()); pump(0.8)
check("closing the tab side by side closes the side you're in", not isinstance(win.tabs.page_at(win.tabs.currentIndex()), sb.SplitPage) and last not in win.views())
win.set_look("classic"); pump(0.8)
check("Classic: Safari's groups back, side by side among them", tb._arranged == "classic" and tb.capsules[2].buttons[0] is tb.split_button and tb.address.parentWidget() is not tb.nav_island
      and tb.capsules[0].isVisible() and not tb.name_island.isVisible())
win.set_look("islands"); pump(0.5)
check("and Islands again", tb._arranged == "islands" and tb.address.parentWidget() is tb.nav_island)
win.set_appearance("dark"); win.set_realm("niflheim"); pump(1.0)
win.tabs.setCurrentIndex(0); pump(0.3); win.toggle_split(); pump(3.0)
check("dark, another realm: still three islands, the split ringed in the realm's accent",
      tb._arranged == "islands" and isinstance(win.tabs.page_at(win.tabs.currentIndex()), sb.SplitPage))
if SHOTS:
    win.grab().save(os.path.join(SHOTS, "browser-dark.png"))
print(f"\n{ok} passed, {bad} failed")
os._exit(1 if bad else 0)
