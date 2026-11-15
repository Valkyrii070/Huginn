import QtQuick

// Tempo, "the stage": a glowing transport display sits at the top like the front of a mixing desk, the tracks run
// across the middle as coloured lanes under a ruler of bars, and the bench below changes with what you're working
// on: a piano roll, a drum grid, the drummer's pad, Smart Controls, the mixer or a keyboard. Loops and instruments
// slide in from the right. Warm, like a studio's red "on air" light.
GlassWindow {
    id: win
    title: "Tempo"; heading: Backend.hasSong ? Backend.song.name : ""; glow: "bottom"; width: 1400; height: 880; minimumWidth: 1080; minimumHeight: 680
    property string bench: "auto"                 // auto | roll | drums | drummer | smart | mixer | keys
    property bool benchOpen: true
    property string drawer: ""                    // loops | library | ""
    property string loopFamily: "All"
    property real ppb: 26                         // pixels a beat
    property real grid: 0.25                      // the piano roll's grid, in beats
    property int octave: 4
    property bool typing: false                   // musical typing (A W S E D F …)
    property string sheet: Backend.hasSong ? "" : "songs"
    property bool autoOn: false                   // automation lanes
    property var picked: []                       // tracks Ctrl-clicked together, to stack them
    property string selSection: ""
    property var laneMenu: null                   // the knob menu for an automation lane: { tid, x, y }
    property bool duckMenu: false
    readonly property var shown: Backend.tracks.filter(function (t) { return !t.hidden })
    readonly property int laneH: rowH + (autoOn ? 30 : 0)
    function rowOf(y) { return win.shown[Math.max(0, Math.min(win.shown.length - 1, Math.floor(y / (win.laneH + 4))))] }
    component Chips: Flow {
        id: chips
        property var items: []        // [[id, name]]
        property string current: ""
        signal chosen(string id)
        width: parent ? parent.width : 280; spacing: 4
        Repeater { model: chips.items
            Seg { required property var modelData; anchors.verticalCenter: undefined; text: modelData[1]; on: chips.current === String(modelData[0]); onClicked: chips.chosen(String(modelData[0])) } } }
    component Heading: Label { font.pixelSize: 10; font.weight: Font.Bold; font.letterSpacing: 1.2; secondary: true }
    readonly property var song: Backend.song
    readonly property int bpb: song.sig ? song.sig[0] : 4
    readonly property var selTrack: { var t = Backend.tracks; for (var i = 0; i < t.length; i++) if (t[i].id === Backend.selectedTrack) return t[i]; return null }
    readonly property var reg: Backend.selectedRegion !== "" ? Backend.region(Backend.selectedRegion) : ({})
    readonly property string benchKind: bench !== "auto" ? bench : !selTrack ? "keys" : selTrack.kind === "drummer" ? "drummer"
                                        : reg.id && (reg.kind === "audio" || (reg.takeViews || []).length) ? "region"
                                        : selTrack.kind === "audio" || selTrack.kind === "stack" ? "smart" : reg.id && reg.kit ? "drums" : reg.id ? "roll" : "smart"
    readonly property color hot: Theme.t.accent
    readonly property color lcd: "#FF9F5A"
    function trackColour(t) { return t ? t.colour : hot }
    Connections { target: Backend; function onSaid(msg, bad) { toast.say(msg, bad) } }
    // MIDI files and sounds dropped on the window come in as tracks (loops have a drop area of their own)
    DropArea { anchors.fill: parent; keys: ["text/uri-list"]; onDropped: function (d) { if (d.hasUrls) Backend.importFiles(d.urls) } }

    Shortcut { sequence: "Space"; enabled: win.sheet === ""; onActivated: Backend.toggle() }
    Shortcut { sequence: "R"; enabled: win.sheet === "" && !win.typing; onActivated: Backend.recording ? Backend.stop() : Backend.record() }
    Shortcut { sequence: "Return"; enabled: win.sheet === ""; onActivated: Backend.toStart() }
    Shortcut { sequence: "C"; enabled: win.sheet === "" && !win.typing; onActivated: Backend.setSong("cycle", Object.assign({}, win.song.cycle, { on: !win.song.cycle.on })) }
    Shortcut { sequence: "K"; enabled: win.sheet === "" && !win.typing; onActivated: Backend.setSong("metronome", !win.song.metronome) }
    Shortcut { sequences: [StandardKey.Undo]; onActivated: Backend.undo() }
    Shortcut { sequences: [StandardKey.Redo, "Ctrl+Shift+Z"]; onActivated: Backend.redo() }
    Shortcut { sequence: "Ctrl+D"; onActivated: if (Backend.selectedRegion) Backend.duplicateRegion(Backend.selectedRegion) }
    Shortcut { sequence: "Delete"; enabled: win.sheet === ""; onActivated: if (Backend.selectedRegion) Backend.removeRegion(Backend.selectedRegion) }
    Shortcut { sequence: "Ctrl+T"; onActivated: if (Backend.selectedRegion) Backend.splitRegion(Backend.selectedRegion, Backend.position) }
    Shortcut { sequence: "Ctrl+K"; onActivated: { win.typing = !win.typing; if (win.typing) keyCatcher.forceActiveFocus() } }
    // musical typing: the computer keyboard as a piano while it's on
    Item { id: keyCatcher; focus: win.typing
        Keys.onPressed: function (e) {
            if (e.isAutoRepeat) { e.accepted = true; return }
            if (e.text === "z") { win.octave = Math.max(1, win.octave - 1); e.accepted = true; return }
            if (e.text === "x") { win.octave = Math.min(7, win.octave + 1); e.accepted = true; return }
            var k = Backend.keyPitch(e.text); if (k >= 0) { Backend.noteOn(12 * (win.octave + 1) + k, 100); e.accepted = true } }
        Keys.onReleased: function (e) { if (e.isAutoRepeat) return; var k = Backend.keyPitch(e.text); if (k >= 0) { Backend.noteOff(12 * (win.octave + 1) + k); e.accepted = true } } }

    toolbar: [
        Seg { icon: "download"; text: "Export"; enabled: Backend.hasSong; onClicked: win.sheet = "export" },
        Seg { icon: "sliders"; text: "Mixer"; on: win.benchOpen && win.benchKind === "mixer"; onClicked: { win.bench = win.bench === "mixer" ? "auto" : "mixer"; win.benchOpen = true } },
        Seg { icon: "music"; text: "Instruments"; on: win.drawer === "library"; onClicked: win.drawer = win.drawer === "library" ? "" : "library" },
        Seg { icon: "refresh"; text: "Loops"; on: win.drawer === "loops"; onClicked: win.drawer = win.drawer === "loops" ? "" : "loops" },
        Seg { icon: "list"; tip: "Songs"; onClicked: win.sheet = "songs" }
    ]

    // ================================================================ the transport display
    Rectangle { id: transport; objectName: "transport"; z: 6; visible: Backend.hasSong; x: Math.max(250, (parent.width - width) / 2 - 90); y: 10; height: 50; width: tRow.width + 16; radius: 18
        color: Theme.t.island; border.width: 1; border.color: Theme.t.islandLine
        Row { id: tRow; x: 8; anchors.verticalCenter: parent.verticalCenter; spacing: 3
            Seg { icon: "prev"; tip: "To the start (Return)"; onClicked: Backend.toStart() }
            Pressable { objectName: "playBtn"; width: 40; height: 34; radius: 12; color: Backend.playing ? win.hot : (hovered ? Theme.t.hover : "transparent"); onClicked: Backend.toggle()
                Glyph { anchors.centerIn: parent; name: Backend.playing ? "pause" : "play"; size: 16; ink: Backend.playing ? Theme.t.onAccent : Theme.t.icon } }
            Pressable { objectName: "recBtn"; width: 40; height: 34; radius: 12; color: Backend.recording ? "#E5484D" : (hovered ? Theme.t.hover : "transparent")
                onClicked: Backend.recording ? Backend.stop() : Backend.record()
                Rectangle { anchors.centerIn: parent; width: 14; height: 14; radius: 7; color: Backend.recording ? "#FFFFFF" : "#E5484D" } }
            Seg { icon: "refresh"; tip: "Cycle (C)"; on: !!(win.song.cycle && win.song.cycle.on); onClicked: Backend.setSong("cycle", Object.assign({}, win.song.cycle, { on: !win.song.cycle.on })) }
            // the display
            Rectangle { width: 330; height: 38; radius: 10; color: "#0E0A08"; border.width: 1; border.color: "#2A1C14"; anchors.verticalCenter: parent.verticalCenter
                Row { anchors.centerIn: parent; spacing: 16
                    Column { anchors.verticalCenter: parent.verticalCenter
                        Text { objectName: "lcdBar"; text: Backend.clock; color: win.lcd; font.family: Theme.t.fontMono; font.pixelSize: 19; font.weight: Font.DemiBold; anchors.horizontalCenter: parent.horizontalCenter }
                        Text { text: "BAR   BEAT"; color: "#8A5A3C"; font.pixelSize: 7; font.letterSpacing: 1; anchors.horizontalCenter: parent.horizontalCenter } }
                    Column { anchors.verticalCenter: parent.verticalCenter
                        Text { text: Backend.time; color: win.lcd; font.family: Theme.t.fontMono; font.pixelSize: 13; anchors.horizontalCenter: parent.horizontalCenter }
                        Text { text: "TIME"; color: "#8A5A3C"; font.pixelSize: 7; font.letterSpacing: 1; anchors.horizontalCenter: parent.horizontalCenter } }
                    Column { anchors.verticalCenter: parent.verticalCenter
                        Text { objectName: "lcdTempo"; text: Math.round(win.song.tempo || 120); color: win.lcd; font.family: Theme.t.fontMono; font.pixelSize: 15; anchors.horizontalCenter: parent.horizontalCenter
                            MouseArea { anchors.fill: parent; anchors.margins: -6; cursorShape: Qt.SizeVerCursor; property real y0: 0; property real t0: 120
                                onPressed: function (m) { y0 = m.y; t0 = win.song.tempo } onPositionChanged: function (m) { Backend.setSong("tempo", Math.round(t0 + (y0 - m.y) / 3)) }
                                onWheel: function (w) { Backend.setSong("tempo", win.song.tempo + (w.angleDelta.y > 0 ? 1 : -1)) } } }
                        Text { text: "TEMPO"; color: "#8A5A3C"; font.pixelSize: 7; font.letterSpacing: 1; anchors.horizontalCenter: parent.horizontalCenter } }
                    Column { anchors.verticalCenter: parent.verticalCenter
                        Text { text: (win.song.sig || [4, 4]).join("/"); color: win.lcd; font.family: Theme.t.fontMono; font.pixelSize: 13; anchors.horizontalCenter: parent.horizontalCenter
                            MouseArea { anchors.fill: parent; anchors.margins: -6; onClicked: { var opts = [[4, 4], [3, 4], [6, 8], [2, 4], [5, 4]], cur = (win.song.sig || [4, 4]).join("/"), k = 0
                                for (var i = 0; i < opts.length; i++) if (opts[i].join("/") === cur) k = (i + 1) % opts.length; Backend.setSong("sig", opts[k]) } } }
                        Text { text: "TIME SIG"; color: "#8A5A3C"; font.pixelSize: 7; font.letterSpacing: 1; anchors.horizontalCenter: parent.horizontalCenter } }
                    Column { anchors.verticalCenter: parent.verticalCenter
                        Text { text: Backend.noteNames[win.song.key || 0].replace(/-?\d+$/, "") + (win.song.mode === "minor" ? " min" : " maj"); color: win.lcd; font.family: Theme.t.fontMono; font.pixelSize: 13; anchors.horizontalCenter: parent.horizontalCenter
                            MouseArea { anchors.fill: parent; anchors.margins: -6; onClicked: win.sheet = "key" } }
                        Text { text: "KEY"; color: "#8A5A3C"; font.pixelSize: 7; font.letterSpacing: 1; anchors.horizontalCenter: parent.horizontalCenter } } } }
            Seg { icon: "bell"; tip: "Metronome (K)"; on: !!win.song.metronome; onClicked: Backend.setSong("metronome", !win.song.metronome) }
            Seg { text: "1234"; tip: "Count in a bar before recording"; on: (win.song.countIn || 0) > 0; onClicked: Backend.setSong("countIn", win.song.countIn > 0 ? 0 : 1) }
            Seg { icon: "keyboard"; tip: "Musical typing (Ctrl+K): A–K play notes, Z and X change octave"; on: win.typing; onClicked: { win.typing = !win.typing; if (win.typing) keyCatcher.forceActiveFocus() } } } }

    // ================================================================ tracks and their lanes
    readonly property int headW: 218
    readonly property int rowH: 64
    Rectangle { id: arrange; objectName: "arrange"; visible: Backend.hasSong; x: 12; y: 70; width: parent.width - 24 - (win.drawer !== "" ? 312 : 0)
        height: parent.height - y - 12 - (win.benchOpen ? benchBox.height + 12 : 0); radius: 18; color: Theme.t.island; border.width: 1; border.color: Theme.t.islandLine; clip: true
        Behavior on width { NumberAnimation { duration: Theme.t.still ? 0 : 160; easing.type: Easing.OutCubic } }
        // add a track
        Row { x: 12; y: 8; spacing: 3; height: 30
            Seg { icon: "plus"; text: "Instrument"; onClicked: Backend.addTrack("instrument", "grand") }
            Seg { text: "Drummer"; onClicked: Backend.addTrack("drummer", "drums") }
            Seg { icon: "mic"; text: "Voice or Guitar"; onClicked: Backend.addTrack("audio", "") }
            Seg { objectName: "autoBtn"; text: "A"; tip: "Automation: draw any knob over time"; on: win.autoOn; onClicked: win.autoOn = !win.autoOn }
            Seg { objectName: "stackBtn"; visible: win.picked.length >= 2; icon: "layers"; text: "Stack " + win.picked.length; tip: "These tracks play into one stack with its own effects and fader"
                onClicked: { Backend.makeStack(win.picked); win.picked = [] } }
            IslandGap {}
            Seg { icon: "undo"; enabled: Backend.canUndo; opacity: enabled ? 1 : 0.4; tip: "Undo (Ctrl+Z)"; onClicked: Backend.undo() }
            Seg { icon: "redo"; enabled: Backend.canRedo; opacity: enabled ? 1 : 0.4; tip: "Redo"; onClicked: Backend.redo() } }
        // what to do with the selected region
        Row { visible: Backend.selectedRegion !== "" && win.selSection === ""; anchors { right: zoomRow.left; rightMargin: 14 } y: 8; spacing: 3; height: 30
            Seg { text: "Split at Playhead"; tip: "Ctrl+T"; onClicked: Backend.splitRegion(Backend.selectedRegion, Backend.position) }
            Seg { text: "Duplicate"; tip: "Ctrl+D"; onClicked: Backend.duplicateRegion(Backend.selectedRegion) }
            Seg { text: "Loop ×" + (win.reg.loops || 1); tip: "Repeat it"; onClicked: Backend.setLoops(Backend.selectedRegion, ((win.reg.loops || 1) % 8) + 1) }
            Seg { icon: "trash"; danger: true; tip: "Delete"; onClicked: Backend.removeRegion(Backend.selectedRegion) } }
        // what to do with the selected section
        Row { objectName: "sectionActions"; visible: win.selSection !== ""; anchors { right: zoomRow.left; rightMargin: 14 } y: 8; spacing: 3; height: 30
            readonly property int at: { var s = Backend.sections; for (var i = 0; i < s.length; i++) if (s[i].id === win.selSection) return i; return -1 }
            Seg { icon: "back"; tip: "Earlier in the song"; enabled: parent.at > 0; opacity: enabled ? 1 : 0.4; onClicked: Backend.moveSection(win.selSection, parent.at - 1) }
            Seg { icon: "forward"; tip: "Later in the song"; enabled: parent.at >= 0 && parent.at < Backend.sections.length - 1; opacity: enabled ? 1 : 0.4; onClicked: Backend.moveSection(win.selSection, parent.at + 1) }
            Seg { objectName: "copySection"; text: "Copy After"; tip: "Play it again straight after; the rest moves along"; onClicked: win.selSection = Backend.duplicateSection(win.selSection) }
            Seg { text: "Remove Marker"; tip: "The music stays"; onClicked: { Backend.removeSection(win.selSection); win.selSection = "" } }
            Seg { icon: "trash"; danger: true; text: "Delete with Music"; tip: "The section and its music go; the song closes up"; onClicked: { Backend.deleteSection(win.selSection); win.selSection = "" } } }
        Row { id: zoomRow; anchors { right: parent.right; rightMargin: 14 } y: 8; spacing: 6; height: 30
            Glyph { name: "zoom"; size: 13; anchors.verticalCenter: parent.verticalCenter }
            Meter { width: 120; anchors.verticalCenter: parent.verticalCenter; interactive: true; value: (win.ppb - 8) / 92; onMoved: function (v) { win.ppb = 8 + v * 92 } } }

        // the arrangement: Intro, Verse, Chorus… over the bars
        Row { x: 20; y: 44; height: 20; spacing: 6
            Label { anchors.verticalCenter: parent.verticalCenter; text: "SECTIONS"; font.pixelSize: 9; font.weight: Font.Bold; font.letterSpacing: 1.2; secondary: true }
            Pressable { objectName: "addSection"; width: 20; height: 18; radius: 5; anchors.verticalCenter: parent.verticalCenter; onClicked: win.selSection = Backend.addSection("", Backend.position, win.bpb * 8)
                Glyph { anchors.centerIn: parent; name: "plus"; size: 11 } } }
        Item { id: secStrip; objectName: "sections"; x: win.headW; y: 44; width: parent.width - win.headW - 8; height: 20; clip: true
            Repeater { model: Backend.sections
                Rectangle { id: sec; required property var modelData; required property int index; objectName: "section" + index
                    readonly property color ink: ["#FF8A5B", "#4FA3FF", "#3DDC84", "#B57BFF", "#F5C542", "#FF5FA2"][index % 6]
                    readonly property bool on: win.selSection === modelData.id
                    property real dw: 0
                    x: modelData.start * win.ppb - lanes.contentX; width: Math.max(10, modelData.length * win.ppb - 2 + dw); height: 18; radius: 6
                    color: Qt.rgba(ink.r, ink.g, ink.b, on ? 0.75 : 0.35); border.width: on ? 1 : 0; border.color: "#FFFFFF"
                    Label { visible: !secEdit.visible; x: 6; width: parent.width - 12; anchors.verticalCenter: parent.verticalCenter; elide: Text.ElideRight; text: sec.modelData.name; font.pixelSize: 10; font.weight: Font.DemiBold; color: "#FFFFFF" }
                    TextInput { id: secEdit; visible: false; x: 6; width: parent.width - 12; anchors.verticalCenter: parent.verticalCenter; font.pixelSize: 10; color: "#FFFFFF"; selectByMouse: true
                        onAccepted: { Backend.setSection(sec.modelData.id, "name", text); visible = false } onActiveFocusChanged: if (!activeFocus) visible = false }
                    MouseArea { anchors.fill: parent; anchors.rightMargin: 6
                        onClicked: { win.selSection = sec.modelData.id; Backend.selectRegion(""); Backend.seek(sec.modelData.start) }
                        onDoubleClicked: { secEdit.text = sec.modelData.name; secEdit.visible = true; secEdit.forceActiveFocus(); secEdit.selectAll() } }
                    MouseArea { anchors.right: parent.right; width: 8; height: parent.height; cursorShape: Qt.SizeHorCursor; preventStealing: true; property real x0: 0
                        onPressed: function (m) { x0 = mapToItem(secStrip, m.x, 0).x }
                        onPositionChanged: function (m) { sec.dw = mapToItem(secStrip, m.x, 0).x - x0 }
                        onReleased: { var len = Math.max(win.bpb, Math.round((sec.modelData.length * win.ppb + sec.dw) / win.ppb / win.bpb) * win.bpb); sec.dw = 0; Backend.setSection(sec.modelData.id, "length", len) } } } }
            Label { visible: Backend.sections.length === 0; x: 6; anchors.verticalCenter: parent.verticalCenter; text: "Mark the parts of your song (+) to copy, move or delete a whole verse at once."; font.pixelSize: 10; secondary: true } }

        // the ruler: bars, the cycle and the playhead's handle
        Item { id: ruler; objectName: "ruler"; x: win.headW; y: 66; width: parent.width - win.headW - 8; height: 30; clip: true
            Rectangle { visible: !!(win.song.cycle && win.song.cycle.on); y: 2; height: 10; radius: 4; color: "#F5C542"; opacity: 0.85
                x: (win.song.cycle ? win.song.cycle.start : 0) * win.ppb - lanes.contentX; width: ((win.song.cycle ? win.song.cycle.end - win.song.cycle.start : 0)) * win.ppb
                MouseArea { anchors.fill: parent; property real x0: 0; property var c0: null; cursorShape: Qt.SizeHorCursor
                    onPressed: function (m) { x0 = mapToItem(ruler, m.x, 0).x; c0 = win.song.cycle }
                    onPositionChanged: function (m) { var dx = Math.round((mapToItem(ruler, m.x, 0).x - x0) / win.ppb); Backend.setSong("cycle", { on: true, start: Math.max(0, c0.start + dx), end: Math.max(1, c0.end + dx) }) } }
                Rectangle { anchors.right: parent.right; width: 8; height: parent.height; color: "#C9962A"; radius: 3
                    MouseArea { anchors.fill: parent; anchors.margins: -3; cursorShape: Qt.SizeHorCursor
                        onPositionChanged: function (m) { var b = Math.max(win.song.cycle.start + 1, Math.round((mapToItem(ruler, m.x, 0).x + lanes.contentX) / win.ppb)); Backend.setSong("cycle", Object.assign({}, win.song.cycle, { end: b })) } } } }
            Repeater { model: Math.max(0, Math.ceil((ruler.width + lanes.contentX) / (win.ppb * win.bpb)) + 1)
                Item { required property int index; x: index * win.bpb * win.ppb - lanes.contentX; height: ruler.height
                    Rectangle { y: 14; width: 1; height: 16; color: Theme.t.text_secondary; opacity: 0.6 }
                    Label { x: 4; y: 14; text: index + 1; font.pixelSize: 10; secondary: true; visible: win.ppb * win.bpb > 26 || index % 4 === 0 } } }
            MouseArea { anchors.fill: parent; z: -1; onPressed: function (m) { Backend.seek(Math.max(0, (m.x + lanes.contentX) / win.ppb)) }
                onPositionChanged: function (m) { Backend.seek(Math.max(0, (m.x + lanes.contentX) / win.ppb)) } } }

        // the track headers
        Flickable { id: heads; x: 0; y: 98; width: win.headW; height: parent.height - y - 8; contentHeight: lanesCol.height; contentY: lanes.contentY; interactive: false; clip: true
            Column { width: parent.width; spacing: 4
                Repeater { model: win.shown
                    Rectangle { id: head; required property var modelData; required property int index; objectName: "head_" + modelData.id
                        readonly property bool member: !!modelData.output
                        readonly property bool stack: modelData.kind === "stack"
                        x: 8 + (member ? 14 : 0); width: win.headW - 14 - (member ? 14 : 0); height: win.laneH; radius: 12
                        readonly property bool on: Backend.selectedTrack === modelData.id
                        readonly property bool pickedOne: win.picked.length > 1 && win.picked.indexOf(modelData.id) >= 0
                        color: on || pickedOne ? Qt.rgba(Qt.color(modelData.colour).r, Qt.color(modelData.colour).g, Qt.color(modelData.colour).b, 0.18) : (Theme.t.dark ? "#10FFFFFF" : "#08000000")
                        border.width: on || pickedOne ? 1 : 0; border.color: modelData.colour
                        MouseArea { anchors.fill: parent
                            onClicked: function (m) {
                                if (m.modifiers & Qt.ControlModifier) {                  // Ctrl-click: pick several (to stack them)
                                    var p = win.picked.slice(), i = p.indexOf(head.modelData.id)
                                    if (p.length === 0 && Backend.selectedTrack) p.push(Backend.selectedTrack)
                                    if (i >= 0) p.splice(i, 1); else if (p.indexOf(head.modelData.id) < 0) p.push(head.modelData.id)
                                    win.picked = p
                                } else { win.picked = [head.modelData.id]; Backend.selectTrack(head.modelData.id) } } }
                        Rectangle { x: 0; width: 5; height: parent.height; radius: 2; color: head.modelData.colour }
                        Rectangle { x: 14; y: 10; width: 34; height: 34; radius: 10; color: Qt.rgba(Qt.color(head.modelData.colour).r, Qt.color(head.modelData.colour).g, Qt.color(head.modelData.colour).b, 0.28)
                            Glyph { anchors.centerIn: parent; size: 17; ink: head.modelData.colour; name: head.stack ? "layers" : head.modelData.kind === "audio" ? "mic" : head.modelData.kind === "drummer" ? "disc" : head.modelData.family === "Drums" ? "disc" : "music" }
                            MouseArea { enabled: head.stack; anchors.fill: parent; onClicked: Backend.setTrack(head.modelData.id, "open", !head.modelData.open) } }
                        Column { x: 56; y: 9; width: parent.width - 56 - (head.stack ? 60 : 86); spacing: 1
                            Label { width: parent.width; elide: Text.ElideRight; text: head.modelData.name; font.pixelSize: 12; font.weight: Font.DemiBold }
                            Label { width: parent.width; elide: Text.ElideRight; font.pixelSize: 10; secondary: true
                                text: head.stack ? (head.modelData.open ? "▾ " : "▸ ") + head.modelData.instName : head.modelData.kind === "audio" ? "Recording" : head.modelData.instName } }
                        Row { anchors { right: parent.right; rightMargin: 8 } y: 10; spacing: 2
                            Pressable { width: 24; height: 22; radius: 6; color: head.modelData.mute ? Theme.t.danger : (hovered ? Theme.t.hover : "transparent"); onClicked: Backend.setTrack(head.modelData.id, "mute", !head.modelData.mute)
                                Text { anchors.centerIn: parent; text: "M"; font.pixelSize: 10; font.weight: Font.Bold; color: head.modelData.mute ? "#FFFFFF" : Theme.t.text } }
                            Pressable { width: 24; height: 22; radius: 6; color: head.modelData.solo ? "#F5C542" : (hovered ? Theme.t.hover : "transparent"); onClicked: Backend.setTrack(head.modelData.id, "solo", !head.modelData.solo)
                                Text { anchors.centerIn: parent; text: "S"; font.pixelSize: 10; font.weight: Font.Bold; color: head.modelData.solo ? "#111111" : Theme.t.text } }
                            Pressable { visible: !head.stack; width: 24; height: 22; radius: 6; color: head.modelData.arm ? "#E5484D" : (hovered ? Theme.t.hover : "transparent"); onClicked: Backend.setTrack(head.modelData.id, "arm", !head.modelData.arm)
                                Rectangle { anchors.centerIn: parent; width: 9; height: 9; radius: 4.5; color: head.modelData.arm ? "#FFFFFF" : "#E5484D" } } }
                        // the track's level: a small fader with its meter underneath
                        Item { x: 56; y: 46; width: parent.width - 56 - 12; height: 10
                            Rectangle { y: 7; width: parent.width * Math.min(1, (Backend.levels[head.modelData.id] || 0)); height: 3; radius: 1.5; color: "#3DDC84"; opacity: 0.85 }
                            Meter { width: parent.width; height: 6; interactive: true; value: (head.modelData.volume + 60) / 66; onMoved: function (v) { Backend.setTrack(head.modelData.id, "volume", Math.round((v * 66 - 60) * 2) / 2) } } }
                        // which knob the automation lane draws
                        Pressable { objectName: "laneKnob"; visible: win.autoOn; x: 10; y: win.rowH + 2; width: parent.width - 20; height: 24; radius: 7; color: hovered ? Theme.t.hover : "transparent"
                            onClicked: { var p = mapToItem(laneMenuBox.parent, 0, height); win.laneMenu = { tid: head.modelData.id, x: p.x, y: p.y } }
                            Label { x: 6; width: parent.width - 24; anchors.verticalCenter: parent.verticalCenter; elide: Text.ElideRight; font.pixelSize: 10; secondary: true
                                text: { var l = Backend.automatable(head.modelData.id); for (var i = 0; i < l.length; i++) if (l[i].param === head.modelData.lane) return l[i].name; return "Volume" } }
                            Glyph { anchors { right: parent.right; rightMargin: 6; verticalCenter: parent.verticalCenter } name: "down"; size: 10 } } } } } }

        // the lanes
        Flickable { id: lanes; objectName: "lanes"; x: win.headW; y: 98; width: parent.width - win.headW - 8; height: parent.height - y - 8; clip: true
            contentWidth: Math.max(width, (Math.max(Backend.length, 32) + 16) * win.ppb); contentHeight: lanesCol.height + 30; boundsBehavior: Flickable.StopAtBounds
            WheelHandler { acceptedModifiers: Qt.ControlModifier; onWheel: function (e) { win.ppb = Math.max(8, Math.min(100, win.ppb * (e.angleDelta.y > 0 ? 1.15 : 1 / 1.15))) } }
            MouseArea { width: lanes.contentWidth; height: Math.max(lanes.height, lanesCol.height); onClicked: function (m) { Backend.selectRegion(""); Backend.seek(m.x / win.ppb) } }
            // bar lines
            Repeater { model: Math.max(0, Math.ceil(lanes.contentWidth / (win.ppb * win.bpb)))
                Rectangle { required property int index; x: index * win.bpb * win.ppb; width: 1; height: Math.max(lanes.height, lanesCol.height); color: Theme.t.text; opacity: 0.06 } }
            Column { id: lanesCol; width: lanes.contentWidth; spacing: 4
                Repeater { model: win.shown
                    Item { id: lane; required property var modelData; required property int index; width: lanes.contentWidth; height: win.laneH
                        // a stack shows where its tracks play
                        Repeater { model: lane.modelData.kind === "stack" ? lane.modelData.summary : []
                            Rectangle { required property var modelData; x: modelData[0] * win.ppb; y: 10; width: Math.max(2, modelData[1] * win.ppb - 1); height: win.rowH - 20; radius: 6
                                color: Qt.rgba(Qt.color(lane.modelData.colour).r, Qt.color(lane.modelData.colour).g, Qt.color(lane.modelData.colour).b, 0.16)
                                border.width: 1; border.color: Qt.rgba(Qt.color(lane.modelData.colour).r, Qt.color(lane.modelData.colour).g, Qt.color(lane.modelData.colour).b, 0.4) } }
                        DropArea { anchors.fill: parent; keys: ["loop"]
                            onDropped: function (d) { Backend.addLoop(d.source.loopId, lane.modelData.id, Math.max(0, d.x / win.ppb)) } }
                        MouseArea { width: parent.width; height: win.rowH; onDoubleClicked: function (m) { if (lane.modelData.kind !== "stack") Backend.addRegion(lane.modelData.id, m.x / win.ppb, win.bpb * 4) }
                            onClicked: function (m) { Backend.selectTrack(lane.modelData.id); Backend.selectRegion(""); win.selSection = ""; Backend.seek(m.x / win.ppb) } }
                        Repeater { model: lane.modelData.regions
                            Item { id: rg; required property var modelData
                                property real dx: 0
                                property real dw: 0
                                readonly property bool on: Backend.selectedRegion === modelData.id
                                readonly property color ink: lane.modelData.colour
                                x: modelData.start * win.ppb + dx; y: 3; z: on ? 3 : 1; width: modelData.length * modelData.loops * win.ppb + dw; height: win.rowH - 6
                                // repeats, drawn faintly after the first
                                Repeater { model: Math.max(0, rg.modelData.loops - 1)
                                    Rectangle { required property int index; x: (index + 1) * rg.modelData.length * win.ppb; width: rg.modelData.length * win.ppb - 1; height: rg.height; radius: 8
                                        color: Qt.rgba(rg.ink.r, rg.ink.g, rg.ink.b, 0.14); border.width: 1; border.color: Qt.rgba(rg.ink.r, rg.ink.g, rg.ink.b, 0.4) } }
                                Rectangle { id: body; width: rg.modelData.length * win.ppb + rg.dw; height: parent.height; radius: 8; clip: true
                                    color: Qt.rgba(rg.ink.r, rg.ink.g, rg.ink.b, rg.modelData.muted ? 0.1 : 0.3); border.width: rg.on ? 2 : 1; border.color: rg.on ? "#FFFFFF" : rg.ink
                                    Rectangle { width: parent.width; height: 15; color: Qt.rgba(rg.ink.r, rg.ink.g, rg.ink.b, 0.55)
                                        Label { x: 6; width: parent.width - 10; anchors.verticalCenter: parent.verticalCenter; elide: Text.ElideRight; text: rg.modelData.name; font.pixelSize: 9; color: "#FFFFFF"; font.weight: Font.DemiBold } }
                                    // notes, drawn small
                                    Repeater { model: rg.modelData.kind !== "audio" ? rg.modelData.notes : []
                                        Rectangle { required property var modelData; readonly property real span: Math.max(6, rg.modelData.high - rg.modelData.low)
                                            x: modelData[0] * win.ppb; width: Math.max(2, modelData[1] * win.ppb - 1); height: rg.modelData.kind === "drummer" ? 3 : 2
                                            y: 18 + (body.height - 24) * (1 - (modelData[2] - rg.modelData.low) / span); color: "#FFFFFF"; opacity: 0.85; radius: 1 } }
                                    // fades drawn as slopes, a badge for takes, ↺ when reversed
                                    Canvas { visible: rg.modelData.kind === "audio" && ((rg.modelData.fadeIn || 0) > 0 || (rg.modelData.fadeOut || 0) > 0); anchors.fill: parent; z: 2
                                        property var k: [rg.modelData.fadeIn, rg.modelData.fadeOut, width]; onKChanged: requestPaint()
                                        onPaint: { var c = getContext("2d"); c.reset(); var bps = win.song.tempo / 60, fi = (rg.modelData.fadeIn || 0) * bps * win.ppb, fo = (rg.modelData.fadeOut || 0) * bps * win.ppb
                                            c.strokeStyle = "#FFFFFF"; c.lineWidth = 1.2; c.beginPath(); c.moveTo(0, height); c.lineTo(fi, 15); c.moveTo(width - fo, 15); c.lineTo(width, height); c.stroke() } }
                                    Rectangle { visible: rg.modelData.takes > 0; anchors { right: parent.right; rightMargin: 4 } y: 17; z: 2; width: tkL.width + 8; height: 14; radius: 4; color: "#C0000000"
                                        Text { id: tkL; anchors.centerIn: parent; text: (rg.modelData.comp.length ? "Comp · " : "Take " + (rg.modelData.take + 1) + " / ") + rg.modelData.takes + (rg.modelData.comp.length ? " takes" : ""); font.pixelSize: 8; color: "#FFFFFF" } }
                                    Text { visible: !!rg.modelData.reverse || !!rg.modelData.transpose || !!rg.modelData.follow; x: 6; y: 17; z: 2; font.pixelSize: 9; color: "#FFFFFF"
                                        text: (rg.modelData.reverse ? "↺ " : "") + (rg.modelData.transpose ? (rg.modelData.transpose > 0 ? "+" : "") + rg.modelData.transpose + " st " : "") + (rg.modelData.follow ? "♩=" : "") }
                                    // a recording's wave
                                    Row { visible: rg.modelData.kind === "audio"; y: 16; height: parent.height - 18; width: parent.width
                                        Repeater { model: rg.modelData.peaks || []
                                            Rectangle { required property real modelData; width: Math.max(1, body.width / Math.max(1, (rg.modelData.peaks || []).length)); height: Math.max(1, modelData * parent.height)
                                                anchors.verticalCenter: parent.verticalCenter; color: "#FFFFFF"; opacity: 0.75 } } } }
                                MouseArea { anchors.fill: body; anchors.rightMargin: 8; preventStealing: true; cursorShape: Qt.OpenHandCursor
                                    property real x0: 0; property real y0: 0; property bool moved: false
                                    onPressed: function (m) { var p = mapToItem(lanes.contentItem, m.x, m.y); x0 = p.x; y0 = p.y; moved = false; win.selSection = ""; Backend.selectRegion(rg.modelData.id) }
                                    onPositionChanged: function (m) { var p = mapToItem(lanes.contentItem, m.x, m.y); rg.dx = p.x - x0; moved = Math.abs(rg.dx) > 3 || Math.abs(p.y - y0) > 12 }
                                    onReleased: function (m) {
                                        if (moved) { var p = mapToItem(lanes.contentItem, m.x, m.y), tr = win.rowOf(p.y)
                                            var at = Math.round((rg.modelData.start * win.ppb + rg.dx) / win.ppb * (win.ppb > 30 ? 1 : 1 / win.bpb)) / (win.ppb > 30 ? 1 : 1 / win.bpb)
                                            rg.dx = 0; Backend.moveRegion(rg.modelData.id, tr.id, Math.max(0, at)) }
                                        rg.dx = 0 }
                                    onDoubleClicked: { win.bench = "auto"; win.benchOpen = true } }
                                MouseArea { x: body.width - 8; width: 10; height: parent.height; cursorShape: Qt.SizeHorCursor; preventStealing: true
                                    property real x0: 0
                                    onPressed: function (m) { x0 = mapToItem(lanes.contentItem, m.x, 0).x; Backend.selectRegion(rg.modelData.id) }
                                    onPositionChanged: function (m) { rg.dw = mapToItem(lanes.contentItem, m.x, 0).x - x0 }
                                    onReleased: { var len = Math.max(win.ppb > 30 ? 1 : win.bpb, Math.round((rg.modelData.length * win.ppb + rg.dw) / win.ppb / (win.ppb > 30 ? 1 : win.bpb)) * (win.ppb > 30 ? 1 : win.bpb)); rg.dw = 0; Backend.resizeRegion(rg.modelData.id, len) } } } }
                        // automation: any knob as points on a line; click adds, drag moves, double-click removes
                        Item { id: autoLane; objectName: "autoLane"; visible: win.autoOn; y: win.rowH; width: parent.width; height: 28
                            readonly property string param: lane.modelData.lane || "volume"
                            readonly property var info: { var l = Backend.automatable(lane.modelData.id); for (var i = 0; i < l.length; i++) if (l[i].param === autoLane.param) return l[i]; return { low: -60, high: 6, value: lane.modelData.volume } }
                            readonly property var pts: (lane.modelData.automation && lane.modelData.automation[param]) || []
                            function yOf(v) { return 2 + (1 - (v - info.low) / (info.high - info.low)) * (height - 4) }
                            function vOf(y) { return Math.max(info.low, Math.min(info.high, info.low + (1 - (y - 2) / (height - 4)) * (info.high - info.low))) }
                            Rectangle { anchors.fill: parent; color: Theme.t.dark ? "#0AFFFFFF" : "#06000000"; radius: 6 }
                            Canvas { id: autoLine; anchors.fill: parent; property var p: [autoLane.pts, autoLane.info]; onPChanged: requestPaint()
                                onPaint: { var c = getContext("2d"); c.reset(); c.strokeStyle = lane.modelData.colour; c.lineWidth = 1.5; c.beginPath()
                                    var p = autoLane.pts; if (!p.length) { var y = autoLane.yOf(autoLane.info.value); c.moveTo(0, y); c.lineTo(width, y) }
                                    else { c.moveTo(0, autoLane.yOf(p[0][1])); for (var i = 0; i < p.length; i++) c.lineTo(p[i][0] * win.ppb, autoLane.yOf(p[i][1])); c.lineTo(width, autoLane.yOf(p[p.length - 1][1])) }
                                    c.stroke() } }
                            MouseArea { anchors.fill: parent; onClicked: function (m) { var p = autoLane.pts.slice(); p.push([m.x / win.ppb, autoLane.vOf(m.y)]); Backend.setAutomation(lane.modelData.id, autoLane.param, p) } }
                            Repeater { model: autoLane.pts
                                Rectangle { required property var modelData; required property int index; x: modelData[0] * win.ppb - 5; y: autoLane.yOf(modelData[1]) - 5; width: 10; height: 10; radius: 5
                                    color: "#FFFFFF"; border.width: 2; border.color: lane.modelData.colour
                                    MouseArea { anchors.fill: parent; anchors.margins: -4; preventStealing: true
                                        onPositionChanged: function (m) { var q = mapToItem(autoLane, m.x, m.y), p = autoLane.pts.slice(); p[index] = [Math.max(0, q.x / win.ppb), autoLane.vOf(q.y)]; Backend.setAutomation(lane.modelData.id, autoLane.param, p) }
                                        onDoubleClicked: { var p = autoLane.pts.slice(); p.splice(index, 1); Backend.setAutomation(lane.modelData.id, autoLane.param, p) } } } } } } } }
            // the playhead
            Rectangle { objectName: "playhead"; x: Backend.position * win.ppb - 1; width: 2; height: Math.max(lanes.height, lanesCol.height); color: Backend.recording ? "#E5484D" : "#FFFFFF"; z: 20; opacity: 0.9 } }
        Rectangle { visible: Backend.hasSong; x: win.headW + Backend.position * win.ppb - lanes.contentX - 6; y: 84; width: 12; height: 12; radius: 3; rotation: 45; color: Backend.recording ? "#E5484D" : "#FFFFFF" }
        Label { visible: Backend.tracks.length === 0; anchors.centerIn: parent; secondary: true; text: "Add an instrument, a drummer or a microphone above, or drag in a loop." } }

    // ================================================================ the bench
    Rectangle { id: benchBox; objectName: "bench"; visible: Backend.hasSong && win.benchOpen; x: 12; width: arrange.width; height: Math.min(330, win.height * 0.38); y: parent.height - height - 12; radius: 18
        color: Theme.t.island; border.width: 1; border.color: Theme.t.islandLine; clip: true
        Row { id: benchTabs; x: 12; y: 8; spacing: 2; height: 30
            Repeater { model: [["roll", "Piano Roll"], ["drums", "Drum Grid"], ["drummer", "Drummer"], ["region", "Region"], ["smart", "Smart Controls"], ["mixer", "Mixer"], ["keys", "Keyboard"]]
                Seg { required property var modelData; text: modelData[1]; on: win.benchKind === modelData[0]; onClicked: win.bench = modelData[0] } }
            IslandGap {}
            Seg { icon: "down"; tip: "Hide"; onClicked: win.benchOpen = false }
            Label { anchors.verticalCenter: parent.verticalCenter; leftPadding: 10; secondary: true; font.pixelSize: 11
                text: win.selTrack ? win.selTrack.name + (win.reg.id ? "  ·  " + (win.reg.name || "Region") : "") : "" } }

        // ---- the piano roll
        Item { id: roll; objectName: "pianoRoll"; visible: win.benchKind === "roll"; x: 12; y: 46; width: parent.width - 24; height: parent.height - 56
            readonly property var notes: win.reg.notes || []
            readonly property int topPitch: 96
            readonly property real nh: 11
            readonly property real bpp: win.ppb * 2.2                         // the roll zooms closer than the arrangement
            Label { visible: !win.reg.id || win.reg.trackKind === "audio"; anchors.centerIn: parent; secondary: true; text: "Pick a region on an instrument track (or double-click a lane to make one) to write its notes here." }
            Row { visible: !!win.reg.id; anchors.right: parent.right; y: -38; spacing: 3; height: 30
                Repeater { model: [[1, "1/4"], [0.5, "1/8"], [0.25, "1/16"], [1 / 3, "1/8T"]]
                    Seg { required property var modelData; text: modelData[1]; on: Math.abs(win.grid - modelData[0]) < 1e-3; onClicked: win.grid = modelData[0] } }
                IslandGap {}
                Seg { text: "Quantize"; onClicked: Backend.quantize(win.reg.id, win.grid, 1.0) }
                Seg { text: "−12"; onClicked: Backend.transpose(win.reg.id, -12) }
                Seg { text: "+12"; onClicked: Backend.transpose(win.reg.id, 12) } }
            Flickable { id: rollView; visible: !!win.reg.id && win.reg.trackKind !== "audio"; anchors.fill: parent; clip: true; boundsBehavior: Flickable.StopAtBounds
                contentWidth: 50 + (win.reg.length || 16) * roll.bpp + 40; contentHeight: (roll.topPitch - 24) * roll.nh
                Component.onCompleted: contentY = (roll.topPitch - 76) * roll.nh
                // the keys down the left
                Column { x: rollView.contentX; z: 3
                    Repeater { model: roll.topPitch - 24
                        Rectangle { required property int index; readonly property int pitch: roll.topPitch - 1 - index; readonly property bool black: [1, 3, 6, 8, 10].indexOf(pitch % 12) >= 0
                            width: 48; height: roll.nh; color: black ? "#1C1C22" : "#ECECEF"; border.width: 1; border.color: "#33000000"
                            Text { visible: parent.pitch % 12 === 0; anchors { right: parent.right; rightMargin: 3; verticalCenter: parent.verticalCenter } text: Backend.noteNames[parent.pitch]; font.pixelSize: 8; color: "#555" }
                            MouseArea { anchors.fill: parent; onPressed: Backend.noteOn(parent.pitch, 100); onReleased: Backend.noteOff(parent.pitch) } } } }
                // the grid
                Item { x: 50; width: (win.reg.length || 16) * roll.bpp; height: rollView.contentHeight
                    Repeater { model: roll.topPitch - 24
                        Rectangle { required property int index; y: index * roll.nh; width: parent.width; height: roll.nh; color: [1, 3, 6, 8, 10].indexOf((roll.topPitch - 1 - index) % 12) >= 0 ? (Theme.t.dark ? "#0DFFFFFF" : "#08000000") : "transparent" } }
                    Repeater { model: Math.ceil((win.reg.length || 16) / win.grid)
                        Rectangle { required property int index; readonly property real b: index * win.grid; x: b * roll.bpp; width: 1; height: parent.height; color: Theme.t.text
                            opacity: Math.abs(b % win.bpb) < 1e-3 ? 0.25 : Math.abs(b % 1) < 1e-3 ? 0.12 : 0.05 } }
                    MouseArea { anchors.fill: parent
                        onClicked: function (m) { var t = Math.floor(m.x / roll.bpp / win.grid) * win.grid, p = roll.topPitch - 1 - Math.floor(m.y / roll.nh); Backend.addNote(win.reg.id, t, p, win.grid, 100) } }
                    Repeater { model: roll.notes
                        Rectangle { id: nt; required property var modelData
                            property real dx: 0; property real dy: 0; property real dw: 0
                            x: modelData.t * roll.bpp + dx; y: (roll.topPitch - 1 - modelData.p) * roll.nh + dy + 1; width: Math.max(4, modelData.d * roll.bpp + dw - 1); height: roll.nh - 2; radius: 3
                            color: Qt.rgba(win.hot.r, win.hot.g, win.hot.b, 0.45 + 0.55 * modelData.v / 127); border.width: 1; border.color: "#33000000"
                            MouseArea { anchors.fill: parent; anchors.rightMargin: 6; preventStealing: true; cursorShape: Qt.SizeAllCursor
                                property point p0
                                onPressed: function (m) { p0 = mapToItem(rollView.contentItem, m.x, m.y) }
                                onPositionChanged: function (m) { var p = mapToItem(rollView.contentItem, m.x, m.y); nt.dx = p.x - p0.x; nt.dy = Math.round((p.y - p0.y) / roll.nh) * roll.nh }
                                onReleased: { var t = Math.max(0, Math.round((nt.modelData.t + nt.dx / roll.bpp) / win.grid) * win.grid), p = nt.modelData.p - Math.round(nt.dy / roll.nh)
                                    nt.dx = 0; nt.dy = 0; if (t !== nt.modelData.t || p !== nt.modelData.p) Backend.moveNote(win.reg.id, nt.modelData.i, t, p) }
                                onDoubleClicked: Backend.removeNote(win.reg.id, nt.modelData.i) }
                            MouseArea { anchors.right: parent.right; width: 7; height: parent.height; cursorShape: Qt.SizeHorCursor; preventStealing: true
                                property real x0: 0
                                onPressed: function (m) { x0 = mapToItem(rollView.contentItem, m.x, 0).x }
                                onPositionChanged: function (m) { nt.dw = mapToItem(rollView.contentItem, m.x, 0).x - x0 }
                                onReleased: { var d = Math.max(win.grid, Math.round((nt.modelData.d + nt.dw / roll.bpp) / win.grid) * win.grid); nt.dw = 0; Backend.resizeNote(win.reg.id, nt.modelData.i, d) } } } }
                    // where the song is
                    Rectangle { visible: win.reg.id !== undefined; x: (Backend.position - (win.reg.start || 0)) * roll.bpp; width: 2; height: parent.height; color: "#FFFFFF"; opacity: 0.7 } } } }


        // ---- the region: a recording's gain, fades, reverse, transpose and tempo; takes and comps
        Flickable { id: regionPane; objectName: "regionPane"; visible: win.benchKind === "region"; x: 16; y: 46; width: parent.width - 32; height: parent.height - 54; clip: true
            contentWidth: regionRow.width; boundsBehavior: Flickable.StopAtBounds
            Label { visible: !win.reg.id; anchors.centerIn: parent; secondary: true; text: "Pick a region to shape it here." }
            Row { id: regionRow; visible: !!win.reg.id; spacing: 18; height: parent.height
                Column { visible: win.reg.kind === "audio"; width: 230; spacing: 6
                    Heading { text: "THE RECORDING" }
                    Label { text: "Gain  " + ((win.reg.gain || 0) > 0 ? "+" : "") + (win.reg.gain || 0).toFixed(1) + " dB"; font.pixelSize: 11 }
                    Meter { objectName: "gainMeter"; width: 220; interactive: true; value: ((win.reg.gain || 0) + 30) / 42; onMoved: function (v) { Backend.setRegion(win.reg.id, "gain", Math.round((v * 42 - 30) * 2) / 2) } }
                    Label { text: "Fade in  " + (win.reg.fadeIn || 0).toFixed(2) + " s     Fade out  " + (win.reg.fadeOut || 0).toFixed(2) + " s"; font.pixelSize: 11 }
                    Row { spacing: 10
                        Meter { width: 105; interactive: true; value: Math.min(1, (win.reg.fadeIn || 0) / Math.max(0.01, Math.min(4, win.reg.span || 1))); onMoved: function (v) { Backend.setRegion(win.reg.id, "fadeIn", v * Math.min(4, win.reg.span || 1)) } }
                        Meter { width: 105; interactive: true; value: Math.min(1, (win.reg.fadeOut || 0) / Math.max(0.01, Math.min(4, win.reg.span || 1))); onMoved: function (v) { Backend.setRegion(win.reg.id, "fadeOut", v * Math.min(4, win.reg.span || 1)) } } }
                    Row { spacing: 8; height: 30
                        Toggle { objectName: "reverseToggle"; anchors.verticalCenter: parent.verticalCenter; on: !!win.reg.reverse; onToggled: function (v) { Backend.setRegion(win.reg.id, "reverse", v) } }
                        Label { anchors.verticalCenter: parent.verticalCenter; text: "Reverse"; font.pixelSize: 12 } } }
                Column { visible: win.reg.kind === "audio"; width: 230; spacing: 6
                    Heading { text: "PITCH AND TIME" }
                    Row { spacing: 4; height: 30
                        Seg { text: "−12"; onClicked: Backend.setRegion(win.reg.id, "transpose", (win.reg.transpose || 0) - 12) }
                        Seg { objectName: "transposeDown"; text: "−1"; onClicked: Backend.setRegion(win.reg.id, "transpose", (win.reg.transpose || 0) - 1) }
                        Label { objectName: "transposeValue"; width: 56; horizontalAlignment: Text.AlignHCenter; anchors.verticalCenter: parent.verticalCenter; font.family: Theme.t.fontMono
                            text: ((win.reg.transpose || 0) > 0 ? "+" : "") + (win.reg.transpose || 0) + " st" }
                        Seg { objectName: "transposeUp"; text: "+1"; onClicked: Backend.setRegion(win.reg.id, "transpose", (win.reg.transpose || 0) + 1) }
                        Seg { text: "+12"; onClicked: Backend.setRegion(win.reg.id, "transpose", (win.reg.transpose || 0) + 12) } }
                    Row { spacing: 8; height: 30
                        Toggle { objectName: "followToggle"; anchors.verticalCenter: parent.verticalCenter; on: !!win.reg.follow; onToggled: function (v) { Backend.setRegion(win.reg.id, "follow", v) } }
                        Label { anchors.verticalCenter: parent.verticalCenter; text: "Follow the song's tempo"; font.pixelSize: 12 } }
                    Label { width: parent.width; wrapMode: Text.WordWrap; secondary: true; font.pixelSize: 10
                        text: "Transposing keeps the timing; following the tempo keeps the pitch. Recorded at " + Math.round(win.reg.srcTempo || win.song.tempo) + " BPM." } }
                // takes: one row each; click to play that take, drag across one to use that part (a comp)
                Column { objectName: "takesPanel"; visible: (win.reg.takeViews || []).length > 0; width: Math.max(420, regionPane.width - (win.reg.kind === "audio" ? 520 : 20)); spacing: 4
                    Row { spacing: 8; height: 24
                        Heading { anchors.verticalCenter: parent.verticalCenter; text: "TAKES" }
                        Label { anchors.verticalCenter: parent.verticalCenter; secondary: true; font.pixelSize: 10; text: "Click a take to hear it; drag across the best part of each to comp them." }
                        Seg { objectName: "flattenTakes"; text: "Keep This and Flatten"; onClicked: Backend.flattenTakes(win.reg.id) } }
                    Repeater { model: win.reg.takeViews || []
                        Rectangle { id: tkRow; required property var modelData; required property int index; objectName: "take" + index; width: parent.width; height: 34; radius: 8
                            readonly property bool live: !(win.reg.comp || []).length && win.reg.take === index
                            color: live ? Qt.rgba(win.hot.r, win.hot.g, win.hot.b, 0.22) : (Theme.t.dark ? "#0CFFFFFF" : "#06000000"); border.width: live ? 1 : 0; border.color: win.hot
                            Label { x: 8; width: 54; anchors.verticalCenter: parent.verticalCenter; text: tkRow.modelData.name; font.pixelSize: 10; font.weight: Font.DemiBold }
                            Item { id: tkStrip; objectName: "takeStrip"; x: 66; width: parent.width - 74; height: parent.height
                                readonly property real bw: width / Math.max(1, win.reg.length || 4)
                                // the parts of this take the comp uses
                                Repeater { model: (win.reg.comp || []).filter(function (c) { return c[2] === tkRow.index })
                                    Rectangle { required property var modelData; x: modelData[0] * tkStrip.bw; width: (modelData[1] - modelData[0]) * tkStrip.bw; height: parent.height; color: Qt.rgba(win.hot.r, win.hot.g, win.hot.b, 0.4); radius: 4 } }
                                Row { visible: win.reg.kind === "audio"; anchors.verticalCenter: parent.verticalCenter; height: parent.height - 8; width: parent.width
                                    Repeater { model: tkRow.modelData.peaks || []
                                        Rectangle { required property real modelData; width: Math.max(1, tkStrip.width / Math.max(1, (tkRow.modelData.peaks || []).length)); height: Math.max(1, modelData * parent.height)
                                            anchors.verticalCenter: parent.verticalCenter; color: Theme.t.text; opacity: 0.6 } } }
                                Repeater { model: win.reg.kind !== "audio" ? (tkRow.modelData.notes || []) : []
                                    Rectangle { required property var modelData; readonly property real span: Math.max(6, tkRow.modelData.high - tkRow.modelData.low)
                                        x: modelData[0] * tkStrip.bw; width: Math.max(2, modelData[1] * tkStrip.bw - 1); height: 2; y: 4 + (tkStrip.height - 10) * (1 - (modelData[2] - tkRow.modelData.low) / span); color: Theme.t.text; opacity: 0.7 } }
                                Rectangle { id: swipe; visible: false; height: parent.height; color: "#55FFFFFF"; radius: 4 }
                                MouseArea { anchors.fill: parent; preventStealing: true; property real x0: 0; property bool dragged: false
                                    onPressed: function (m) { x0 = m.x; dragged = false; swipe.x = m.x; swipe.width = 0 }
                                    onPositionChanged: function (m) { dragged = Math.abs(m.x - x0) > 4; swipe.visible = dragged; swipe.x = Math.min(x0, m.x); swipe.width = Math.abs(m.x - x0) }
                                    onReleased: function (m) { swipe.visible = false
                                        if (dragged) Backend.compTake(win.reg.id, Math.min(x0, m.x) / tkStrip.bw, Math.max(x0, m.x) / tkStrip.bw, tkRow.index)
                                        else Backend.chooseTake(win.reg.id, tkRow.index) } } } } } }
                Column { visible: win.reg.kind !== "audio" && !(win.reg.takeViews || []).length; width: 320; spacing: 6
                    Heading { text: "TAKES" }
                    Label { width: parent.width; wrapMode: Text.WordWrap; secondary: true; font.pixelSize: 11
                        text: "Turn the cycle on (C) and record: every time round becomes a take. Pick the best one, or comp the best parts of each." } } } }

        // ---- the drum grid
        Item { id: drumGrid; objectName: "drumGrid"; visible: win.benchKind === "drums"; x: 12; y: 46; width: parent.width - 24; height: parent.height - 56
            readonly property int steps: Math.round((win.reg.length || 4) * 4)
            readonly property real cw: Math.max(14, Math.min(34, (width - 120) / Math.max(1, steps)))
            Label { visible: !win.reg.id; anchors.centerIn: parent; secondary: true; text: "Pick a region on a drum track to program its beat. Drop a sound on a drum's name to play your own." }
            Flickable { visible: !!win.reg.id; anchors.fill: parent; contentWidth: 120 + drumGrid.steps * drumGrid.cw; contentHeight: Backend.kitRows.length * 20; clip: true; boundsBehavior: Flickable.StopAtBounds
                Column {
                    Repeater { model: Backend.kitRows
                        Row { id: dRow; required property int modelData; height: 20
                            readonly property string own: (win.selTrack && win.selTrack.instrument && win.selTrack.instrument.pads && win.selTrack.instrument.pads[String(modelData)]) || ""
                            Pressable { width: 112; height: 18; radius: 5; color: padDrop.containsDrag ? Qt.rgba(win.hot.r, win.hot.g, win.hot.b, 0.35) : hovered ? Theme.t.hover : "transparent"
                                onClicked: { Backend.noteOn(dRow.modelData, 110); Backend.noteOff(dRow.modelData) }
                                Label { x: 6; width: 86; anchors.verticalCenter: parent.verticalCenter; elide: Text.ElideRight; font.pixelSize: 10; color: dRow.own ? win.hot : Theme.t.text
                                    text: (Backend.drumNames[String(dRow.modelData)] || dRow.modelData) + (dRow.own ? " ●" : "") }
                                Pressable { visible: dRow.own !== ""; anchors { right: parent.right; rightMargin: 2; verticalCenter: parent.verticalCenter } width: 16; height: 16; radius: 4
                                    onClicked: Backend.clearPad(win.selTrack.id, dRow.modelData); Glyph { anchors.centerIn: parent; name: "x"; size: 8 } }
                                // drop a sound of your own on a drum
                                DropArea { id: padDrop; anchors.fill: parent; keys: ["text/uri-list"]
                                    onDropped: function (d) { if (d.hasUrls && win.selTrack) { Backend.setPad(win.selTrack.id, dRow.modelData, d.urls[0]); d.accept() } } } }
                            Item { width: 8; height: 1 }
                            Repeater { model: drumGrid.steps
                                Rectangle { required property int index; readonly property bool hit: (win.reg.notes || []).some(function (n) { return n.p === dRow.modelData && Math.abs(n.t - index / 4) < 1e-3 })
                                    width: drumGrid.cw - 2; height: 17; radius: 4
                                    color: hit ? win.hot : (Math.floor(index / 4) % 2 ? (Theme.t.dark ? "#16FFFFFF" : "#0E000000") : (Theme.t.dark ? "#0AFFFFFF" : "#06000000"))
                                    border.width: Math.floor((Backend.position - (win.reg.start || 0)) * 4) === index ? 1 : 0; border.color: "#FFFFFF"
                                    MouseArea { anchors.fill: parent; onClicked: Backend.toggleStep(win.reg.id, dRow.modelData, index) } } } } } } } }

        // ---- the drummer
        Item { id: drummerPane; objectName: "drummerPane"; visible: win.benchKind === "drummer"; x: 16; y: 48; width: parent.width - 32; height: parent.height - 60
            readonly property var d: win.selTrack && win.selTrack.drummer ? win.selTrack.drummer : ({ style: "pop", complexity: 0.5, loudness: 0.5, fills: 0.4 })
            Label { visible: !win.selTrack || win.selTrack.kind !== "drummer"; anchors.centerIn: parent; secondary: true; text: "Pick a drummer track to set how it plays." }
            Row { visible: !!win.selTrack && win.selTrack.kind === "drummer"; spacing: 24; height: parent.height
                // the pad: simple to complex across, soft to loud up
                Rectangle { id: pad; objectName: "drummerPad"; width: Math.min(360, parent.height * 1.5); height: parent.height - 8; radius: 14
                    gradient: Gradient { orientation: Gradient.Horizontal; GradientStop { position: 0; color: Qt.rgba(1, 0.77, 0.24, 0.10) } GradientStop { position: 1; color: Qt.rgba(1, 0.42, 0.24, 0.30) } }
                    border.width: 1; border.color: Theme.t.islandLine
                    Label { x: 10; anchors.bottom: parent.bottom; anchors.bottomMargin: 6; text: "Simple"; font.pixelSize: 10; secondary: true }
                    Label { anchors { right: parent.right; rightMargin: 10; bottom: parent.bottom; bottomMargin: 6 } text: "Complex"; font.pixelSize: 10; secondary: true }
                    Label { x: 10; y: 6; text: "Loud"; font.pixelSize: 10; secondary: true }
                    Label { x: 10; anchors.verticalCenter: parent.verticalCenter; text: "Soft"; font.pixelSize: 10; secondary: true; anchors.verticalCenterOffset: parent.height * 0.4 - 10; visible: false }
                    Rectangle { x: drummerPane.d.complexity * (pad.width - 26); y: (1 - drummerPane.d.loudness) * (pad.height - 26); width: 26; height: 26; radius: 13; color: "#FFC53D"; border.width: 3; border.color: "#FFFFFF" }
                    MouseArea { anchors.fill: parent; preventStealing: true
                        function put(m) { var cx = Math.max(0, Math.min(1, (m.x - 13) / (pad.width - 26))), cy = Math.max(0, Math.min(1, 1 - (m.y - 13) / (pad.height - 26)))
                            Backend.setDrummer(win.selTrack.id, "complexity", cx); Backend.setDrummer(win.selTrack.id, "loudness", cy) }
                        onPressed: function (m) { put(m) } onReleased: function (m) { put(m) } } }
                Column { width: parent.width - pad.width - 24; spacing: 10
                    Label { text: "STYLE"; font.pixelSize: 10; font.weight: Font.Bold; font.letterSpacing: 1.2; secondary: true }
                    Flow { width: parent.width; spacing: 4
                        Repeater { model: [["pop", "Pop"], ["rock", "Rock"], ["hiphop", "Hip Hop"], ["house", "House"], ["funk", "Funk"], ["trap", "Trap"]]
                            Seg { required property var modelData; anchors.verticalCenter: undefined; text: modelData[1]; on: drummerPane.d.style === modelData[0]; onClicked: Backend.setDrummer(win.selTrack.id, "style", modelData[0]) } } }
                    Label { text: "FILLS"; font.pixelSize: 10; font.weight: Font.Bold; font.letterSpacing: 1.2; secondary: true }
                    Meter { width: Math.min(300, parent.width); interactive: true; value: drummerPane.d.fills; onMoved: function (v) { Backend.setDrummer(win.selTrack.id, "fills", v) } }
                    Label { text: "KIT"; font.pixelSize: 10; font.weight: Font.Bold; font.letterSpacing: 1.2; secondary: true }
                    Flow { width: parent.width; spacing: 4
                        Repeater { model: [["drums", "Studio"], ["electronic", "Electronic"], ["vintage", "Vintage"]]
                            Seg { required property var modelData; anchors.verticalCenter: undefined; text: modelData[1]; on: win.selTrack && win.selTrack.instrument && win.selTrack.instrument.id === modelData[0]
                                onClicked: Backend.setInstrument(win.selTrack.id, modelData[0]) } } }
                    Label { width: parent.width; wrapMode: Text.WordWrap; secondary: true; font.pixelSize: 11
                        text: "Drag on the pad: further right plays busier (ghost notes, open hats, extra kicks), higher hits harder. A fill comes every fourth bar. Its regions change as you do; edit one in the drum grid to make it yours." } } } }

        // ---- Smart Controls: the instrument, its sound, its effects
        Flickable { id: smartPane; objectName: "smartPane"; visible: win.benchKind === "smart"; x: 16; y: 46; width: parent.width - 32; height: parent.height - 54; clip: true
            contentWidth: smartRow.width; boundsBehavior: Flickable.StopAtBounds
            property var controls: win.selTrack ? Backend.smartControls(win.selTrack.id) : []
            property var fx: win.selTrack ? Backend.effectsOf(win.selTrack.id) : []
            Connections { target: Backend; function onChanged() { if (win.selTrack) { smartPane.controls = Backend.smartControls(win.selTrack.id); smartPane.fx = Backend.effectsOf(win.selTrack.id) } } }
            Row { id: smartRow; spacing: 18; height: parent.height
                Column { visible: !!win.selTrack && win.selTrack.kind !== "audio" && win.selTrack.kind !== "stack"; width: 200; spacing: 8
                    readonly property bool sampler: !!(win.selTrack && win.selTrack.instrument && win.selTrack.instrument.id === "sampler")
                    Label { width: parent.width; elide: Text.ElideRight; text: win.selTrack ? win.selTrack.instName : ""; font.pixelSize: 15; font.weight: Font.DemiBold }
                    Label { text: win.selTrack ? win.selTrack.family : ""; secondary: true; font.pixelSize: 11 }
                    Btn { text: "Change Instrument…"; onClicked: win.drawer = "library" }
                    // the sampler: its root note and how it plays
                    Row { visible: parent.sampler; spacing: 4; height: 28
                        Label { anchors.verticalCenter: parent.verticalCenter; text: "Its note"; font.pixelSize: 11; secondary: true }
                        Seg { text: "−"; onClicked: Backend.setSampler(win.selTrack.id, "root", win.selTrack.instrument.root - 1) }
                        Label { objectName: "samplerRoot"; anchors.verticalCenter: parent.verticalCenter; width: 40; horizontalAlignment: Text.AlignHCenter; font.family: Theme.t.fontMono
                            text: parent.parent.sampler ? Backend.noteNames[win.selTrack.instrument.root] : "" }
                        Seg { text: "+"; onClicked: Backend.setSampler(win.selTrack.id, "root", win.selTrack.instrument.root + 1) } }
                    Chips { visible: parent.sampler; width: parent.width; items: [["held", "Held"], ["oneshot", "One shot"]]; current: parent.sampler ? (win.selTrack.instrument.mode || "held") : ""
                        onChosen: function (id) { Backend.setSamplerMode(win.selTrack.id, id) } }
                    Rectangle { width: parent.width; height: 46; radius: 10; color: dropS.containsDrag ? Qt.rgba(win.hot.r, win.hot.g, win.hot.b, 0.25) : "transparent"
                        border.width: 1; border.color: dropS.containsDrag ? win.hot : Theme.t.islandLine
                        Label { anchors.fill: parent; anchors.margins: 6; wrapMode: Text.WordWrap; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter; font.pixelSize: 10; secondary: true
                            text: "Drop a sound here to play it across the keys (a sampler)" }
                        DropArea { id: dropS; anchors.fill: parent; keys: ["text/uri-list"]; onDropped: function (d) { if (d.hasUrls) { Backend.makeSampler(win.selTrack.id, d.urls[0]); d.accept() } } } } }
                // MIDI effects: chords and the arpeggiator
                Column { objectName: "midiFxPane"; visible: !!win.selTrack && win.selTrack.kind === "instrument" && win.selTrack.family !== "Drums"; width: 300; spacing: 5
                    readonly property var arp: (win.selTrack && win.selTrack.midiFx && win.selTrack.midiFx.arp) || ({ on: false, mode: "up", rate: 0.25, octaves: 1 })
                    readonly property var chord: (win.selTrack && win.selTrack.midiFx && win.selTrack.midiFx.chord) || ({ on: false, shape: "major" })
                    Row { spacing: 8; height: 26
                        Toggle { objectName: "arpToggle"; anchors.verticalCenter: parent.verticalCenter; on: !!parent.parent.arp.on; onToggled: function (v) { Backend.setMidiFx(win.selTrack.id, "arp", "on", v) } }
                        Heading { anchors.verticalCenter: parent.verticalCenter; text: "ARPEGGIATOR" } }
                    Chips { visible: !!parent.arp.on; width: parent.width; items: Backend.arpModes.map(function (m) { return [m.id, m.name] }); current: parent.arp.mode || "up"
                        onChosen: function (id) { Backend.setMidiFx(win.selTrack.id, "arp", "mode", id) } }
                    Chips { visible: !!parent.arp.on; width: parent.width; items: [[0.5, "1/8"], [0.25, "1/16"], [0.125, "1/32"], [1 / 3, "1/8T"]]; current: String(parent.arp.rate || 0.25)
                        onChosen: function (id) { Backend.setMidiFx(win.selTrack.id, "arp", "rate", parseFloat(id)) } }
                    Chips { visible: !!parent.arp.on; width: parent.width; items: [[1, "1 octave"], [2, "2"], [3, "3"]]; current: String(parent.arp.octaves || 1)
                        onChosen: function (id) { Backend.setMidiFx(win.selTrack.id, "arp", "octaves", parseInt(id)) } }
                    Row { spacing: 8; height: 26
                        Toggle { objectName: "chordToggle"; anchors.verticalCenter: parent.verticalCenter; on: !!parent.parent.chord.on; onToggled: function (v) { Backend.setMidiFx(win.selTrack.id, "chord", "on", v) } }
                        Heading { anchors.verticalCenter: parent.verticalCenter; text: "CHORD TRIGGER" } }
                    Chips { visible: !!parent.chord.on; width: parent.width; items: Backend.chordShapes.map(function (m) { return [m.id, m.name] }); current: parent.chord.shape || "major"
                        onChosen: function (id) { Backend.setMidiFx(win.selTrack.id, "chord", "shape", id) } }
                    Label { visible: !parent.arp.on && !parent.chord.on; width: parent.width; wrapMode: Text.WordWrap; secondary: true; font.pixelSize: 10
                        text: "One finger plays a chord; held notes play one at a time, in time." } }
                // the instrument's own knobs
                Repeater { model: smartPane.controls
                    Column { required property var modelData; width: 86; spacing: 6
                        Canvas { id: knobC; width: 64; height: 64; anchors.horizontalCenter: parent.horizontalCenter
                            readonly property real v: (modelData.value - modelData.low) / Math.max(1e-6, modelData.high - modelData.low)
                            onVChanged: requestPaint()
                            onPaint: { var c = getContext("2d"); c.reset(); var a0 = Math.PI * 0.75, a1 = Math.PI * 2.25
                                c.lineWidth = 6; c.lineCap = "round"; c.strokeStyle = Theme.t.dark ? "rgba(255,255,255,0.1)" : "rgba(0,0,0,0.1)"; c.beginPath(); c.arc(32, 32, 26, a0, a1); c.stroke()
                                c.strokeStyle = win.hot; c.beginPath(); c.arc(32, 32, 26, a0, a0 + (a1 - a0) * Math.max(0, Math.min(1, v))); c.stroke()
                                c.fillStyle = Theme.t.dark ? "#2A2D33" : "#FFFFFF"; c.beginPath(); c.arc(32, 32, 18, 0, Math.PI * 2); c.fill() }
                            MouseArea { anchors.fill: parent; preventStealing: true; cursorShape: Qt.SizeVerCursor; property real y0: 0; property real v0: 0
                                onPressed: function (m) { y0 = m.y; v0 = knobC.v }
                                onPositionChanged: function (m) { var v = Math.max(0, Math.min(1, v0 + (y0 - m.y) / 140)); Backend.setSmart(win.selTrack.id, modelData.key, modelData.low + v * (modelData.high - modelData.low)) } } }
                        Label { anchors.horizontalCenter: parent.horizontalCenter; text: modelData.name; font.pixelSize: 11 } } }
                Rectangle { width: 1; height: parent.height - 10; color: Theme.t.islandLine; visible: !!win.selTrack }
                // sends
                Column { visible: !!win.selTrack; width: 150; spacing: 6
                    Label { text: "SPACE"; font.pixelSize: 10; font.weight: Font.Bold; font.letterSpacing: 1.2; secondary: true }
                    Label { text: "Reverb"; font.pixelSize: 11 }
                    Meter { width: 140; interactive: true; value: win.selTrack ? win.selTrack.reverb : 0; onMoved: function (v) { Backend.setTrack(win.selTrack.id, "reverb", v) } }
                    Label { text: "Echo"; font.pixelSize: 11 }
                    Meter { width: 140; interactive: true; value: win.selTrack ? win.selTrack.echo : 0; onMoved: function (v) { Backend.setTrack(win.selTrack.id, "echo", v) } }
                    Label { text: "Pan"; font.pixelSize: 11 }
                    Meter { width: 140; interactive: true; value: win.selTrack ? (win.selTrack.pan + 1) / 2 : 0.5; onMoved: function (v) { Backend.setTrack(win.selTrack.id, "pan", Math.abs(v - 0.5) < 0.04 ? 0 : v * 2 - 1) } }
                    // where it goes: the master, or a stack
                    Heading { visible: !!win.selTrack && win.selTrack.kind !== "stack" && Backend.stacks.length > 0; text: "PLAYS INTO"; topPadding: 4 }
                    Chips { objectName: "outputChips"; visible: !!win.selTrack && win.selTrack.kind !== "stack" && Backend.stacks.length > 0; width: 150
                        items: [["", "Master"]].concat(Backend.stacks.map(function (x) { return [x.id, x.name] })); current: win.selTrack ? win.selTrack.output : ""
                        onChosen: function (id) { Backend.setOutput(win.selTrack.id, id) } }
                    Seg { objectName: "duckBtn"; visible: !!win.selTrack && win.selTrack.kind !== "stack"; anchors.verticalCenter: undefined; text: "Duck Under…"; on: win.duckMenu
                        tip: "Dip whenever another track plays (the bass under the kick)"; onClicked: win.duckMenu = !win.duckMenu }
                    Chips { objectName: "duckChips"; visible: win.duckMenu && !!win.selTrack; width: 150
                        items: Backend.tracks.filter(function (t) { return win.selTrack && t.id !== win.selTrack.id && t.kind !== "stack" }).map(function (t) { return [t.id, t.name] })
                        onChosen: function (id) { Backend.duckUnder(win.selTrack.id, id); win.duckMenu = false } } }
                Rectangle { width: 1; height: parent.height - 10; color: Theme.t.islandLine; visible: !!win.selTrack }
                // the effects, in order
                Repeater { model: smartPane.fx
                    Rectangle { id: fxCard; required property var modelData; required property int index; width: 178; height: smartPane.height - 6; radius: 12
                        color: Theme.t.dark ? "#12FFFFFF" : "#08000000"; border.width: 1; border.color: modelData.on ? Qt.rgba(win.hot.r, win.hot.g, win.hot.b, 0.6) : Theme.t.islandLine
                        Row { x: 10; y: 8; spacing: 6
                            Toggle { on: fxCard.modelData.on; onToggled: function (v) { Backend.setEffect(win.selTrack.id, fxCard.index, "on", v) } }
                            Label { text: fxCard.modelData.name; font.weight: Font.DemiBold; font.pixelSize: 12; anchors.verticalCenter: parent.verticalCenter } }
                        Pressable { anchors { right: parent.right; rightMargin: 6 } y: 8; width: 22; height: 22; radius: 6; onClicked: Backend.removeEffect(win.selTrack.id, fxCard.index)
                            Glyph { anchors.centerIn: parent; name: "x"; size: 10 } }
                        Column { x: 10; y: 42; width: parent.width - 20; spacing: 3; opacity: fxCard.modelData.on ? 1 : 0.5
                            Repeater { model: ({ eq: [["low", "Low", -12, 12], ["mid", "Middle", -12, 12], ["high", "High", -12, 12]], comp: [["threshold", "Threshold", -48, 0], ["ratio", "Ratio", 1, 12], ["makeup", "Make-up", 0, 18]],
                                                 drive: [["amount", "Amount", 0, 1], ["tone", "Tone", 0, 1]], chorus: [["rate", "Speed", 0.1, 3], ["depth", "Depth", 0, 1], ["mix", "Mix", 0, 1]],
                                                 delay: [["feedback", "Repeats", 0, 0.9], ["mix", "Mix", 0, 1]], filter: [["cutoff", "Cutoff", 100, 12000], ["res", "Resonance", 0.5, 8]] })[fxCard.modelData.kind] || []
                                Column { required property var modelData; width: parent.width; spacing: 1
                                    Label { text: modelData[1] + "  " + Number(fxCard.modelData.params[modelData[0]]).toFixed(Math.abs(modelData[3]) > 20 ? 0 : 1); font.pixelSize: 10; secondary: true }
                                    Meter { width: parent.width; interactive: true; value: (fxCard.modelData.params[modelData[0]] - modelData[2]) / (modelData[3] - modelData[2])
                                        onMoved: function (v) { Backend.setEffect(win.selTrack.id, fxCard.index, modelData[0], modelData[2] + v * (modelData[3] - modelData[2])) } } } }
                            // a compressor can listen to another track (sidechain)
                            Label { visible: fxCard.modelData.kind === "comp"; text: "Listens to"; font.pixelSize: 10; secondary: true; topPadding: 2 }
                            Chips { visible: fxCard.modelData.kind === "comp"; width: parent.width
                                items: [["", "Itself"]].concat(Backend.tracks.filter(function (t) { return win.selTrack && t.id !== win.selTrack.id && t.kind !== "stack" }).map(function (t) { return [t.id, t.name] }))
                                current: fxCard.modelData.params.key || ""; onChosen: function (id) { Backend.setEffect(win.selTrack.id, fxCard.index, "key", id) } }
                            Flow { visible: fxCard.modelData.kind === "delay"; width: parent.width; spacing: 2
                                Repeater { model: [[0.5, "1/8"], [0.75, "1/8."], [1, "1/4"], [1.5, "1/4."]]
                                    Seg { required property var modelData; anchors.verticalCenter: undefined; text: modelData[1]; on: Math.abs(fxCard.modelData.params.time - modelData[0]) < 1e-3
                                        onClicked: Backend.setEffect(win.selTrack.id, fxCard.index, "time", modelData[0]) } } } } } }
                Column { visible: !!win.selTrack; width: 120; spacing: 4
                    Label { text: "ADD AN EFFECT"; font.pixelSize: 10; font.weight: Font.Bold; font.letterSpacing: 1.2; secondary: true }
                    Repeater { model: Backend.effectKinds
                        Seg { required property var modelData; anchors.verticalCenter: undefined; text: "+ " + modelData.name; onClicked: Backend.addEffect(win.selTrack.id, modelData.id) } } } } }

        // ---- the mixer
        ListView { id: mixer; objectName: "mixerStrips"; visible: win.benchKind === "mixer"; x: 12; y: 46; width: parent.width - 24; height: parent.height - 56; orientation: ListView.Horizontal; spacing: 6; clip: true
            boundsBehavior: Flickable.StopAtBounds
            readonly property var list: Backend.tracks
            model: list.length + 1
            delegate: Rectangle { id: strip; required property int index; readonly property var t: index < mixer.list.length ? mixer.list[index] : null
                width: 84; height: mixer.height; radius: 12; color: Theme.t.dark ? "#121419" : "#F3F4F7"; border.width: 1; border.color: strip.t && Backend.selectedTrack === strip.t.id ? strip.t.colour : Theme.t.islandLine
                readonly property real vol: strip.t ? strip.t.volume : (Backend.song.master ? Backend.song.master.volume || 0 : 0)
                readonly property real lvl: Backend.levels[strip.t ? strip.t.id : "master"] || 0
                function pos(db) { return Math.pow((db + 60) / 66, 1.6) }
                Rectangle { width: parent.width; height: 4; radius: 2; color: strip.t ? strip.t.colour : win.hot }
                Label { x: 6; y: 10; width: parent.width - 12; horizontalAlignment: Text.AlignHCenter; elide: Text.ElideRight; text: strip.t ? strip.t.name : "Master"; font.pixelSize: 11; font.weight: Font.DemiBold }
                Label { x: 6; y: 26; width: parent.width - 12; horizontalAlignment: Text.AlignHCenter; font.pixelSize: 9; secondary: true; font.family: Theme.t.fontMono; elide: Text.ElideRight
                    text: (strip.vol > 0 ? "+" : "") + strip.vol.toFixed(1) + " dB" + (strip.t && strip.t.outputName ? " → " + strip.t.outputName : "") }
                Item { x: 12; y: 46; width: parent.width - 24; height: parent.height - 46 - (strip.t ? 40 : 12)
                    Rectangle { x: 0; width: 6; height: parent.height; radius: 3; color: Theme.t.dark ? "#1F232B" : "#E1E4EA"
                        Rectangle { anchors.bottom: parent.bottom; width: parent.width; radius: 3; height: parent.height * Math.min(1, strip.lvl)
                            gradient: Gradient { GradientStop { position: 0; color: "#FF5A4F" } GradientStop { position: 0.15; color: "#F5C542" } GradientStop { position: 0.35; color: "#3DDC84" } GradientStop { position: 1; color: "#2BAA5A" } } } }
                    Rectangle { x: parent.width / 2 + 4; width: 4; height: parent.height; radius: 2; color: Theme.t.islandLine }
                    Rectangle { x: parent.width / 2 - 9; width: 30; height: 14; radius: 5; y: (parent.height - height) * (1 - strip.pos(strip.vol)); color: Theme.t.dark ? "#E7E9EE" : "#FFFFFF"; border.width: 1; border.color: Theme.t.islandLine
                        Rectangle { anchors.centerIn: parent; width: 18; height: 2; color: strip.t ? strip.t.colour : win.hot } }
                    MouseArea { anchors.fill: parent; preventStealing: true; cursorShape: Qt.SizeVerCursor
                        function put(m) { var p = Math.max(0, Math.min(1, 1 - (m.y - 7) / (height - 14))), dbv = Math.round((Math.pow(p, 1 / 1.6) * 66 - 60) * 2) / 2
                            if (strip.t) Backend.setTrack(strip.t.id, "volume", dbv); else Backend.setMaster("volume", dbv) }
                        onPressed: function (m) { put(m) } onPositionChanged: function (m) { put(m) }
                        onDoubleClicked: strip.t ? Backend.setTrack(strip.t.id, "volume", 0) : Backend.setMaster("volume", 0) } }
                Row { visible: !!strip.t; anchors { horizontalCenter: parent.horizontalCenter; bottom: parent.bottom; bottomMargin: 8 } spacing: 4
                    Pressable { width: 26; height: 24; radius: 6; color: strip.t && strip.t.mute ? Theme.t.danger : (hovered ? Theme.t.hover : "transparent"); onClicked: Backend.setTrack(strip.t.id, "mute", !strip.t.mute)
                        Text { anchors.centerIn: parent; text: "M"; font.pixelSize: 11; font.weight: Font.Bold; color: strip.t && strip.t.mute ? "#FFFFFF" : Theme.t.text } }
                    Pressable { width: 26; height: 24; radius: 6; color: strip.t && strip.t.solo ? "#F5C542" : (hovered ? Theme.t.hover : "transparent"); onClicked: Backend.setTrack(strip.t.id, "solo", !strip.t.solo)
                        Text { anchors.centerIn: parent; text: "S"; font.pixelSize: 11; font.weight: Font.Bold; color: strip.t && strip.t.solo ? "#111" : Theme.t.text } } } } }

        // ---- the keyboard
        Item { id: keysPane; objectName: "keysPane"; visible: win.benchKind === "keys"; x: 16; y: 48; width: parent.width - 32; height: parent.height - 60
            Row { id: octRow; spacing: 6; height: 30
                Seg { text: "Octave −"; onClicked: win.octave = Math.max(1, win.octave - 1) }
                Label { anchors.verticalCenter: parent.verticalCenter; text: "C" + win.octave; font.family: Theme.t.fontMono }
                Seg { text: "Octave +"; onClicked: win.octave = Math.min(7, win.octave + 1) }
                Label { anchors.verticalCenter: parent.verticalCenter; secondary: true; font.pixelSize: 11
                    text: "  Plays " + (win.selTrack ? win.selTrack.instName || win.selTrack.name : "the selected track") + (Backend.midiInputs.length ? "  ·  MIDI: " + Backend.midiInputs.join(", ") : "") + "  ·  Musical typing: Ctrl+K" } }
            Item { id: piano; y: 40; width: parent.width; height: parent.height - 44
                readonly property int whites: 21
                readonly property real ww: width / whites
                Repeater { model: 21
                    Rectangle { required property int index; readonly property int pitch: 12 * (win.octave + 1) + [0, 2, 4, 5, 7, 9, 11][index % 7] + 12 * Math.floor(index / 7)
                        x: index * piano.ww; width: piano.ww - 2; height: piano.height; radius: 6; color: ma.pressed ? Qt.lighter(win.hot, 1.3) : "#F4F4F6"; border.width: 1; border.color: "#33000000"
                        Text { visible: parent.pitch % 12 === 0; anchors { bottom: parent.bottom; bottomMargin: 6; horizontalCenter: parent.horizontalCenter } text: Backend.noteNames[parent.pitch]; font.pixelSize: 10; color: "#777" }
                        MouseArea { id: ma; anchors.fill: parent; onPressed: Backend.noteOn(parent.pitch, 100); onReleased: Backend.noteOff(parent.pitch) } } }
                Repeater { model: 21
                    Rectangle { required property int index; readonly property int step: index % 7; visible: [0, 1, 3, 4, 5].indexOf(step) >= 0
                        readonly property int pitch: 12 * (win.octave + 1) + [1, 3, 0, 6, 8, 10, 0][step] + 12 * Math.floor(index / 7)
                        x: (index + 1) * piano.ww - piano.ww * 0.3; width: piano.ww * 0.6; height: piano.height * 0.6; radius: 4; z: 2; color: mb.pressed ? win.hot : "#1C1C22"
                        MouseArea { id: mb; anchors.fill: parent; onPressed: Backend.noteOn(parent.pitch, 100); onReleased: Backend.noteOff(parent.pitch) } } } } } }
    Pressable { visible: Backend.hasSong && !win.benchOpen; z: 5; anchors { horizontalCenter: arrange.horizontalCenter; bottom: parent.bottom; bottomMargin: 18 } width: 140; height: 30; radius: 15
        color: Theme.t.island; border.width: 1; border.color: Theme.t.islandLine; onClicked: win.benchOpen = true
        Label { anchors.centerIn: parent; text: "Show the Bench"; font.pixelSize: 11 } }

    // ================================================================ loops and instruments, from the right
    Rectangle { id: drawerBox; objectName: "drawer"; visible: Backend.hasSong && win.drawer !== ""; x: parent.width - width - 12; y: 70; width: 300; height: parent.height - 82; radius: 18
        color: Theme.t.island; border.width: 1; border.color: Theme.t.islandLine; clip: true
        Label { x: 16; y: 14; text: win.drawer === "loops" ? "Loops" : "Instruments"; font.pixelSize: 16; font.weight: Font.DemiBold }
        Label { x: 16; y: 36; width: parent.width - 32; wrapMode: Text.WordWrap; secondary: true; font.pixelSize: 11
            text: win.drawer === "loops" ? "Click ▶ to hear one, drag it onto a lane (or press +). They play in your song's key and tempo." : "For " + (win.selTrack ? win.selTrack.name : "the selected track") + "." }
        Flow { visible: win.drawer === "loops"; x: 12; y: 70; width: parent.width - 24; spacing: 3
            Repeater { model: ["All", "Drums", "Bass", "Keys", "Synth", "Strings"]
                Seg { required property string modelData; anchors.verticalCenter: undefined; text: modelData; on: win.loopFamily === modelData; onClicked: win.loopFamily = modelData } } }
        ListView { id: loopList; objectName: "loopList"; visible: win.drawer === "loops"; x: 10; y: 140; width: parent.width - 20; height: parent.height - 150; clip: true; spacing: 4
            model: Backend.loops.filter(function (l) { return win.loopFamily === "All" || l.family === win.loopFamily })
            delegate: Rectangle { id: lp; required property var modelData; width: loopList.width; height: 44; radius: 10; color: dragArea.containsMouse ? Theme.t.hover : (Theme.t.dark ? "#0CFFFFFF" : "#06000000")
                property string loopId: modelData.id
                Drag.active: dragArea.drag.active; Drag.keys: ["loop"]; Drag.source: lp; Drag.hotSpot.x: 20; Drag.hotSpot.y: 20
                Pressable { x: 6; anchors.verticalCenter: parent.verticalCenter; width: 30; height: 30; radius: 15; color: win.hot; onClicked: Backend.previewLoop(lp.modelData.id)
                    Glyph { anchors.centerIn: parent; name: "play"; size: 12; ink: Theme.t.onAccent } }
                Column { x: 44; anchors.verticalCenter: parent.verticalCenter; width: parent.width - 84
                    Label { width: parent.width; elide: Text.ElideRight; text: lp.modelData.name; font.pixelSize: 12; font.weight: Font.DemiBold }
                    Label { text: lp.modelData.family + "  ·  " + lp.modelData.bars + " bars"; font.pixelSize: 10; secondary: true } }
                MouseArea { id: dragArea; x: 40; width: parent.width - 76; height: parent.height; hoverEnabled: true; drag.target: ghost; cursorShape: Qt.OpenHandCursor
                    onReleased: { if (ghost.Drag.target) ghost.Drag.drop(); ghost.x = 0; ghost.y = 0 } }
                Item { id: ghost; width: 120; height: 30; Drag.active: dragArea.drag.active; Drag.keys: ["loop"]; Drag.source: lp; Drag.hotSpot.x: 10; Drag.hotSpot.y: 10
                    Rectangle { visible: dragArea.drag.active; anchors.fill: parent; radius: 8; color: win.hot; opacity: 0.85
                        Label { anchors.centerIn: parent; text: lp.modelData.name; font.pixelSize: 10; color: Theme.t.onAccent } } }
                Pressable { anchors { right: parent.right; rightMargin: 6; verticalCenter: parent.verticalCenter } width: 28; height: 28; radius: 8
                    onClicked: Backend.addLoop(lp.modelData.id, Backend.selectedTrack, Backend.position)
                    Glyph { anchors.centerIn: parent; name: "plus"; size: 13 } } } }
        Rectangle { visible: win.drawer === "library"; x: 12; y: 66; width: parent.width - 24; height: 50; radius: 12; color: libDrop.containsDrag ? Qt.rgba(win.hot.r, win.hot.g, win.hot.b, 0.25) : (Theme.t.dark ? "#0CFFFFFF" : "#06000000")
            border.width: 1; border.color: libDrop.containsDrag ? win.hot : Theme.t.islandLine
            Glyph { x: 12; anchors.verticalCenter: parent.verticalCenter; name: "wand"; size: 16 }
            Label { x: 38; width: parent.width - 48; anchors.verticalCenter: parent.verticalCenter; wrapMode: Text.WordWrap; font.pixelSize: 11
                text: "<b>Sampler</b>: drop any sound here and play it across the keys, in tune." }
            DropArea { id: libDrop; anchors.fill: parent; keys: ["text/uri-list"]; onDropped: function (d) { if (d.hasUrls) { Backend.makeSampler(win.selTrack ? win.selTrack.id : "", d.urls[0]); d.accept() } } } }
        ListView { id: instList; visible: win.drawer === "library"; x: 10; y: 124; width: parent.width - 20; height: parent.height - 134; clip: true; spacing: 2
            model: Backend.instruments; section.property: "family"
            section.delegate: Label { required property string section; text: section.toUpperCase(); font.pixelSize: 10; font.weight: Font.Bold; font.letterSpacing: 1.2; secondary: true; topPadding: 10; leftPadding: 6 }
            delegate: Pressable { required property var modelData; width: instList.width; height: 36; radius: 9
                readonly property bool on: win.selTrack && win.selTrack.instrument && win.selTrack.instrument.id === modelData.id
                color: on ? Qt.rgba(win.hot.r, win.hot.g, win.hot.b, 0.2) : hovered ? Theme.t.hover : "transparent"
                onClicked: if (win.selTrack) Backend.setInstrument(win.selTrack.id, modelData.id)
                Glyph { x: 10; anchors.verticalCenter: parent.verticalCenter; name: modelData.kit ? "disc" : "music"; size: 14 }
                Label { x: 34; anchors.verticalCenter: parent.verticalCenter; text: modelData.name; font.pixelSize: 12 } } } }

    // which knob an automation lane draws
    MouseArea { anchors.fill: parent; z: 29; visible: win.laneMenu !== null; onClicked: win.laneMenu = null }
    Rectangle { id: laneMenuBox; objectName: "laneMenu"; z: 30; visible: win.laneMenu !== null; x: win.laneMenu ? win.laneMenu.x : 0; y: win.laneMenu ? Math.min(win.laneMenu.y, win.height - height - 10) : 0
        readonly property var opts: win.laneMenu ? Backend.automatable(win.laneMenu.tid) : []
        width: 230; height: Math.min(360, opts.length * 28 + 12); radius: 12; color: Theme.t.menu_bg; border.width: 1; border.color: Theme.t.menu_border
        ListView { id: laneList; x: 6; y: 6; width: parent.width - 12; height: parent.height - 12; clip: true
            model: laneMenuBox.opts
            delegate: Pressable { required property var modelData; width: laneList.width; height: 28; radius: 7; color: hovered ? Theme.t.hover : "transparent"
                onClicked: { Backend.setTrack(win.laneMenu.tid, "lane", modelData.param); win.laneMenu = null }
                Label { x: 8; anchors.verticalCenter: parent.verticalCenter; width: parent.width - 30; elide: Text.ElideRight; text: modelData.name; font.pixelSize: 11 }
                Rectangle { visible: modelData.drawn; anchors { right: parent.right; rightMargin: 10; verticalCenter: parent.verticalCenter } width: 6; height: 6; radius: 3; color: win.hot } } } }

    Toast { id: toast; z: 50; anchors { horizontalCenter: parent.horizontalCenter; bottom: parent.bottom; bottomMargin: 30 } }

    // ================================================================ sheets: songs, key, export
    Item { anchors.fill: parent; z: 40; visible: win.sheet !== ""
        Rectangle { anchors.fill: parent; radius: win.r; color: "#77000000"; MouseArea { anchors.fill: parent; onClicked: if (Backend.hasSong) win.sheet = "" } }
        Rectangle { anchors.centerIn: parent; width: win.sheet === "songs" ? 760 : 520; height: win.sheet === "songs" ? Math.min(win.height - 80, 600) : win.sheet === "key" ? 250 : 330; radius: 18
            color: Theme.t.menu_bg; border.width: 1; border.color: Theme.t.menu_border
            MouseArea { anchors.fill: parent }
            Label { x: 24; y: 20; font.pixelSize: 18; font.weight: Font.DemiBold; text: win.sheet === "songs" ? "Make music" : win.sheet === "key" ? "The song's key" : "Share your song" }
            // songs
            Column { visible: win.sheet === "songs"; x: 24; y: 58; width: parent.width - 48; spacing: 12
                Label { text: "NEW SONG"; font.pixelSize: 10; font.weight: Font.Bold; font.letterSpacing: 1.2; secondary: true }
                TextBox { id: songName; width: 300; placeholder: "Name it (you can change it later)" }
                Flow { width: parent.width; spacing: 10
                    Repeater { model: Backend.templates()
                        Pressable { required property var modelData; width: (parent.width - 30) / 3 - 1; height: 86; radius: 14; color: hovered ? Theme.t.hover : (Theme.t.dark ? "#10FFFFFF" : "#08000000")
                            border.width: 1; border.color: Theme.t.islandLine; onClicked: { Backend.newProject(modelData.id, songName.text); win.sheet = "" }
                            Column { x: 14; y: 12; width: parent.width - 28; spacing: 4
                                Label { text: modelData.name; font.weight: Font.DemiBold }
                                Label { width: parent.width; wrapMode: Text.WordWrap; text: modelData.about; font.pixelSize: 11; secondary: true } } } } }
                Label { visible: songList.count > 0; text: "YOUR SONGS"; font.pixelSize: 10; font.weight: Font.Bold; font.letterSpacing: 1.2; secondary: true; topPadding: 6 }
                ListView { id: songList; width: parent.width; height: Math.min(200, count * 42); clip: true; model: win.sheet === "songs" ? Backend.songs() : []
                    delegate: Pressable { required property var modelData; width: songList.width; height: 40; radius: 10; color: hovered ? Theme.t.hover : "transparent"
                        onClicked: { Backend.openProject(modelData.path); win.sheet = "" }
                        Glyph { x: 10; anchors.verticalCenter: parent.verticalCenter; name: "music"; size: 15 }
                        Label { x: 36; anchors.verticalCenter: parent.verticalCenter; text: modelData.name; font.weight: Font.DemiBold }
                        Label { anchors { right: parent.right; rightMargin: 10; verticalCenter: parent.verticalCenter } text: modelData.tracks + " tracks  ·  " + modelData.when; font.pixelSize: 11; secondary: true } } } }
            // key
            Column { visible: win.sheet === "key"; x: 24; y: 60; width: parent.width - 48; spacing: 12
                Flow { width: parent.width; spacing: 3
                    Repeater { model: 12
                        Seg { required property int index; anchors.verticalCenter: undefined; text: Backend.noteNames[index].replace(/-?\d+$/, ""); on: win.song.key === index; onClicked: Backend.setSong("key", index) } } }
                Row { spacing: 3
                    Seg { anchors.verticalCenter: undefined; text: "Major"; on: win.song.mode !== "minor"; onClicked: Backend.setSong("mode", "major") }
                    Seg { anchors.verticalCenter: undefined; text: "Minor"; on: win.song.mode === "minor"; onClicked: Backend.setSong("mode", "minor") } }
                Label { width: parent.width; wrapMode: Text.WordWrap; secondary: true; font.pixelSize: 11; text: "Loops and drummers follow the key. Notes you've written stay where they are." } }
            // export
            Column { visible: win.sheet === "export"; x: 24; y: 60; width: parent.width - 48; spacing: 10
                Label { width: parent.width; wrapMode: Text.WordWrap; secondary: true; font.pixelSize: 12; text: "Saved in Music/Tempo Exports. The mix goes through a limiter, so it never clips." }
                Flow { width: parent.width; spacing: 6
                    Repeater { model: [["wav", "WAV (best)"], ["flac", "FLAC"], ["mp3", "MP3"], ["m4a", "AAC"], ["ogg", "Ogg"], ["stems", "Stems (a WAV per track)"], ["midi", "MIDI"]]
                        Btn { required property var modelData; text: modelData[1]; primary: modelData[0] === "wav"; onClicked: Backend.export(modelData[0]) } } }
                Label { visible: Backend.lastExport !== ""; width: parent.width; elide: Text.ElideMiddle; font.pixelSize: 11; secondary: true; text: "Last: " + Backend.lastExport } }
            Row { anchors { right: parent.right; rightMargin: 20; bottom: parent.bottom; bottomMargin: 16 } spacing: 8
                Btn { visible: Backend.hasSong; text: "Done"; onClicked: win.sheet = "" } } } }
}
