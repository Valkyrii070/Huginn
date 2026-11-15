/*
    Huginn OS: tells Huginn's shell (org.huginn.Shell.Active) which app is in front, its window's title, and whether
    that window fills the screen (the top bar turns to glass then). Only changes are sent.
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
