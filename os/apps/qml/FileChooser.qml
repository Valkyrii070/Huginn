import QtQuick
import QtQuick.Window

// Huginn's Open and Save window, for every app (through the desktop portal). The places down the left (Recent, Home
// and its folders, drives); a path to click back along, back and forward, search and list-or-pictures at the top;
// the folder in the middle, folders first; a preview at the right for one file; and an island at the bottom with
// the filter, the app's own choices and the answer. Saving adds a name (the extension follows the filter), New
// Folder, and a question before replacing anything.
GlassWindow {
    id: win
    title: Chooser.title
    heading: Chooser.app ? "for " + Chooser.app.replace(/^.*\./, "") : ""
    width: 960; height: 600; minimumWidth: 720; minimumHeight: 440
    visible: Chooser.active
    glow: "left"
    flags: Qt.Dialog | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
    property var picked: ({})              // path → true
    property int anchorRow: -1
    property string ask: ""                // "replace": the name exists already
    property string problem: ""
    property bool making: false            // New Folder's name field is showing
    readonly property var pickedPaths: Object.keys(picked)
    readonly property var one: pickedPaths.length === 1 ? Chooser.rows.filter(function (r) { return r.path === pickedPaths[0] })[0] : null
    readonly property bool saving: Chooser.mode === "save"
    readonly property bool chips: Chooser.filters.length <= (win.saving ? 2 : 3) && win.width >= 900
    readonly property int strip: Chooser.choices.length > 0 ? 46 : 0      // room for the app's own choices
    onClosing: function (close) { Chooser.cancel() }
    onVisibleChanged: if (visible) { picked = {}; anchorRow = -1; ask = ""; problem = ""; making = false
        nameBox.text = Chooser.name; Qt.callLater(function () { if (win.saving) { nameBox.focusIn(); nameBox.input.select(0, win.stem(Chooser.name)) } else listView.forceActiveFocus(); win.requestActivate() }) }
    Connections { target: Chooser; function onListed() { win.picked = {}; win.anchorRow = -1 }
        function onChanged() { if (win.saving && nameBox.text !== Chooser.name && !nameBox.input.activeFocus) nameBox.text = Chooser.name } }

    function stem(n) { var i = n.lastIndexOf("."); return i > 0 ? i : n.length }
    function pick(i, mods) {
        var r = Chooser.rows[i]
        if (!r) return
        var next = {}
        if ((mods & Qt.ControlModifier) && Chooser.multiple) {
            for (var k in picked) next[k] = true
            if (next[r.path]) delete next[r.path]; else next[r.path] = true
            anchorRow = i
        } else if ((mods & Qt.ShiftModifier) && Chooser.multiple && anchorRow >= 0) {
            for (var j = Math.min(anchorRow, i); j <= Math.max(anchorRow, i); j++) next[Chooser.rows[j].path] = true
        } else {
            next[r.path] = true
            anchorRow = i
        }
        picked = next
        if (win.saving && !r.dir) nameBox.text = r.name
    }
    function activate(i) {
        var r = Chooser.rows[i]
        if (!r) return
        if (r.dir) Chooser.open(r.path)
        else if (Chooser.mode === "open") Chooser.accept([r.path])
        else if (win.saving) { nameBox.text = r.name; win.go() }
    }
    function go() {
        problem = ""
        if (Chooser.mode === "saveFiles") { Chooser.saveHere(); return }
        if (win.saving) {
            var said = Chooser.save(nameBox.text)
            if (said === "exists") ask = "replace"
            else if (said === "folder") nameBox.text = Chooser.name
            else problem = said
            return
        }
        Chooser.accept(pickedPaths)
    }

    // ================================================================ the places
    Column {
        id: side
        x: 14; y: 62; width: 186; spacing: 2
        Label { text: "Places"; secondary: true; font.pixelSize: 11; font.weight: Font.DemiBold; leftPadding: 10; bottomPadding: 4 }
        Seg { fill: true; objectName: "place-recent"; visible: Chooser.mode === "open" && !Chooser.directory; text: "Recent"; icon: "history"; on: Chooser.recent; onClicked: Chooser.showRecent() }
        Repeater { model: Chooser.places
            Seg { required property var modelData; fill: true; objectName: "place-" + modelData.name; text: modelData.name; icon: modelData.glyph
                on: !Chooser.recent && Chooser.folder === modelData.path; onClicked: Chooser.open(modelData.path) } }
        Label { visible: Chooser.drives.length > 0; text: "Drives"; secondary: true; font.pixelSize: 11; font.weight: Font.DemiBold; leftPadding: 10; topPadding: 12; bottomPadding: 4 }
        Repeater { model: Chooser.drives
            Seg { required property var modelData; fill: true; text: modelData.name; icon: modelData.glyph; on: Chooser.folder === modelData.path; onClicked: Chooser.open(modelData.path) } }
        Seg { fill: true; text: "Computer"; icon: "disc"; on: !Chooser.recent && Chooser.folder === "/"; onClicked: Chooser.open("/") }
    }
    Rectangle { x: 210; y: 56; width: 1; height: parent.height - 120; color: Theme.t.separator }

    // ================================================================ along the top
    Row {
        id: top
        x: 226; y: 14; spacing: 6; height: 36
        Seg { icon: "back"; tip: "Back"; enabled: Chooser.canBack; opacity: enabled ? 1 : 0.4; onClicked: Chooser.back() }
        Seg { icon: "forward"; tip: "Forward"; enabled: Chooser.canForward; opacity: enabled ? 1 : 0.4; onClicked: Chooser.forward() }
        Row { objectName: "crumbs"; spacing: 0; anchors.verticalCenter: parent.verticalCenter
            Label { visible: Chooser.recent; text: "Recent"; font.pixelSize: 14; font.weight: Font.DemiBold; leftPadding: 6 }
            Repeater { model: Chooser.crumbs
                Row { required property var modelData; required property int index; spacing: 0
                    Label { visible: index > 0; text: "›"; secondary: true; font.pixelSize: 14; anchors.verticalCenter: parent.verticalCenter; leftPadding: 2; rightPadding: 2 }
                    Seg { objectName: "crumb-" + modelData.name; text: modelData.name; on: index === Chooser.crumbs.length - 1; onClicked: Chooser.open(modelData.path) } } } }
    }
    Row {
        anchors { right: parent.right; rightMargin: 14 } y: 14; spacing: 6; height: 36
        TextBox { id: searchBox; objectName: "search"; width: 200; height: 32; placeholder: "Search this folder"; anchors.verticalCenter: parent.verticalCenter
            onEdited: Chooser.search(text) }
        Island { anchors.verticalCenter: parent.verticalCenter; height: 34
            Seg { objectName: "viewList"; icon: "list"; tip: "As a list"; on: !Chooser.grid; onClicked: Chooser.setGrid(false) }
            Seg { objectName: "viewGrid"; icon: "grid"; tip: "As pictures"; on: Chooser.grid; onClicked: Chooser.setGrid(true) } }
    }

    // ================================================================ the folder
    Item {
        id: middle
        x: 222; y: 58; width: parent.width - x - (preview.visible ? preview.width + 22 : 14); height: parent.height - y - 76 - win.strip
        // New Folder: its name, right here
        Rectangle { id: maker; visible: win.making; width: parent.width; height: 44; radius: 12; color: Theme.t.group; border.width: 1; border.color: Theme.t.islandLine
            Row { x: 10; anchors.verticalCenter: parent.verticalCenter; spacing: 8
                Glyph { name: "folder"; size: 18; anchors.verticalCenter: parent.verticalCenter }
                TextBox { id: folderName; objectName: "folderName"; width: 260; height: 30; placeholder: "Name of the new folder"
                    onAccepted: { var e = Chooser.newFolder(text); if (e) win.problem = e; else { win.making = false; Chooser.open(Chooser.folder + "/" + text.trim()) } } }
                Btn { primary: true; text: "Create"; anchors.verticalCenter: parent.verticalCenter; onClicked: folderName.accepted() }
                Btn { text: "Cancel"; anchors.verticalCenter: parent.verticalCenter; onClicked: win.making = false } } }
        // the list's heading: click to sort
        Row {
            id: heads
            visible: !Chooser.grid
            y: win.making ? 52 : 0; x: 44; height: 26
            Repeater { model: [{ key: "name", label: "Name", w: middle.width - 44 - 320 }, { key: "kind", label: "Kind", w: 130 }, { key: "size", label: "Size", w: 80 }, { key: "date", label: "Modified", w: 110 }]
                Item { required property var modelData; width: modelData.w; height: 26
                    Label { text: parent.modelData.label + (Chooser.sort === parent.modelData.key ? " ▾" : ""); font.pixelSize: 11; font.weight: Font.DemiBold
                        color: Chooser.sort === parent.modelData.key ? Theme.t.text : Theme.t.text_secondary; anchors.verticalCenter: parent.verticalCenter }
                    MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: Chooser.sortBy(parent.modelData.key) } } }
        }
        Label { visible: Chooser.rows.length === 0; anchors.centerIn: parent; secondary: true
            text: Chooser.query ? "Nothing here is called “" + Chooser.query + "”" : Chooser.recent ? "No files used lately" : "This folder is empty" }
        ListView {
            id: listView
            objectName: "list"
            visible: !Chooser.grid
            anchors { fill: parent; topMargin: heads.y + 28 }
            clip: true; spacing: 1; boundsBehavior: Flickable.StopAtBounds
            model: Chooser.rows
            keyNavigationEnabled: false
            Keys.onPressed: function (e) { win.keys(e) }
            delegate: Rectangle {
                required property var modelData
                required property int index
                objectName: "row-" + modelData.name
                width: listView.width; height: 34; radius: 9
                readonly property bool on: !!win.picked[modelData.path]
                color: on ? Theme.t.accent : (rh.containsMouse ? Theme.t.hover : (index % 2 ? "transparent" : Qt.alpha(Theme.t.hover, 0.35)))
                Item { x: 12; width: 22; height: parent.height
                    Glyph { anchors.centerIn: parent; visible: !thumb.visible; name: modelData.glyph; size: 17; ink: parent.parent.on ? Theme.t.onAccent : modelData.dir ? Theme.t.accent : Theme.t.icon }
                    Image { id: thumb; anchors.centerIn: parent; width: 22; height: 22; source: modelData.picture; sourceSize: Qt.size(44, 44); asynchronous: true
                        fillMode: Image.PreserveAspectCrop; visible: status === Image.Ready } }
                Row { x: 44; height: parent.height
                    Label { width: middle.width - 44 - 320; text: modelData.name; elide: Text.ElideMiddle; anchors.verticalCenter: parent.verticalCenter
                        color: parent.parent.on ? Theme.t.onAccent : Theme.t.text; font.weight: modelData.dir ? Font.DemiBold : Font.Normal }
                    Label { width: 130; text: modelData.kind; elide: Text.ElideRight; font.pixelSize: 12; anchors.verticalCenter: parent.verticalCenter; color: parent.parent.on ? Theme.t.onAccent : Theme.t.text_secondary }
                    Label { width: 80; text: modelData.sizeText; font.pixelSize: 12; anchors.verticalCenter: parent.verticalCenter; color: parent.parent.on ? Theme.t.onAccent : Theme.t.text_secondary }
                    Label { width: 110; text: modelData.when; font.pixelSize: 12; anchors.verticalCenter: parent.verticalCenter; color: parent.parent.on ? Theme.t.onAccent : Theme.t.text_secondary } }
                MouseArea { id: rh; anchors.fill: parent; hoverEnabled: true
                    onClicked: function (m) { listView.forceActiveFocus(); win.pick(index, m.modifiers) }
                    onDoubleClicked: win.activate(index) }
            }
        }
        GridView {
            id: gridView
            objectName: "grid"
            visible: Chooser.grid
            anchors { fill: parent; topMargin: win.making ? 52 : 0 }
            clip: true; cellWidth: Math.floor(width / Math.max(1, Math.floor(width / 132))); cellHeight: 132
            model: Chooser.rows
            Keys.onPressed: function (e) { win.keys(e) }
            delegate: Item {
                required property var modelData
                required property int index
                width: gridView.cellWidth; height: 132
                readonly property bool on: !!win.picked[modelData.path]
                Rectangle { anchors { fill: parent; margins: 5 } radius: 14; color: parent.on ? Qt.alpha(Theme.t.accent, 0.25) : (gh.containsMouse ? Theme.t.hover : "transparent")
                    border.width: parent.on ? 1.5 : 0; border.color: Theme.t.accent }
                Item { x: (parent.width - 84) / 2; y: 10; width: 84; height: 84
                    Glyph { anchors.centerIn: parent; visible: big.status !== Image.Ready; name: modelData.glyph; size: 44; ink: modelData.dir ? Theme.t.accent : Theme.t.icon }
                    Image { id: big; anchors.fill: parent; source: modelData.picture; sourceSize: Qt.size(168, 168); asynchronous: true; fillMode: Image.PreserveAspectFit; smooth: true } }
                Label { x: 8; y: 100; width: parent.width - 16; horizontalAlignment: Text.AlignHCenter; text: modelData.name; elide: Text.ElideMiddle; font.pixelSize: 12 }
                MouseArea { id: gh; anchors.fill: parent; hoverEnabled: true
                    onClicked: function (m) { gridView.forceActiveFocus(); win.pick(index, m.modifiers) }
                    onDoubleClicked: win.activate(index) }
            }
        }
    }
    function keys(e) {
        if (e.key === Qt.Key_Return || e.key === Qt.Key_Enter) { if (win.pickedPaths.length === 1 && win.one && win.one.dir && !Chooser.directory) Chooser.open(win.one.path); else win.go(); e.accepted = true }
        else if (e.key === Qt.Key_Backspace || (e.key === Qt.Key_Up && (e.modifiers & Qt.AltModifier))) { Chooser.up(); e.accepted = true }
        else if (e.key === Qt.Key_H && (e.modifiers & Qt.ControlModifier)) { Chooser.showHidden(!Chooser.hidden); e.accepted = true }
        else if (e.key === Qt.Key_Escape) { Chooser.cancel(); e.accepted = true }
        else if (e.key === Qt.Key_Down || e.key === Qt.Key_Up) {
            var i = Math.max(0, Math.min(Chooser.rows.length - 1, win.anchorRow + (e.key === Qt.Key_Down ? 1 : -1)))
            win.pick(i, e.modifiers); listView.positionViewAtIndex(i, ListView.Contain); e.accepted = true }
    }
    Shortcut { sequence: "Escape"; onActivated: Chooser.cancel() }

    // ================================================================ one file, up close
    Rectangle {
        id: preview
        objectName: "preview"
        visible: win.width >= 900 && win.one !== null && win.one !== undefined && !win.one.dir
        x: parent.width - width - 14; y: 58; width: 220; height: middle.height; radius: 16
        color: Theme.t.group; border.width: 1; border.color: Theme.t.islandLine
        Column { x: 14; y: 14; width: parent.width - 28; spacing: 8
            Item { width: parent.width; height: 160
                Image { id: pv; anchors.fill: parent; source: win.one ? win.one.picture : ""; sourceSize: Qt.size(384, 320); fillMode: Image.PreserveAspectFit; asynchronous: true }
                Glyph { anchors.centerIn: parent; visible: pv.status !== Image.Ready; name: win.one ? win.one.glyph : "file"; size: 64 } }
            Label { width: parent.width; text: win.one ? win.one.name : ""; wrapMode: Text.WrapAnywhere; font.weight: Font.DemiBold; horizontalAlignment: Text.AlignHCenter }
            Label { width: parent.width; text: win.one ? win.one.kind + " · " + win.one.sizeText : ""; secondary: true; font.pixelSize: 12; horizontalAlignment: Text.AlignHCenter; wrapMode: Text.WordWrap }
            Label { width: parent.width; text: win.one ? "Modified " + win.one.when : ""; secondary: true; font.pixelSize: 12; horizontalAlignment: Text.AlignHCenter } }
    }

    // ================================================================ replacing?
    Rectangle {
        visible: win.ask === "replace"
        objectName: "replaceAsk"
        anchors { left: middle.left; right: parent.right; rightMargin: 14 } y: parent.height - 120 - win.strip; height: 48; radius: 14; z: 8
        color: Qt.alpha(Theme.t.danger, 0.16); border.width: 1; border.color: Theme.t.danger
        Label { x: 16; anchors.verticalCenter: parent.verticalCenter; width: parent.width - 220; elide: Text.ElideRight
            text: "“" + nameBox.text.trim() + "” is already here. Replace it?" }
        Row { anchors { right: parent.right; rightMargin: 10; verticalCenter: parent.verticalCenter } spacing: 6
            Btn { text: "Cancel"; onClicked: win.ask = "" }
            Btn { objectName: "replaceYes"; danger: true; text: "Replace"; onClicked: { win.ask = ""; Chooser.replace(nameBox.text) } } }
    }

    // ================================================================ the answer, along the bottom
    Row {
        id: bottomLeft
        x: 222; y: parent.height - 56; height: 40; spacing: 10
        Label { visible: win.saving; text: "Name"; anchors.verticalCenter: parent.verticalCenter; font.weight: Font.DemiBold }
        TextBox { id: nameBox; objectName: "name"; visible: win.saving; width: Math.max(180, Math.min(300, win.width - 720)); height: 34; anchors.verticalCenter: parent.verticalCenter
            onEdited: { Chooser.setName(text); win.problem = "" } onAccepted: win.go() }
        Label { visible: Chooser.mode === "saveFiles"; anchors.verticalCenter: parent.verticalCenter; width: 300; elide: Text.ElideRight
            text: Chooser.files.length + " file" + (Chooser.files.length === 1 ? "" : "s") + " into “" + Chooser.folderName + "”" }
        // the filter: a few as choices, many as a list that opens upwards
        Island { visible: Chooser.filters.length > 1 && !Chooser.directory; height: 34; anchors.verticalCenter: parent.verticalCenter
            Repeater { model: win.chips ? Chooser.filters : []
                Seg { required property var modelData; required property int index; objectName: "filter-" + index; text: modelData; on: index === Chooser.filterIndex
                    onClicked: { Chooser.setFilter(index); if (win.saving) nameBox.text = Chooser.name } } }
            Seg { objectName: "filterPick"; visible: !win.chips; text: Chooser.filters[Chooser.filterIndex] || ""; icon: "down"; onClicked: filterMenu.visible = !filterMenu.visible } }
        Label { visible: win.problem !== ""; text: win.problem; color: Theme.t.danger; font.pixelSize: 12; anchors.verticalCenter: parent.verticalCenter }
    }
    Row {
        objectName: "choices"
        x: 222; y: parent.height - 56 - win.strip; height: 40; spacing: 18; visible: win.strip > 0
        Repeater { model: Chooser.choices
            Row { id: choiceRow; required property var modelData; spacing: 6; anchors.verticalCenter: parent.verticalCenter
                Toggle { visible: modelData.options.length === 0; on: modelData.value === "true"; anchors.verticalCenter: parent.verticalCenter
                    onToggled: function (v) { Chooser.setChoice(modelData.id, v ? "true" : "false") } }
                Label { text: modelData.label; anchors.verticalCenter: parent.verticalCenter }
                Island { visible: modelData.options.length > 0; height: 32
                    Repeater { model: modelData.options
                        Seg { required property var modelData; objectName: "choice-" + choiceRow.modelData.id + "-" + modelData.id
                            text: modelData.label; on: choiceRow.modelData.value === modelData.id
                            onClicked: Chooser.setChoice(choiceRow.modelData.id, modelData.id) } } } } }
    }
    Rectangle {
        id: filterMenu
        visible: false; z: 9
        x: bottomLeft.x + (win.saving ? nameBox.width + 50 : 0); width: 260; height: fcol.height + 12; y: parent.height - 66 - height; radius: 14
        color: Theme.t.menu_bg; border.width: 1; border.color: Theme.t.menu_border
        Column { id: fcol; x: 6; y: 6; width: parent.width - 12
            Repeater { model: Chooser.filters
                Seg { required property var modelData; required property int index; fill: true; text: modelData; on: index === Chooser.filterIndex
                    onClicked: { Chooser.setFilter(index); filterMenu.visible = false; if (win.saving) nameBox.text = Chooser.name } } } }
    }
    Row {
        anchors { right: parent.right; rightMargin: 16 } y: parent.height - 54; spacing: 8
        Btn { visible: Chooser.mode !== "open" || Chooser.directory; objectName: "newFolder"; text: "New Folder"; onClicked: { win.making = true; folderName.text = ""; folderName.focusIn() } }
        Btn { objectName: "cancel"; text: "Cancel"; onClicked: Chooser.cancel() }
        Btn { objectName: "accept"; primary: true; text: Chooser.acceptLabel
            enabled: win.saving ? nameBox.text.trim() !== "" : (Chooser.directory || win.pickedPaths.length > 0 || Chooser.mode === "saveFiles")
            opacity: enabled ? 1 : 0.45
            onClicked: win.go() }
    }
}
