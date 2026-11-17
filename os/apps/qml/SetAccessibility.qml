import QtQuick

// Accessibility: seeing, hearing, typing and moving. Huginn's own look (contrast, solid surfaces, stillness, size)
// lives in the shared settings every app reads; the rest is KDE's own (KWin, KAccess), so it works everywhere.
Column {
    id: pg
    width: parent ? parent.width : 600; spacing: 18
    readonly property var a: Backend.a11y
    readonly property var filterNames: { var o = {}; (a.filters || []).forEach(function (f) { o[f.id] = f.label }); return o }

    // a live sample of what the settings below do
    Rectangle { width: parent.width; height: 132; radius: Theme.t.radiusCard; color: Theme.t.group; border.width: 1; border.color: Theme.t.separator; clip: true
        Row { x: 22; anchors.verticalCenter: parent.verticalCenter; spacing: 22
            Rectangle { width: 88; height: 88; radius: 22; anchors.verticalCenter: parent.verticalCenter
                gradient: Gradient { GradientStop { position: 0; color: "#5EC8FF" } GradientStop { position: 1; color: "#1A73E8" } }
                Text { anchors.centerIn: parent; text: "Aa"; color: "#FFFFFF"; font.pixelSize: 26 * Number(Settings.uiScale); font.weight: Font.DemiBold } }
            Column { anchors.verticalCenter: parent.verticalCenter; spacing: 6; width: pg.width - 190
                Label { text: "Make Huginn work the way you do"; font.pixelSize: 17; font.weight: Font.DemiBold }
                Label { width: parent.width; wrapMode: Text.WordWrap; secondary: true
                    text: [Settings.contrast ? "High contrast" : "", Settings.reduceTransparency ? "solid surfaces" : "", Settings.reduceMotion ? "no motion" : "",
                           Number(Settings.uiScale) > 1 ? "everything " + Math.round(Number(Settings.uiScale) * 100) + "%" : "", pg.a.reader ? "screen reader on" : "",
                           pg.a.filter ? pg.filterNames[pg.a.filter] : ""].filter(function (x) { return x }).join(" · ") || "Nothing changed yet. Everything here can be turned back at any time." } } } }

    SetCard { title: "Seeing"; note: "Meta+Alt+S turns the screen reader on and off from anywhere. Meta and + or − zooms; Meta+0 goes back to normal."
        SetRow { glyph: "speaker"; tile: "#1A73E8"; title: "Screen reader"; sub: pg.a.hasReader ? "Reads out what's on the screen and what you type (Orca)." : "Needs Orca, which isn't installed."
            Toggle { enabled: !!pg.a.hasReader; on: !!pg.a.reader; onToggled: function (v) { Backend.setA11y("reader", v) } } }
        SetRow { glyph: "zoom"; tile: "#0EA5E9"; title: "Zoom"; sub: "Meta and + or − magnifies the whole screen, around the pointer."
            Toggle { on: !!pg.a.zoom; onToggled: function (v) { Backend.setA11y("zoom", v) } } }
        SetRow { visible: !!pg.a.zoom; title: "Each step zooms"
            SetChoice { each: 64; options: [["1.2", "A little"], ["1.5", "More"], ["2", "Double"]]; value: String(pg.a.zoomStep || 1.2); onPicked: function (v) { Backend.setA11y("zoomStep", v) } } }
        SetRow { visible: !!pg.a.zoom; title: "When the pointer moves"
            SetChoice { each: 104; options: [["0", "Follow it"], ["1", "Keep it centred"], ["2", "Push at edges"]]; value: pg.a.zoomFollow || "0"; onPicked: function (v) { Backend.setA11y("zoomFollow", v) } } }
        SetRow { glyph: "expand"; tile: "#6366F1"; title: "Make everything bigger"; sub: "Text, controls and pictures in Huginn's apps and the top bar. Apps change when they're next opened."
            SetChoice { each: 54; options: [["1", "100%"], ["1.25", "125%"], ["1.5", "150%"], ["1.75", "175%"], ["2", "200%"]]; value: Settings.uiScale; onPicked: function (v) { Settings.set("uiScale", v) } } }
        SetRow { glyph: "contrast"; tile: "#111827"; title: "High contrast"; sub: "Solid backgrounds, stronger text and clear outlines on every control."
            Toggle { on: Settings.contrast; onToggled: function (v) { Settings.set("contrast", v ? "true" : "false") } } }
        SetRow { glyph: "layers"; tile: "#64748B"; title: "Solid surfaces instead of glass"; sub: "Nothing shows through windows, menus or the bar."
            Toggle { on: Settings.reduceTransparency; onToggled: function (v) { Settings.set("reduceTransparency", v ? "true" : "false") } } }
        SetRow { glyph: "palette"; tile: "#DB2777"; title: "Colour filter"; sub: "Makes colours easier to tell apart for colour blindness, or turns them inside out."; chevron: true
            onClicked: win.pick("Colour filter", (pg.a.filters || []).map(function (f) { return { id: f.id, label: f.label } }), pg.a.filter || "", function (v) { Backend.setA11y("filter", v) })
            Label { text: pg.filterNames[pg.a.filter || ""] || "None"; secondary: true } }
        SetRow { visible: pg.a.filter !== "" && pg.a.filter !== "invert" && pg.a.filter !== undefined; title: "Filter strength"
            SetSlider { width: 220; value: pg.a.filterStrength || 1; lowText: "Light"; highText: "Full"; onMoved: function (v) { Backend.setA11y("filterStrength", Math.max(0.1, v)) } } }
        SetRow { glyph: "mouse"; tile: "#F59E0B"; title: "Pointer size"
            Row { spacing: 6
                Repeater { model: [24, 32, 48, 64, 96]
                    Pressable { required property int modelData; width: 44; height: 44; radius: 10
                        color: pg.a.cursor === modelData ? Qt.alpha(Theme.t.accent, 0.25) : (hovered ? Theme.t.hover : "transparent")
                        border.width: pg.a.cursor === modelData ? 2 : 0; border.color: Theme.t.accent
                        onClicked: Backend.setA11y("cursor", modelData)
                        Canvas { anchors.centerIn: parent; width: 8 + modelData * 0.32; height: width
                            onPaint: { var c = getContext("2d"), w = width; c.reset(); c.fillStyle = Theme.t.text; c.strokeStyle = Theme.t.dark ? "#000000" : "#FFFFFF"; c.lineWidth = 1.2
                                c.beginPath(); c.moveTo(1, 1); c.lineTo(1, w * 0.92); c.lineTo(w * 0.3, w * 0.68); c.lineTo(w * 0.52, w); c.lineTo(w * 0.66, w * 0.92)
                                c.lineTo(w * 0.46, w * 0.6); c.lineTo(w * 0.8, w * 0.6); c.closePath(); c.fill(); c.stroke() } } } } } } }

    SetCard { title: "Hearing"; note: "Clips can write captions from what's said in a video, and Recorder can turn speech into text."
        SetRow { glyph: "bolt"; tile: "#EF4444"; title: "Flash the screen for alert sounds"; sub: "Instead of the beep, the screen flashes briefly."
            Toggle { on: !!pg.a.flash; onToggled: function (v) { Backend.setA11y("flash", v) } } } }

    SetCard { title: "Moving and typing"
        SetRow { glyph: "sparkle"; tile: "#14B8A6"; title: "Reduce motion"; sub: "Windows, menus and pages appear without sliding, zooming or fading."
            Toggle { on: Settings.reduceMotion; onToggled: function (v) { Settings.set("reduceMotion", v ? "true" : "false"); Backend.setA11y("animations", !v) } } }
        SetRow { glyph: "keyboard"; tile: "#8B5CF6"; title: "On-screen keyboard"; sub: pg.a.hasOsk ? "A keyboard on the screen whenever you tap where text goes." : "Needs an on-screen keyboard, which isn't installed."
            Toggle { enabled: !!pg.a.hasOsk; on: !!pg.a.osk; onToggled: function (v) { Backend.setA11y("osk", v) } } }
        SetRow { title: "Sticky keys"; sub: "Press Shift, Ctrl, Alt or Meta, let go, then press the next key, instead of holding them together."
            Toggle { on: !!pg.a.sticky; onToggled: function (v) { Backend.setA11y("sticky", v) } } }
        SetRow { visible: !!pg.a.sticky; title: "Pressing one twice keeps it down"
            Toggle { on: pg.a.stickyLock !== false; onToggled: function (v) { Backend.setA11y("stickyLock", v) } } }
        SetRow { title: "Slow keys"; sub: "A key only counts once it's been held a moment, so brushing one doesn't type it."
            Toggle { on: !!pg.a.slow; onToggled: function (v) { Backend.setA11y("slow", v) } } }
        SetRow { visible: !!pg.a.slow; title: "Hold for"; sub: (pg.a.slowDelay || 300) + " ms"
            SetSlider { width: 220; value: ((pg.a.slowDelay || 300) - 50) / 950; lowText: "Short"; highText: "Long"; onMoved: function (v) { Backend.setA11y("slowDelay", Math.round(50 + v * 950)) } } }
        SetRow { title: "Bounce keys"; sub: "Ignores a key pressed again straight away, for hands that tremble."
            Toggle { on: !!pg.a.bounce; onToggled: function (v) { Backend.setA11y("bounce", v) } } }
        SetRow { visible: !!pg.a.bounce; title: "Ignore repeats within"; sub: (pg.a.bounceDelay || 500) + " ms"
            SetSlider { width: 220; value: ((pg.a.bounceDelay || 500) - 100) / 900; lowText: "Short"; highText: "Long"; onMoved: function (v) { Backend.setA11y("bounceDelay", Math.round(100 + v * 900)) } } }
        SetRow { title: "Move the pointer with the number keys"; sub: "Mouse keys: 8, 2, 4 and 6 move it, 5 clicks."
            Toggle { on: !!pg.a.mouseKeys; onToggled: function (v) { Backend.setA11y("mouseKeys", v) } } } }
}
