import QtQuick

// The sign-in screen's line icons, drawn rather than taken from a font so they're crisp at any size and need nothing
// installed: moon, restart, power, arrow, caps, keyboard, session, chevron, plus, back, person.
Canvas {
    id: icon
    property string name: ""
    property color ink: "white"
    property real stroke: 1.7
    width: 20; height: 20
    onNameChanged: requestPaint()
    onInkChanged: requestPaint()
    onWidthChanged: requestPaint()
    renderStrategy: Canvas.Cooperative
    onPaint: {
        var c = getContext("2d")
        c.reset()
        var s = width / 24
        c.scale(s, s)
        c.strokeStyle = ink; c.fillStyle = ink
        c.lineWidth = stroke; c.lineCap = "round"; c.lineJoin = "round"
        c.beginPath()
        switch (name) {
        case "moon":
            c.arc(12, 12, 8, 0, Math.PI * 2); c.fill()
            c.globalCompositeOperation = "destination-out"
            c.beginPath(); c.arc(16.6, 8.4, 6.6, 0, Math.PI * 2); c.fill()
            c.globalCompositeOperation = "source-over"
            return
        case "restart":
            c.arc(12, 12, 7.2, -Math.PI * 0.35, Math.PI * 1.45); c.stroke()
            c.beginPath(); c.moveTo(15.6, 2.8); c.lineTo(16.6, 6.6); c.lineTo(12.8, 7.4); c.stroke()
            return
        case "power":
            c.arc(12, 13, 7.2, -Math.PI / 2 + 0.75, -Math.PI / 2 - 0.75 + Math.PI * 2); c.stroke()
            c.beginPath(); c.moveTo(12, 3.5); c.lineTo(12, 11.5); c.stroke()
            return
        case "arrow":
            c.moveTo(6, 12); c.lineTo(18, 12); c.moveTo(13, 7); c.lineTo(18, 12); c.lineTo(13, 17); c.stroke()
            return
        case "caps":
            c.moveTo(12, 4); c.lineTo(19, 11.5); c.lineTo(15, 11.5); c.lineTo(15, 15); c.lineTo(9, 15); c.lineTo(9, 11.5); c.lineTo(5, 11.5); c.closePath(); c.stroke()
            c.beginPath(); c.moveTo(9, 19); c.lineTo(15, 19); c.stroke()
            return
        case "keyboard":
            c.roundedRect(3, 6.5, 18, 11, 2.5, 2.5); c.stroke()
            for (var i = 0; i < 4; i++) { c.beginPath(); c.arc(7 + i * 3.4, 10.3, 0.75, 0, Math.PI * 2); c.fill() }
            c.beginPath(); c.moveTo(8, 14); c.lineTo(16, 14); c.stroke()
            return
        case "session":
            c.roundedRect(4, 4, 7, 7, 1.8, 1.8); c.roundedRect(13, 4, 7, 7, 1.8, 1.8); c.roundedRect(4, 13, 7, 7, 1.8, 1.8); c.roundedRect(13, 13, 7, 7, 1.8, 1.8); c.stroke()
            return
        case "chevron":
            c.moveTo(7, 10); c.lineTo(12, 15); c.lineTo(17, 10); c.stroke()
            return
        case "plus":
            c.moveTo(12, 5); c.lineTo(12, 19); c.moveTo(5, 12); c.lineTo(19, 12); c.stroke()
            return
        case "back":
            c.moveTo(14.5, 5.5); c.lineTo(8, 12); c.lineTo(14.5, 18.5); c.stroke()
            return
        case "person":
            c.arc(12, 8.5, 4, 0, Math.PI * 2); c.fill()
            c.beginPath(); c.moveTo(4.5, 20.5); c.bezierCurveTo(5, 15, 8.5, 13.5, 12, 13.5); c.bezierCurveTo(15.5, 13.5, 19, 15, 19.5, 20.5); c.closePath(); c.fill()
            return
        }
    }
}
