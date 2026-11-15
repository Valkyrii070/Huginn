import QtQuick

// Clips, "the cutting room": the library of footage on the left, the picture in the middle, the inspector on the
// right, and the timeline across the bottom: video tracks stacked above the main one (V1), sound tracks below it.
// What the viewer shows is drawn by the same engine that makes the finished video.
GlassWindow {
    id: win
    title: "Clips"; heading: Backend.name; width: 1400; height: 880; minimumWidth: 1100; minimumHeight: 700; glow: "bottom"
    property string tool: "select"                 // select | blade
    property bool ripple: false
    property string tab: "video"
    property var sheet: null
    property string bin: ""
    property var dragMedia: null
    property bool mixer: false                     // the library island shows the mixer instead
    property bool boxing: false                    // drawing a box round something to follow
    readonly property bool multicam: hasClip && clip.kind === "multicam"
    property real topH: Math.max(300, (height - 64) * 0.52)
    readonly property var clip: Backend.clip
    readonly property bool hasClip: !!clip.id
    readonly property real z: Backend.zoom
    readonly property int headW: 132
    readonly property color cutBg: Theme.t.dark ? "#101216" : "#F4F5F8"
    function rowH(t) { return t.role === "captions" ? 40 : t.kind === "video" ? 66 : 52 }
    function ask(kind, extra) { var s = extra || {}; s.kind = kind; sheet = s }
    function tracksTop() { var y = 0, out = []; for (var i = 0; i < Backend.tracks.length; i++) { out.push(y); y += rowH(Backend.tracks[i]) + 4 } return out }
    function trackAt(y) { var tops = tracksTop(); for (var i = Backend.tracks.length - 1; i >= 0; i--) if (y >= tops[i]) return Backend.tracks[i]; return Backend.tracks.length ? Backend.tracks[0] : null }
    function clipColour(c) { return c.kind === "multicam" ? "#22D3EE" : c.kind === "title" ? "#8B5CF6" : c.mediaKind === "audio" || c.audioTrack ? "#10B981" : c.mediaKind === "image" ? "#F59E0B" : "#3B82F6" }
    function tc(s) { var f = Backend.fps, n = Math.round(s * f), fr = n % f, sec = Math.floor(n / f) % 60, m = Math.floor(n / f / 60); return m + ":" + (sec < 10 ? "0" : "") + sec + ":" + (fr < 10 ? "0" : "") + fr }
    function dropMedia(px, py) {
        var d = dragMedia; dragMedia = null
        if (!d) return
        var p = lanes.mapFromItem(win.contentItem, px, py)
        if (p.x < 0 || p.y < 0 || p.x > lanes.width || p.y > lanes.height) return
        var t = trackAt(p.y + lanes.contentY), at = (p.x + lanes.contentX) / win.z
        var why = Backend.place(d.id, t ? t.id : "", at); if (why) toast.say(why, true)
    }
    Connections { target: Backend; function onSaid(msg, wrong) { toast.say(msg, wrong) } }
    DropArea { anchors.fill: parent; onDropped: function (d) { if (d.hasUrls) Backend.importFiles(d.urls) } }

    Shortcut { sequence: "Space"; onActivated: Backend.toggle() }
    Shortcut { sequence: "K"; onActivated: Backend.pause() }
    Shortcut { sequence: "L"; onActivated: Backend.play() }
    Shortcut { sequence: "J"; onActivated: Backend.seek(Backend.head - 1) }
    Shortcut { sequence: "Left"; onActivated: Backend.step(-1) }
    Shortcut { sequence: "Right"; onActivated: Backend.step(1) }
    Shortcut { sequence: "Shift+Left"; onActivated: Backend.step(-Backend.fps) }
    Shortcut { sequence: "Shift+Right"; onActivated: Backend.step(Backend.fps) }
    Shortcut { sequence: "Up"; onActivated: Backend.jumpEdit(-1) }
    Shortcut { sequence: "Down"; onActivated: Backend.jumpEdit(1) }
    Shortcut { sequence: "Home"; onActivated: Backend.seek(0) }
    Shortcut { sequence: "End"; onActivated: Backend.seek(Backend.length) }
    Shortcut { sequence: "B"; onActivated: win.tool = win.tool === "blade" ? "select" : "blade" }
    Shortcut { sequence: "A"; onActivated: win.tool = "select" }
    Shortcut { sequences: ["S", "Ctrl+B"]; onActivated: { var n = Backend.cut(); if (!n) toast.say("Nothing under the playhead to cut", true) } }
    Shortcut { sequences: ["Delete", "Backspace"]; onActivated: Backend.removePicked(win.ripple) }
    Shortcut { sequence: "Shift+Delete"; onActivated: Backend.removePicked(true) }
    Shortcut { sequence: "M"; onActivated: Backend.addMarker("") }
    Shortcut { sequence: "T"; onActivated: { Backend.addTitle("lower", -1); win.tab = "title" } }
    Shortcut { sequence: "Ctrl+D"; onActivated: Backend.duplicatePicked() }
    Shortcut { sequences: [StandardKey.Undo]; onActivated: Backend.undo() }
    Shortcut { sequences: [StandardKey.Redo, "Ctrl+Shift+Z"]; onActivated: Backend.redo() }
    Shortcut { sequences: ["=", "+"]; onActivated: Backend.setZoom(win.z * 1.4) }
    Shortcut { sequence: "-"; onActivated: Backend.setZoom(win.z / 1.4) }
    Shortcut { sequence: "Ctrl+E"; onActivated: win.ask("export", { preset: "h264", quality: "high", size: "" }) }
    Shortcut { sequence: "Escape"; onActivated: { if (win.boxing) win.boxing = false; else if (win.sheet) win.sheet = null; else Backend.pick("", false) } }
    // multicam: 1 to 4 cut to that angle at the playhead (while it plays, too)
    Repeater { model: 4
        Item { required property int index
            Shortcut { sequence: String(index + 1); enabled: win.multicam; onActivated: Backend.cutTo(win.clip.id, index) } } }

    // ---------------------------------------------------------------- pieces
    component Knob: Item {
        id: knob
        property string label: ""
        property real value: 0
        property real from: 0
        property real to: 1
        property real zero: from
        property string unit: ""
        property int decimals: 2
        property string keyProp: ""
        signal moved(real v)
        width: parent ? parent.width : 280; height: 40
        Label { y: 0; text: knob.label; font.pixelSize: 11; secondary: true }
        Label { anchors.right: keyBtn.visible ? keyBtn.left : parent.right; anchors.rightMargin: 6; y: 0; text: knob.value.toFixed(knob.decimals) + knob.unit; font.pixelSize: 11; font.family: Theme.t.fontMono
            MouseArea { anchors.fill: parent; onDoubleClicked: knob.moved(knob.zero) } }
        Pressable { id: keyBtn; visible: knob.keyProp !== "" && win.hasClip; anchors.right: parent.right; y: -2; width: 18; height: 18; radius: 4
            color: (win.clip.keys && win.clip.keys[knob.keyProp] && win.clip.keys[knob.keyProp].length) ? Theme.t.accent : hovered ? Theme.t.hover : "transparent"
            onClicked: Backend.setKey(win.clip.id, knob.keyProp, knob.value)
            Text { anchors.centerIn: parent; text: "◆"; font.pixelSize: 10; color: parent.color === Theme.t.accent ? Theme.t.onAccent : Theme.t.text_secondary } }
        Meter { y: 22; width: parent.width; interactive: true; value: (knob.value - knob.from) / (knob.to - knob.from)
            onMoved: function (v) { knob.moved(knob.from + v * (knob.to - knob.from)) } }
    }
    component Wheel: Item {
        id: wh
        property string label: ""
        property var at: [0, 0]
        signal moved(var xy)
        width: 92; height: 112
        Rectangle { id: disc; width: 84; height: 84; radius: 42; x: 4
            gradient: Gradient { orientation: Gradient.Horizontal
                GradientStop { position: 0; color: "#33FF3B30" } GradientStop { position: 0.5; color: "#3330D158" } GradientStop { position: 1; color: "#330A84FF" } }
            border.width: 1; border.color: Theme.t.islandLine
            Rectangle { anchors.centerIn: parent; width: 4; height: 4; radius: 2; color: Theme.t.text_secondary }
            Rectangle { width: 14; height: 14; radius: 7; color: "#FFFFFF"; border.width: 2; border.color: Theme.t.accent
                x: 35 + (wh.at[0] || 0) * 35; y: 35 - (wh.at[1] || 0) * 35 }
            MouseArea { anchors.fill: parent
                function put(m) { var dx = (m.x - 42) / 35, dy = -(m.y - 42) / 35, r = Math.sqrt(dx * dx + dy * dy); if (r > 1) { dx /= r; dy /= r } wh.moved([Math.round(dx * 100) / 100, Math.round(dy * 100) / 100]) }
                onPressed: function (m) { put(m) } onPositionChanged: function (m) { put(m) } onDoubleClicked: wh.moved([0, 0]) } }
        Label { anchors.horizontalCenter: disc.horizontalCenter; y: 90; text: wh.label; font.pixelSize: 11; secondary: true }
    }
    // a colour curve: drag points, click to add one, double-click a point to take it away
    component CurvePad: Item {
        id: pad
        property var points: [[0, 0], [1, 1]]
        property color ink: Theme.t.text
        property var dragPts: null
        property int dragging: -1
        readonly property var shown: dragPts || points
        signal changed(var points)
        width: parent ? parent.width : 280; height: width * 0.72
        Rectangle { anchors.fill: parent; radius: 12; color: Theme.t.dark ? "#0E1014" : "#F1F2F5"; border.width: 1; border.color: Theme.t.islandLine }
        Canvas { id: cv; anchors.fill: parent; anchors.margins: 10
            property var samples: Backend.curveSamples(pad.shown)
            onSamplesChanged: requestPaint()
            Connections { target: pad; function onShownChanged() { cv.samples = Backend.curveSamples(pad.shown) } }
            onPaint: { var c = getContext("2d"), w = width, h = height; c.reset()
                c.strokeStyle = Theme.t.dark ? "rgba(255,255,255,0.08)" : "rgba(0,0,0,0.08)"; c.lineWidth = 1
                for (var k = 1; k < 4; k++) { c.beginPath(); c.moveTo(w * k / 4, 0); c.lineTo(w * k / 4, h); c.moveTo(0, h * k / 4); c.lineTo(w, h * k / 4); c.stroke() }
                c.beginPath(); c.moveTo(0, h); c.lineTo(w, 0); c.stroke()
                c.strokeStyle = pad.ink; c.lineWidth = 2; c.beginPath()
                for (var i = 0; i < samples.length; i++) { var x = w * i / (samples.length - 1), y = h * (1 - samples[i]); if (i) c.lineTo(x, y); else c.moveTo(x, y) }
                c.stroke(); c.fillStyle = Theme.t.dark ? "#0E1014" : "#FFFFFF"
                for (var j = 0; j < pad.shown.length; j++) { c.beginPath(); c.arc(w * pad.shown[j][0], h * (1 - pad.shown[j][1]), 5, 0, Math.PI * 2); c.fill(); c.stroke() } } }
        MouseArea { anchors.fill: cv; preventStealing: true
            function at(m) { return [Math.max(0, Math.min(1, m.x / width)), Math.max(0, Math.min(1, 1 - m.y / height))] }
            onPressed: function (m) { var p = at(m), list = pad.points.map(function (q) { return [q[0], q[1]] }), best = -1, bd = 0.06
                for (var i = 0; i < list.length; i++) { var d = Math.abs(list[i][0] - p[0]) + Math.abs(list[i][1] - p[1]); if (d < bd) { bd = d; best = i } }
                if (best < 0) { list.push(p); list.sort(function (a, b) { return a[0] - b[0] }); best = list.indexOf(p) }
                pad.dragPts = list; pad.dragging = best }
            onPositionChanged: function (m) { if (pad.dragging < 0) return; var p = at(m), list = pad.dragPts.slice(), i = pad.dragging
                var lo = i > 0 ? list[i - 1][0] + 0.01 : 0, hi = i < list.length - 1 ? list[i + 1][0] - 0.01 : 1
                list[i] = [i === 0 ? 0 : i === list.length - 1 ? 1 : Math.max(lo, Math.min(hi, p[0])), p[1]]; pad.dragPts = list }
            onReleased: { if (pad.dragPts) pad.changed(pad.dragPts); pad.dragPts = null; pad.dragging = -1 }
            onDoubleClicked: function (m) { var p = at(m), list = pad.points.slice()
                for (var i = 1; i < list.length - 1; i++) if (Math.abs(list[i][0] - p[0]) + Math.abs(list[i][1] - p[1]) < 0.06) { list.splice(i, 1); pad.changed(list); return } } }
    }
    // one channel of the mixer: meter, fader, pan, mute and solo
    component Strip: Item {
        id: strip
        property var track: ({})
        readonly property real gain: track.gain || 0
        readonly property real pan: track.pan || 0
        readonly property real level: Backend.levels[track.id] || 0
        readonly property bool quiet: !!track.muted || (Backend.anySolo && !track.solo)
        width: 66; height: parent ? parent.height : 300
        function dbToPos(db) { return Math.pow((db + 60) / 72, 1.6) }          // more room near 0 dB, where it matters
        function posToDb(p) { return Math.round((Math.pow(Math.max(0, Math.min(1, p)), 1 / 1.6) * 72 - 60) * 2) / 2 }
        Rectangle { anchors.fill: parent; radius: 12; color: Theme.t.dark ? "#121419" : "#F3F4F7"; border.width: 1; border.color: Theme.t.islandLine }
        Label { x: 6; y: 8; width: parent.width - 12; horizontalAlignment: Text.AlignHCenter; elide: Text.ElideRight; text: strip.track.name || ""; font.pixelSize: 11; font.weight: Font.DemiBold }
        Label { x: 6; y: 24; width: parent.width - 12; horizontalAlignment: Text.AlignHCenter; text: (strip.gain > 0 ? "+" : "") + strip.gain.toFixed(1); font.family: Theme.t.fontMono; font.pixelSize: 10; secondary: true }
        // pan
        Item { id: panBox; x: 8; y: 42; width: parent.width - 16; height: 14
            Rectangle { y: 6; width: parent.width; height: 2; radius: 1; color: Theme.t.islandLine }
            Rectangle { x: parent.width / 2 - 1; y: 2; width: 2; height: 10; color: Theme.t.text_secondary; opacity: 0.5 }
            Rectangle { x: (strip.pan + 1) / 2 * (parent.width - 10); y: 2; width: 10; height: 10; radius: 5; color: "#43D9B8" }
            MouseArea { anchors.fill: parent; anchors.margins: -4; preventStealing: true
                function put(m) { var v = Math.max(-1, Math.min(1, (m.x - 5) / (width - 18) * 2 - 1)); Backend.setTrack(strip.track.id, "pan", Math.abs(v) < 0.06 ? 0 : v) }
                onPressed: function (m) { put(m) } onPositionChanged: function (m) { put(m) } onDoubleClicked: Backend.setTrack(strip.track.id, "pan", 0) } }
        Label { x: 4; y: 56; width: parent.width - 8; horizontalAlignment: Text.AlignHCenter; font.pixelSize: 9; secondary: true
            text: Math.abs(strip.pan) < 0.01 ? "centre" : (strip.pan < 0 ? "L " : "R ") + Math.round(Math.abs(strip.pan) * 100) }
        // fader and meter
        Item { id: fader; x: 8; y: 74; width: parent.width - 16; height: parent.height - 74 - 40
            Rectangle { id: meter; x: 2; width: 6; height: parent.height; radius: 3; color: Theme.t.dark ? "#1F232B" : "#E1E4EA"
                Rectangle { anchors.bottom: parent.bottom; width: parent.width; radius: 3; height: parent.height * (strip.quiet ? 0 : strip.level)
                    gradient: Gradient { GradientStop { position: 0; color: "#FF5A4F" } GradientStop { position: 0.12; color: "#F5C542" } GradientStop { position: 0.3; color: "#3DDC6E" } GradientStop { position: 1; color: "#2BAA5A" } }
                    Behavior on height { NumberAnimation { duration: 90 } } } }
            Rectangle { x: parent.width / 2; width: 4; height: parent.height; radius: 2; color: Theme.t.islandLine }
            Rectangle { x: parent.width / 2 - 6; y: parent.height * (1 - strip.dbToPos(0)); width: 16; height: 1; color: Theme.t.text_secondary; opacity: 0.6 }
            Rectangle { id: knobF; x: parent.width / 2 - 13; width: 30; height: 14; radius: 5; y: (parent.height - height) * (1 - strip.dbToPos(strip.gain))
                color: Theme.t.dark ? "#E7E9EE" : "#FFFFFF"; border.width: 1; border.color: Theme.t.islandLine
                Rectangle { anchors.centerIn: parent; width: 18; height: 2; color: "#43D9B8" } }
            MouseArea { anchors.fill: parent; preventStealing: true; cursorShape: Qt.SizeVerCursor
                function put(m) { Backend.setTrack(strip.track.id, "gain", strip.posToDb(1 - (m.y - 7) / (height - 14))) }
                onPressed: function (m) { put(m) } onPositionChanged: function (m) { put(m) } onDoubleClicked: Backend.setTrack(strip.track.id, "gain", 0) } }
        Row { anchors { horizontalCenter: parent.horizontalCenter; bottom: parent.bottom; bottomMargin: 8 } spacing: 4
            Pressable { width: 24; height: 24; radius: 6; color: strip.track.muted ? Theme.t.danger : hovered ? Theme.t.hover : "transparent"
                onClicked: Backend.setTrack(strip.track.id, "muted", !strip.track.muted)
                Text { anchors.centerIn: parent; text: "M"; font.pixelSize: 11; font.weight: Font.Bold; color: strip.track.muted ? "#FFFFFF" : Theme.t.text } }
            Pressable { width: 24; height: 24; radius: 6; color: strip.track.solo ? "#F5C542" : hovered ? Theme.t.hover : "transparent"
                onClicked: Backend.setTrack(strip.track.id, "solo", !strip.track.solo)
                Text { anchors.centerIn: parent; text: "S"; font.pixelSize: 11; font.weight: Font.Bold; color: strip.track.solo ? "#111111" : Theme.t.text } } }
    }
    component Chips: Flow {
        id: chips
        property var items: []        // [[id, name]]
        property string current: ""
        signal chosen(string id)
        width: parent ? parent.width : 280; spacing: 6
        Repeater { model: chips.items
            Seg { required property var modelData; anchors.verticalCenter: undefined; text: modelData[1]; on: chips.current === String(modelData[0]); onClicked: chips.chosen(String(modelData[0])) } }
    }

    islands: [
        Island { anchors { right: parent.right; rightMargin: 12 } y: 12
            Seg { icon: "back"; tip: "Undo (Ctrl+Z)"; enabled: Backend.canUndo; opacity: Backend.canUndo ? 1 : 0.4; onClicked: Backend.undo() }
            Seg { icon: "forward"; tip: "Redo"; enabled: Backend.canRedo; opacity: Backend.canRedo ? 1 : 0.4; onClicked: Backend.redo() }
            IslandGap {}
            Seg { icon: "plus"; text: "Import"; onClicked: win.ask("import", { list: Backend.mediaChoices() }) }
            Seg { icon: "edit"; text: "Title"; onClicked: { Backend.addTitle("lower", -1); win.tab = "title" } }
            Seg { objectName: "multicamBtn"; visible: Backend.picked.length >= 2 && Backend.picked.length <= 4; icon: "split"; text: "Multicam"
                tip: "The picked clips are the same moment from different cameras: line them up by their sound"; onClicked: { win.tab = "angles"; Backend.makeMulticam() } }
            IslandGap {}
            Seg { icon: "download"; text: Backend.exporting ? Math.round(Backend.exportShare * 100) + "%" : "Export"; on: Backend.exporting
                onClicked: win.ask("export", { preset: "h264", quality: "high", size: "" }) } },
        Toast { id: toast; anchors { horizontalCenter: parent.horizontalCenter; bottom: parent.bottom; bottomMargin: 24 } },
        // a library item being dragged to the timeline
        Rectangle { visible: !!win.dragMedia; z: 40; x: win.dragMedia ? win.dragMedia.x - 60 : 0; y: win.dragMedia ? win.dragMedia.y - 18 : 0; width: 120; height: 36; radius: 10; opacity: 0.85
            color: Theme.t.accent; Label { anchors.centerIn: parent; width: 108; elide: Text.ElideRight; horizontalAlignment: Text.AlignHCenter; text: win.dragMedia ? win.dragMedia.name : ""; color: Theme.t.onAccent; font.pixelSize: 11 } },

        Item { anchors.fill: parent; z: 30; visible: win.sheet !== null
            Rectangle { anchors.fill: parent; radius: win.r; color: "#77000000"; MouseArea { anchors.fill: parent; onClicked: if (!Backend.exporting) win.sheet = null } }
            Rectangle { id: card; anchors.centerIn: parent; width: 560; radius: 18; color: Theme.t.menu_bg; border.width: 1; border.color: Theme.t.menu_border
                readonly property string kind: win.sheet ? win.sheet.kind : ""
                height: kind === "export" ? 520 : kind === "captions" ? Math.min(win.height - 100, 330 + Math.min(6, capFiles.count) * 36) : Math.min(win.height - 100, 150 + Math.max(1, picks.count) * 40)
                MouseArea { anchors.fill: parent }
                Label { x: 24; y: 20; font.pixelSize: 17; font.weight: Font.DemiBold; text: card.kind === "export" ? "Make the video" : card.kind === "captions" ? "Captions" : "Bring in footage, music and pictures" }
                Label { visible: card.kind === "import"; x: 24; y: 46; width: parent.width - 48; wrapMode: Text.WordWrap; secondary: true; font.pixelSize: 12
                    text: picks.count ? "From Videos, Music, Pictures and Downloads. You can also drop files or folders on the window." : "No videos, music or pictures in Videos, Music, Pictures or Downloads. Drop files on the window instead." }
                Repeater { id: picks; model: card.kind === "import" ? win.sheet.list : []
                    Pressable { required property var modelData; required property int index; x: 16; y: 76 + index * 40; width: card.width - 32; height: 38; radius: 9
                        color: hovered ? Theme.t.hover : "transparent"; opacity: modelData.known ? 0.5 : 1
                        onClicked: { if (!modelData.known) { Backend.importFiles([modelData.path]); var l = win.sheet.list.slice(); l[index] = Object.assign({}, modelData, { known: true }); win.sheet = { kind: "import", list: l } } }
                        Glyph { x: 10; anchors.verticalCenter: parent.verticalCenter; name: modelData.kind === "audio" ? "music" : modelData.kind === "image" ? "image" : "video"; size: 15 }
                        Label { x: 36; width: parent.width - 170; elide: Text.ElideMiddle; anchors.verticalCenter: parent.verticalCenter; text: modelData.name }
                        Label { anchors { right: parent.right; rightMargin: 10; verticalCenter: parent.verticalCenter } text: modelData.known ? "in the library" : modelData.where; secondary: true; font.pixelSize: 11 } } }
                Column { visible: card.kind === "captions"; x: 24; y: 50; width: parent.width - 48; spacing: 10
                    Label { width: parent.width; wrapMode: Text.WordWrap; secondary: true; font.pixelSize: 12
                        text: Backend.captions.length ? Backend.captions.length + " caption" + (Backend.captions.length === 1 ? "" : "s") + " on the Captions track. They're burned into the video and saved alongside it as an .srt file."
                                                      : "Captions go on their own track at the top, as words in a box at the bottom of the picture." }
                    Flow { width: parent.width; spacing: 8
                        Btn { text: "Add One Here"; onClicked: { var why = Backend.addCaption(); if (why) toast.say(why, true); else { win.sheet = null; win.tab = "title" } } }
                        Btn { objectName: "transcribeBtn"; primary: true; enabled: !!(win.sheet && win.sheet.tool) && !Backend.words.busy; opacity: enabled ? 1 : 0.5
                            text: Backend.words.busy ? "Listening…" : "Write Them from Speech"; onClicked: Backend.transcribe("") }
                        Btn { visible: Backend.words.busy; danger: true; text: "Stop"; onClicked: Backend.stopTranscribing() } }
                    Label { width: parent.width; wrapMode: Text.WordWrap; font.pixelSize: 11; secondary: true
                        text: Backend.words.busy ? Backend.words.step : win.sheet && win.sheet.tool ? "Uses " + win.sheet.tool + ", on this computer: nothing is sent anywhere. Check the words afterwards; names get misheard."
                            : "Writing captions from speech needs whisper.cpp with a speech model, or the faster-whisper package. Nothing is sent anywhere." }
                    Row { spacing: 8; visible: Backend.captions.length > 0
                        Label { text: "Save as"; font.pixelSize: 12; anchors.verticalCenter: parent.verticalCenter }
                        Seg { text: ".srt"; onClicked: Backend.exportCaptions("srt") }
                        Seg { text: ".vtt (for the web)"; onClicked: Backend.exportCaptions("vtt") } }
                    Label { text: "BRING IN CAPTIONS"; font.pixelSize: 10; font.weight: Font.Bold; font.letterSpacing: 1.2; secondary: true; topPadding: 4 }
                    Label { visible: capFiles.count === 0; width: parent.width; wrapMode: Text.WordWrap; font.pixelSize: 11; secondary: true; text: "No .srt or .vtt files in Videos, Downloads, Documents or the Desktop." }
                    Column { width: parent.width; spacing: 0
                        Repeater { id: capFiles; model: card.kind === "captions" && win.sheet ? win.sheet.files.slice(0, 6) : []
                            Pressable { required property var modelData; width: parent.width; height: 36; radius: 9; color: hovered ? Theme.t.hover : "transparent"
                                onClicked: { var why = Backend.importCaptions(modelData.path, true); if (why) toast.say(why, true); else win.sheet = null }
                                Glyph { x: 8; anchors.verticalCenter: parent.verticalCenter; name: "type"; size: 14 }
                                Label { x: 32; width: parent.width - 180; elide: Text.ElideMiddle; anchors.verticalCenter: parent.verticalCenter; text: modelData.name }
                                Label { anchors { right: parent.right; rightMargin: 10; verticalCenter: parent.verticalCenter } text: modelData.where; secondary: true; font.pixelSize: 11 } } } } }
                Column { visible: card.kind === "export"; x: 24; y: 56; width: parent.width - 48; spacing: 10
                    Repeater { model: Backend.presets
                        Pressable { required property var modelData; readonly property bool on: win.sheet && win.sheet.preset === modelData.id; width: parent.width; height: 44; radius: 10
                            color: on ? Qt.rgba(Theme.t.accent.r, Theme.t.accent.g, Theme.t.accent.b, 0.2) : hovered ? Theme.t.hover : "transparent"; border.width: on ? 1 : 0; border.color: Theme.t.accent
                            onClicked: win.sheet = Object.assign({}, win.sheet, { preset: modelData.id })
                            Label { x: 12; y: 5; text: modelData.name; font.weight: Font.DemiBold }
                            Label { x: 12; y: 23; text: modelData.detail; font.pixelSize: 11; secondary: true } } }
                    Row { spacing: 8; visible: win.sheet && ["prores", "m4a", "wav"].indexOf(win.sheet.preset) < 0
                        Label { text: "Quality"; width: 70; anchors.verticalCenter: parent.verticalCenter; font.pixelSize: 12 }
                        Chips { width: 380; items: [["high", "High"], ["medium", "Medium"], ["small", "Small file"]]; current: (win.sheet && win.sheet.quality) || ""
                            onChosen: function (id) { win.sheet = Object.assign({}, win.sheet, { quality: id }) } } }
                    Row { spacing: 8; visible: win.sheet && ["m4a", "wav"].indexOf(win.sheet.preset) < 0
                        Label { text: "Size"; width: 70; anchors.verticalCenter: parent.verticalCenter; font.pixelSize: 12 }
                        Chips { width: 380; items: [["", "Project's"], ["4k", "4K"], ["1080p", "1080p"], ["720p", "720p"], ["half", "Half"]]; current: (win.sheet && win.sheet.size) || ""
                            onChosen: function (id) { win.sheet = Object.assign({}, win.sheet, { size: id }) } } }
                    Item { width: 1; height: 4 }
                    Meter { visible: Backend.exporting || Backend.exportShare > 0; width: parent.width; value: Backend.exportShare }
                    Label { visible: Backend.exporting || !!Backend.exported; font.pixelSize: 12; secondary: true
                        text: Backend.exporting ? "Making it: " + Math.round(Backend.exportShare * 100) + "%. You can keep editing; the video is made from the project as it was." : "Saved: " + Backend.exported.split("/").pop() } }
                Row { anchors { right: parent.right; rightMargin: 20; bottom: parent.bottom; bottomMargin: 18 } spacing: 8
                    Btn { visible: card.kind === "export" && !!Backend.exported && !Backend.exporting; text: "Show in Files"; onClicked: Backend.showExported() }
                    Btn { visible: card.kind === "export" && Backend.exporting; danger: true; text: "Stop"; onClicked: Backend.stopExport() }
                    Btn { text: card.kind === "export" && Backend.exporting ? "Hide" : "Done"; onClicked: win.sheet = null }
                    Btn { visible: card.kind === "export" && !Backend.exporting; primary: true; text: "Make Video"
                        onClicked: Backend.export(win.sheet.preset, win.sheet.quality, win.sheet.size) } } } }
    ]

    // ================================================================ the library
    // ================================================================ the mixer
    Rectangle { id: mix; objectName: "mixer"; visible: win.mixer; x: 12; y: 64; width: 300; height: win.topH; radius: 18; color: Theme.t.island; border.width: 1; border.color: Theme.t.islandLine; clip: true
        Label { x: 16; y: 14; text: "Mixer"; font.pixelSize: 15; font.weight: Font.DemiBold }
        Label { x: 16; y: 34; text: Backend.anySolo ? "Soloed tracks only" : "Every track's level"; font.pixelSize: 11; secondary: true }
        Pressable { anchors { right: parent.right; rightMargin: 10 } y: 12; width: 30; height: 30; radius: 9; onClicked: win.mixer = false
            Glyph { anchors.centerIn: parent; name: "x"; size: 13 } }
        ListView { id: strips; objectName: "strips"; x: 10; y: 58; width: parent.width - 20; height: parent.height - 68; orientation: ListView.Horizontal; spacing: 6; clip: true; boundsBehavior: Flickable.StopAtBounds
            // by number, so a fader being dragged isn't rebuilt each time the project changes
            readonly property var list: Backend.tracks.filter(function (t) { return t.role !== "captions" })
            model: list.length
            delegate: Strip { required property int index; track: strips.list[index] || ({}); height: strips.height } } }
    Rectangle { id: lib; objectName: "library"; visible: !win.mixer; x: 12; y: 64; width: 300; height: win.topH; radius: 18; color: Theme.t.island; border.width: 1; border.color: Theme.t.islandLine; clip: true
        Flow { id: binRow; x: 10; y: 10; width: parent.width - 20; spacing: 4
            Seg { anchors.verticalCenter: undefined; text: "All"; on: win.bin === ""; onClicked: win.bin = "" }
            Repeater { model: Backend.bins; Seg { required property string modelData; anchors.verticalCenter: undefined; text: modelData; on: win.bin === modelData; onClicked: win.bin = modelData } } }
        GridView { id: mediaGrid; objectName: "mediaGrid"; x: 8; y: binRow.height + 18; width: parent.width - 16; height: parent.height - y - 44; clip: true; cellWidth: width / 2; cellHeight: 112
            boundsBehavior: Flickable.StopAtBounds
            model: Backend.media.filter(function (m) { return !win.bin || m.bin === win.bin })
            delegate: Item { id: tile; required property var modelData; width: mediaGrid.cellWidth; height: mediaGrid.cellHeight
                Rectangle { x: 4; y: 4; width: parent.width - 8; height: 72; radius: 10; color: Theme.t.dark ? "#0B0D10" : "#E5E7EB"; clip: true; border.width: 1; border.color: Theme.t.islandLine
                    Image { anchors.fill: parent; source: tile.modelData.thumb || ""; fillMode: Image.PreserveAspectCrop; visible: !!tile.modelData.thumb; asynchronous: true }
                    Glyph { anchors.centerIn: parent; visible: !tile.modelData.thumb; size: 24; name: tile.modelData.kind === "audio" ? "music" : tile.modelData.kind === "image" ? "image" : "video"; ink: Theme.t.text_secondary }
                    Rectangle { anchors { right: parent.right; bottom: parent.bottom; margins: 4 } width: durL.width + 8; height: 16; radius: 5; color: "#B0000000"
                        Label { id: durL; anchors.centerIn: parent; text: tile.modelData.kind === "image" ? "still" : tile.modelData.length; font.pixelSize: 9; color: "#FFFFFF" } }
                    Row { anchors { left: parent.left; top: parent.top; margins: 4 } spacing: 3
                        Rectangle { visible: tile.modelData.big; width: 22; height: 14; radius: 4; color: "#B0000000"; Label { anchors.centerIn: parent; text: "4K"; font.pixelSize: 8; font.bold: true; color: "#FFFFFF" } }
                        Rectangle { visible: tile.modelData.proxy || tile.modelData.proxying; width: 34; height: 14; radius: 4; color: tile.modelData.proxy ? "#10B981" : "#B0000000"
                            Label { anchors.centerIn: parent; text: tile.modelData.proxy ? "proxy" : "…"; font.pixelSize: 8; color: "#FFFFFF" } } }
                    Rectangle { visible: tile.modelData.used; anchors { left: parent.left; bottom: parent.bottom; margins: 4 } width: 8; height: 8; radius: 4; color: Theme.t.accent } }
                Label { x: 6; y: 80; width: parent.width - 12; elide: Text.ElideMiddle; text: tile.modelData.name; font.pixelSize: 11 }
                MouseArea { anchors.fill: parent; acceptedButtons: Qt.LeftButton
                    property point from
                    onPressed: function (m) { from = Qt.point(m.x, m.y) }
                    onPositionChanged: function (m) { if (Math.abs(m.x - from.x) + Math.abs(m.y - from.y) > 6) { var p = mapToItem(win.contentItem, m.x, m.y); win.dragMedia = { id: tile.modelData.id, name: tile.modelData.name, x: p.x, y: p.y } } }
                    onReleased: function (m) { if (win.dragMedia) { var p = mapToItem(win.contentItem, m.x, m.y); win.dropMedia(p.x, p.y) } }
                    onDoubleClicked: { var why = Backend.place(tile.modelData.id, "", -1); if (why) toast.say(why, true) } } }
            Column { visible: mediaGrid.count === 0; anchors.centerIn: parent; spacing: 8; width: parent.width - 30
                Label { width: parent.width; wrapMode: Text.WordWrap; horizontalAlignment: Text.AlignHCenter; secondary: true; text: "Drop videos, music and pictures here, or press Import." } } }
        Row { x: 10; anchors { bottom: parent.bottom; bottomMargin: 8 } spacing: 4
            Seg { icon: "plus"; text: "Import"; onClicked: win.ask("import", { list: Backend.mediaChoices() }) }
            Seg { text: "Make Proxies"; tip: "Light copies of 4K footage, so editing stays smooth"; onClicked: Backend.makeProxies() } } }

    // ================================================================ the viewer
    Item { id: viewer; objectName: "viewer"; x: lib.x + lib.width + 12; y: 64; width: insp.x - x - 12; height: win.topH
        Rectangle { id: screen; width: parent.width; height: parent.height - 52; radius: 18; color: "#000000"; clip: true
            Image { id: picture; objectName: "picture"; anchors.fill: parent; anchors.margins: 6; fillMode: Image.PreserveAspectFit; cache: false; smooth: true
                source: demo ? "" : "image://clips/" + Backend.frame }
            // the demo has no footage: draw a calm stand-in so the window can be seen
            Rectangle { visible: demo; anchors.centerIn: parent; width: Math.min(parent.width - 12, (parent.height - 12) * Backend.aspect); height: width / Backend.aspect
                gradient: Gradient { GradientStop { position: 0; color: "#0F2742" } GradientStop { position: 0.55; color: "#1C4F6E" } GradientStop { position: 1; color: "#E8A45C" } }
                Rectangle { x: parent.width * 0.12; y: parent.height * 0.18; width: parent.width * 0.76; height: parent.height * 0.06; radius: height / 2; color: "#5543D9B8"; rotation: -4 }
                Rectangle { x: parent.width * 0.62; y: parent.height * 0.12; width: parent.width * 0.3; height: parent.height * 0.3; radius: 8; color: "#DDEEF2F6"
                    Label { anchors.centerIn: parent; text: "Route map"; color: "#1C4F6E"; font.pixelSize: 11 } }
                Rectangle { x: parent.width * 0.06; y: parent.height * 0.72; width: lowerT.width + 30; height: lowerT.height + 18; color: "#8C000000"
                    Label { id: lowerT; anchors.centerIn: parent; text: "Tromsø, November"; color: "#FFFFFF"; font.pixelSize: Math.max(12, parent.parent.height * 0.055); font.weight: Font.Bold } }
                // the caption under the playhead (the real viewer has it in the picture MLT draws)
                Rectangle { readonly property var cap: Backend.captions.filter(function (c) { return c.at <= Backend.head && Backend.head < c.end })[0]
                    visible: !!cap; anchors { horizontalCenter: parent.horizontalCenter; bottom: parent.bottom; bottomMargin: parent.height * 0.07 }
                    width: capT.width + 28; height: capT.height + 14; radius: 4; color: "#A6000000"
                    Label { id: capT; anchors.centerIn: parent; text: parent.cap ? parent.cap.text : ""; color: "#FFFFFF"; font.pixelSize: Math.max(11, parent.parent.height * 0.045); font.weight: Font.DemiBold } } }
            Label { visible: !demo && Backend.length === 0; anchors.centerIn: parent; color: "#9AA3AF"; text: "Drag footage from the library onto the timeline" }
            Label { visible: !Backend.live; anchors { left: parent.left; bottom: parent.bottom; margins: 12 } color: "#9AA3AF"; font.pixelSize: 10; text: "Still frames only: install python3-mlt to play" }
            // where the picture sits on the screen, for following things in it
            Item { id: frameArea; objectName: "frameArea"; anchors.centerIn: parent; width: Math.min(parent.width - 12, (parent.height - 12) * Backend.aspect); height: width / Backend.aspect
                Rectangle { objectName: "trackedBox"; readonly property var b: Backend.trackBox
                    visible: !!b.w && !win.boxing; x: (b.x || 0) * parent.width; y: (b.y || 0) * parent.height; width: (b.w || 0) * parent.width; height: (b.h || 0) * parent.height
                    color: "transparent"; border.width: 2; border.color: "#FACC15"; radius: 3
                    Rectangle { anchors { left: parent.left; bottom: parent.top; bottomMargin: 3 } width: tbL.width + 10; height: 16; radius: 4; color: "#FACC15"
                        Text { id: tbL; anchors.centerIn: parent; text: win.clip.obscure ? "pixelated" : "followed"; font.pixelSize: 9; font.weight: Font.Bold; color: "#2A2000" } } }
                MouseArea { objectName: "boxDrawer"; anchors.fill: parent; enabled: win.boxing; visible: win.boxing; cursorShape: Qt.CrossCursor; preventStealing: true
                    property point from
                    property rect r: Qt.rect(0, 0, 0, 0)
                    onPressed: function (m) { from = Qt.point(m.x, m.y); r = Qt.rect(m.x, m.y, 0, 0) }
                    onPositionChanged: function (m) { r = Qt.rect(Math.min(from.x, m.x), Math.min(from.y, m.y), Math.abs(m.x - from.x), Math.abs(m.y - from.y)) }
                    onReleased: { win.boxing = false
                        if (r.width > 6 && r.height > 6) Backend.trackMotion(win.clip.id, r.x / width, r.y / height, r.width / width, r.height / height)
                        r = Qt.rect(0, 0, 0, 0) }
                    Rectangle { anchors.fill: parent; color: "#33000000" }
                    Rectangle { x: parent.r.x; y: parent.r.y; width: parent.r.width; height: parent.r.height; color: "#22FACC15"; border.width: 2; border.color: "#FACC15" } } } }
        Item { y: screen.height + 8; width: parent.width; height: 44
            Text { anchors.verticalCenter: parent.verticalCenter; text: Backend.headText; font.family: Theme.t.fontMono; font.pixelSize: 16; color: Theme.t.text }
            Row { anchors.centerIn: parent; spacing: 4
                Seg { icon: "prev"; tip: "Previous cut (Up)"; onClicked: Backend.jumpEdit(-1) }
                Seg { text: "◂"; tip: "Back a frame (Left)"; onClicked: Backend.step(-1) }
                Pressable { objectName: "playBtn"; width: 44; height: 44; radius: 22; color: Theme.t.accent; onClicked: Backend.toggle()
                    Glyph { anchors.centerIn: parent; name: Backend.playing ? "pause" : "play"; size: 18; ink: Theme.t.onAccent } }
                Seg { text: "▸"; tip: "On a frame (Right)"; onClicked: Backend.step(1) }
                Seg { icon: "next"; tip: "Next cut (Down)"; onClicked: Backend.jumpEdit(1) } }
            Text { anchors { right: parent.right; verticalCenter: parent.verticalCenter } text: Backend.lengthText; font.family: Theme.t.fontMono; font.pixelSize: 12; color: Theme.t.text_secondary } } }

    // ================================================================ the inspector
    Rectangle { id: insp; objectName: "inspector"; x: parent.width - width - 12; y: 64; width: 330; height: win.topH; radius: 18; color: Theme.t.island; border.width: 1; border.color: Theme.t.islandLine; clip: true
        readonly property var tabs: !win.hasClip ? [] : win.clip.kind === "title" ? [["title", "Title"], ["video", "Place"], ["colour", "Colour"]]
                                   : win.multicam ? [["angles", "Angles"], ["video", "Place"], ["colour", "Colour"], ["audio", "Sound"]]
                                   : win.clip.trackKind === "audio" || win.clip.mediaKind === "audio" ? [["audio", "Sound"], ["speed", "Speed"]]
                                   : [["video", "Place"], ["colour", "Colour"], ["effects", "Effects"], ["audio", "Sound"], ["speed", "Speed"]]
        onTabsChanged: { var ok = false; for (var i = 0; i < tabs.length; i++) if (tabs[i][0] === win.tab) ok = true; if (!ok && tabs.length) win.tab = tabs[0][0] }
        Column { x: 16; y: 14; width: parent.width - 32; spacing: 2
            Label { width: parent.width; elide: Text.ElideRight; text: win.hasClip ? win.clip.name || "Title" : "Project"; font.pixelSize: 15; font.weight: Font.DemiBold }
            Label { visible: win.hasClip; font.pixelSize: 11; secondary: true
                text: win.hasClip ? win.clip.lengthText + (win.clip.kind === "title" ? "" : "  ·  from " + win.clip.sourceText) + (win.clip.speed !== 1 ? "  ·  " + win.clip.speed + "×" : "") : "" } }
        Flow { id: inspTabs; x: 12; y: 58; width: parent.width - 24; spacing: 2; visible: win.hasClip
            Repeater { model: insp.tabs; Seg { required property var modelData; anchors.verticalCenter: undefined; text: modelData[1]; on: win.tab === modelData[0]; onClicked: win.tab = modelData[0] } } }
        Flickable { id: inspScroll; x: 16; y: win.hasClip ? inspTabs.y + inspTabs.height + 10 : 50; width: parent.width - 32; height: parent.height - y - 10; clip: true; contentHeight: inspCol.height + 20
            boundsBehavior: Flickable.StopAtBounds
            Column { id: inspCol; width: parent.width; spacing: 10
                // ---- nothing picked: the project
                Column { visible: !win.hasClip; width: parent.width; spacing: 10
                    TextBox { width: parent.width; text: Backend.name; placeholder: "The film's name"; onAccepted: Backend.setProject("name", text) }
                    Label { text: "SHAPE"; font.pixelSize: 10; font.weight: Font.Bold; font.letterSpacing: 1.2; secondary: true }
                    Chips { items: Backend.sizes.map(function (s) { return [s.id, s.name] }); current: Backend.size; onChosen: function (id) { Backend.setProject("size", id) } }
                    Label { text: "FRAMES A SECOND"; font.pixelSize: 10; font.weight: Font.Bold; font.letterSpacing: 1.2; secondary: true }
                    Chips { items: Backend.rates.map(function (r) { return [r, String(r)] }); current: String(Backend.fps); onChosen: function (id) { Backend.setProject("fps", parseInt(id)) } }
                    Label { text: "SOUND"; font.pixelSize: 10; font.weight: Font.Bold; font.letterSpacing: 1.2; secondary: true }
                    Row { spacing: 10; Toggle { on: Backend.duck; onToggled: function (v) { Backend.setProject("duck", v) } }
                        Label { anchors.verticalCenter: parent.verticalCenter; width: 240; wrapMode: Text.WordWrap; font.pixelSize: 12; text: "Turn the music down while someone talks" } }
                    Knob { visible: Backend.duck; label: "Music under voices"; value: Backend.duckBy; from: -30; to: 0; zero: -12; unit: " dB"; decimals: 0; onMoved: function (v) { Backend.setProject("duckBy", Math.round(v)) } }
                    Row { spacing: 10; Toggle { on: Backend.loudness; onToggled: function (v) { Backend.setProject("loudness", v) } }
                        Label { anchors.verticalCenter: parent.verticalCenter; width: 240; wrapMode: Text.WordWrap; font.pixelSize: 12; text: "Even out the loudness when making the video (−16 LUFS, right for the web)" } }
                    Label { text: "OTHER EDITORS"; font.pixelSize: 10; font.weight: Font.Bold; font.letterSpacing: 1.2; secondary: true }
                    Btn { text: "Save as an MLT Project"; onClicked: Backend.saveMlt() }
                    Label { width: parent.width; wrapMode: Text.WordWrap; font.pixelSize: 11; secondary: true; text: "Shotcut opens it as it is; Kdenlive can bring it in." }
                    Btn { danger: true; text: "Start Over"; onClicked: Backend.startOver() } }

                // ---- place: size, position, turn, see-through, crop
                Column { visible: win.hasClip && win.tab === "video"; width: parent.width; spacing: 6
                    Knob { label: "Size"; keyProp: "scale"; value: win.clip.transform ? win.clip.transform.scale : 1; from: 0.05; to: 3; zero: 1; unit: "×"; onMoved: function (v) { Backend.set(win.clip.id, "transform.scale", v) } }
                    Knob { label: "Left – right"; keyProp: "x"; value: win.clip.transform ? win.clip.transform.x : 0; from: -1; to: 1; zero: 0; onMoved: function (v) { Backend.set(win.clip.id, "transform.x", v) } }
                    Knob { label: "Up – down"; keyProp: "y"; value: win.clip.transform ? win.clip.transform.y : 0; from: -1; to: 1; zero: 0; onMoved: function (v) { Backend.set(win.clip.id, "transform.y", v) } }
                    Knob { label: "Turn"; value: win.clip.transform ? win.clip.transform.rotation : 0; from: -180; to: 180; zero: 0; unit: "°"; decimals: 0; onMoved: function (v) { Backend.set(win.clip.id, "transform.rotation", Math.round(v)) } }
                    Knob { label: "See-through"; keyProp: "opacity"; value: win.clip.transform ? win.clip.transform.opacity : 1; from: 0; to: 1; zero: 1; onMoved: function (v) { Backend.set(win.clip.id, "transform.opacity", v) } }
                    Knob { label: "Fade in"; value: win.clip.fadeIn || 0; from: 0; to: 3; zero: 0; unit: " s"; decimals: 1; onMoved: function (v) { Backend.set(win.clip.id, "fadeIn", Math.round(v * 10) / 10) } }
                    Knob { label: "Fade out"; value: win.clip.fadeOut || 0; from: 0; to: 3; zero: 0; unit: " s"; decimals: 1; onMoved: function (v) { Backend.set(win.clip.id, "fadeOut", Math.round(v * 10) / 10) } }
                    Repeater { model: win.clip.kind === "title" ? [] : [["Crop left", 0], ["Crop top", 1], ["Crop right", 2], ["Crop bottom", 3]]
                        Knob { required property var modelData; label: modelData[0]; value: win.clip.transform ? win.clip.transform.crop[modelData[1]] : 0; from: 0; to: 0.45; zero: 0
                            onMoved: function (v) { var c = win.clip.transform.crop.slice(); c[modelData[1]] = Math.round(v * 100) / 100; Backend.set(win.clip.id, "transform.crop", c) } } }
                    Label { visible: !!win.clip.keyTimes && win.clip.keyTimes.length > 0; width: parent.width; wrapMode: Text.WordWrap; font.pixelSize: 11; secondary: true
                        text: "◆ Keyframes at " + (win.clip.keyTimes || []).map(function (t) { return t.toFixed(1) + " s" }).join(", ") + ". Move the playhead and press ◆ for another." }
                    Label { text: "BETWEEN KEYFRAMES"; font.pixelSize: 10; font.weight: Font.Bold; font.letterSpacing: 1.2; secondary: true; topPadding: 4 }
                    Row { width: parent.width; spacing: 10
                        Canvas { id: easeCurve; width: 54; height: 54
                            property string kind: win.clip.ease || "linear"
                            onKindChanged: requestPaint()
                            function f(u) { var k = kind; if (k === "in") return u * u * u; if (k === "out") return 1 - Math.pow(1 - u, 3)
                                if (k === "inout") return u < 0.5 ? 4 * u * u * u : 1 - Math.pow(-2 * u + 2, 3) / 2; if (k === "hold") return u < 1 ? 0 : 1; return u }
                            onPaint: { var c = getContext("2d"); c.reset(); c.fillStyle = Theme.t.dark ? "#0E1014" : "#F1F2F5"; c.fillRect(0, 0, width, height)
                                c.strokeStyle = "#43D9B8"; c.lineWidth = 2; c.beginPath()
                                for (var i = 0; i <= 40; i++) { var u = i / 40, x = 4 + u * (width - 8), y = height - 4 - f(u) * (height - 8); if (i) c.lineTo(x, y); else c.moveTo(x, y) }
                                c.stroke() } }
                        Chips { objectName: "easeChips"; width: parent.width - 64; items: Backend.eases.map(function (e) { return [e.id, e.name] }); current: win.clip.ease || "linear"
                            onChosen: function (id) { Backend.set(win.clip.id, "ease", id) } } }
                    Label { visible: (win.clip.followable || []).length > 0; text: "FOLLOW"; font.pixelSize: 10; font.weight: Font.Bold; font.letterSpacing: 1.2; secondary: true; topPadding: 4 }
                    Chips { visible: (win.clip.followable || []).length > 0; items: (win.clip.followable || []).map(function (f) { return [f.id, "What was followed in " + f.name] })
                        onChosen: function (id) { Backend.follow(win.clip.id, id); toast.say("It moves with it now: keyframes for left–right and up–down.", false) } } }


                // ---- multicam: the angles
                Column { visible: win.multicam && win.tab === "angles"; width: parent.width; spacing: 8
                    Grid { objectName: "angleGrid"; columns: 2; spacing: 8; width: parent.width
                        Repeater { model: win.multicam ? win.clip.angleViews : []
                            Pressable { required property var modelData; required property int index; objectName: "angle" + index
                                width: (parent.width - 8) / 2; height: width * 9 / 16 + 22; radius: 10; color: Theme.t.dark ? "#0B0D10" : "#E5E7EB"
                                readonly property bool live: Backend.angleNow === index
                                border.width: live ? 2 : 1; border.color: live ? "#22D3EE" : Theme.t.islandLine
                                onClicked: Backend.cutTo(win.clip.id, index)
                                Image { x: 3; y: 3; width: parent.width - 6; height: parent.height - 25; source: modelData.thumb || ""; fillMode: Image.PreserveAspectCrop; asynchronous: true; clip: true }
                                Rectangle { x: 7; y: 7; width: 20; height: 20; radius: 6; color: parent.live ? "#22D3EE" : "#B0000000"
                                    Text { anchors.centerIn: parent; text: index + 1; font.pixelSize: 12; font.weight: Font.Bold; color: parent.parent.live ? "#06202A" : "#FFFFFF" } }
                                Label { x: 8; y: parent.height - 19; width: parent.width - 16; elide: Text.ElideMiddle; font.pixelSize: 10; text: modelData.name
                                    + (Math.abs(modelData.offset) > 0.01 ? "  ·  " + (modelData.offset > 0 ? "+" : "") + modelData.offset.toFixed(2) + " s" : "") } } } }
                    Label { width: parent.width; wrapMode: Text.WordWrap; font.pixelSize: 11; secondary: true
                        text: "Lined up by their sound. Play, and press 1–" + (win.multicam ? win.clip.angleViews.length : 4) + " (or click an angle) to cut to it at the playhead." }
                    Label { text: "SOUND FROM"; font.pixelSize: 10; font.weight: Font.Bold; font.letterSpacing: 1.2; secondary: true }
                    Chips { items: win.multicam ? win.clip.angleViews.map(function (a, k) { return [k, (k + 1) + "  " + a.name] }) : []; current: String(win.clip.audioAngle || 0)
                        onChosen: function (id) { Backend.setSoundAngle(win.clip.id, parseInt(id)) } }
                    Btn { text: "Flatten into Clips"; onClicked: Backend.flatten(win.clip.id) }
                    Label { width: parent.width; wrapMode: Text.WordWrap; font.pixelSize: 10; secondary: true; text: "Flattening keeps the cuts as ordinary clips, with the sound as a clip of its own." } }
                // ---- colour
                Column { visible: win.hasClip && win.tab === "colour"; width: parent.width; spacing: 6
                    Knob { label: "Exposure"; value: win.clip.colour ? win.clip.colour.exposure : 0; from: -3; to: 3; zero: 0; unit: " stops"; onMoved: function (v) { Backend.set(win.clip.id, "colour.exposure", Math.round(v * 100) / 100) } }
                    Knob { label: "Contrast"; value: win.clip.colour ? win.clip.colour.contrast : 1; from: 0.3; to: 2; zero: 1; onMoved: function (v) { Backend.set(win.clip.id, "colour.contrast", Math.round(v * 100) / 100) } }
                    Knob { label: "Colour strength"; value: win.clip.colour ? win.clip.colour.saturation : 1; from: 0; to: 2.5; zero: 1; onMoved: function (v) { Backend.set(win.clip.id, "colour.saturation", Math.round(v * 100) / 100) } }
                    Knob { label: "Warmth (white balance)"; value: win.clip.colour ? win.clip.colour.temperature : 6500; from: 2500; to: 11000; zero: 6500; unit: " K"; decimals: 0; onMoved: function (v) { Backend.set(win.clip.id, "colour.temperature", Math.round(v / 50) * 50) } }
                    Knob { label: "Tint (green – magenta)"; value: win.clip.colour ? win.clip.colour.tint : 0; from: -1; to: 1; zero: 0; onMoved: function (v) { Backend.set(win.clip.id, "colour.tint", Math.round(v * 100) / 100) } }
                    Row { spacing: 6; topPadding: 6
                        Wheel { label: "Shadows"; at: win.clip.colour ? win.clip.colour.shadows : [0, 0]; onMoved: function (xy) { Backend.set(win.clip.id, "colour.shadows", xy) } }
                        Wheel { label: "Midtones"; at: win.clip.colour ? win.clip.colour.midtones : [0, 0]; onMoved: function (xy) { Backend.set(win.clip.id, "colour.midtones", xy) } }
                        Wheel { label: "Highlights"; at: win.clip.colour ? win.clip.colour.highlights : [0, 0]; onMoved: function (xy) { Backend.set(win.clip.id, "colour.highlights", xy) } } }
                    Label { text: "LOOK (LUT)"; font.pixelSize: 10; font.weight: Font.Bold; font.letterSpacing: 1.2; secondary: true }
                    Chips { items: [["", "None"]].concat(Backend.lutChoices().map(function (l) { return [l.path, l.name] })); current: win.clip.colour ? win.clip.colour.lut : ""
                        onChosen: function (id) { Backend.set(win.clip.id, "colour.lut", id) } }
                    Label { width: parent.width; wrapMode: Text.WordWrap; font.pixelSize: 10; secondary: true; text: ".cube files in Videos/LUTs, Downloads or Documents appear here." }
                    Item { width: 1; height: 4 }
                    Row { width: parent.width; spacing: 6
                        Label { text: "CURVES"; font.pixelSize: 10; font.weight: Font.Bold; font.letterSpacing: 1.2; secondary: true; anchors.verticalCenter: parent.verticalCenter }
                        Item { width: parent.width - 220; height: 1 }
                        Repeater { model: [["rgb", "All", Theme.t.text], ["r", "R", "#FF5A4F"], ["g", "G", "#3DDC6E"], ["b", "B", "#4D8DFF"]]
                            Pressable { required property var modelData; width: 30; height: 22; radius: 6; color: curvePad.ch === modelData[0] ? Qt.rgba(1, 1, 1, Theme.t.dark ? 0.14 : 0) : "transparent"
                                border.width: curvePad.ch === modelData[0] ? 1 : 0; border.color: modelData[2]; onClicked: curvePad.ch = modelData[0]
                                Text { anchors.centerIn: parent; text: modelData[1]; color: modelData[2]; font.pixelSize: 10; font.weight: Font.Bold } } } }
                    CurvePad { id: curvePad; objectName: "curvePad"
                        property string ch: "rgb"
                        readonly property var all: win.clip.colour && win.clip.colour.curves ? win.clip.colour.curves : ({})
                        points: all[ch] || [[0, 0], [1, 1]]
                        ink: ({ rgb: Theme.t.text, r: "#FF5A4F", g: "#3DDC6E", b: "#4D8DFF" })[ch]
                        onChanged: function (pts) { var c = Object.assign({}, curvePad.all); c[curvePad.ch] = pts; Backend.set(win.clip.id, "colour.curves", c) } }
                    Item { width: parent.width; height: Math.max(curveHint.height, 14)
                        Label { id: curveHint; width: parent.width - 52; wrapMode: Text.WordWrap; font.pixelSize: 10; secondary: true; text: "Click to add a point and drag it; double-click a point to take it away." }
                        Label { anchors.right: parent.right; text: "Reset"; font.pixelSize: 11; color: Theme.t.accent
                            MouseArea { anchors.fill: parent; anchors.margins: -4; onClicked: Backend.set(win.clip.id, "colour.curves", ({})) } } }
                    Label { text: "SCOPES"; font.pixelSize: 10; font.weight: Font.Bold; font.letterSpacing: 1.2; secondary: true }
                    Row { spacing: 4
                        Seg { text: "Waveform"; onClicked: scopeImg.source = Backend.scope("waveform") }
                        Seg { text: "Vectorscope"; onClicked: scopeImg.source = Backend.scope("vectorscope") }
                        Seg { text: "Histogram"; onClicked: scopeImg.source = Backend.scope("histogram") } }
                    Image { id: scopeImg; width: parent.width; height: source != "" ? width * sourceSize.height / Math.max(1, sourceSize.width) : 0; cache: false; fillMode: Image.PreserveAspectFit } }

                // ---- effects
                Column { visible: win.hasClip && win.tab === "effects"; width: parent.width; spacing: 6
                    Knob { id: steadyKnob; objectName: "steadyKnob"; label: "Steady shaky footage"; value: win.clip.effects ? (win.clip.effects.stabilise || 0) : 0; from: 0; to: 1; zero: 0
                        property real want: -1
                        onMoved: function (v) { want = Math.round(v * 20) / 20; steadyCommit.restart() }
                        Timer { id: steadyCommit; interval: 500; onTriggered: { Backend.stabilise(win.clip.id, steadyKnob.want); steadyKnob.want = -1 } } }
                    Row { visible: win.hasClip && (win.clip.effects && win.clip.effects.stabilise > 0); spacing: 8; width: parent.width
                        readonly property var share: Backend.steadying[win.clip.id]
                        Meter { visible: parent.share !== undefined; width: 90; value: parent.share || 0; anchors.verticalCenter: parent.verticalCenter }
                        Label { width: parent.width - 100; wrapMode: Text.WordWrap; font.pixelSize: 10; secondary: true; anchors.verticalCenter: parent.verticalCenter
                            text: parent.share !== undefined ? "Steadying carefully: " + Math.round(parent.share * 100) + "%. A quick version plays meanwhile." : "Steadied. Stronger follows the camera's path less closely, and zooms in a little more." } }
                    Knob { label: "Blur"; value: win.clip.effects ? win.clip.effects.blur : 0; from: 0; to: 1; zero: 0; onMoved: function (v) { Backend.set(win.clip.id, "effects.blur", Math.round(v * 100) / 100) } }
                    Knob { label: "Sharpen"; value: win.clip.effects ? win.clip.effects.sharpen : 0; from: 0; to: 1; zero: 0; onMoved: function (v) { Backend.set(win.clip.id, "effects.sharpen", Math.round(v * 100) / 100) } }
                    Knob { label: "Vignette"; value: win.clip.effects ? win.clip.effects.vignette : 0; from: 0; to: 1; zero: 0; onMoved: function (v) { Backend.set(win.clip.id, "effects.vignette", Math.round(v * 100) / 100) } }
                    Repeater { model: [["bw", "Black and white"], ["flipH", "Mirror left to right"], ["flipV", "Upside down"], ["videoNoise", "Clean up grain"]]
                        Row { required property var modelData; spacing: 10; height: 34
                            Toggle { anchors.verticalCenter: parent.verticalCenter; on: win.clip.effects ? !!win.clip.effects[modelData[0]] : false; onToggled: function (v) { Backend.set(win.clip.id, "effects." + modelData[0], v) } }
                            Label { anchors.verticalCenter: parent.verticalCenter; text: modelData[1]; font.pixelSize: 12 } } }
                    Label { text: "FOLLOW SOMETHING THAT MOVES"; font.pixelSize: 10; font.weight: Font.Bold; font.letterSpacing: 1.2; secondary: true; topPadding: 6 }
                    Label { width: parent.width; wrapMode: Text.WordWrap; font.pixelSize: 11; secondary: true
                        text: win.clip.tracked ? "Followed from where it was drawn. Pixelate it, or put a title on it that moves with it."
                                               : "Put the playhead where it's clearly seen, then draw a box round it in the picture." }
                    Btn { objectName: "drawBoxBtn"; text: win.boxing ? "Drawing… (Esc to stop)" : win.clip.tracked ? "Follow Something Else" : "Draw a Box Round It"; primary: !win.clip.tracked
                        onClicked: { win.boxing = !win.boxing; if (win.boxing) toast.say("Drag a box round it in the picture", false) } }
                    Row { visible: !!win.clip.tracked; spacing: 10; height: 34
                        Toggle { anchors.verticalCenter: parent.verticalCenter; on: !!win.clip.obscure; onToggled: function (v) { Backend.setObscure(win.clip.id, v) } }
                        Label { anchors.verticalCenter: parent.verticalCenter; text: "Pixelate it (faces, number plates)"; font.pixelSize: 12 } }
                    Row { visible: !!win.clip.tracked; spacing: 6
                        Btn { text: "Add a Title on It"; onClicked: { if (Backend.addFollower(win.clip.id)) win.tab = "title" } }
                        Btn { text: "Forget It"; onClicked: Backend.clearTracking(win.clip.id) } } }

                // ---- sound
                Column { visible: win.hasClip && win.tab === "audio"; width: parent.width; spacing: 6
                    Label { visible: !win.clip.hasAudio; width: parent.width; wrapMode: Text.WordWrap; secondary: true; font.pixelSize: 12; text: "This clip has no sound." }
                    Knob { visible: !!win.clip.hasAudio; label: "Volume"; keyProp: "volume"; value: win.clip.volume || 0; from: -40; to: 12; zero: 0; unit: " dB"; decimals: 1; onMoved: function (v) { Backend.set(win.clip.id, "volume", Math.round(v * 10) / 10) } }
                    Knob { visible: !!win.clip.hasAudio && win.clip.trackKind === "audio"; label: "Fade in"; value: win.clip.fadeIn || 0; from: 0; to: 5; zero: 0; unit: " s"; decimals: 1; onMoved: function (v) { Backend.set(win.clip.id, "fadeIn", Math.round(v * 10) / 10) } }
                    Knob { visible: !!win.clip.hasAudio && win.clip.trackKind === "audio"; label: "Fade out"; value: win.clip.fadeOut || 0; from: 0; to: 5; zero: 0; unit: " s"; decimals: 1; onMoved: function (v) { Backend.set(win.clip.id, "fadeOut", Math.round(v * 10) / 10) } }
                    Row { visible: !!win.clip.hasAudio; spacing: 10; height: 34
                        Toggle { anchors.verticalCenter: parent.verticalCenter; on: !!win.clip.mute; onToggled: function (v) { Backend.set(win.clip.id, "mute", v) } }
                        Label { anchors.verticalCenter: parent.verticalCenter; text: "Silent"; font.pixelSize: 12 } }
                    Row { visible: !!win.clip.hasAudio; spacing: 10; height: 34
                        Toggle { anchors.verticalCenter: parent.verticalCenter; on: !!win.clip.denoise; onToggled: function (v) { Backend.set(win.clip.id, "denoise", v) } }
                        Label { anchors.verticalCenter: parent.verticalCenter; text: "Clean up background noise"; font.pixelSize: 12 } }
                    Item { visible: !!win.clip.hasAudio; width: parent.width; height: 22
                        Label { y: 8; text: "SOUND EFFECTS"; font.pixelSize: 10; font.weight: Font.Bold; font.letterSpacing: 1.2; secondary: true }
                        Label { anchors.right: parent.right; y: 6; text: "Reset"; font.pixelSize: 11; color: Theme.t.accent; visible: Object.keys(win.clip.sound || {}).length > 0
                            MouseArea { anchors.fill: parent; anchors.margins: -4; onClicked: Backend.set(win.clip.id, "sound", ({})) } } }
                    Row { visible: !!win.clip.hasAudio; spacing: 10; height: 34
                        Toggle { objectName: "voiceToggle"; anchors.verticalCenter: parent.verticalCenter; on: !!(win.clip.sound || {}).voice; onToggled: function (v) { Backend.set(win.clip.id, "sound.voice", v) } }
                        Label { anchors.verticalCenter: parent.verticalCenter; width: 230; wrapMode: Text.WordWrap; text: "Clear voice (no rumble, a little presence, an even level)"; font.pixelSize: 12 } }
                    Knob { visible: !!win.clip.hasAudio; label: "Even out loudness (compressor)"; value: (win.clip.sound || {}).comp || 0; from: 0; to: 1; zero: 0
                        onMoved: function (v) { Backend.set(win.clip.id, "sound.comp", Math.round(v * 100) / 100) } }
                    Repeater { model: win.clip.hasAudio ? [["low", "Low (bass)"], ["mid", "Middle"], ["high", "High (treble)"]] : []
                        Knob { required property var modelData; label: modelData[1]; value: ((win.clip.sound || {}).eq || {})[modelData[0]] || 0; from: -12; to: 12; zero: 0; unit: " dB"; decimals: 1
                            onMoved: function (v) { Backend.set(win.clip.id, "sound.eq." + modelData[0], Math.round(v * 2) / 2) } } }
                    Knob { visible: !!win.clip.hasAudio; label: "Echo"; value: (win.clip.sound || {}).echo || 0; from: 0; to: 1; zero: 0
                        onMoved: function (v) { Backend.set(win.clip.id, "sound.echo", Math.round(v * 100) / 100) } } }

                // ---- speed
                Column { visible: win.hasClip && win.tab === "speed"; width: parent.width; spacing: 8
                    Chips { items: [[0.25, "¼×"], [0.5, "½×"], [0.75, "¾×"], [1, "1×"], [1.5, "1½×"], [2, "2×"], [4, "4×"], [8, "8×"]]; current: String(win.clip.speed || 1)
                        onChosen: function (id) { Backend.set(win.clip.id, "speed", parseFloat(id)) } }
                    Row { spacing: 10; height: 34
                        Toggle { anchors.verticalCenter: parent.verticalCenter; on: win.clip.keepPitch !== false; onToggled: function (v) { Backend.set(win.clip.id, "keepPitch", v) } }
                        Label { anchors.verticalCenter: parent.verticalCenter; text: "Keep voices sounding natural"; font.pixelSize: 12 } } }

                // ---- title
                Column { visible: win.hasClip && win.tab === "title"; width: parent.width; spacing: 8
                    TextBox { id: titleText; width: parent.width; lines: 3; many: win.clip.text || ""; onEdited: titleSave.restart() }
                    Timer { id: titleSave; interval: 400; onTriggered: Backend.set(win.clip.id, "text", titleText.many) }
                    Chips { items: Backend.titleStyles.map(function (s) { return [s.id, s.name] }); current: ""
                        onChosen: function (id) { var st = Object.assign({}, win.clip.style, { place: { lower: "lower", centre: "centre", top: "top", caption: "bottom" }[id], size: { lower: 54, centre: 110, top: 72, caption: 46 }[id], box: id === "lower" || id === "caption", align: id === "lower" ? "left" : "centre" }); Backend.set(win.clip.id, "style", st) } }
                    Knob { label: "Letter size"; value: win.clip.style ? win.clip.style.size : 54; from: 16; to: 200; zero: 54; decimals: 0; onMoved: function (v) { Backend.set(win.clip.id, "style.size", Math.round(v)) } }
                    Knob { label: "On screen for"; value: win.clip.length || 4; from: 0.5; to: 20; zero: 4; unit: " s"; decimals: 1; onMoved: function (v) { Backend.set(win.clip.id, "length", Math.round(v * 10) / 10) } }
                    Chips { items: [["left", "Left"], ["centre", "Centre"], ["right", "Right"]]; current: win.clip.style ? win.clip.style.align : ""; onChosen: function (id) { Backend.set(win.clip.id, "style.align", id) } }
                    Chips { items: [["top", "Top"], ["centre", "Middle"], ["lower", "Lower third"], ["bottom", "Bottom"]]; current: win.clip.style ? win.clip.style.place : ""; onChosen: function (id) { Backend.set(win.clip.id, "style.place", id) } }
                    Row { spacing: 6
                        Repeater { model: ["#FFFFFF", "#111111", "#F5C542", "#FF5A36", "#43D9B8", "#7C9CFF"]
                            Rectangle { required property string modelData; width: 26; height: 26; radius: 13; color: modelData; border.width: win.clip.style && win.clip.style.colour === modelData ? 3 : 1; border.color: win.clip.style && win.clip.style.colour === modelData ? Theme.t.accent : Theme.t.islandLine
                                MouseArea { anchors.fill: parent; onClicked: Backend.set(win.clip.id, "style.colour", modelData) } } } }
                    Row { spacing: 10; height: 34
                        Toggle { anchors.verticalCenter: parent.verticalCenter; on: win.clip.style ? !!win.clip.style.box : false; onToggled: function (v) { Backend.set(win.clip.id, "style.box", v) } }
                        Label { anchors.verticalCenter: parent.verticalCenter; text: "Band behind the words"; font.pixelSize: 12 } }
                    Row { spacing: 10; height: 34
                        Toggle { anchors.verticalCenter: parent.verticalCenter; on: win.clip.style ? !!win.clip.style.shadow : false; onToggled: function (v) { Backend.set(win.clip.id, "style.shadow", v) } }
                        Label { anchors.verticalCenter: parent.verticalCenter; text: "Shadow"; font.pixelSize: 12 } } }

                // ---- into the next clip
                Column { visible: win.hasClip && win.clip.kind !== "title" && win.tab !== "speed"; width: parent.width; spacing: 6; topPadding: 8
                    Label { text: "INTO THE NEXT CLIP"; font.pixelSize: 10; font.weight: Font.Bold; font.letterSpacing: 1.2; secondary: true }
                    Chips { items: [["", "Cut"]].concat(Backend.transitions.map(function (t) { return [t.id, t.name] })); current: win.clip.transition ? win.clip.transition.kind : ""
                        onChosen: function (id) { var why = Backend.setTransition(win.clip.id, id, win.clip.transition ? win.clip.transition.length : 1.0); if (why) toast.say(why, true) } }
                    Knob { visible: !!win.clip.transition; label: "Transition length"; value: win.clip.transition ? win.clip.transition.length : 1; from: 0.2; to: 4; zero: 1; unit: " s"; decimals: 1
                        onMoved: function (v) { Backend.setTransition(win.clip.id, win.clip.transition.kind, Math.round(v * 10) / 10) } } } } } }

    // ================================================================ the timeline
    Rectangle { id: tl; objectName: "timeline"; x: 12; y: 64 + win.topH + 12; width: parent.width - 24; height: parent.height - y - 12; radius: 18; color: win.cutBg; border.width: 1; border.color: Theme.t.islandLine; clip: true
        // tools
        Row { id: tools; x: 12; y: 8; spacing: 4; height: 32
            Seg { text: "Select"; tip: "A"; on: win.tool === "select"; onClicked: win.tool = "select" }
            Seg { text: "Blade"; tip: "B: click a clip to cut it there"; on: win.tool === "blade"; onClicked: win.tool = "blade" }
            IslandGap {}
            Seg { text: "Ripple"; tip: "Deleting and trimming close the gaps"; on: win.ripple; onClicked: win.ripple = !win.ripple }
            Seg { text: "Cut Here"; tip: "S: cut at the playhead"; onClicked: { if (!Backend.cut()) toast.say("Nothing under the playhead to cut", true) } }
            Seg { text: "Marker"; tip: "M"; onClicked: Backend.addMarker("") }
            IslandGap {}
            Seg { text: "+ Video Track"; onClicked: Backend.addTrack("video") }
            Seg { text: "+ Audio Track"; onClicked: Backend.addTrack("audio") }
            IslandGap {}
            Seg { objectName: "mixerBtn"; text: "Mixer"; on: win.mixer; onClicked: win.mixer = !win.mixer }
            Seg { objectName: "captionsBtn"; text: Backend.words.busy ? "Listening…" : "Captions"; on: Backend.words.busy; onClicked: win.ask("captions", { files: Backend.captionFiles(), tool: Backend.speechTool() }) } }
        Row { anchors { right: parent.right; rightMargin: 14 } y: 8; height: 32; spacing: 8
            Glyph { name: "search"; size: 13; anchors.verticalCenter: parent.verticalCenter }
            Meter { width: 160; anchors.verticalCenter: parent.verticalCenter; interactive: true; value: Math.log(win.z / 4) / Math.log(100); onMoved: function (v) { Backend.setZoom(4 * Math.pow(100, v)) } }
            Label { anchors.verticalCenter: parent.verticalCenter; text: Backend.lengthText; font.family: Theme.t.fontMono; font.pixelSize: 11; secondary: true } }

        // track names down the left
        Flickable { id: heads; x: 0; y: 74; width: win.headW; height: parent.height - y - 8; contentHeight: lanesCol.height; contentY: lanes.contentY; interactive: false; clip: true
            Column { width: parent.width; spacing: 4
                Repeater { model: Backend.tracks
                    Rectangle { required property var modelData; width: win.headW - 10; x: 8; height: win.rowH(modelData); radius: 10; color: Theme.t.island; border.width: 1; border.color: Theme.t.islandLine
                        Label { x: 10; y: 8; text: modelData.name; font.pixelSize: 12; font.weight: Font.DemiBold }
                        Label { x: 10; y: 26; text: modelData.role === "captions" ? "captions" : modelData.kind === "video" ? (modelData.id === "v1" ? "main" : "layer") : (modelData.role || "sound"); font.pixelSize: 9; secondary: true }
                        Row { anchors { right: parent.right; rightMargin: 6; verticalCenter: parent.verticalCenter } spacing: 2
                            Pressable { width: 24; height: 24; radius: 6; onClicked: Backend.setTrack(modelData.id, modelData.kind === "video" ? "hidden" : "muted", !(modelData.hidden || modelData.muted))
                                Glyph { anchors.centerIn: parent; size: 13; name: modelData.kind === "video" ? "eye" : "volume"; ink: (modelData.hidden || modelData.muted) ? Theme.t.danger : Theme.t.icon; opacity: (modelData.hidden || modelData.muted) ? 0.6 : 1 } }
                            Pressable { width: 24; height: 24; radius: 6; onClicked: Backend.setTrack(modelData.id, "locked", !modelData.locked)
                                Glyph { anchors.centerIn: parent; size: 13; name: "lock"; ink: modelData.locked ? Theme.t.accent : Theme.t.icon; opacity: modelData.locked ? 1 : 0.35 } } } } } } }

        // the ruler
        Item { id: ruler; x: win.headW; y: 44; width: parent.width - win.headW - 8; height: 26; clip: true
            readonly property real stepS: win.z > 120 ? 1 : win.z > 40 ? 2 : win.z > 15 ? 5 : win.z > 6 ? 10 : 30
            Repeater { model: Math.ceil((ruler.width + lanes.contentX) / (win.z * ruler.stepS)) + 1
                Item { required property int index; readonly property real s: index * ruler.stepS; x: s * win.z - lanes.contentX; width: 1; height: ruler.height
                    Rectangle { width: 1; height: 8; y: ruler.height - 8; color: Theme.t.text_secondary }
                    Label { x: 3; y: 2; text: Math.floor(parent.s / 60) + ":" + ("0" + Math.floor(parent.s % 60)).slice(-2); font.pixelSize: 9; secondary: true } } }
            Repeater { model: Backend.markers
                Rectangle { required property var modelData; x: modelData.t * win.z - lanes.contentX - 5; y: 2; width: 10; height: 10; radius: 2; rotation: 45; color: modelData.colour
                    MouseArea { anchors.fill: parent; anchors.margins: -4; onClicked: Backend.seek(modelData.t); onDoubleClicked: Backend.removeMarker(modelData.t) } } }
            MouseArea { anchors.fill: parent; z: -1; onPressed: function (m) { Backend.seek((m.x + lanes.contentX) / win.z) } onPositionChanged: function (m) { Backend.seek((m.x + lanes.contentX) / win.z) } } }

        // the lanes
        Flickable { id: lanes; objectName: "lanes"; x: win.headW; y: 74; width: parent.width - win.headW - 8; height: parent.height - y - 8; clip: true
            contentWidth: Math.max(width, (Backend.length + 30) * win.z); contentHeight: lanesCol.height + 20; boundsBehavior: Flickable.StopAtBounds
            WheelHandler { acceptedModifiers: Qt.ControlModifier; onWheel: function (e) { Backend.setZoom(win.z * (e.angleDelta.y > 0 ? 1.15 : 1 / 1.15)) } }
            MouseArea { width: lanes.contentWidth; height: Math.max(lanes.height, lanesCol.height); onClicked: function (m) { Backend.pick("", false); Backend.seek(m.x / win.z) } }
            Column { id: lanesCol; width: lanes.contentWidth; spacing: 4
                Repeater { model: Backend.tracks
                    Rectangle { id: lane; required property var modelData; required property int index; width: lanes.contentWidth; height: win.rowH(modelData); radius: 8
                        color: index % 2 ? (Theme.t.dark ? "#15181E" : "#ECEEF2") : (Theme.t.dark ? "#13161B" : "#F0F1F4"); opacity: modelData.hidden || modelData.muted ? 0.55 : 1
                        Repeater { model: lane.modelData.clips
                            Rectangle { id: cl; required property var modelData
                                property real dx: 0
                                property real dy: 0
                                property real trimL: 0
                                property real trimR: 0
                                x: (modelData.at * win.z) + dx + trimL; y: 3 + dy; z: dx || dy ? 10 : 1
                                width: Math.max(4, modelData.length * win.z - trimL + trimR); height: lane.height - 6; radius: 7; clip: true
                                color: Qt.rgba(Qt.color(win.clipColour(modelData)).r, Qt.color(win.clipColour(modelData)).g, Qt.color(win.clipColour(modelData)).b, Theme.t.dark ? 0.42 : 0.3)
                                readonly property bool chosen: Backend.picked.indexOf(modelData.id) >= 0
                                border.width: chosen ? 2 : 1; border.color: chosen ? "#FFFFFF" : win.clipColour(modelData)
                                // pictures along a video clip
                                Row { visible: cl.modelData.thumbs.length > 0 && lane.modelData.kind === "video"; y: 16; height: parent.height - 18; clip: true; width: parent.width; opacity: 0.85
                                    Repeater { model: Math.min(40, Math.ceil(cl.width / 80))
                                        Image { required property int index; width: 80; height: parent.height; fillMode: Image.PreserveAspectCrop; asynchronous: true
                                            source: cl.modelData.thumbs.length ? cl.modelData.thumbs[Math.min(cl.modelData.thumbs.length - 1, Math.floor(index * 80 / Math.max(1, cl.width) * cl.modelData.thumbs.length))] : "" } } }
                                // the sound's outline
                                Row { visible: cl.modelData.wave.length > 0 && (lane.modelData.kind === "audio" || cl.modelData.thumbs.length === 0); anchors.bottom: parent.bottom; anchors.bottomMargin: 2; height: parent.height - 18; width: parent.width
                                    Repeater { model: cl.modelData.wave
                                        Rectangle { required property real modelData; width: Math.max(1, cl.width / Math.max(1, cl.modelData.wave.length)); height: Math.max(1, modelData * parent.height); anchors.verticalCenter: parent.verticalCenter
                                            color: win.clipColour(cl.modelData); opacity: 0.9 } } }
                                // multicam: where it cuts, and to which angle
                                Repeater { model: cl.modelData.kind === "multicam" ? cl.modelData.cuts : []
                                    Item { required property var modelData; x: modelData[0] * win.z; y: 16; width: 18; height: cl.height - 16
                                        Rectangle { width: 2; height: parent.height; color: "#22D3EE"; visible: parent.x > 0 }
                                        Rectangle { x: 3; y: 3; width: 15; height: 15; radius: 4; color: "#22D3EE"
                                            Text { anchors.centerIn: parent; text: parent.parent.modelData[1] + 1; font.pixelSize: 9; font.weight: Font.Bold; color: "#06202A" } } } }
                                Rectangle { width: parent.width; height: 16; color: Qt.rgba(0, 0, 0, 0.35)
                                    Label { x: 6; width: parent.width - 12; elide: Text.ElideRight; anchors.verticalCenter: parent.verticalCenter; font.pixelSize: 10; color: "#FFFFFF"
                                        text: (cl.modelData.kind === "title" ? "T  " : "") + cl.modelData.name + (cl.modelData.speed !== 1 ? "  " + cl.modelData.speed + "×" : "") + (cl.modelData.keys ? "  ◆" + cl.modelData.keys : "") } }
                                // fades
                                Canvas { anchors.fill: parent; visible: cl.modelData.fadeIn > 0 || cl.modelData.fadeOut > 0
                                    onPaint: { var c = getContext("2d"); c.reset(); c.fillStyle = "rgba(0,0,0,0.35)"; var fi = cl.modelData.fadeIn * win.z, fo = cl.modelData.fadeOut * win.z
                                        if (fi > 0) { c.beginPath(); c.moveTo(0, 16); c.lineTo(fi, 16); c.lineTo(0, height); c.closePath(); c.fill() }
                                        if (fo > 0) { c.beginPath(); c.moveTo(width, 16); c.lineTo(width - fo, 16); c.lineTo(width, height); c.closePath(); c.fill() } }
                                    onWidthChanged: requestPaint() }
                                MouseArea { id: body; anchors.fill: parent; anchors.leftMargin: 7; anchors.rightMargin: 7; preventStealing: true; cursorShape: win.tool === "blade" ? Qt.SplitHCursor : Qt.OpenHandCursor
                                    property point from
                                    property bool moved: false
                                    onPressed: function (m) { from = mapToItem(lanes.contentItem, m.x, m.y); moved = false
                                        if (win.tool === "blade") { Backend.pick(cl.modelData.id, false); Backend.seek(cl.modelData.at + (m.x + 7) / win.z); Backend.cut(); return }
                                        if (!cl.chosen || (m.modifiers & Qt.ControlModifier)) Backend.pick(cl.modelData.id, (m.modifiers & Qt.ControlModifier)) }
                                    onPositionChanged: function (m) { if (win.tool === "blade") return; var p = mapToItem(lanes.contentItem, m.x, m.y); cl.dx = p.x - from.x; cl.dy = p.y - from.y; moved = Math.abs(cl.dx) + Math.abs(cl.dy) > 3 }
                                    onReleased: function (m) {
                                        if (win.tool === "blade") return
                                        if (moved) { var t = win.trackAt(lane.y + 3 + cl.dy + height / 2); var ok = Backend.move(cl.modelData.id, t ? t.id : cl.modelData.track, cl.modelData.at + cl.dx / win.z); if (!ok) toast.say("It doesn't fit there", true) }
                                        cl.dx = 0; cl.dy = 0 } }
                                MouseArea { width: 8; height: parent.height; cursorShape: Qt.SizeHorCursor; preventStealing: true
                                    property real fromX
                                    onPressed: function (m) { fromX = mapToItem(lanes.contentItem, m.x, 0).x; Backend.pick(cl.modelData.id, false) }
                                    onPositionChanged: function (m) { cl.trimL = mapToItem(lanes.contentItem, m.x, 0).x - fromX }
                                    onReleased: { Backend.trim(cl.modelData.id, "in", cl.modelData.at + cl.trimL / win.z, win.ripple); cl.trimL = 0 } }
                                MouseArea { anchors.right: parent.right; width: 8; height: parent.height; cursorShape: Qt.SizeHorCursor; preventStealing: true
                                    property real fromX
                                    onPressed: function (m) { fromX = mapToItem(lanes.contentItem, m.x, 0).x; Backend.pick(cl.modelData.id, false) }
                                    onPositionChanged: function (m) { cl.trimR = mapToItem(lanes.contentItem, m.x, 0).x - fromX }
                                    onReleased: { Backend.trim(cl.modelData.id, "out", cl.modelData.end + cl.trimR / win.z, win.ripple); cl.trimR = 0 } } }
                        }
                        // transitions sit on the cut, as a bow tie
                        Repeater { model: lane.modelData.clips.filter(function (c) { return !!c.transition })
                            Rectangle { required property var modelData; x: modelData.end * win.z - width / 2; y: (lane.height - height) / 2; width: Math.max(14, modelData.transitionLength * win.z); height: 22; radius: 6; z: 5
                                color: Theme.t.dark ? "#E6FFFFFF" : "#E6111827"
                                Text { anchors.centerIn: parent; text: "⋈"; font.pixelSize: 13; color: Theme.t.dark ? "#111" : "#FFF" }
                                MouseArea { anchors.fill: parent; onClicked: { Backend.pick(modelData.id, false); win.tab = "video" } } } } } } }
            // the playhead
            Rectangle { objectName: "playhead"; x: Backend.head * win.z - 1; y: 0; width: 2; height: Math.max(lanes.height, lanesCol.height); color: "#FF3B30"; z: 20 } }
        Rectangle { x: win.headW + Backend.head * win.z - lanes.contentX - 6; y: 62; width: 12; height: 12; radius: 3; rotation: 45; color: "#FF3B30"; visible: x > win.headW - 8 && x < tl.width }
    }
}
