import QtQuick

// A ring gauge: one value around the outside, optionally a second on an inner ring.
Canvas {
    id: r
    property real value: 0
    property real inner: -1
    property color ink: Theme.t.accent
    property color innerInk: Theme.t.glowB
    property color track: Theme.t.dark ? "#22FFFFFF" : "#1F141E28"
    property int thickness: 9
    property bool full: false                  // a whole circle, from the top (a countdown) instead of a gauge
    width: 120; height: 120
    onValueChanged: requestPaint(); onFullChanged: requestPaint(); onInnerChanged: requestPaint(); onInkChanged: requestPaint(); onTrackChanged: requestPaint()
    onPaint: {
        var c = getContext("2d"), cx = width / 2, cy = height / 2, start = full ? -Math.PI / 2 : Math.PI * 0.75, sweep = full ? Math.PI * 2 : Math.PI * 1.5
        c.reset(); c.lineCap = "round"
        function arc(radius, v, colour, w) {
            c.lineWidth = w; c.strokeStyle = track; c.beginPath(); c.arc(cx, cy, radius, start, start + sweep); c.stroke()
            if (v > 0.004) { c.strokeStyle = colour; c.beginPath(); c.arc(cx, cy, radius, start, start + sweep * Math.min(1, v)); c.stroke() }
        }
        arc(width / 2 - thickness / 2 - 1, value, ink, thickness)
        if (inner >= 0) arc(width / 2 - thickness * 1.9 - 3, inner, innerInk, thickness * 0.6)
    }
}
