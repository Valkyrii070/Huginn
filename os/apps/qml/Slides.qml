import QtQuick

// Slides, "filmstrip island": the slide on a stage; the filmstrip is the island the light comes from.
GlassWindow {
    id: win
    title: "Slides"; heading: browsing ? "" : (Backend.title || ""); width: 1220; height: 780; glow: "bottom"; padTop: 60; bare: presenting
    sidebarWidth: browsing ? 232 : 0
    property bool browsing: Backend.current === ""
    property bool presenting: false
    property int showing: 0
    property string notice: ""
    property string exported: ""
    property bool adding: false
    property var shots: []
    readonly property var cur: Backend.count > 0 ? Backend.slides[Backend.index] : ({ layout: "blank", title: "", body: "", notes: "" })
    Connections { target: Backend
        function onFailed(msg) { win.notice = msg; hide.restart() } }
    Timer { id: hide; interval: 7000; onTriggered: { win.notice = ""; win.exported = "" } }
    onClosing: Backend.save()
    function present(from) { showing = from; presenting = true; showFullScreen(); stage.forceActiveFocus() }
    function stop() { presenting = false; showNormal() }
    function openFile() { Picker.open("Open a presentation", [["Presentations", "*.odp *.pptx"]], function (paths) { if (paths.length) Backend.open(paths[0]) }) }
    function newSlide() { if (Backend.current !== "") Backend.add("content") }
    function duplicateSlide() { if (Backend.current !== "") Backend.duplicate() }
    function deleteSlide() { if (Backend.current !== "" && Backend.count > 1) Backend.remove() }
    // PDF export: draw each slide off-screen at full HD, then bind the pictures into one file.
    function exportPdf() { shots = []; folder = Backend.scratch(); step(0) }
    property string folder: ""
    function step(i) {
        if (i >= Backend.count) { var p = Backend.pdf(shots); if (p) { exported = p; hide.restart() } return }
        printer.slide = Backend.slides[i]
        Qt.callLater(function () { printer.grabToImage(function (r) { var f = folder + "/slide-" + ("000" + i).slice(-4) + ".png"; if (r.saveToFile(f)) { shots = shots.concat([f]); step(i + 1) } else { notice = "A slide couldn't be drawn for the PDF."; hide.restart() } }, Qt.size(1920, 1080)) })
    }
    SlideFace { id: printer; x: -4000; width: 960; theme: Backend.theme }

    sidebar: [ DocList { newLabel: "New Presentation"; icon: "slides"; empty: "Presentations you make appear here, along with PowerPoint files in your Documents folder." } ]
    islands: [
        Island {   // the filmstrip: the main island
            visible: !win.browsing; height: 76; radius: 20; pad: 8; anchors { horizontalCenter: parent.horizontalCenter; bottom: parent.bottom; bottomMargin: 14 }
            Flickable { width: Math.min(nav.width, win.width - 150); height: 60; contentWidth: nav.width; clip: true; anchors.verticalCenter: parent.verticalCenter; flickableDirection: Flickable.HorizontalFlick
                Row { id: nav; spacing: 6
                    Repeater { model: Backend.slides
                        Rectangle { required property var modelData; required property int index; width: 104; height: 60; radius: 9; color: "transparent"; border.width: Backend.index === index ? 2 : 0; border.color: Theme.t.accent
                            SlideFace { x: 3; y: 3; width: 98; slide: modelData; theme: Backend.theme }
                            Rectangle { x: 6; y: 6; width: n.width + 8; height: 14; radius: 5; color: "#99000000"; Label { id: n; anchors.centerIn: parent; text: index + 1; color: "#FFFFFF"; font.pixelSize: 9; font.weight: Font.Bold } }
                            MouseArea { anchors.fill: parent; onClicked: Backend.select(index) } } } } }
            Seg { icon: "plus"; tip: "Add a slide"; on: win.adding; onClicked: win.adding = !win.adding }
        },
        Island {   // saved or not, and which slide
            visible: !win.browsing; anchors { left: parent.left; leftMargin: 14; bottom: parent.bottom; bottomMargin: 14 }
            Label { leftPadding: 10; rightPadding: 10; width: Math.min(implicitWidth, 300); elide: Text.ElideMiddle; font.pixelSize: 12; anchors.verticalCenter: parent.verticalCenter
                color: win.notice ? Theme.t.danger : Theme.t.text_secondary
                text: win.notice || (win.exported ? "Exported to " + win.exported : ((Backend.saved ? "Saved" : "Saving…") + "  ·  Slide " + (Backend.index + 1) + " of " + Backend.count)) } }
    ]
    toolbar: [
        ExportMenu { visible: !win.browsing; choices: [["pdf", "PDF", "One page per slide"], ["pptx", "PowerPoint", "A .pptx file: text and notes, plain design"]]
            onChosen: function (key) { if (key === "pdf") win.exportPdf(); else { var p = Backend.exportPowerPoint(); if (p) { win.exported = p; hide.restart() } } } },
        Seg { visible: !win.browsing; icon: "play"; text: "Present"; on: true; onClicked: win.present(Backend.index) },
        Row { visible: !win.browsing; spacing: 6; anchors.verticalCenter: parent.verticalCenter
            Repeater { model: [["realm", "#0F2624", "#17192C"], ["paper", "#FFFFFF", "#FFFFFF"], ["night", "#101317", "#101317"]]
                Rectangle { required property var modelData; width: 30; height: 20; radius: 5; border.width: Backend.theme === modelData[0] ? 2 : 1; border.color: Backend.theme === modelData[0] ? Theme.t.accent : Theme.t.capsule_border
                    gradient: Gradient { orientation: Gradient.Horizontal; GradientStop { position: 0; color: modelData[1] } GradientStop { position: 1; color: modelData[2] } }
                    MouseArea { anchors.fill: parent; onClicked: Backend.setTheme(parent.modelData[0]) } } } },
        Seg { visible: !win.browsing; icon: "trash"; tip: "Delete this slide"; opacity: Backend.count > 1 ? 1 : 0.4; onClicked: Backend.remove() },
        Seg { visible: !win.browsing; icon: "down"; tip: "Move slide later"; onClicked: Backend.move(1) },
        Seg { visible: !win.browsing; icon: "up"; tip: "Move slide earlier"; onClicked: Backend.move(-1) },
        Seg { visible: !win.browsing; icon: "back"; text: "All Presentations"; onClicked: { Backend.save(); win.browsing = true } }
    ]
    Connections { target: Backend; function onChanged() { if (Backend.current !== "" && win.browsing && Backend.count > 0 && !win.wasOpen) { win.browsing = false } win.wasOpen = Backend.current !== "" } }
    property bool wasOpen: Backend.current !== ""

    Column { visible: win.browsing; anchors.verticalCenter: parent.verticalCenter; x: win.middleX(width, parent.y + y, height) - parent.x; spacing: 10
        Item { width: 300; height: 170; anchors.horizontalCenter: parent.horizontalCenter      // three slides fanned out, the front one with a title on it
            Rectangle { x: 60; y: 0; width: 224; height: 126; radius: 10; color: Theme.t.island; border.width: 1; border.color: Theme.t.islandLine; rotation: 7; opacity: 0.5 }
            Rectangle { x: 44; y: 14; width: 224; height: 126; radius: 10; color: Theme.t.island; border.width: 1; border.color: Theme.t.islandLine; rotation: 3; opacity: 0.75 }
            Rectangle { x: 24; y: 32; width: 240; height: 135; radius: 10; border.width: 1; border.color: Theme.t.islandLine
                gradient: Gradient { GradientStop { position: 0; color: Theme.t.accent } GradientStop { position: 1; color: Qt.darker(Theme.t.accent, 1.9) } }
                Rectangle { x: 22; y: 44; width: 130; height: 12; radius: 4; color: "#FFFFFF" } Rectangle { x: 22; y: 66; width: 84; height: 6; radius: 3; color: "#B3FFFFFF" }
                Rectangle { x: 180; y: 86; width: 38; height: 38; radius: 19; color: "#33FFFFFF" } } }
        Label { text: Backend.current === "" ? "Start a presentation" : "Choose a presentation on the left"; font.pixelSize: 17; font.weight: Font.DemiBold; anchors.horizontalCenter: parent.horizontalCenter }
        Btn { text: "New Presentation"; primary: true; anchors.horizontalCenter: parent.horizontalCenter; onClicked: { Backend.create(); win.browsing = false } }
        Btn { visible: Backend.current !== ""; text: "Back to “" + Backend.title + "”"; anchors.horizontalCenter: parent.horizontalCenter; onClicked: win.browsing = false } }
    Item { visible: !win.browsing; anchors.fill: parent
        ImportNote { id: note; x: 16; y: 12; width: parent.width - 32; file: Backend.importedFile; dropped: Backend.importedDropped; onDismissed: Backend.dismissNote() }
        Item { id: canvas; x: 24; y: (note.visible ? note.height + 22 : 20); width: parent.width - 48; height: parent.height - y - 200
            SlideFace { id: main; anchors.centerIn: parent; width: Math.min(canvas.width, canvas.height * 16 / 9); slide: win.cur; theme: Backend.theme; editable: true
                onEdited: function (field, text) { Backend.write(Backend.index, field, text) } }
            Rectangle { anchors.fill: main; color: "transparent"; border.width: 1; border.color: Theme.t.dark ? "#000000" : "#C3C9D0" } }
        Rectangle { visible: win.adding; z: 20; anchors { bottom: parent.bottom; bottomMargin: 100; horizontalCenter: parent.horizontalCenter } width: 4 * 132 + 22; height: 120; radius: 16; color: Theme.t.menu_bg; border.width: 1; border.color: Theme.t.menu_border
            Row { x: 11; y: 11; spacing: 8
                Repeater { model: [["title", "Title", "Presentation title"], ["content", "Title & Text", "Heading"], ["section", "Section", "Section"], ["blank", "Blank", ""]]
                    Column { required property var modelData; spacing: 6
                        Rectangle { width: 124; height: 70 + 4; radius: 6; color: "transparent"; border.width: hit.containsMouse ? 2 : 1; border.color: hit.containsMouse ? Theme.t.accent : Theme.t.separator
                            SlideFace { x: 2; y: 2; width: 120; theme: Backend.theme; slide: ({ layout: modelData[0], title: modelData[2], body: modelData[0] === "content" ? "First point\nSecond point" : (modelData[0] === "title" ? "Subtitle" : "") }) }
                            MouseArea { id: hit; anchors.fill: parent; hoverEnabled: true; onClicked: { Backend.add(modelData[0]); win.adding = false } } }
                        Label { text: modelData[1]; font.pixelSize: 11; anchors.horizontalCenter: parent.horizontalCenter } } } } }
        Rectangle { x: 24; anchors { bottom: parent.bottom; bottomMargin: 102 } width: parent.width - 48; height: 86; radius: 12; color: Theme.t.group; border.width: 1; border.color: Theme.t.islandLine
            Label { x: 16; y: 8; text: "SPEAKER NOTES"; color: Theme.t.text_secondary; font.pixelSize: 10; font.weight: Font.DemiBold }
            Flickable { x: 16; y: 26; width: parent.width - 32; height: 54; contentHeight: notes.height; clip: true
                TextEdit { id: notes; width: parent.width; wrapMode: TextEdit.Wrap; color: Theme.t.text; font.family: Theme.t.font; font.pixelSize: 13; selectionColor: Theme.t.accent; selectByMouse: true
                    property int slot: Backend.index; property string source: win.cur.notes || ""
                    onSlotChanged: text = source; onSourceChanged: if (!activeFocus) text = source; Component.onCompleted: text = source
                    onTextChanged: if (activeFocus) Backend.write(Backend.index, "notes", text)
                    Label { visible: notes.text === ""; text: "Notes only you see while presenting"; color: Theme.t.text_secondary } } } }
    }
    // ---- presenting: the slide alone, full screen. Arrow keys or click to move, Esc to stop.
    Rectangle { id: stage; visible: win.presenting; anchors.fill: parent; z: 100; color: "#000000"; focus: win.presenting
        SlideFace { anchors.centerIn: parent; width: Math.min(parent.width, parent.height * 16 / 9); theme: Backend.theme; slide: Backend.count > 0 ? Backend.slides[Math.min(win.showing, Backend.count - 1)] : ({}) }
        MouseArea { anchors.fill: parent; acceptedButtons: Qt.LeftButton | Qt.RightButton; onClicked: function (m) { if (m.button === Qt.RightButton) win.showing = Math.max(0, win.showing - 1); else if (win.showing < Backend.count - 1) win.showing++; else win.stop() } }
        Keys.onPressed: function (e) {
            if (e.key === Qt.Key_Escape) win.stop()
            else if (e.key === Qt.Key_Right || e.key === Qt.Key_Down || e.key === Qt.Key_Space || e.key === Qt.Key_PageDown || e.key === Qt.Key_Return) { if (win.showing < Backend.count - 1) win.showing++; else win.stop() }
            else if (e.key === Qt.Key_Left || e.key === Qt.Key_Up || e.key === Qt.Key_PageUp || e.key === Qt.Key_Backspace) win.showing = Math.max(0, win.showing - 1)
            e.accepted = true }
        Label { anchors { bottom: parent.bottom; right: parent.right; margins: 14 } text: (win.showing + 1) + " / " + Backend.count; color: "#66FFFFFF"; font.pixelSize: 12 } }
}
