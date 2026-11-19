import QtQuick

// A small history graph for one or two series, scaled to its own peak (or to 1 when `unit` is true).
Canvas {
    id: g
    property var first: []
    property var second: []
    property color ink: Theme.t.accent
    property color secondInk: Theme.t.glowB
    property bool unit: false
    property bool filled: true
    height: 56
    onFirstChanged: requestPaint(); onSecondChanged: requestPaint(); onInkChanged: requestPaint()
    onPaint: {
        var c = getContext("2d"), w = width, h = height
        c.reset()
        c.strokeStyle = Theme.t.dark ? "#14FFFFFF" : "#14141E28"; c.lineWidth = 1
        for (var k = 0; k <= 2; k++) { c.beginPath(); c.moveTo(0, Math.round(k * (h - 1) / 2) + 0.5); c.lineTo(w, Math.round(k * (h - 1) / 2) + 0.5); c.stroke() }
        var peak = unit ? 1 : 1
        if (!unit) { for (var i = 0; i < first.length; i++) peak = Math.max(peak, first[i]); for (var j = 0; j < second.length; j++) peak = Math.max(peak, second[j]) }
        function draw(data, colour, fill) {
            if (!data || data.length < 2) return
            c.beginPath(); c.lineWidth = 1.8; c.lineJoin = "round"; c.strokeStyle = colour
            for (var i = 0; i < data.length; i++) { var x = i * w / (data.length - 1), y = h - 2 - data[i] / peak * (h - 5); i ? c.lineTo(x, y) : c.moveTo(x, y) }
            c.stroke()
            if (fill) { c.lineTo(w, h); c.lineTo(0, h); c.closePath(); c.globalAlpha = 0.13; c.fillStyle = colour; c.fill(); c.globalAlpha = 1 }
        }
        draw(second, secondInk, false); draw(first, ink, filled)
    }
}
