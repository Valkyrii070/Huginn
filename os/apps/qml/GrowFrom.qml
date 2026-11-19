import QtQuick

// Opening something from a list, the way Huginn does it: what opens grows out of the row you clicked and shrinks
// back into it when you go back (or, picked in Settings › Desktop & Dock, slides in from the side). Put the opened
// view inside; call open(row) and close(). `shown` stays true until it has gone back in.
// Reduce Motion: a short fade.
Item {
    id: g
    property bool shown: false
    property bool opened: false
    property rect from: Qt.rect(0, 0, width, height)
    readonly property bool motion: Theme.t.openMs > 0
    readonly property bool slide: (typeof Settings !== "undefined" && Settings.inAppMotion === "slide")
    property real p: 0                                     // 0: in the row, 1: open
    visible: shown
    clip: true
    function open(row) {
        if (row) { var r = row.mapToItem(g.parent, 0, 0); openAt(Qt.rect(r.x, r.y, row.width, row.height)) } else openAt(null)
    }
    function openAt(r) {   // r: where it grows from, in the parent's coordinates (null: the whole of it, so it just fades in)
        from = r ? Qt.rect(r.x - g.x, r.y - g.y, r.width, r.height) : Qt.rect(0, 0, width, height)
        shown = true; opened = true; anim.to = 1; anim.duration = motion ? 240 : 120; anim.easing.type = Easing.OutCubic; anim.restart()
    }
    function close() { opened = false; anim.to = 0; anim.duration = motion ? 180 : 100; anim.easing.type = Easing.InCubic; anim.restart() }
    NumberAnimation { id: anim; target: g; property: "p"; onFinished: if (!g.opened) g.shown = false }
    default property alias content: holder.data
    Item {
        id: holder
        width: g.width; height: g.height
        opacity: g.motion ? Math.min(1, g.p * 1.8) : g.p
        transform: [
            Scale {
                xScale: !g.motion || g.slide ? 1 : (g.from.width + (g.width - g.from.width) * g.p) / Math.max(1, g.width)
                yScale: !g.motion || g.slide ? 1 : (g.from.height + (g.height - g.from.height) * g.p) / Math.max(1, g.height)
            },
            Translate {
                x: !g.motion ? 0 : g.slide ? (1 - g.p) * g.width : g.from.x * (1 - g.p)
                y: !g.motion || g.slide ? 0 : g.from.y * (1 - g.p)
            }
        ]
    }
}
