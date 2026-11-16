/*
    Huginn OS: tells Huginn's shell (org.huginn.Shell.Active) which app is in front, its window's title, and whether
    that window fills the screen (the top bar turns to glass then). Only changes are sent.
    It also gives the shell its keys: Print (a screenshot), Shift+Print and Meta+Shift+S (the Screenshot app),
    Meta+Space (Search everything). Meta alone opens the start menu, through kwinrc's ModifierOnlyShortcuts.
    And it keeps the shell's list of windows and spaces (org.huginn.Shell.Windows), for the dock (an app's windows,
    hiding the app in front) and the space names: {"current", "spaces", "windows": [{"id", "app", "title",
    "minimised", "active", "space", "x", "y", "w", "h"}]}.
*/
var watched = null;
var last = "";

function filled(w) {
    if (!w) return false;
    if (w.fullScreen) return true;
    var area = workspace.clientArea(KWin.MaximizeArea, w);
    return w.frameGeometry.width >= area.width - 2 && w.frameGeometry.height >= area.height - 2;
}

function report() {
    var w = workspace.activeWindow;
    if (w && !(w.normalWindow || w.dialog)) return;          // the shell's own bar, dock and menus don't count
    var state = [w ? w.caption : "", w ? w.resourceClass : "", w ? w.desktopFileName : "", filled(w)];
    var key = JSON.stringify(state);
    if (key === last) return;
    last = key;
    callDBus("org.huginn.Shell", "/org/huginn/Shell", "org.huginn.Shell", "Active", state[0], state[1], state[2], state[3]);
}

function watch(w) {
    if (watched) {
        try {
            watched.captionChanged.disconnect(report);
            watched.frameGeometryChanged.disconnect(report);
            watched.fullScreenChanged.disconnect(report);
        } catch (e) {}
    }
    watched = (w && (w.normalWindow || w.dialog)) ? w : watched;
    if (watched) {
        watched.captionChanged.connect(report);
        watched.frameGeometryChanged.connect(report);
        watched.fullScreenChanged.connect(report);
    }
    report();
}

workspace.windowActivated.connect(watch);
workspace.windowRemoved.connect(function (w) { if (w === watched) { watched = null; report(); } });
watch(workspace.activeWindow);

function shell(method, arg) {
    callDBus("org.huginn.Shell", "/org/huginn/Shell", "org.huginn.Shell", method, arg);
}
registerShortcut("Huginn Screenshot", "Huginn: take a screenshot of the whole screen", "Print", function () { shell("Screenshot", "screen"); });
registerShortcut("Huginn Screenshot App", "Huginn: open Screenshot to choose what to take", "Shift+Print", function () { shell("Screenshot", "choose"); });
registerShortcut("Huginn Screenshot Choose", "Huginn: open Screenshot to choose what to take", "Meta+Shift+S", function () { shell("Screenshot", "choose"); });
registerShortcut("Huginn Search", "Huginn: Search everything", "Meta+Space", function () { shell("Search", ""); });
registerShortcut("Huginn Today", "Huginn: Today (the month, the weather, what's coming)", "Meta+T", function () { shell("Key", "today"); });
// The Overview (KWin's own, in this session) and spaces: Meta+Tab, Meta+1…9, Meta+Shift+←/→ takes the window along.
registerShortcut("Huginn Overview", "Huginn: every window and your spaces", "Meta+Tab", function () {
    callDBus("org.kde.kglobalaccel", "/component/kwin", "org.kde.kglobalaccel.Component", "invokeShortcut", "Overview");
});
function goSpace(n) { var d = workspace.desktops[n]; if (d) workspace.currentDesktop = d; }
for (var n = 0; n < 9; n++) {
    (function (i) { registerShortcut("Huginn Space " + (i + 1), "Huginn: space " + (i + 1), "Meta+" + (i + 1), function () { goSpace(i); }); })(n);
}
function takeAlong(step) {
    var w = workspace.activeWindow, all = workspace.desktops, at = all.indexOf(workspace.currentDesktop) + step;
    if (!w || at < 0) return;
    if (at >= all.length) workspace.createDesktop(all.length, "Space " + (all.length + 1));
    var d = workspace.desktops[at];
    w.desktops = [d];
    workspace.currentDesktop = d;
    workspace.activeWindow = w;
}
registerShortcut("Huginn Take Left", "Huginn: take the window to the space on the left", "Meta+Shift+Left", function () { takeAlong(-1); });
registerShortcut("Huginn Take Right", "Huginn: take the window to the space on the right", "Meta+Shift+Right", function () { takeAlong(1); });

// ------------------------------------------------------------------ every window, for the dock
var lastWindows = "";

function spaceOf(w) {
    if (w.onAllDesktops || !w.desktops || w.desktops.length === 0) return -1;
    return workspace.desktops.indexOf(w.desktops[0]);
}

function reportWindows() {
    var rows = [];
    var all = workspace.windowList();
    for (var i = 0; i < all.length; i++) {
        var w = all[i];
        if (!w.normalWindow || w.skipTaskbar) continue;
        var g = w.frameGeometry;
        rows.push({ id: String(w.internalId), app: w.desktopFileName || w.resourceClass || "", cls: w.resourceClass || "",
                    title: w.caption, minimised: w.minimized, active: w === workspace.activeWindow, space: spaceOf(w), pid: w.pid, full: w.fullScreen,
                    x: g.x, y: g.y, w: g.width, h: g.height });
    }
    var spaces = [];
    for (var j = 0; j < workspace.desktops.length; j++) spaces.push(workspace.desktops[j].name);
    var now = JSON.stringify({ current: workspace.desktops.indexOf(workspace.currentDesktop), spaces: spaces, windows: rows });
    if (now === lastWindows) return;
    lastWindows = now;
    callDBus("org.huginn.Shell", "/org/huginn/Shell", "org.huginn.Shell", "Windows", now);
}

function hook(w) {
    if (!w.normalWindow) return;
    w.captionChanged.connect(reportWindows);
    w.minimizedChanged.connect(reportWindows);
    w.desktopsChanged.connect(reportWindows);
    w.fullScreenChanged.connect(reportWindows);
}

workspace.windowAdded.connect(function (w) { hook(w); reportWindows(); });
workspace.windowRemoved.connect(reportWindows);
workspace.windowActivated.connect(reportWindows);
workspace.currentDesktopChanged.connect(reportWindows);
workspace.desktopsChanged.connect(reportWindows);
workspace.windowList().forEach(hook);
reportWindows();
