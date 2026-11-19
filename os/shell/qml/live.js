.pragma library
// Small helpers the live island (LiveIsland.qml) and the opened island (LivePanel.qml) share.

function kindOf(it) { return it && it.kind ? it.kind : "" }
function privacy(it) { var k = kindOf(it); return k === "screen" || k === "camera" || k === "mic" }
function clock(ms) {
    var t = Math.max(0, Math.round(ms / 1000)), h = Math.floor(t / 3600), m = Math.floor(t / 60) % 60, s = t % 60
    return (h > 0 ? h + ":" + (m < 10 ? "0" : "") : "") + m + ":" + (s < 10 ? "0" : "") + s
}
// a timer: what's left, in ms
function left(it, now) { return it.paused ? (it.left || 0) : (it.ends || 0) - now }
// something playing: where it is now, in ms (players say where they were, and when)
function position(it, now) {
    var p = (it.position || 0) + (it.playing && it.posAt ? (now - it.posAt) * (it.rate || 1) : 0)
    return it.length ? Math.min(it.length, Math.max(0, p)) : Math.max(0, p)
}
function sub(it, now) {
    var k = kindOf(it)
    if (k === "event") {
        var mins = Math.round(((it.starts || 0) - now) / 60000)
        return (mins > 0 ? "in " + mins + " min" : mins === 0 ? "starting now" : "started " + (-mins) + " min ago") + " · Calendar"
    }
    if (k === "timer") return (it.paused ? "Paused" : "Rings at " + Qt.formatTime(new Date(it.ends || 0), "HH:mm")) + " · " + (it.app || "Clock")
    return it.sub || ""
}
function action(it, ids) {
    var a = it && it.actions ? it.actions : []
    for (var i = 0; i < a.length; i++) if (ids.indexOf(a[i].id) >= 0) return a[i]
    return null
}
// the round buttons in the island itself: the one or two you'd want without opening it
function quick(it) {
    var k = kindOf(it)
    if (k === "playing") return [{ id: "playpause", glyph: it.playing ? "pause" : "play" }]
    var want = k === "timer" ? [["pause", "resume"]] : k === "alarm" ? [["stop", "dismiss"]] : k === "call" ? [["decline"], ["answer", "silence"]]
             : k === "event" ? [["join"]] : k === "screen" ? [["stop"]] : []
    var out = []
    for (var i = 0; i < want.length; i++) { var a = action(it, want[i]); if (a) out.push(a) }
    return out
}
function tone(a) {
    if (a.tone) return a.tone
    return a.id === "join" || a.id === "answer" ? "go" : a.id === "decline" || a.id === "stop" || a.id === "hangup" ? "danger" : ""
}
function initials(text) {
    var w = String(text || "").split(/\s+/).filter(function (x) { return x && /[A-Za-zÀ-ÿÞþÐð]/.test(x[0]) })
    return (w.slice(0, 2).map(function (x) { return x[0] }).join("") || "#").toUpperCase()
}
