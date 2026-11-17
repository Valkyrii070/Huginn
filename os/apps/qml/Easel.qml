import QtQuick
import Huginn.Easel

// Easel, "studio": the canvas floats on the glass and fills the window. Tools are a tall island at the left, the
// tool's own settings an island across the top, colour and layers a tall island at the right, and the light comes
// from the middle, behind the picture. Pixel and Vector switch what the tools are, like two benches in one studio.
GlassWindow {
    id: win
    title: "Easel"; glow: "centre"; glowY: 0.5; width: 1320; height: 840; minimumWidth: 980; minimumHeight: 600
    property string sheet: ""                     // which sheet is open (new, open, save, export, colour, canvas, imagesize, filter, ...)
    property var sheetData: ({})
    property string browseAt: ""
    property bool menuOpen: false
    property bool textOpen: false
    property string colourFor: "fg"
    readonly property var p: Backend.picked
    readonly property bool shapeTool: ["pointer", "rect", "ellipse", "line", "star", "pen"].indexOf(Backend.toolName) >= 0
    readonly property string fill2: win.p.count ? (win.p.fill2 || "") : (Backend.shapeStyle.fill2 || "")
    readonly property var glyphs: ({ move: "move", select: "select", ellipsesel: "contrast", lasso: "lasso", wand: "wand", brush: "brush", eraser: "eraser", fill: "bucket",
                                     gradient: "sliders", picker: "picker", text: "type", crop: "crop", hand: "hand", zoom: "zoom", pointer: "forward", pen: "pen",
                                     rect: "box", ellipse: "contrast", line: "edit", star: "star", transform: "transform", clone: "stamp", heal: "bandage", nodes: "nodes" })
    function say(msg, bad) { toast.say(msg, bad) }
    function open(kind, data) { sheet = kind; sheetData = data || ({}); menuOpen = false }
    function startBrowse(folder) { browseAt = folder || Backend.suggestedFolder() }
    Connections { target: Backend
        function onSaid(msg, bad) { toast.say(msg, bad) }
        function onEditText(text, x, y) { textBox.many = text; win.textOpen = true; textBox.focusIn() } }
    Component.onCompleted: if (!Backend.hasDoc) open("new")

    // shortcuts that hold the Control key (single keys belong to the canvas, so typing in a box is never taken)
    Shortcut { sequences: [StandardKey.Undo]; onActivated: Backend.undo() }
    Shortcut { sequences: [StandardKey.Redo, "Ctrl+Shift+Z"]; onActivated: Backend.redo() }
    Shortcut { sequences: [StandardKey.New]; onActivated: win.open("new") }
    Shortcut { sequences: [StandardKey.Open]; onActivated: { win.startBrowse(""); win.open("open") } }
    Shortcut { sequences: [StandardKey.Save]; onActivated: if (Backend.hasDoc && !Backend.save()) { win.startBrowse(""); win.open("save", { name: Backend.suggestedName() }) } }
    Shortcut { sequence: "Ctrl+Shift+S"; onActivated: if (Backend.hasDoc) { win.startBrowse(""); win.open("save", { name: Backend.suggestedName() }) } }
    Shortcut { sequence: "Ctrl+E"; onActivated: if (Backend.hasDoc) { win.startBrowse(""); win.open("export", { name: Backend.suggestedName(), format: "png", quality: 0.9 }) } }
    Shortcut { sequences: [StandardKey.Copy]; enabled: !win.textOpen; onActivated: Backend.copy(false) }
    Shortcut { sequences: [StandardKey.Cut]; enabled: !win.textOpen; onActivated: Backend.copy(true) }
    Shortcut { sequences: [StandardKey.Paste]; enabled: !win.textOpen; onActivated: Backend.paste() }
    Shortcut { sequences: [StandardKey.SelectAll]; enabled: !win.textOpen; onActivated: Backend.selectAll() }
    Shortcut { sequence: "Ctrl+D"; onActivated: Backend.deselect() }
    Shortcut { sequence: "Ctrl+Shift+I"; onActivated: Backend.invertSelection() }
    Shortcut { sequence: "Ctrl+J"; onActivated: Backend.duplicateLayer() }
    Shortcut { sequence: "Ctrl+T"; onActivated: Backend.startTransform() }
    Shortcut { sequence: "Ctrl+Shift+N"; onActivated: Backend.addLayer("pixel") }
    Shortcut { sequence: "Ctrl+0"; onActivated: view.fit() }
    Shortcut { sequence: "Ctrl+1"; onActivated: view.actualSize() }
    Shortcut { sequences: ["Ctrl+=", "Ctrl++"]; onActivated: view.setZoom(view.zoom * 1.25) }
    Shortcut { sequence: "Ctrl+-"; onActivated: view.setZoom(view.zoom / 1.25) }

    // ---------------------------------------------------------------- the canvas, under everything
    // a pen on a drawing tablet: its pressure, for the brush (the view gets the strokes themselves)
    PointHandler { acceptedDevices: PointerDevice.Stylus; target: null; grabPermissions: PointerHandler.ApprovesTakeOverByAnything
        onPointChanged: if (active) Backend.setPressure(point.pressure > 0 ? point.pressure : 1.0) }
    Rectangle { visible: Backend.busyText !== ""; z: 20; anchors.centerIn: parent; width: busyL.width + 40; height: 44; radius: 22; color: Theme.t.island; border.width: 1; border.color: Theme.t.islandLine
        Label { id: busyL; anchors.centerIn: parent; text: Backend.busyText } }
    EaselView { id: view; anchors.fill: parent; backend: Backend; visible: Backend.hasDoc
        Component.onCompleted: setPads(76, 60, 312, 64) }

    // ---------------------------------------------------------------- small parts
    component Chip: Rectangle {        // a colour you can click
        property color c: "transparent"
        property bool none: false
        width: 26; height: 26; radius: 7; border.width: 1; border.color: Theme.t.islandLine; clip: true; color: "#FFFFFF"
        Image { anchors.fill: parent; source: ""; visible: false }
        Rectangle { anchors.fill: parent; anchors.margins: 1; radius: 6; color: parent.none ? "transparent" : parent.c }
        Rectangle { visible: parent.none; width: parent.width * 1.3; height: 2; color: Theme.t.danger; rotation: -45; anchors.centerIn: parent }
    }
    component Slide: Row {            // a labelled slider for the bars
        id: sl
        property string label: ""
        property real value: 0
        property real from: 0
        property real to: 1
        property string unit: ""
        property int digits: 0
        property real scale: 100
        property int w: 120
        signal moved(real v)
        signal begin()
        spacing: 8; anchors.verticalCenter: parent ? parent.verticalCenter : undefined
        Label { text: sl.label; font.pixelSize: 11; secondary: true; anchors.verticalCenter: parent.verticalCenter }
        SetSlider { width: sl.w; anchors.verticalCenter: parent.verticalCenter; value: (sl.value - sl.from) / (sl.to - sl.from)
            onMoved: function (v) { sl.moved(sl.from + v * (sl.to - sl.from)) } }
        Label { text: (sl.value * sl.scale).toFixed(sl.digits) + sl.unit; font.pixelSize: 11; font.family: Theme.t.fontMono; width: 30; anchors.verticalCenter: parent.verticalCenter }
    }

    // ---------------------------------------------------------------- the start: something new, or something to open
    Item { visible: !Backend.hasDoc && win.sheet !== "open"; anchors.fill: parent
        Column { anchors.centerIn: parent; spacing: 22; width: Math.min(parent.width - 120, 900)
            Column { spacing: 4
                Label { text: "Start a picture"; font.pixelSize: 30; font.weight: Font.Light }
                Label { text: "Pixel layers for painting and photos, vector layers for shapes and type: both in one picture."; secondary: true } }
            Flow { width: parent.width; spacing: 12
                Repeater { model: Backend.presets
                    Pressable { required property var modelData; width: 164; height: 132; radius: 16; color: hovered ? Theme.t.hover : Theme.t.group; border.width: 1; border.color: Theme.t.islandLine
                        onClicked: Backend.newDoc(modelData.w, modelData.h, startBg.value)
                        Rectangle { readonly property real k: Math.min(120 / modelData.w, 62 / modelData.h); width: modelData.w * k; height: modelData.h * k; y: 14
                            anchors.horizontalCenter: parent.horizontalCenter; radius: 4; color: startBg.value === "transparent" ? "transparent" : startBg.value
                            border.width: 1; border.color: Theme.t.islandLine }
                        Label { x: 12; y: 88; text: modelData.name; font.weight: Font.DemiBold; font.pixelSize: 13 }
                        Label { x: 12; y: 106; text: modelData.w + " × " + modelData.h; secondary: true; font.pixelSize: 11 } } }
                Pressable { width: 164; height: 132; radius: 16; color: hovered ? Theme.t.hover : Theme.t.group; border.width: 1; border.color: Theme.t.islandLine
                    onClicked: win.open("custom", { w: "1600", h: "1200" })
                    Glyph { anchors.horizontalCenter: parent.horizontalCenter; y: 30; name: "plus"; size: 30; ink: Theme.t.accent }
                    Label { x: 12; y: 88; text: "Your own size"; font.weight: Font.DemiBold; font.pixelSize: 13 }
                    Label { x: 12; y: 106; text: "Any width and height"; secondary: true; font.pixelSize: 11 } } }
            Row { spacing: 12
                Label { text: "Background"; secondary: true; anchors.verticalCenter: parent.verticalCenter }
                SetChoice { id: startBg; each: 104; value: "#FFFFFF"; options: [["#FFFFFF", "White"], ["#14171C", "Black"], ["transparent", "See-through"]]; onPicked: function (v) { value = v } }
                Item { width: 24; height: 1 }
                Btn { text: "Open a Picture…"; onClicked: { win.startBrowse(""); win.open("open") } } }
            Column { visible: Backend.recent.length > 0; spacing: 8; width: parent.width
                Label { text: "RECENT"; secondary: true; font.pixelSize: 11; font.weight: Font.DemiBold }
                Flow { width: parent.width; spacing: 8
                    Repeater { model: Backend.recent
                        Pressable { required property var modelData; width: 214; height: 50; radius: 12; color: hovered ? Theme.t.hover : Theme.t.group
                            onClicked: Backend.open(modelData.path)
                            Glyph { x: 12; anchors.verticalCenter: parent.verticalCenter; name: "image"; size: 18; ink: Theme.t.accent }
                            Column { x: 40; width: parent.width - 52; anchors.verticalCenter: parent.verticalCenter
                                Label { width: parent.width; text: modelData.name; elide: Text.ElideMiddle; font.pixelSize: 12; font.weight: Font.DemiBold }
                                Label { width: parent.width; text: modelData.folder; elide: Text.ElideLeft; font.pixelSize: 10; secondary: true } } } } } }
        } }

    islands: [
        // the file island, next to the name
        Island { id: fileIsland; visible: true; x: 120; y: 12
            Label { visible: Backend.hasDoc; text: Backend.docName + (Backend.dirty ? "  •" : ""); font.pixelSize: 12; secondary: true; leftPadding: 6; rightPadding: 4
                width: Math.min(implicitWidth, 200); elide: Text.ElideMiddle; anchors.verticalCenter: parent.verticalCenter }
            Seg { icon: "list"; tip: "Menu"; on: win.menuOpen; onClicked: win.menuOpen = !win.menuOpen }
            Seg { icon: "plus"; tip: "New (Ctrl+N)"; onClicked: win.open("new") }
            Seg { icon: "folder"; tip: "Open (Ctrl+O)"; onClicked: { win.startBrowse(""); win.open("open") } }
            Seg { visible: Backend.hasDoc; icon: "download"; tip: "Save (Ctrl+S)"; onClicked: if (!Backend.save()) { win.startBrowse(""); win.open("save", { name: Backend.suggestedName() }) } }
            Seg { visible: Backend.hasDoc; icon: "share"; tip: "Export (Ctrl+E)"; onClicked: { win.startBrowse(""); win.open("export", { name: Backend.suggestedName(), format: "png", quality: 0.9 }) } }
            IslandGap { visible: Backend.hasDoc }
            Seg { visible: Backend.hasDoc; icon: "undo"; tip: "Undo" + (Backend.steps.length ? ": " + Backend.steps[Backend.steps.length - 1] : ""); enabled: Backend.canUndo; opacity: enabled ? 1 : 0.4; onClicked: Backend.undo() }
            Seg { visible: Backend.hasDoc; icon: "redo"; tip: "Redo"; enabled: Backend.canRedo; opacity: enabled ? 1 : 0.4; onClicked: Backend.redo() }
        },
        // the tool's own settings
        Island { id: ctx; visible: Backend.hasDoc; x: fileIsland.x + fileIsland.width + 10; y: 12
            Label { text: ({ move: "Move", select: "Rectangle", ellipsesel: "Ellipse", lasso: "Lasso", wand: "Magic Wand", brush: "Brush", eraser: "Eraser", fill: "Fill",
                             gradient: "Gradient", picker: "Picker", text: "Text", crop: "Crop", hand: "Hand", zoom: "Zoom", pointer: "Select", pen: "Pen",
                             rect: "Rectangle", ellipse: "Ellipse", line: "Line", star: "Star", transform: "Transform", clone: "Clone", heal: "Heal", nodes: "Points" })[Backend.toolName] || ""
                font.pixelSize: 12; font.weight: Font.DemiBold; leftPadding: 8; rightPadding: 4; anchors.verticalCenter: parent.verticalCenter }
            IslandGap {}
            // free transform
            Row { visible: Backend.toolName === "transform"; spacing: 6; anchors.verticalCenter: parent.verticalCenter
                Label { visible: !Backend.transforming; text: "Click the picture (or press Ctrl+T) to resize, turn or flip the layer, or what's selected"; font.pixelSize: 11; secondary: true; rightPadding: 8; anchors.verticalCenter: parent.verticalCenter }
                Label { visible: Backend.transforming; text: "W " + (Backend.transformInfo.w || 100) + "%   H " + (Backend.transformInfo.h || 100) + "%   " + (Backend.transformInfo.angle || 0) + "°"
                    font.pixelSize: 11; font.family: Theme.t.fontMono; rightPadding: 6; anchors.verticalCenter: parent.verticalCenter }
                Label { visible: Backend.transforming; text: "Shift: freely · Alt: from the middle · outside turns"; font.pixelSize: 11; secondary: true; rightPadding: 6; anchors.verticalCenter: parent.verticalCenter }
                Seg { visible: Backend.transforming; text: "Flip ↔"; onClicked: Backend.flipTransform("x") }
                Seg { visible: Backend.transforming; text: "Flip ↕"; onClicked: Backend.flipTransform("y") }
                Seg { visible: Backend.transforming; text: "Apply"; on: true; onClicked: Backend.applyTransform() }
                Seg { visible: Backend.transforming; text: "Cancel"; onClicked: Backend.cancelTransform() } }
            // clone and heal
            Row { visible: Backend.toolName === "clone" || Backend.toolName === "heal"; spacing: 10; anchors.verticalCenter: parent.verticalCenter
                SetChoice { visible: Backend.toolName === "heal"; each: 104; value: Backend.healSpot ? "spot" : "point"; options: [["spot", "From around it"], ["point", "From a point"]]
                    anchors.verticalCenter: parent.verticalCenter; onPicked: function (v) { Backend.setHealSpot(v === "spot") } }
                Slide { label: "Size"; value: Backend.brushSize; from: 1; to: 400; scale: 1; w: 90; onMoved: function (v) { Backend.setBrush("size", v) } }
                Slide { label: "Hard"; value: Backend.brushHardness; w: 60; onMoved: function (v) { Backend.setBrush("hardness", v) } }
                Label { text: Backend.toolName === "heal" && Backend.healSpot ? "Paint over a spot: it's filled from around it" : Backend.cloneReady ? "Paint to copy · Alt-click to copy from somewhere else" : "Alt-click where to copy from"
                    font.pixelSize: 11; secondary: true; rightPadding: 8; anchors.verticalCenter: parent.verticalCenter } }
            // editing points
            Row { visible: Backend.toolName === "nodes"; spacing: 4; anchors.verticalCenter: parent.verticalCenter
                Label { text: "Drag points and handles · click a line to add a point · Alt breaks a smooth point"; font.pixelSize: 11; secondary: true; rightPadding: 6; anchors.verticalCenter: parent.verticalCenter }
                Seg { visible: Backend.nodePicked; text: "Corner ⇄ Smooth"; onClicked: Backend.toggleSmooth() }
                Seg { visible: Backend.nodePicked; text: "Delete Point"; onClicked: Backend.deleteNode() } }
            // brushes
            Row { visible: Backend.toolName === "brush" || Backend.toolName === "eraser"; spacing: 12; anchors.verticalCenter: parent.verticalCenter
                SetPick { text: Backend.brushes.filter(function (b) { return b.id === Backend.brushKey })[0].name; anchors.verticalCenter: parent.verticalCenter
                    onClicked: win.open("brushes") }
                Slide { label: "Size"; value: Backend.brushSize; from: 1; to: 400; scale: 1; unit: ""; w: 96; onMoved: function (v) { Backend.setBrush("size", v) } }
                Slide { label: "Hard"; value: Backend.brushHardness; w: 60; onMoved: function (v) { Backend.setBrush("hardness", v) } }
                Slide { label: "Flow"; value: Backend.brushFlow; w: 60; onMoved: function (v) { Backend.setBrush("flow", v) } }
                Slide { label: "Opacity"; value: Backend.strokeOpacity; w: 60; onMoved: function (v) { Backend.setBrush("opacity", v) } }
                SetChoice { visible: Backend.penSeen; anchors.verticalCenter: parent.verticalCenter; each: 62; value: Backend.pressureMode
                    options: [["size", "Size"], ["opacity", "Opacity"], ["both", "Both"], ["off", "Off"]]; onPicked: function (v) { Backend.setOption("pressure", v) } }
                Label { visible: Backend.penSeen; anchors.verticalCenter: parent.verticalCenter; text: "← pen pressure"; secondary: true; font.pixelSize: 10 } }
            // fill and wand
            Row { visible: Backend.toolName === "wand" || (Backend.toolName === "fill" && Backend.personaName === "pixel"); spacing: 12; anchors.verticalCenter: parent.verticalCenter
                Slide { label: "Tolerance"; value: Backend.wandTolerance; onMoved: function (v) { Backend.setBrush("tolerance", v) } }
                Label { text: "Touching only"; font.pixelSize: 11; secondary: true; anchors.verticalCenter: parent.verticalCenter }
                Toggle { on: Backend.contiguousOn; anchors.verticalCenter: parent.verticalCenter; onToggled: function (v) { Backend.setOption("contiguous", v) } } }
            Label { visible: Backend.toolName === "fill" && Backend.personaName === "vector"; text: "Click a shape to fill it · Alt-click colours its outline"; secondary: true; font.pixelSize: 11; anchors.verticalCenter: parent.verticalCenter; rightPadding: 8 }
            // gradient
            Row { visible: Backend.toolName === "gradient"; spacing: 10; anchors.verticalCenter: parent.verticalCenter
                SetChoice { each: 70; value: Backend.gradientKind; options: [["linear", "Straight"], ["radial", "Round"]]; onPicked: function (v) { Backend.setOption("gradientKind", v) } }
                Label { text: "To clear"; font.pixelSize: 11; secondary: true; anchors.verticalCenter: parent.verticalCenter }
                Toggle { on: Backend.gradientClear; anchors.verticalCenter: parent.verticalCenter; onToggled: function (v) { Backend.setOption("gradientClear", v) } }
                Slide { label: "Opacity"; value: Backend.strokeOpacity; w: 80; onMoved: function (v) { Backend.setBrush("opacity", v) } } }
            // choosing
            Row { visible: ["select", "ellipsesel", "lasso", "wand"].indexOf(Backend.toolName) >= 0; spacing: 4; anchors.verticalCenter: parent.verticalCenter
                Label { visible: Backend.toolName !== "wand"; text: "Shift adds · Alt takes away"; font.pixelSize: 11; secondary: true; rightPadding: 6; anchors.verticalCenter: parent.verticalCenter }
                Seg { text: "All"; onClicked: Backend.selectAll() }
                Seg { text: "None"; enabled: Backend.hasSelection; onClicked: Backend.deselect() }
                Seg { text: "Invert"; onClicked: Backend.invertSelection() }
                Seg { text: "Feather…"; enabled: Backend.hasSelection; onClicked: win.open("feather", { v: 0.2 }) }
                Seg { text: "To New Layer"; enabled: Backend.hasSelection; onClicked: Backend.layerFromSelection(false) } }
            Label { visible: Backend.toolName === "move"; text: Backend.hasSelection ? "Drag to move what's selected · Shift keeps it straight" : "Drag to move the layer · arrow keys nudge"; font.pixelSize: 11; secondary: true; anchors.verticalCenter: parent.verticalCenter; rightPadding: 8 }
            Label { visible: Backend.toolName === "picker"; text: "Click for the main colour · Alt-click for the second"; font.pixelSize: 11; secondary: true; anchors.verticalCenter: parent.verticalCenter; rightPadding: 8 }
            Label { visible: Backend.toolName === "hand" || Backend.toolName === "zoom"; text: Backend.toolName === "hand" ? "Drag to look around · or hold Space with any tool" : "Click to zoom in · Alt-click to zoom out"; font.pixelSize: 11; secondary: true; anchors.verticalCenter: parent.verticalCenter; rightPadding: 8 }
            Row { visible: Backend.toolName === "crop"; spacing: 4; anchors.verticalCenter: parent.verticalCenter
                Label { visible: !Backend.cropping; text: "Drag over the part to keep"; font.pixelSize: 11; secondary: true; rightPadding: 6; anchors.verticalCenter: parent.verticalCenter }
                Seg { visible: Backend.cropping; text: "Crop"; on: true; onClicked: Backend.applyCrop() }
                Seg { visible: Backend.cropping; text: "Cancel"; onClicked: Backend.cancelCrop() } }
            // text
            Row { visible: Backend.toolName === "text"; spacing: 8; anchors.verticalCenter: parent.verticalCenter
                SetPick { text: Backend.textStyle.font || "Inter"; maxWidth: 160; anchors.verticalCenter: parent.verticalCenter
                    onClicked: win.open("fonts") }
                Slide { label: "Size"; value: Backend.textStyle.size || 72; from: 6; to: 400; scale: 1; w: 90; onMoved: function (v) { Backend.setTextStyle("size", Math.round(v)) } }
                SetChoice { each: 56; value: String(Backend.textStyle.weight || 400); options: [["300", "Light"], ["400", "Plain"], ["700", "Bold"], ["900", "Black"]]
                    onPicked: function (v) { Backend.setTextStyle("weight", Number(v)) } }
                Seg { icon: "alignleft"; on: Backend.textStyle.align === "left"; onClicked: Backend.setTextStyle("align", "left") }
                Seg { icon: "aligncenter"; on: Backend.textStyle.align === "center"; onClicked: Backend.setTextStyle("align", "center") }
                Seg { icon: "alignright"; on: Backend.textStyle.align === "right"; onClicked: Backend.setTextStyle("align", "right") } }
            // shapes: style of the picked ones (or of the next one)
            Row { visible: win.shapeTool; spacing: 8; anchors.verticalCenter: parent.verticalCenter
                Label { text: "Fill"; font.pixelSize: 11; secondary: true; anchors.verticalCenter: parent.verticalCenter }
                Chip { readonly property string v: win.p.count ? win.p.fill : Backend.shapeStyle.fill; c: v || "transparent"; none: !v; anchors.verticalCenter: parent.verticalCenter
                    MouseArea { anchors.fill: parent; onClicked: { win.colourFor = "fill"; win.open("colour") } } }
                Seg { text: win.fill2 ? "" : "Gradient"; icon: win.fill2 ? "x" : ""; tip: win.fill2 ? "Plain fill" : ""; onClicked: Backend.setStyle("fill2", win.fill2 ? "" : Backend.bgColour) }
                Chip { visible: win.fill2 !== ""; c: win.fill2 || "transparent"; anchors.verticalCenter: parent.verticalCenter
                    MouseArea { anchors.fill: parent; onClicked: { win.colourFor = "fill2"; win.open("colour") } } }
                SetChoice { visible: win.fill2 !== ""; each: 34; anchors.verticalCenter: parent.verticalCenter
                    value: (win.p.count ? win.p.gkind : Backend.shapeStyle.gkind) === "radial" ? "r" : String(Math.round(win.p.count ? win.p.gangle : (Backend.shapeStyle.gangle === undefined ? 90 : Backend.shapeStyle.gangle)))
                    options: [["90", "↓"], ["0", "→"], ["45", "↘"], ["r", "◎"]]
                    onPicked: function (v) { if (v === "r") Backend.setStyle("gkind", "radial"); else { Backend.setStyle("gkind", "linear"); Backend.setStyle("gangle", Number(v)) } } }
                Label { text: "Line"; font.pixelSize: 11; secondary: true; anchors.verticalCenter: parent.verticalCenter }
                Chip { readonly property string v: win.p.count ? win.p.stroke : Backend.shapeStyle.stroke; c: v || "transparent"; none: !v; anchors.verticalCenter: parent.verticalCenter
                    MouseArea { anchors.fill: parent; onClicked: { win.colourFor = "stroke"; win.open("colour") } } }
                Slide { label: ""; value: win.p.count ? win.p.width : Backend.shapeStyle.width; from: 0; to: 40; scale: 1; unit: " px"; w: 70
                    onMoved: function (v) { Backend.setStyle("width", Math.round(v * 2) / 2) } }
                Slide { visible: Backend.toolName === "rect" || win.p.type === "rect"; label: "Round"; value: win.p.count ? win.p.radius : Backend.shapeStyle.radius; from: 0; to: 200; scale: 1; w: 60
                    onMoved: function (v) { Backend.setStyle("radius", Math.round(v)) } }
                Slide { visible: Backend.toolName === "star" || win.p.type === "star"; label: "Points"; value: win.p.count ? win.p.points : Backend.shapeStyle.points; from: 3; to: 16; scale: 1; w: 60
                    onMoved: function (v) { Backend.setStyle("points", Math.round(v)) } }
                Slide { label: "Opacity"; value: win.p.count ? win.p.opacity : Backend.shapeStyle.opacity; w: 60; onMoved: function (v) { Backend.setStyle("opacity", v) } }
                Seg { visible: win.p.count > 0; text: "Arrange"; onClicked: win.open("arrange") }
                Seg { visible: win.p.count > 1; text: "Combine"; onClicked: win.open("combine") }
                Seg { visible: Backend.penActive; text: "Done"; on: true; onClicked: Backend.finishPen() } }
        },
        // tools
        Rectangle { visible: Backend.hasDoc; x: 12; y: 64; width: 52; height: toolCol.height + 16; radius: 18; color: Theme.t.island; border.width: 1; border.color: Theme.t.islandLine
            MouseArea { anchors.fill: parent }
            Column { id: toolCol; x: 6; y: 8; spacing: 3; width: 40
                Rectangle { width: 40; height: 66; radius: 12; color: Theme.t.dark ? "#22FFFFFF" : "#14141E28"
                    Column { anchors.centerIn: parent; spacing: 2
                        Seg { anchors.verticalCenter: undefined; icon: "brush"; tip: "Pixel: paint and retouch"; on: Backend.personaName === "pixel"; onClicked: Backend.setPersona("pixel") }
                        Seg { anchors.verticalCenter: undefined; icon: "pen"; tip: "Vector: shapes and type"; on: Backend.personaName === "vector"; onClicked: Backend.setPersona("vector") } } }
                Item { width: 1; height: 4 }
                Repeater { model: Backend.tools
                    Seg { required property var modelData; anchors.verticalCenter: undefined; width: 40; icon: win.glyphs[modelData.id] || "edit"; tip: modelData.name; on: Backend.toolName === modelData.id; onClicked: Backend.setTool(modelData.id) } }
                Item { width: 1; height: 6 }
                Item { width: 40; height: 44     // the two colours: click to change, the arrow swaps them
                    Chip { x: 14; y: 14; c: Backend.bgColour; MouseArea { anchors.fill: parent; onClicked: { win.colourFor = "bg"; win.open("colour") } } }
                    Chip { x: 0; y: 0; c: Backend.fgColour; border.width: 2; border.color: Theme.t.text; MouseArea { anchors.fill: parent; onClicked: { win.colourFor = "fg"; win.open("colour") } } }
                    Glyph { x: 28; y: 0; name: "refresh"; size: 11; ink: Theme.t.text_secondary; MouseArea { anchors.fill: parent; anchors.margins: -3; onClicked: Backend.swapColours() } } }
            }
        },
        // colour and layers
        Rectangle { id: side; visible: Backend.hasDoc; anchors { right: parent.right; rightMargin: 12 } y: 64; width: 288; height: parent.height - 64 - 60; radius: 18
            color: Theme.t.island; border.width: 1; border.color: Theme.t.islandLine
            MouseArea { anchors.fill: parent }
            Column { id: sideTop; x: 14; y: 12; width: parent.width - 28; spacing: 8
                Label { text: "COLOUR"; secondary: true; font.pixelSize: 11; font.weight: Font.DemiBold }
                Flow { width: parent.width; spacing: 6
                    Repeater { model: Backend.swatches
                        Chip { required property string modelData; c: modelData; width: 22; height: 22
                            MouseArea { anchors.fill: parent; acceptedButtons: Qt.LeftButton | Qt.RightButton
                                onClicked: function (m) { if (m.button === Qt.RightButton) Backend.setColour("bg", modelData); else { Backend.setColour("fg", modelData); if (win.p.count && Backend.personaName === "vector") Backend.setStyle("fill", modelData) } } } } }
                    Rectangle { width: 22; height: 22; radius: 7; color: "transparent"; border.width: 1; border.color: Theme.t.islandLine
                        Glyph { anchors.centerIn: parent; name: "plus"; size: 12; ink: Theme.t.text_secondary }
                        MouseArea { anchors.fill: parent; onClicked: Backend.keepSwatch() } } }
                Item { width: 1; height: 4 }
                // the active layer's settings
                Row { width: parent.width; spacing: 8
                    Label { text: "LAYERS"; secondary: true; font.pixelSize: 11; font.weight: Font.DemiBold; anchors.verticalCenter: parent.verticalCenter }
                    Item { width: parent.width - 60 - layerBtns.width; height: 1 }
                    Row { id: layerBtns; spacing: 0
                        Seg { icon: "plus"; tip: "New pixel layer"; onClicked: Backend.addLayer("pixel") }
                        Seg { icon: "pen"; tip: "New vector layer"; onClicked: Backend.addLayer("vector") }
                        Seg { icon: "contrast"; tip: "New adjustment layer"; onClicked: win.open("adjust") }
                        Seg { icon: "layers"; tip: "Mask and more"; onClicked: win.open("layer") } } }
                Row { width: parent.width; spacing: 8; visible: Backend.activeLayer.kind !== undefined
                    SetPick { text: (Backend.blends.filter(function (b) { return b.id === Backend.activeLayer.blend })[0] || { name: "Normal" }).name; maxWidth: 110
                        onClicked: win.open("blend") }
                    SetSlider { width: parent.width - 170; anchors.verticalCenter: parent.verticalCenter; value: Backend.activeLayer.opacity || 0
                        onMoved: function (v) { Backend.setLayer(Backend.activeLayer.id, "opacity", v) } }
                    Label { text: Math.round((Backend.activeLayer.opacity || 0) * 100) + "%"; font.pixelSize: 11; font.family: Theme.t.fontMono; anchors.verticalCenter: parent.verticalCenter } }
                Column { id: curves; visible: Backend.activeLayer.adjust === "curves"; width: parent.width; spacing: 6
                    property string ch: "rgb"
                    readonly property var pts: Backend.activeLayer.params && Backend.activeLayer.params.curves && Backend.activeLayer.params.curves[ch] ? Backend.activeLayer.params.curves[ch] : [[0, 0], [1, 1]]
                    property var dragPts: null
                    property int dragging: -1
                    readonly property var shown: dragPts || pts
                    SetChoice { each: 64; value: curves.ch; options: [["rgb", "RGB"], ["r", "Red"], ["g", "Green"], ["b", "Blue"]]; onPicked: function (v) { curves.ch = v } }
                    Rectangle { width: parent.width; height: Math.min(parent.width, 220); radius: 8; color: Theme.t.dark ? "#22000000" : "#0A141E28"; border.width: 1; border.color: Theme.t.islandLine
                        Canvas { id: curveCanvas; anchors.fill: parent; anchors.margins: 8
                            property var samples: curves.visible ? Backend.curveSamples(curves.ch) : []
                            Connections { target: Backend; function onChanged() { curveCanvas.samples = curves.visible ? Backend.curveSamples(curves.ch) : []; curveCanvas.requestPaint() } }
                            onSamplesChanged: requestPaint()
                            onPaint: {
                                var c = getContext("2d"), w = width, h = height
                                c.reset(); c.strokeStyle = Theme.t.dark ? "rgba(255,255,255,0.12)" : "rgba(0,0,0,0.12)"; c.lineWidth = 1
                                for (var i = 1; i < 4; i++) { c.beginPath(); c.moveTo(w * i / 4, 0); c.lineTo(w * i / 4, h); c.moveTo(0, h * i / 4); c.lineTo(w, h * i / 4); c.stroke() }
                                c.beginPath(); c.moveTo(0, h); c.lineTo(w, 0); c.stroke()
                                c.strokeStyle = ({ rgb: Theme.t.text, r: "#FF4D4D", g: "#3DDC6E", b: "#4D8DFF" })[curves.ch]; c.lineWidth = 2; c.beginPath()
                                for (var k = 0; k < samples.length; k++) { var x = w * k / (samples.length - 1), y = h * (1 - samples[k]); if (k === 0) c.moveTo(x, y); else c.lineTo(x, y) }
                                c.stroke()
                                c.fillStyle = "#FFFFFF"; c.strokeStyle = "#000000"; c.lineWidth = 1
                                for (var j = 0; j < curves.shown.length; j++) { c.beginPath(); c.arc(w * curves.shown[j][0], h * (1 - curves.shown[j][1]), 5, 0, Math.PI * 2); c.fill(); c.stroke() } } }
                        MouseArea { anchors.fill: parent; anchors.margins: 8
                            function at(m) { return [Math.max(0, Math.min(1, m.x / width)), Math.max(-0.2, Math.min(1.2, 1 - m.y / height))] }
                            onPressed: function (m) {
                                var p = at(m), list = curves.pts.map(function (q) { return [q[0], q[1]] }), best = -1
                                for (var i = 0; i < list.length; i++) if (Math.abs(list[i][0] - p[0]) * width < 10 && Math.abs(list[i][1] - p[1]) * height < 10) best = i
                                if (best < 0) { list.push([p[0], Math.max(0, Math.min(1, p[1]))]); list.sort(function (a, b) { return a[0] - b[0] }); best = list.findIndex(function (q) { return q[0] === p[0] }) }
                                Backend.markLayer(); curves.dragPts = list; curves.dragging = best; curveCanvas.requestPaint() }
                            onPositionChanged: function (m) {
                                if (curves.dragging < 0) return
                                var p = at(m), list = curves.dragPts.slice(), i = curves.dragging
                                var lo = i > 0 ? list[i - 1][0] + 0.01 : 0, hi = i < list.length - 1 ? list[i + 1][0] - 0.01 : 1
                                list[i] = [Math.max(lo, Math.min(hi, p[0])), p[1]]
                                curves.dragPts = list; curveCanvas.requestPaint(); push.restart() }
                            onReleased: function (m) {
                                var list = curves.dragPts.slice(), i = curves.dragging, p = at(m)
                                if (i > 0 && i < list.length - 1 && (p[1] < -0.1 || p[1] > 1.1)) list.splice(i, 1)          // dragged off: the point goes
                                list = list.map(function (q) { return [q[0], Math.max(0, Math.min(1, q[1]))] })
                                Backend.setCurve(curves.ch, list); curves.dragPts = null; curves.dragging = -1 }
                            Timer { id: push; interval: 100; onTriggered: if (curves.dragPts) Backend.setCurve(curves.ch, curves.dragPts.map(function (q) { return [q[0], Math.max(0, Math.min(1, q[1]))] })) } } }
                    Label { width: parent.width; wrapMode: Text.WordWrap; secondary: true; font.pixelSize: 10; text: "Click to add a point, drag to bend, drag a point off the square to remove it." } }
                Column { visible: Backend.activeLayer.kind === "adjust"; width: parent.width; spacing: 4
                    Repeater { model: Backend.activeLayer.paramList || []
                        Row { required property var modelData; width: parent.width; spacing: 8
                            Label { text: modelData.name; font.pixelSize: 11; width: 80; anchors.verticalCenter: parent.verticalCenter }
                            SetSlider { width: parent.width - 88; anchors.verticalCenter: parent.verticalCenter
                                readonly property bool unit: ["black", "white"].indexOf(modelData.id) >= 0
                                value: unit ? (Backend.activeLayer.params[modelData.id] || 0) : ((Backend.activeLayer.params[modelData.id] || 0) + 1) / 2
                                onMoved: function (v) { Backend.setAdjust(modelData.id, unit ? v : v * 2 - 1) } } } } }
            }
            ListView { id: layerList; x: 8; y: sideTop.y + sideTop.height + 8; width: parent.width - 16; height: parent.height - y - 10; clip: true; spacing: 2
                boundsBehavior: Flickable.StopAtBounds; model: Backend.layers
                delegate: Pressable { required property var modelData; required property int index; width: layerList.width; height: 50; radius: 11
                    color: modelData.active ? Qt.alpha(Theme.t.accent, 0.2) : (hovered ? Theme.t.hover : "transparent")
                    onClicked: Backend.selectLayer(modelData.id)
                    onDoubleClicked: win.open("rename", { id: modelData.id, name: modelData.name })
                    Glyph { x: 8; anchors.verticalCenter: parent.verticalCenter; name: "eye"; size: 15; ink: modelData.visible ? Theme.t.icon : Theme.t.text_tertiary; opacity: modelData.visible ? 1 : 0.4
                        MouseArea { anchors.fill: parent; anchors.margins: -5; onClicked: Backend.setLayer(modelData.id, "visible", !modelData.visible) } }
                    Rectangle { id: thumb; x: 32; width: 48; height: 36; radius: 6; anchors.verticalCenter: parent.verticalCenter; clip: true; color: Theme.t.group; border.width: 1; border.color: Theme.t.islandLine
                        Image { anchors.fill: parent; anchors.margins: 1; visible: modelData.kind !== "adjust"; source: "image://easel/layer/" + modelData.id + "/" + modelData.v; fillMode: Image.PreserveAspectCrop; cache: false; asynchronous: true }
                        Glyph { visible: modelData.kind === "adjust"; anchors.centerIn: parent; name: "contrast"; size: 18; ink: Theme.t.accent } }
                    Rectangle { visible: modelData.hasMask; x: 84; width: 28; height: 36; radius: 6; anchors.verticalCenter: parent.verticalCenter; clip: true; color: "#000000"
                        border.width: Backend.maskEditing && modelData.active ? 2 : 1; border.color: Backend.maskEditing && modelData.active ? Theme.t.accent : Theme.t.islandLine
                        Image { anchors.fill: parent; anchors.margins: 1; source: "image://easel/mask/" + modelData.id + "/" + modelData.v; fillMode: Image.PreserveAspectCrop; cache: false; asynchronous: true }
                        MouseArea { anchors.fill: parent; onClicked: { Backend.selectLayer(modelData.id); Backend.editMask(true) } } }
                    Column { x: modelData.hasMask ? 120 : 88; width: parent.width - x - 44; anchors.verticalCenter: parent.verticalCenter
                        Label { width: parent.width; text: modelData.name; elide: Text.ElideRight; font.pixelSize: 12; font.weight: modelData.active ? Font.DemiBold : Font.Normal }
                        Label { width: parent.width; elide: Text.ElideRight; font.pixelSize: 10; secondary: true
                            text: (modelData.kind === "vector" ? modelData.shapes + (modelData.shapes === 1 ? " shape" : " shapes") : modelData.kind === "adjust" ? "Adjustment" : "Pixels")
                                  + (modelData.blend !== "normal" ? " · " + modelData.blend : "") + (modelData.opacity < 1 ? " · " + Math.round(modelData.opacity * 100) + "%" : "") } }
                    Column { anchors { right: parent.right; rightMargin: 4; verticalCenter: parent.verticalCenter } visible: parent.hovered || modelData.locked
                        Glyph { name: "up"; size: 12; ink: Theme.t.text_secondary; visible: !modelData.locked && index > 0; MouseArea { anchors.fill: parent; anchors.margins: -3; onClicked: Backend.moveLayer(modelData.id, 1) } }
                        Glyph { name: "lock"; size: 12; ink: modelData.locked ? Theme.t.accent : Theme.t.text_secondary; MouseArea { anchors.fill: parent; anchors.margins: -3; onClicked: Backend.setLayer(modelData.id, "locked", !modelData.locked) } }
                        Glyph { name: "down"; size: 12; ink: Theme.t.text_secondary; visible: !modelData.locked && index < layerList.count - 1; MouseArea { anchors.fill: parent; anchors.margins: -3; onClicked: Backend.moveLayer(modelData.id, -1) } } } } }
        },
        // what's where
        Island { visible: Backend.hasDoc; x: 76; anchors { bottom: parent.bottom; bottomMargin: 14 }
            Seg { text: "−"; tip: "Zoom out"; onClicked: view.setZoom(view.zoom / 1.25) }
            Label { text: Math.round(view.zoom * 100) + "%"; font.pixelSize: 12; font.family: Theme.t.fontMono; width: 46; horizontalAlignment: Text.AlignHCenter; anchors.verticalCenter: parent.verticalCenter
                MouseArea { anchors.fill: parent; onClicked: view.actualSize() } }
            Seg { text: "+"; tip: "Zoom in"; onClicked: view.setZoom(view.zoom * 1.25) }
            Seg { icon: "expand"; tip: "Fit (Ctrl+0)"; onClicked: view.fit() }
            IslandGap {}
            Label { text: Backend.docW + " × " + Backend.docH + " px"; font.pixelSize: 11; secondary: true; leftPadding: 4; anchors.verticalCenter: parent.verticalCenter }
            Label { visible: Backend.cursorText !== ""; text: "·  " + Backend.cursorText; font.pixelSize: 11; font.family: Theme.t.fontMono; secondary: true; anchors.verticalCenter: parent.verticalCenter }
            Seg { visible: Backend.maskEditing; text: "Painting the mask · white shows, black hides"; on: true; onClicked: Backend.editMask(false) }
            Item { width: 6; height: 1 }
        },
        // typing
        Rectangle { visible: win.textOpen; anchors.horizontalCenter: parent.horizontalCenter; anchors { bottom: parent.bottom; bottomMargin: 14 } width: 520; height: 130; radius: 18
            color: Theme.t.island; border.width: 1; border.color: Theme.t.islandLine
            Label { x: 16; y: 12; text: "Type here · the text appears on the picture as you type"; secondary: true; font.pixelSize: 11 }
            TextBox { id: textBox; x: 14; y: 34; width: parent.width - 120; lines: 3; onEdited: Backend.setText(many) }
            Btn { anchors { right: parent.right; rightMargin: 14; bottom: parent.bottom; bottomMargin: 14 } text: "Done"; primary: true; onClicked: { win.textOpen = false; Backend.doneText() } } },
        Toast { id: toast; anchors { horizontalCenter: parent.horizontalCenter; bottom: parent.bottom; bottomMargin: win.textOpen ? 160 : 70 } }
    ]

    // ---------------------------------------------------------------- the menu
    Rectangle { visible: win.menuOpen; z: 30; x: 120; y: 58; width: menuRow.width + 24; height: menuRow.height + 24; radius: 16; color: Theme.t.menu_bg; border.width: 1; border.color: Theme.t.menu_border
        MouseArea { anchors.fill: parent }
        Row { id: menuRow; x: 12; y: 12; spacing: 18
            Repeater {
                model: [
                    { title: "Image", items: [["Canvas Size…", "canvas"], ["Image Size…", "imagesize"], ["Crop to Selection", "cropsel"], ["Trim Edges", "trim"], ["Rotate Right", "cw"], ["Rotate Left", "ccw"], ["Rotate 180°", "180"], ["Flip Across", "fliph"], ["Flip Upside Down", "flipv"]] },
                    { title: "Select", items: [["Select All", "all"], ["Deselect", "none"], ["Invert", "invert"], ["Feather…", "feather"], ["Grow or Shrink…", "grow"], ["Copy to New Layer", "copylayer"], ["Cut to New Layer", "cutlayer"], ["Fill with Colour", "fill"], ["Fill with Surroundings", "aware"], ["Delete Inside", "clear"]] },
                    { title: "Layer", items: [["New Pixel Layer", "newpixel"], ["New Vector Layer", "newvector"], ["New Adjustment…", "adjust"], ["Duplicate", "duplicate"], ["Merge Down", "merge"], ["Flatten", "flatten"], ["Rasterise", "rasterise"], ["Delete Layer", "delete"]] },
                    { title: "Filters", items: Backend.filters.map(function (f) { return [f.name + ([ "invert", "desaturate", "autolevels"].indexOf(f.id) < 0 ? "…" : ""), "f:" + f.id] }) } ]
                Column { required property var modelData; spacing: 1; width: 170
                    Label { text: modelData.title.toUpperCase(); secondary: true; font.pixelSize: 10; font.weight: Font.DemiBold; bottomPadding: 4; leftPadding: 8 }
                    Repeater { model: modelData.items
                        Pressable { required property var modelData; width: 170; height: 28; radius: 8; color: hovered ? Theme.t.hover : "transparent"; enabled: Backend.hasDoc; opacity: enabled ? 1 : 0.4
                            onClicked: win.act(modelData[1])
                            Label { x: 8; anchors.verticalCenter: parent.verticalCenter; text: modelData[0]; font.pixelSize: 12 } } } } } } }
    MouseArea { visible: win.menuOpen; anchors.fill: parent; z: 29; onClicked: win.menuOpen = false }
    function act(what) {
        menuOpen = false
        if (what.indexOf("f:") === 0) { var id = what.slice(2); if (["invert", "desaturate", "autolevels"].indexOf(id) >= 0) Backend.applyFilter(id, 1); else open("filter", { id: id, v: 0.4 }); return }
        var direct = { cropsel: Backend.applyCrop, trim: Backend.trim, all: Backend.selectAll, none: Backend.deselect, invert: Backend.invertSelection, fill: Backend.fillSelection, aware: Backend.fillAware,
                       clear: Backend.clearSelection, duplicate: Backend.duplicateLayer, merge: Backend.mergeDown, flatten: Backend.flatten, rasterise: Backend.rasterize, delete: Backend.deleteLayer }
        if (direct[what]) { direct[what](); return }
        if (["cw", "ccw", "180", "fliph", "flipv"].indexOf(what) >= 0) { Backend.transformCanvas(what); view.fit(); return }
        if (what === "copylayer" || what === "cutlayer") { Backend.layerFromSelection(what === "cutlayer"); return }
        if (what === "newpixel" || what === "newvector") { Backend.addLayer(what === "newpixel" ? "pixel" : "vector"); return }
        if (what === "canvas") open("canvas", { w: String(Backend.docW), h: String(Backend.docH), anchor: "c" })
        else if (what === "imagesize") open("imagesize", { w: String(Backend.docW), h: String(Backend.docH), keep: true })
        else if (what === "feather") open("feather", { v: 0.2 })
        else if (what === "grow") open("grow", { v: 0.5 })
        else if (what === "adjust") open("adjust")
    }

    // ---------------------------------------------------------------- sheets
    Item { anchors.fill: parent; z: 40; visible: win.sheet !== "" && !(win.sheet === "new" && !Backend.hasDoc)
        Rectangle { anchors.fill: parent; radius: win.r; color: "#77000000"; MouseArea { anchors.fill: parent; acceptedButtons: Qt.AllButtons; onClicked: win.sheet = "" } }
        Rectangle { id: card; anchors.centerIn: parent; radius: 20; color: Theme.t.menu_bg; border.width: 1; border.color: Theme.t.menu_border
            readonly property string kind: win.sheet
            readonly property bool browsing: kind === "open" || kind === "save" || kind === "export"
            width: browsing ? 620 : kind === "colour" ? 340 : kind === "new" ? 640 : ["brushes", "blend", "fonts", "adjust", "layer", "arrange", "combine"].indexOf(kind) >= 0 ? 360 : 440
            height: browsing ? Math.min(win.height - 80, 560) : kind === "colour" ? 400 : kind === "new" ? 300 : kind === "fonts" || kind === "blend" ? Math.min(win.height - 100, 520)
                  : ["brushes", "adjust", "layer", "arrange", "combine"].indexOf(kind) >= 0 ? sheetList.contentHeight + 110 : kind === "canvas" ? 300 : 220
            MouseArea { anchors.fill: parent }
            Label { x: 24; y: 20; font.pixelSize: 17; font.weight: Font.DemiBold
                text: ({ new: "New picture", custom: "New picture", open: "Open a picture", save: "Save as an Easel picture", export: "Export", colour: ({ fg: "Main colour", bg: "Second colour", fill: "Fill", fill2: "Gradient's second colour", stroke: "Line" })[win.colourFor],
                         canvas: "Canvas size", imagesize: "Image size", filter: (Backend.filters.filter(function (f) { return f.id === win.sheetData.id })[0] || { name: "" }).name, feather: "Feather the selection",
                         grow: "Grow or shrink the selection", rename: "Rename the layer", brushes: "Brushes", blend: "Blend mode", fonts: "Font", adjust: "New adjustment layer",
                         layer: "Layer", arrange: "Arrange", combine: "Combine shapes" })[card.kind] || "" }
            // --- lists: brushes, blend modes, fonts, adjustments, layer actions, arranging, combining
            ListView { id: sheetList; visible: ["brushes", "blend", "fonts", "adjust", "layer", "arrange", "combine"].indexOf(card.kind) >= 0; x: 12; y: 56; width: parent.width - 24; height: parent.height - 120; clip: true
                boundsBehavior: Flickable.StopAtBounds
                model: card.kind === "brushes" ? Backend.brushes.map(function (b) { return { id: b.id, label: b.name } })
                     : card.kind === "blend" ? Backend.blends.map(function (b) { return { id: b.id, label: b.name } })
                     : card.kind === "fonts" ? Backend.fonts.map(function (f) { return { id: f, label: f, font: f } })
                     : card.kind === "adjust" ? Backend.adjustments.map(function (a) { return { id: a.id, label: a.name } })
                     : card.kind === "layer" ? [{ id: "mask:reveal", label: "Add a mask (shows all)" }, { id: "mask:hide", label: "Add a mask (hides all)" }, { id: "mask:selection", label: "Add a mask from the selection" },
                                                { id: "editmask", label: "Paint on the mask" }, { id: "applymask", label: "Apply the mask" }, { id: "deletemask", label: "Delete the mask" },
                                                { id: "duplicate", label: "Duplicate the layer" }, { id: "merge", label: "Merge down" }, { id: "rasterise", label: "Rasterise (shapes to pixels)" }, { id: "delete", label: "Delete the layer" }]
                     : card.kind === "arrange" ? [{ id: "front", label: "Bring to front" }, { id: "forward", label: "Bring forward" }, { id: "backward", label: "Send backward" }, { id: "back", label: "Send to back" },
                                                  { id: "a:left", label: "Align left" }, { id: "a:hcenter", label: "Align centres across" }, { id: "a:right", label: "Align right" },
                                                  { id: "a:top", label: "Align top" }, { id: "a:vcenter", label: "Align middles" }, { id: "a:bottom", label: "Align bottom" },
                                                  { id: "outline", label: "Convert to Outlines (edit the points)" },
                                                  { id: "onpath", label: "Put the Type on the Line (pick both)" }, { id: "offpath", label: "Take the Type off its Line" }, { id: "del", label: "Delete" }]
                     : card.kind === "combine" ? [{ id: "union", label: "Unite: one shape from all" }, { id: "subtract", label: "Subtract: cut the others out of the bottom one" },
                                                  { id: "intersect", label: "Intersect: only where they overlap" }, { id: "exclude", label: "Exclude: everything but the overlap" }] : []
                delegate: Pressable { required property var modelData; width: sheetList.width; height: 38; radius: 10; color: hovered ? Theme.t.hover : "transparent"
                    onClicked: win.pickFromList(card.kind, modelData.id)
                    Label { x: 12; anchors.verticalCenter: parent.verticalCenter; text: modelData.label; font.family: modelData.font || Theme.t.font; font.pixelSize: 13 } } }
            // --- a colour
            Item { visible: card.kind === "colour"; x: 24; y: 58; width: parent.width - 48; height: 280
                id: picker
                property real hue: 0.6
                property real sat: 0.8
                property real val: 0.9
                readonly property string current: card.kind !== "colour" ? "" : win.colourFor === "fg" ? Backend.fgColour : win.colourFor === "bg" ? Backend.bgColour
                                                  : win.colourFor === "fill2" ? win.fill2
                                                  : (win.p.count ? (win.colourFor === "fill" ? win.p.fill : win.p.stroke) : (win.colourFor === "fill" ? Backend.shapeStyle.fill : Backend.shapeStyle.stroke))
                onCurrentChanged: if (current) { var c = Qt.color(current); hue = Math.max(0, c.hsvHue); sat = c.hsvSaturation; val = c.hsvValue; hex.text = current }
                function send() { var c = Qt.hsva(hue, sat, val, 1); var s = c.toString(); hex.text = s
                    if (win.colourFor === "fg" || win.colourFor === "bg") Backend.setColour(win.colourFor, s); else Backend.setStyle(win.colourFor, s) }
                Rectangle { id: sv; width: parent.width - 40; height: 200; radius: 8; color: Qt.hsva(picker.hue, 1, 1, 1)
                    Rectangle { anchors.fill: parent; radius: 8; gradient: Gradient { orientation: Gradient.Horizontal; GradientStop { position: 0; color: "#FFFFFFFF" } GradientStop { position: 1; color: "#00FFFFFF" } } }
                    Rectangle { anchors.fill: parent; radius: 8; gradient: Gradient { GradientStop { position: 0; color: "#00000000" } GradientStop { position: 1; color: "#FF000000" } } }
                    Rectangle { x: picker.sat * parent.width - 8; y: (1 - picker.val) * parent.height - 8; width: 16; height: 16; radius: 8; color: "transparent"; border.width: 2; border.color: "#FFFFFF" }
                    MouseArea { anchors.fill: parent
                        function at(m) { picker.sat = Math.max(0, Math.min(1, m.x / width)); picker.val = 1 - Math.max(0, Math.min(1, m.y / height)); picker.send() }
                        onPressed: function (m) { at(m) } onPositionChanged: function (m) { at(m) } } }
                Rectangle { x: sv.width + 14; width: 26; height: 200; radius: 8
                    gradient: Gradient { GradientStop { position: 0; color: "#FF0000" } GradientStop { position: 0.17; color: "#FFFF00" } GradientStop { position: 0.33; color: "#00FF00" }
                                         GradientStop { position: 0.5; color: "#00FFFF" } GradientStop { position: 0.67; color: "#0000FF" } GradientStop { position: 0.83; color: "#FF00FF" } GradientStop { position: 1; color: "#FF0000" } }
                    Rectangle { y: picker.hue * parent.height - 3; width: parent.width; height: 6; radius: 3; color: "transparent"; border.width: 2; border.color: "#FFFFFF" }
                    MouseArea { anchors.fill: parent; function at(m) { picker.hue = Math.max(0, Math.min(0.999, m.y / height)); picker.send() }
                        onPressed: function (m) { at(m) } onPositionChanged: function (m) { at(m) } } }
                Row { y: 216; spacing: 10
                    Rectangle { width: 36; height: 30; radius: 8; color: picker.current || "transparent"; border.width: 1; border.color: Theme.t.islandLine }
                    TextBox { id: hex; width: 120; mono: true; onAccepted: { if (win.colourFor === "fg" || win.colourFor === "bg") Backend.setColour(win.colourFor, text); else Backend.setStyle(win.colourFor, text) } }
                    Btn { visible: win.colourFor === "fill" || win.colourFor === "stroke"; text: "None"; onClicked: Backend.setStyle(win.colourFor, "") } } }
            // --- a size, an amount, a name
            Column { visible: ["custom", "canvas", "imagesize", "filter", "feather", "grow", "rename"].indexOf(card.kind) >= 0; x: 24; y: 58; width: parent.width - 48; spacing: 12
                Row { visible: ["custom", "canvas", "imagesize"].indexOf(card.kind) >= 0; spacing: 10
                    Column { spacing: 4; Label { text: "Width (px)"; secondary: true; font.pixelSize: 11 } TextBox { id: wBox; width: 120; text: win.sheetData.w || ""
                        onEdited: if (card.kind === "imagesize" && win.sheetData.keep && Number(text) > 0) hBox.text = String(Math.round(Number(text) * Backend.docH / Backend.docW)) } }
                    Column { spacing: 4; Label { text: "Height (px)"; secondary: true; font.pixelSize: 11 } TextBox { id: hBox; width: 120; text: win.sheetData.h || "" } }
                    Column { visible: card.kind === "imagesize"; spacing: 4; Label { text: "Keep the shape"; secondary: true; font.pixelSize: 11 }
                        Toggle { on: !!win.sheetData.keep; onToggled: function (v) { var d = win.sheetData; d.keep = v; win.sheetData = d } } } }
                Grid { visible: card.kind === "canvas"; columns: 3; spacing: 4
                    Repeater { model: ["tl", "t", "tr", "l", "c", "r", "bl", "b", "br"]
                        Rectangle { required property string modelData; width: 26; height: 26; radius: 6; color: win.sheetData.anchor === modelData ? Theme.t.accent : Theme.t.group; border.width: 1; border.color: Theme.t.islandLine
                            MouseArea { anchors.fill: parent; onClicked: { var d = win.sheetData; d.anchor = modelData; win.sheetData = d } } } } }
                Label { visible: card.kind === "canvas"; text: "Where the picture sits on the new canvas"; secondary: true; font.pixelSize: 11 }
                Row { visible: ["filter", "feather", "grow"].indexOf(card.kind) >= 0; spacing: 10
                    Label { text: card.kind === "feather" ? "Softness" : card.kind === "grow" ? "Shrink · Grow" : "Amount"; anchors.verticalCenter: parent.verticalCenter }
                    SetSlider { id: amount; width: 240; value: win.sheetData.v !== undefined ? win.sheetData.v : 0.4; onMoved: function (v) { var d = win.sheetData; d.v = v; win.sheetData = d } }
                    Label { text: card.kind === "feather" ? Math.round(amount.live * 50) + " px" : card.kind === "grow" ? Math.round((amount.live - 0.5) * 60) + " px" : Math.round(amount.live * 100) + "%"; font.family: Theme.t.fontMono; anchors.verticalCenter: parent.verticalCenter } }
                TextBox { visible: card.kind === "rename"; id: nameBox; width: parent.width; text: win.sheetData.name || ""; onAccepted: okBtn.clicked() } }
            // --- the file browser for open, save and export
            Item { visible: card.browsing; x: 16; y: 54; width: parent.width - 32; height: parent.height - 54 - (card.kind === "open" ? 64 : card.kind === "export" ? 168 : 140)
                Row { id: crumbs; x: 8; spacing: 6; height: 30
                    Seg { icon: "up"; tip: "Up a folder"; onClicked: { var p = win.browseAt.replace(/\/[^\/]+\/?$/, ""); win.browseAt = p || "/" } }
                    Seg { icon: "home"; tip: "Home"; onClicked: win.browseAt = Backend.home }
                    Seg { icon: "image"; tip: "Pictures"; onClicked: win.browseAt = Backend.home + "/Pictures" }
                    Label { anchors.verticalCenter: parent.verticalCenter; text: win.browseAt.replace(Backend.home, "~"); width: card.width - 180; elide: Text.ElideLeft; font.pixelSize: 12 } }
                ListView { id: files; y: 36; width: parent.width; height: parent.height - 36; clip: true; boundsBehavior: Flickable.StopAtBounds
                    model: card.browsing && win.browseAt ? Backend.browse(win.browseAt) : []
                    delegate: Pressable { required property var modelData; width: files.width; height: 36; radius: 9; color: hovered ? Theme.t.hover : "transparent"
                        onClicked: modelData.dir ? win.browseAt = modelData.path : (card.kind === "open" ? (win.sheet = "", Backend.open(modelData.path)) : saveName.text = modelData.name.replace(/\.[^.]+$/, ""))
                        Glyph { x: 10; anchors.verticalCenter: parent.verticalCenter; name: modelData.dir ? "folder" : "image"; size: 15; ink: modelData.dir ? Theme.t.icon : Theme.t.accent }
                        Label { x: 36; width: parent.width - 50; elide: Text.ElideMiddle; anchors.verticalCenter: parent.verticalCenter; text: modelData.name; font.pixelSize: 12 } } } }
            Column { visible: card.kind === "save" || card.kind === "export"; x: 24; anchors { bottom: parent.bottom; bottomMargin: 70 } width: parent.width - 48; spacing: 8
                Row { spacing: 10
                    TextBox { id: saveName; width: 240; text: win.sheetData.name || ""; placeholder: "Name"; onAccepted: okBtn.clicked() }
                    SetChoice { visible: card.kind === "export"; each: 46; value: win.sheetData.format || "png"
                        options: [["png", "PNG"], ["jpg", "JPEG"], ["webp", "WebP"], ["svg", "SVG"], ["pdf", "PDF"], ["psd", "PSD"], ["ora", "ORA"]]
                        onPicked: function (v) { var d = win.sheetData; d.format = v; win.sheetData = d } } }
                Label { visible: card.kind === "export"; secondary: true; font.pixelSize: 11; width: parent.width; wrapMode: Text.WordWrap
                    text: ({ png: "Every pixel exactly, see-through parts kept.", jpg: "Small files for photos; no see-through parts.", webp: "Small files, see-through parts kept.",
                             svg: "Shapes and type stay sharp at any size; pixel layers go in as pictures.", pdf: "For printing: shapes and type stay sharp.",
                             psd: "Layers, blend modes and opacity, for Photoshop and anything that reads its files; shapes and type go in as pictures.",
                             ora: "Layers, blend modes and opacity, for Krita, GIMP and MyPaint." })[win.sheetData.format || "png"] }
                Label { visible: card.kind === "save"; secondary: true; font.pixelSize: 11; text: "An .easel file keeps every layer, mask and shape, ready to change later." } }
            Row { anchors { right: parent.right; rightMargin: 20; bottom: parent.bottom; bottomMargin: 18 } spacing: 8
                Btn { text: "Cancel"; visible: card.kind !== "new" || Backend.hasDoc; onClicked: win.sheet = "" }
                Btn { id: okBtn; primary: true; visible: ["custom", "canvas", "imagesize", "filter", "feather", "grow", "rename", "save", "export"].indexOf(card.kind) >= 0
                    text: ({ custom: "Make", canvas: "Change", imagesize: "Resize", filter: "Apply", feather: "Feather", grow: "Change", rename: "Rename", save: "Save", export: "Export" })[card.kind] || "OK"
                    onClicked: win.finishSheet() }
                Btn { visible: card.kind === "colour"; text: "Done"; primary: true; onClicked: win.sheet = "" } }
            // the "new" sheet over an open picture: the same presets
            Flow { visible: card.kind === "new"; x: 20; y: 58; width: parent.width - 40; spacing: 8
                Repeater { model: card.kind === "new" ? Backend.presets : []
                    Pressable { required property var modelData; width: 140; height: 46; radius: 10; color: hovered ? Theme.t.hover : Theme.t.group
                        onClicked: { win.sheet = ""; Backend.newDoc(modelData.w, modelData.h, "#FFFFFF") }
                        Column { x: 10; anchors.verticalCenter: parent.verticalCenter
                            Label { text: modelData.name; font.pixelSize: 12; font.weight: Font.DemiBold }
                            Label { text: modelData.w + " × " + modelData.h; font.pixelSize: 10; secondary: true } } } }
                Pressable { width: 140; height: 46; radius: 10; color: hovered ? Theme.t.hover : Theme.t.group; onClicked: win.open("custom", { w: "1600", h: "1200" })
                    Label { x: 10; anchors.verticalCenter: parent.verticalCenter; text: "Your own size…"; font.pixelSize: 12; font.weight: Font.DemiBold } } }
        } }
    function pickFromList(kind, id) {
        sheet = ""
        if (kind === "brushes") Backend.setBrushPreset(id)
        else if (kind === "blend") Backend.setLayer(Backend.activeLayer.id, "blend", id)
        else if (kind === "fonts") Backend.setTextStyle("font", id)
        else if (kind === "adjust") Backend.addAdjustment(id)
        else if (kind === "combine") Backend.combine(id)
        else if (kind === "arrange") { if (id === "del") Backend.deleteShapes(); else if (id === "outline") { Backend.outline(); Backend.setTool("nodes") } else if (id === "onpath") Backend.textOnPath(); else if (id === "offpath") Backend.textOffPath(); else if (id.indexOf("a:") === 0) Backend.align(id.slice(2)); else Backend.arrange(id) }
        else if (kind === "layer") {
            if (id.indexOf("mask:") === 0) Backend.addMask(id.slice(5))
            else ({ editmask: function () { Backend.editMask(true) }, applymask: Backend.applyMask, deletemask: Backend.deleteMask, duplicate: Backend.duplicateLayer,
                    merge: Backend.mergeDown, rasterise: Backend.rasterize, delete: Backend.deleteLayer })[id]()
        }
    }
    function finishSheet() {
        var k = sheet, d = sheetData
        if (k === "custom") { sheet = ""; Backend.newDoc(Number(wBox.text) || 1600, Number(hBox.text) || 1200, Backend.hasDoc ? "#FFFFFF" : startBg.value) }
        else if (k === "canvas") { sheet = ""; Backend.canvasSize(Number(wBox.text), Number(hBox.text), d.anchor || "c"); view.fit() }
        else if (k === "imagesize") { sheet = ""; Backend.imageSize(Number(wBox.text), Number(hBox.text)); view.fit() }
        else if (k === "filter") { sheet = ""; Backend.applyFilter(d.id, d.v !== undefined ? d.v : 0.4) }
        else if (k === "feather") { sheet = ""; Backend.feather((d.v !== undefined ? d.v : 0.2) * 50) }
        else if (k === "grow") { sheet = ""; Backend.growSelection(Math.round(((d.v !== undefined ? d.v : 0.5) - 0.5) * 60)) }
        else if (k === "rename") { sheet = ""; Backend.setLayer(d.id, "name", nameBox.text) }
        else if (k === "save") { if (!saveName.text.trim()) return; sheet = ""; Backend.saveAs(browseAt + "/" + saveName.text.trim()) }
        else if (k === "export") { if (!saveName.text.trim()) return; sheet = ""; var f = d.format || "png"; Backend.exportAs(browseAt + "/" + saveName.text.trim().replace(/\.[^.]+$/, "") + "." + f, 90) }
    }
}
