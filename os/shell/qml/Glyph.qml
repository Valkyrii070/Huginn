import QtQuick

// Line icons drawn in code on a 24-unit grid, so they follow the theme colour and need no image files.
Canvas {
    id: g
    property string name: ""
    property color ink: Theme.t.icon
    property int size: 18
    width: size; height: size
    onNameChanged: requestPaint()
    onInkChanged: requestPaint()
    onPaint: {
        var c = getContext("2d"), k = size / 24
        c.reset(); c.scale(k, k); c.strokeStyle = ink; c.fillStyle = ink; c.lineWidth = 1.7; c.lineCap = "round"; c.lineJoin = "round"
        function line() { c.beginPath(); c.moveTo(arguments[0], arguments[1]); for (var i = 2; i < arguments.length; i += 2) c.lineTo(arguments[i], arguments[i + 1]); c.stroke() }
        function poly() { c.beginPath(); c.moveTo(arguments[0], arguments[1]); for (var i = 2; i < arguments.length; i += 2) c.lineTo(arguments[i], arguments[i + 1]); c.closePath(); c.stroke() }
        function fillPoly() { c.beginPath(); c.moveTo(arguments[0], arguments[1]); for (var i = 2; i < arguments.length; i += 2) c.lineTo(arguments[i], arguments[i + 1]); c.closePath(); c.fill() }
        function box(x, y, w, h, r) { c.beginPath(); c.roundedRect(x, y, w, h, r, r); c.stroke() }
        function ring(x, y, r) { c.beginPath(); c.arc(x, y, r, 0, Math.PI * 2); c.stroke() }
        function dot(x, y, r) { c.beginPath(); c.arc(x, y, r, 0, Math.PI * 2); c.fill() }
        switch (name) {
        case "key": ring(8, 14, 4); line(11, 11.5, 20, 4); line(16.5, 7.5, 19, 10); line(18.5, 5.5, 20.5, 7.5); break
        case "lock": box(5, 10.5, 14, 10, 2.5); c.beginPath(); c.arc(12, 10.5, 4, Math.PI, 0); c.stroke(); dot(12, 15.5, 1.2); break
        case "history": c.beginPath(); c.arc(12, 12, 8.5, -Math.PI * 0.85, Math.PI * 0.75); c.stroke(); line(3.2, 5.2, 4.2, 9.6, 8.4, 8.2); line(12, 7.5, 12, 12, 15, 14); break
        case "mic": box(9, 3, 6, 11, 3); c.beginPath(); c.arc(12, 11, 6, 0, Math.PI); c.stroke(); line(12, 17, 12, 21); line(9, 21, 15, 21); break
        case "mute": box(9, 3, 6, 11, 3); c.beginPath(); c.arc(12, 11, 6, 0, Math.PI); c.stroke(); line(12, 17, 12, 21); line(9, 21, 15, 21); line(4, 3.5, 20, 20.5); break
        case "sun": ring(12, 12, 4); line(12, 2.5, 12, 5); line(12, 19, 12, 21.5); line(2.5, 12, 5, 12); line(19, 12, 21.5, 12); line(5.3, 5.3, 7, 7); line(17, 17, 18.7, 18.7); line(5.3, 18.7, 7, 17); line(17, 7, 18.7, 5.3); break
        case "moon": c.beginPath(); c.arc(12, 12, 8, Math.PI * 0.35, Math.PI * 1.65); c.arc(16.5, 12, 6.2, Math.PI * 1.36, Math.PI * 0.64, true); c.closePath(); c.stroke(); break
        case "cloud": c.beginPath(); c.arc(8, 15, 4, Math.PI * 0.5, Math.PI * 1.5); c.arc(12, 10.5, 4.6, Math.PI * 1.15, Math.PI * 1.9); c.arc(16.5, 14.5, 4.5, Math.PI * 1.45, Math.PI * 0.5); c.closePath(); c.stroke(); break
        case "cloudsun": ring(16.5, 7.5, 2.8); line(16.5, 2, 16.5, 3.2); line(22, 7.5, 20.8, 7.5); line(20.4, 3.6, 19.6, 4.4); line(12.6, 3.6, 13.4, 4.4)
            c.beginPath(); c.arc(7, 16.5, 3.5, Math.PI * 0.5, Math.PI * 1.5); c.arc(10.5, 12.6, 4, Math.PI * 1.15, Math.PI * 1.9); c.arc(14.5, 16, 4, Math.PI * 1.45, Math.PI * 0.5); c.closePath(); c.stroke(); break
        case "cloudmoon": c.beginPath(); c.arc(17, 7, 3.6, Math.PI * 0.2, Math.PI * 1.5); c.arc(19.6, 5.6, 3.2, Math.PI * 1.25, Math.PI * 0.5, true); c.stroke()
            c.beginPath(); c.arc(7, 16.5, 3.5, Math.PI * 0.5, Math.PI * 1.5); c.arc(10.5, 12.6, 4, Math.PI * 1.15, Math.PI * 1.9); c.arc(14.5, 16, 4, Math.PI * 1.45, Math.PI * 0.5); c.closePath(); c.stroke(); break
        case "rain": c.beginPath(); c.arc(8, 11, 3.6, Math.PI * 0.5, Math.PI * 1.5); c.arc(12, 7.4, 4.2, Math.PI * 1.15, Math.PI * 1.9); c.arc(16.5, 10.6, 4, Math.PI * 1.45, Math.PI * 0.5); c.closePath(); c.stroke()
            line(8.5, 17, 7.5, 20); line(12.5, 17, 11.5, 20); line(16.5, 17, 15.5, 20); break
        case "snow": c.beginPath(); c.arc(8, 11, 3.6, Math.PI * 0.5, Math.PI * 1.5); c.arc(12, 7.4, 4.2, Math.PI * 1.15, Math.PI * 1.9); c.arc(16.5, 10.6, 4, Math.PI * 1.45, Math.PI * 0.5); c.closePath(); c.stroke()
            dot(8, 18.5, 1.1); dot(12, 20, 1.1); dot(16, 18.5, 1.1); break
        case "storm": c.beginPath(); c.arc(8, 11, 3.6, Math.PI * 0.5, Math.PI * 1.5); c.arc(12, 7.4, 4.2, Math.PI * 1.15, Math.PI * 1.9); c.arc(16.5, 10.6, 4, Math.PI * 1.45, Math.PI * 0.5); c.closePath(); c.stroke()
            line(13, 15.5, 10.5, 18.5, 13.5, 18.5, 11, 22); break
        case "fog": line(4, 8, 20, 8); line(6, 12, 18, 12); line(4, 16, 20, 16); line(8, 20, 16, 20); break
        case "drop": c.beginPath(); c.moveTo(12, 3.5); c.bezierCurveTo(17, 9.5, 18.5, 12.5, 18.5, 15); c.arc(12, 15, 6.5, 0, Math.PI); c.bezierCurveTo(5.5, 12.5, 7, 9.5, 12, 3.5); c.stroke(); break
        case "wind": line(3, 9, 14, 9); c.beginPath(); c.arc(14, 6.5, 2.5, Math.PI * 0.5, Math.PI * 1.1, true); c.stroke(); line(3, 13, 18, 13); c.beginPath(); c.arc(18, 15.5, 2.5, Math.PI * 1.5, Math.PI * 0.9); c.stroke(); line(3, 17, 10, 17); break
        case "phone": c.beginPath(); c.moveTo(5, 4); c.lineTo(9, 4); c.lineTo(10.5, 8.5); c.lineTo(8.3, 10); c.bezierCurveTo(9.5, 12.8, 11.2, 14.5, 14, 15.7); c.lineTo(15.5, 13.5); c.lineTo(20, 15); c.lineTo(20, 19); c.bezierCurveTo(11, 20.5, 3.5, 13, 5, 4); c.closePath(); c.stroke(); break
        case "eye": c.beginPath(); c.moveTo(2.5, 12); c.bezierCurveTo(6, 6, 18, 6, 21.5, 12); c.bezierCurveTo(18, 18, 6, 18, 2.5, 12); c.stroke(); ring(12, 12, 2.8); break
        case "shield": c.beginPath(); c.moveTo(12, 3); c.lineTo(19.5, 6); c.lineTo(19.5, 11.5); c.bezierCurveTo(19.5, 16, 16.5, 19.5, 12, 21); c.bezierCurveTo(7.5, 19.5, 4.5, 16, 4.5, 11.5); c.lineTo(4.5, 6); c.closePath(); c.stroke(); line(8.8, 12, 11.2, 14.4, 15.4, 9.8); break
        case "record": ring(12, 12, 8.5); dot(12, 12, 4.2); break
        case "stop": box(6.5, 6.5, 11, 11, 2); break
        case "folder": poly(3, 7, 3, 18, 21, 18, 21, 9, 12, 9, 10, 6, 4, 6); break
        case "file": poly(6, 3, 14, 3, 18, 7, 18, 21, 6, 21); line(14, 3, 14, 7, 18, 7); break
        case "image": box(3, 5, 18, 14, 2.5); dot(8.5, 10, 1.4); line(4, 17, 10, 12, 14, 15, 17, 12, 20, 15); break
        case "music": line(9, 17, 9, 5, 19, 3, 19, 15); ring(7, 17, 2.2); ring(17, 15, 2.2); break
        case "video": box(3, 6, 13, 12, 2.5); poly(16, 10.5, 21, 7.5, 21, 16.5, 16, 13.5); break
        case "home": poly(4, 11, 12, 4, 20, 11, 20, 20, 4, 20); line(10, 20, 10, 14, 14, 14, 14, 20); break
        case "download": line(12, 4, 12, 15); line(7, 11, 12, 16, 17, 11); line(5, 20, 19, 20); break
        case "doc": poly(6, 3, 18, 3, 18, 21, 6, 21); line(9, 8, 15, 8); line(9, 12, 15, 12); line(9, 16, 13, 16); break
        case "desktop": box(3, 4, 18, 12, 2); line(9, 20, 15, 20); line(12, 16, 12, 20); break
        case "trash": line(4, 7, 20, 7); poly(6, 7, 7, 21, 17, 21, 18, 7); line(9, 7, 9, 4, 15, 4, 15, 7); break
        case "calendar": box(3, 5, 18, 16, 2.5); line(3, 10, 21, 10); line(8, 3, 8, 7); line(16, 3, 16, 7); break
        case "mail": box(3, 5, 18, 14, 2.5); line(4, 7, 12, 13, 20, 7); break
        case "inbox": poly(3, 13, 6, 5, 18, 5, 21, 13, 21, 19, 3, 19); line(3, 13, 8, 13, 9.5, 16, 14.5, 16, 16, 13, 21, 13); break
        case "send": poly(3, 11, 21, 3, 14, 21, 11, 13); line(11, 13, 21, 3); break
        case "star": poly(12, 3, 14.6, 9, 21, 9.6, 16.2, 14, 17.6, 20.5, 12, 17.2, 6.4, 20.5, 7.8, 14, 3, 9.6, 9.4, 9); break
        case "gear": ring(12, 12, 3); for (var a = 0; a < 8; a++) { var t = a * Math.PI / 4; line(12 + 6.3 * Math.cos(t), 12 + 6.3 * Math.sin(t), 12 + 8.8 * Math.cos(t), 12 + 8.8 * Math.sin(t)) } ring(12, 12, 6.3); break
        case "cpu": box(6, 6, 12, 12, 2); box(9.5, 9.5, 5, 5, 1); for (var i = 9; i <= 15; i += 3) { line(i, 3, i, 6); line(i, 18, i, 21); line(3, i, 6, i); line(18, i, 21, i) } break
        case "memory": box(3, 7, 18, 10, 2); line(7, 10, 7, 14); line(11, 10, 11, 14); line(15, 10, 15, 14); line(6, 17, 6, 20); line(18, 17, 18, 20); break
        case "search": ring(10.5, 10.5, 6); line(15, 15, 20, 20); break
        case "plus": line(12, 5, 12, 19); line(5, 12, 19, 12); break
        case "x": line(6, 6, 18, 18); line(18, 6, 6, 18); break
        case "back": line(14, 5, 7, 12, 14, 19); break
        case "forward": line(10, 5, 17, 12, 10, 19); break
        case "up": line(5, 14, 12, 7, 19, 14); break
        case "grid": box(4, 4, 6.5, 6.5, 1.5); box(13.5, 4, 6.5, 6.5, 1.5); box(4, 13.5, 6.5, 6.5, 1.5); box(13.5, 13.5, 6.5, 6.5, 1.5); break
        case "list": line(8, 6, 20, 6); line(8, 12, 20, 12); line(8, 18, 20, 18); dot(4.5, 6, 1.2); dot(4.5, 12, 1.2); dot(4.5, 18, 1.2); break
        case "play": fillPoly(7, 4, 20, 12, 7, 20); break
        case "pause": c.fillRect(6, 4, 4.5, 16); c.fillRect(13.5, 4, 4.5, 16); break
        case "next": fillPoly(5, 5, 15, 12, 5, 19); c.fillRect(16.5, 5, 2.5, 14); break
        case "prev": fillPoly(19, 5, 9, 12, 19, 19); c.fillRect(5, 5, 2.5, 14); break
        case "volume": poly(4, 9, 8, 9, 13, 5, 13, 19, 8, 15, 4, 15); c.beginPath(); c.arc(13, 12, 5, -0.9, 0.9); c.stroke(); break
        case "wifi": for (var r = 4; r <= 12; r += 4) { c.beginPath(); c.arc(12, 18, r, Math.PI * 1.25, Math.PI * 1.75); c.stroke() } dot(12, 18, 1.4); break
        case "display": box(3, 4, 18, 13, 2); line(8, 21, 16, 21); break
        case "palette": ring(12, 12, 8.5); dot(8.5, 9, 1.3); dot(13, 7.5, 1.3); dot(16.5, 11, 1.3); dot(9, 14.5, 1.3); break
        case "printer": box(6, 3.5, 12, 5, 1.5); box(3.5, 8.5, 17, 8, 2.5); box(7, 14, 10, 6.5, 1.2); dot(17, 11.5, 0.9); break
        case "pin": c.beginPath(); c.arc(12, 9.5, 5.5, Math.PI * 0.85, Math.PI * 0.15); c.lineTo(12, 21); c.closePath(); c.stroke(); ring(12, 9.5, 2); break
        case "podcast": ring(12, 10, 2.2); c.beginPath(); c.arc(12, 10, 5.5, Math.PI * 1.15, Math.PI * 1.85); c.stroke(); c.beginPath(); c.arc(12, 10, 8.5, Math.PI * 1.1, Math.PI * 1.9); c.stroke(); line(12, 13, 12, 20.5); line(9, 20.5, 15, 20.5); break
        case "book": c.beginPath(); c.moveTo(12, 6.5); c.quadraticCurveTo(7.5, 4, 3.5, 5.5); c.lineTo(3.5, 18); c.quadraticCurveTo(7.5, 16.5, 12, 19); c.quadraticCurveTo(16.5, 16.5, 20.5, 18); c.lineTo(20.5, 5.5); c.quadraticCurveTo(16.5, 4, 12, 6.5); c.closePath(); c.stroke(); line(12, 6.5, 12, 19); break
        case "gamepad": c.beginPath(); c.moveTo(7.5, 7); c.lineTo(16.5, 7); c.bezierCurveTo(20.5, 7, 22, 11, 22, 14.5); c.bezierCurveTo(22, 18.5, 18.8, 19.2, 17, 16.6); c.lineTo(15.8, 15); c.lineTo(8.2, 15); c.lineTo(7, 16.6); c.bezierCurveTo(5.2, 19.2, 2, 18.5, 2, 14.5); c.bezierCurveTo(2, 11, 3.5, 7, 7.5, 7); c.closePath(); c.stroke(); line(6.5, 11, 9.5, 11); line(8, 9.5, 8, 12.5); dot(15.2, 11.8, 0.9); dot(17.6, 10, 0.9); break
        case "translate": line(3.5, 6.5, 11.5, 6.5); line(7.5, 4.5, 7.5, 6.5); c.beginPath(); c.moveTo(5, 6.5); c.quadraticCurveTo(6, 11, 11, 13); c.stroke(); c.beginPath(); c.moveTo(10, 6.5); c.quadraticCurveTo(9, 11, 4, 13); c.stroke(); line(12.5, 20, 16.5, 10, 20.5, 20); line(14, 16.5, 19, 16.5); break
        case "check": line(5, 12.5, 10, 17.5, 19.5, 7); break
        case "route": ring(6, 18, 2); ring(18, 6, 2); c.beginPath(); c.moveTo(8, 18); c.bezierCurveTo(16, 18, 8, 6, 16, 6); c.stroke(); break
        case "bell": poly(6, 17, 6, 11, 12, 5, 18, 11, 18, 17); line(4, 17, 20, 17); line(10.5, 20, 13.5, 20); break
        case "info": ring(12, 12, 8.5); line(12, 11, 12, 16.5); dot(12, 7.8, 1.1); break
        case "user": ring(12, 8.5, 3.8); c.beginPath(); c.arc(12, 21, 7.5, Math.PI * 1.1, Math.PI * 1.9); c.stroke(); break
        case "apps": for (var y = 6; y <= 18; y += 6) for (var x = 6; x <= 18; x += 6) dot(x, y, 1.6); break
        case "clock": ring(12, 12, 8.5); line(12, 7, 12, 12, 15.5, 14); break
        case "expand": line(5, 10, 5, 5, 10, 5); line(19, 14, 19, 19, 14, 19); break
        case "edit": poly(5, 19, 5, 15, 15, 5, 19, 9, 9, 19); break
        case "disc": ring(12, 12, 8.5); ring(12, 12, 2.2); break
        case "alignleft": line(4, 6, 20, 6); line(4, 10, 14, 10); line(4, 14, 20, 14); line(4, 18, 12, 18); break
        case "aligncenter": line(4, 6, 20, 6); line(7, 10, 17, 10); line(4, 14, 20, 14); line(8, 18, 16, 18); break
        case "alignright": line(4, 6, 20, 6); line(10, 10, 20, 10); line(4, 14, 20, 14); line(12, 18, 20, 18); break
        case "alignjustify": line(4, 6, 20, 6); line(4, 10, 20, 10); line(4, 14, 20, 14); line(4, 18, 20, 18); break
        case "numbers": line(10, 6, 20, 6); line(10, 12, 20, 12); line(10, 18, 20, 18); line(4, 5, 5.5, 4, 5.5, 8); line(4, 11, 6.5, 11, 4, 14, 6.5, 14); line(4, 17, 6.5, 17, 5, 18.5, 6.5, 20, 4, 20); break
        case "table": box(3, 5, 18, 14, 2); line(3, 10, 21, 10); line(3, 14.5, 21, 14.5); line(9, 5, 9, 19); line(15, 5, 15, 19); break
        case "slides": box(3, 5, 18, 12, 2); line(12, 17, 12, 21); line(8, 21, 16, 21); break
        case "share": line(12, 15, 12, 4); line(8, 8, 12, 4, 16, 8); line(5, 12, 5, 20, 19, 20, 19, 12); break
        case "down": line(5, 10, 12, 17, 19, 10); break
        case "terminal": box(3, 5, 18, 14, 2.5); line(7, 10, 10, 12.5, 7, 15); line(12.5, 15, 16.5, 15); break
        case "globe": ring(12, 12, 9); line(3, 12, 21, 12); c.beginPath(); c.ellipse(8, 3, 8, 18); c.stroke(); break
        case "bag": poly(5, 8, 19, 8, 20, 21, 4, 21); c.beginPath(); c.arc(12, 8, 3.5, Math.PI, 0); c.stroke(); break
        case "calc": box(5, 3, 14, 18, 2.5); line(8, 7.5, 16, 7.5); dot(8.5, 12, 0.9); dot(12, 12, 0.9); dot(15.5, 12, 0.9); dot(8.5, 16.5, 0.9); dot(12, 16.5, 0.9); dot(15.5, 16.5, 0.9); break
        case "camera": box(3, 7, 18, 13, 2.5); line(8.5, 7, 10, 4.5, 14, 4.5, 15.5, 7); ring(12, 13.5, 3.2); break
        case "box": poly(4, 8, 12, 4, 20, 8, 20, 17, 12, 21, 4, 17); line(4, 8, 12, 12, 20, 8); line(12, 12, 12, 21); break
        case "note": poly(5, 4, 19, 4, 19, 14, 14, 20, 5, 20); line(19, 14, 14, 14, 14, 20); line(8.5, 9, 15.5, 9); line(8.5, 13, 12, 13); break
        case "chat": c.beginPath(); c.moveTo(7, 4.5); c.lineTo(17, 4.5); c.quadraticCurveTo(20.5, 4.5, 20.5, 8); c.lineTo(20.5, 13); c.quadraticCurveTo(20.5, 16.5, 17, 16.5); c.lineTo(11, 16.5); c.lineTo(6.5, 20); c.lineTo(7, 16.5); c.quadraticCurveTo(3.5, 16.5, 3.5, 13); c.lineTo(3.5, 8); c.quadraticCurveTo(3.5, 4.5, 7, 4.5); c.closePath(); c.stroke(); dot(8.5, 10.5, 1); dot(12, 10.5, 1); dot(15.5, 10.5, 1); break
        case "bolt": poly(13.5, 2.5, 5.5, 13.5, 11.5, 13.5, 10.5, 21.5, 18.5, 10.5, 12.5, 10.5); break
        case "wallet": box(3.5, 6.5, 17, 13, 3); line(6, 6.5, 15.5, 3.5, 17, 6.5); box(14, 11, 6.5, 4.5, 2); dot(16.5, 13.2, 0.9); break
        case "smile": ring(12, 12, 8.5); dot(9, 10, 1.1); dot(15, 10, 1.1); c.beginPath(); c.arc(12, 12.5, 4.2, Math.PI * 0.2, Math.PI * 0.8); c.stroke(); break
        case "type": line(4, 20, 9, 5, 14, 20); line(6, 15, 12, 15); line(15.5, 13, 20.5, 13); c.beginPath(); c.arc(18, 17, 2.8, 0, Math.PI * 2); c.stroke(); line(20.8, 13, 20.8, 20); break
        case "help": ring(12, 12, 8.5); c.beginPath(); c.arc(12, 9.5, 2.8, Math.PI * 1.05, Math.PI * 0.45); c.stroke(); line(12, 12.8, 12, 14); dot(12, 16.8, 1.1); break
        case "code": line(8, 7, 3, 12, 8, 17); line(16, 7, 21, 12, 16, 17); line(13.5, 4.5, 10.5, 19.5); break
        case "bluetooth": line(7, 7.5, 16.5, 16, 12, 20.5, 12, 3.5, 16.5, 8, 7, 16.5); break
        case "battery": box(3, 7.5, 16, 9, 2.5); line(21, 10.5, 21, 13.5); c.fillRect(5.5, 10, 7, 4); break
        case "keyboard": box(2.5, 6, 19, 12, 2.5); dot(6.5, 9.8, 0.9); dot(10, 9.8, 0.9); dot(13.5, 9.8, 0.9); dot(17, 9.8, 0.9); line(7.5, 14.2, 16.5, 14.2); break
        case "refresh": c.beginPath(); c.arc(12, 12, 7.5, Math.PI * 1.15, Math.PI * 2.85); c.stroke(); line(4.4, 5.5, 4.6, 9.4, 8.5, 9.2); break
        case "power": c.beginPath(); c.arc(12, 13, 7.5, -Math.PI * 0.3, Math.PI * 1.3); c.stroke(); line(12, 3, 12, 11); break
        case "signout": line(10, 4, 5, 4, 5, 20, 10, 20); line(10, 12, 20, 12); line(16, 8, 20, 12, 16, 16); break
        case "leaf": c.beginPath(); c.moveTo(5, 19); c.quadraticCurveTo(4, 6, 19, 5); c.quadraticCurveTo(19, 18, 6, 18); c.stroke(); line(5, 19, 13, 11); break
        case "headphones": c.beginPath(); c.arc(12, 13, 8, Math.PI, 0); c.stroke(); box(3.5, 13, 4.5, 7, 1.5); box(16, 13, 4.5, 7, 1.5); break
        case "speaker": box(6, 3, 12, 18, 3); ring(12, 14, 3.5); dot(12, 7, 1.2); break
        case "mouse": box(6.5, 3, 11, 18, 5.5); line(12, 6.5, 12, 9.5); break
        case "crop": line(7, 3, 7, 17, 21, 17); line(3, 7, 17, 7, 17, 21); break
        case "layers": poly(12, 4, 21, 9, 12, 14, 3, 9); line(3, 13, 12, 18, 21, 13); line(3, 16.5, 12, 21.5, 21, 16.5); break
        case "brush": c.beginPath(); c.moveTo(19.5, 3.5); c.lineTo(10.5, 12.5); c.stroke(); c.beginPath(); c.moveTo(10, 13); c.quadraticCurveTo(6, 13, 6, 17); c.quadraticCurveTo(6, 20, 3.5, 20.5); c.quadraticCurveTo(10, 21.5, 11.5, 15.5); c.closePath(); c.stroke(); break
        case "pen": poly(12, 3, 18, 13, 12, 21, 6, 13); line(12, 3, 12, 11); ring(12, 13, 1.6); break
        case "eraser": poly(14, 4, 21, 11, 12, 20, 5, 20, 3, 18, 3, 15); line(8.5, 9.5, 15.5, 16.5); line(12, 20, 21, 20); break
        case "bucket": poly(4, 11, 11, 4, 18, 11, 11, 18); line(11, 4, 11, 8); c.beginPath(); c.moveTo(19.5, 14); c.quadraticCurveTo(21.5, 17, 19.5, 18); c.quadraticCurveTo(17.5, 17, 19.5, 14); c.fill(); break
        case "picker": line(5, 19, 13.5, 10.5); poly(13, 6, 18, 11, 15.5, 13.5, 10.5, 8.5); line(15.5, 8.5, 19, 5); line(4, 20, 5, 19); break
        case "select": c.setLineDash([2.5, 2.5]); box(4, 5, 16, 14, 1); c.setLineDash([]); break
        case "lasso": c.beginPath(); c.ellipse(4, 4, 16, 11); c.stroke(); c.beginPath(); c.moveTo(7, 13.5); c.quadraticCurveTo(5, 18, 9, 20); c.stroke(); break
        case "wand": line(4, 20, 15, 9); line(17, 3, 17, 6); line(17, 9, 17, 12); line(12, 7.5, 15, 7.5); line(19, 7.5, 22, 7.5); break
        case "move": line(12, 3, 12, 21); line(3, 12, 21, 12); line(9, 6, 12, 3, 15, 6); line(9, 18, 12, 21, 15, 18); line(6, 9, 3, 12, 6, 15); line(18, 9, 21, 12, 18, 15); break
        case "hand": c.beginPath(); c.moveTo(8, 12); c.lineTo(8, 5.5); c.quadraticCurveTo(9.5, 4, 11, 5.5); c.lineTo(11, 11); c.lineTo(11, 4); c.quadraticCurveTo(12.5, 2.5, 14, 4); c.lineTo(14, 11); c.lineTo(14, 5.5); c.quadraticCurveTo(15.5, 4, 17, 5.5); c.lineTo(17, 15); c.quadraticCurveTo(17, 21, 11.5, 21); c.quadraticCurveTo(7.5, 21, 5, 15); c.lineTo(4, 12.5); c.quadraticCurveTo(5.5, 10.5, 8, 13); c.stroke(); break
        case "zoom": ring(10.5, 10.5, 6.5); line(15.5, 15.5, 20.5, 20.5); line(8, 10.5, 13, 10.5); line(10.5, 8, 10.5, 13); break
        case "shapes": box(3.5, 10.5, 10, 10, 1.5); ring(15.5, 8.5, 5); break
        case "undo": c.beginPath(); c.moveTo(5, 10); c.lineTo(15, 10); c.quadraticCurveTo(20, 10, 20, 14.5); c.quadraticCurveTo(20, 19, 15, 19); c.lineTo(10, 19); c.stroke(); line(9, 6, 5, 10, 9, 14); break
        case "redo": c.beginPath(); c.moveTo(19, 10); c.lineTo(9, 10); c.quadraticCurveTo(4, 10, 4, 14.5); c.quadraticCurveTo(4, 19, 9, 19); c.lineTo(14, 19); c.stroke(); line(15, 6, 19, 10, 15, 14); break
        case "sliders": line(4, 7, 20, 7); line(4, 12, 20, 12); line(4, 17, 20, 17); dot(9, 7, 2.2); dot(15, 12, 2.2); dot(7, 17, 2.2); break
        case "straighten": line(3, 15, 21, 9); ring(12, 12, 2); line(5, 20, 19, 20); break
        case "sparkle": poly(12, 3, 13.8, 10.2, 21, 12, 13.8, 13.8, 12, 21, 10.2, 13.8, 3, 12, 10.2, 10.2); break
        case "contrast": ring(12, 12, 8.5); c.beginPath(); c.arc(12, 12, 8.5, -Math.PI / 2, Math.PI / 2); c.closePath(); c.fill(); break
        case "flip": line(12, 3, 12, 21); poly(9, 6, 9, 18, 3, 18); poly(15, 6, 15, 18, 21, 18); break
        case "rotate": c.beginPath(); c.arc(12, 13, 7, Math.PI * 1.25, Math.PI * 2.9); c.stroke(); line(5.5, 4.5, 6.5, 8.5, 10.5, 7.5); break
        default: ring(12, 12, 7)
        }
    }
}
