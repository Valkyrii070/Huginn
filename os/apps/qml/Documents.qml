import QtQuick
import QtQuick.Pdf

// Documents, "reader": everything you open that isn't a Writer document. A PDF is read; a plain text or code file is
// edited, with line numbers. Which one follows the file: you never choose. Pages and files are a rail at the left.
GlassWindow {
    id: win
    title: "Documents"; heading: Backend.current !== "" ? Backend.title + (Backend.edited ? "  •" : "") : ""; sidebarWidth: 196; glow: "left"; padTop: 58
    readonly property bool isText: Backend.kind === "text"
    readonly property bool isPdf: Backend.kind === "pdf"
    property bool pages: true
    readonly property bool showPages: pages && isPdf
    property bool wrap: false
    property string notice: ""
    property var asking: null                             // { what: "leave" or "changed", then: a path, "new", "close" or "" }
    property bool loading: false
    property bool sure: false
    readonly property string look: Theme.t.accent + Theme.t.text_secondary
    onLookChanged: restyle()
    PdfDocument { id: doc; source: Backend.currentUrl }
    Connections { target: Backend
        function onTextLoaded() { win.loading = true; editor.text = Backend.text; win.loading = false; editor.cursorPosition = 0; win.restyle() }
        function onFailed(msg) { win.notice = msg; hide.restart() } }
    Timer { id: hide; interval: 6000; onTriggered: win.notice = "" }
    Component.onCompleted: { loading = true; editor.text = Backend.text; loading = false; restyle() }
    function restyle() { Backend.style(editor.textDocument, { key: Theme.t.accent, comment: Theme.t.text_secondary, string: Theme.t.dark ? "#9BE564" : "#3F7D12", number: Theme.t.dark ? "#FFB020" : "#A16207" }) }
    function save(then) {                                 // true when it is saved; a file changed by something else asks first
        if (!isText || Backend.readOnly) return false
        var r = Backend.save(false)
        if (r === "changed") asking = { what: "changed", then: then || "" }
        return r === ""
    }
    function go(where) { if (Backend.edited) asking = { what: "leave", then: where }; else carryOn(where) }   // leaving a file with unsaved changes asks first
    function carryOn(where) { asking = null; if (where === "close") { sure = true; close() } else if (where === "new") Backend.newText(); else if (where !== "") Backend.open(where) }
    onClosing: function (c) { if (Backend.edited && !sure) { c.accepted = false; asking = { what: "leave", then: "close" } } }
    function findNext() {                                 // the next place the words appear, starting again from the top at the end
        var want = find.text.toLowerCase(); if (!want) return
        var all = editor.text.toLowerCase(), i = all.indexOf(want, editor.selectionEnd); if (i < 0) i = all.indexOf(want)
        if (i < 0) { notice = "“" + find.text + "” isn't in this file."; hide.restart(); return }
        notice = ""; editor.select(i, i + want.length)
    }
    Shortcut { sequences: [StandardKey.Save]; onActivated: win.save() }
    Shortcut { sequences: [StandardKey.Find]; onActivated: find.focusInput() }
    sidebar: [
        Pressable { width: parent.width; height: 34; radius: 11; color: Theme.t.accent; onClicked: win.go("new")
            Row { anchors.centerIn: parent; spacing: 6; Glyph { name: "plus"; size: 15; ink: Theme.t.onAccent; anchors.verticalCenter: parent.verticalCenter } Label { text: "New Text File"; color: Theme.t.onAccent; font.weight: Font.DemiBold; font.pixelSize: 12; anchors.verticalCenter: parent.verticalCenter } } },
        Row { visible: win.isPdf; spacing: 6; topPadding: 6; bottomPadding: 2
            Repeater { model: [["Pages", true], ["Files", false]]
                Pressable { required property var modelData; width: (win.sidebarWidth - 16) / 2; height: 28; radius: 9; color: win.pages === modelData[1] ? Theme.t.accent : "transparent"; onClicked: win.pages = modelData[1]
                    Label { anchors.centerIn: parent; text: modelData[0]; font.weight: win.pages === modelData[1] ? Font.DemiBold : Font.Normal; color: win.pages === modelData[1] ? Theme.t.onAccent : Theme.t.text } } } },
        Flickable { width: parent.width; height: Math.min(side.height, win.height - 64 - 14 - 96); contentHeight: side.height; clip: true
            Column { id: side; width: parent.width; spacing: 4; topPadding: 4
                Repeater { model: win.showPages ? [] : Backend.files
                    SideItem { required property var modelData; icon: modelData.kind === "pdf" ? "doc" : "edit"; text: modelData.name; selected: Backend.current === modelData.path; onClicked: if (Backend.current !== modelData.path) win.go(modelData.path) } }
                Repeater { model: win.showPages && doc.status === PdfDocument.Ready ? Math.min(doc.pageCount, 300) : 0
                    Pressable { required property int index; width: side.width; height: thumb.height + 30; radius: 9; color: view.currentPage === index ? Theme.t.hover : "transparent"; onClicked: view.goToPage(index)
                        Rectangle { id: thumb; y: 8; width: 120; height: 120 * (doc.pagePointSize(index).height / Math.max(1, doc.pagePointSize(index).width)); anchors.horizontalCenter: parent.horizontalCenter; color: "#FFFFFF"; border.width: view.currentPage === index ? 2 : 1; border.color: view.currentPage === index ? Theme.t.accent : Theme.t.separator
                            Image { anchors { fill: parent; margins: 1 } source: doc.source; currentFrame: index; sourceSize.width: 240; asynchronous: true } }
                        Label { anchors { top: thumb.bottom; topMargin: 4; horizontalCenter: parent.horizontalCenter } text: index + 1; secondary: true; font.pixelSize: 11 } } }
                Label { visible: !win.showPages && Backend.files.length === 0; leftPadding: 10; width: parent.width; wrapMode: Text.WordWrap; secondary: true; font.pixelSize: 12; text: "PDFs and text files in Documents and Downloads appear here." } } }
    ]
    islands: [
        Island {   // where you are in the file, how to look closer or find something, and Save
            visible: win.isPdf || win.isText; anchors { right: parent.right; rightMargin: 14; bottom: parent.bottom; bottomMargin: 14 }
            Label { visible: win.isPdf && doc.status === PdfDocument.Ready; leftPadding: 10; rightPadding: 6; secondary: true; font.pixelSize: 12; anchors.verticalCenter: parent.verticalCenter; text: "Page " + (view.currentPage + 1) + " of " + doc.pageCount }
            Seg { visible: win.isPdf; icon: "expand"; text: "Fit Width"; onClicked: view.scaleToWidth(view.width - 30, view.height) }
            Seg { visible: win.isPdf; icon: "plus"; tip: "Zoom in"; onClicked: view.renderScale = Math.min(5, view.renderScale * 1.2) }
            Label { visible: win.isText; leftPadding: 10; rightPadding: 6; secondary: true; font.pixelSize: 12; anchors.verticalCenter: parent.verticalCenter
                text: "Line " + editor.line + ", column " + editor.column + "  ·  " + Backend.language + "  ·  " + Backend.encoding }
            Seg { visible: Backend.current !== ""; icon: "mail"; tip: Backend.edited ? "Save, then send by Mail" : "Send by Mail"; onClicked: { if (Backend.edited) win.save(); Backend.sendByMail() } }
            Seg { visible: win.isText; text: "Wrap"; tip: "Wrap long lines"; on: win.wrap; onClicked: win.wrap = !win.wrap }
            IslandGap {}
            IslandField { id: find; placeholder: win.isText ? "Find in file" : "Find in document"; onTextChanged: if (win.isPdf) view.searchString = text; onAccepted: win.isPdf ? view.searchForward() : win.findNext() }
            Seg { visible: win.isText; text: Backend.readOnly ? "Read Only" : "Save"; on: Backend.edited; opacity: Backend.readOnly || !Backend.edited ? 0.55 : 1; onClicked: win.save() }
        },
        Island {   // something to tell you: a problem, or why the file can't be changed
            visible: win.notice !== "" || (win.isText && Backend.readOnly); x: 232; anchors { bottom: parent.bottom; bottomMargin: 14 }
            Label { leftPadding: 10; rightPadding: 10; font.pixelSize: 12; anchors.verticalCenter: parent.verticalCenter; width: Math.min(implicitWidth, win.width - 232 - 640); elide: Text.ElideRight
                color: win.notice ? Theme.t.danger : Theme.t.text_secondary; text: win.notice || Backend.why }
        }
    ]
    // ---------------- A text or code file: edit it
    Flickable { id: scroll; visible: win.isText; anchors.fill: parent; clip: true
        contentWidth: win.wrap ? width : Math.max(width, editor.x + editor.contentWidth + 40); contentHeight: editor.height + 100
        function follow(r) {
            if (r.y + 10 < contentY) contentY = Math.max(0, r.y); else if (r.y + r.height + 100 > contentY + height) contentY = r.y + r.height + 100 - height
            if (win.wrap) return
            var x = editor.x + r.x; if (x - 60 < contentX) contentX = Math.max(0, x - 60); else if (x + 40 > contentX + width) contentX = x + 40 - width }
        Text { id: gutter; visible: !win.wrap; x: 0; y: 10; width: 22 + String(editor.lineCount).length * 9; horizontalAlignment: Text.AlignRight; color: Theme.t.text_secondary; opacity: 0.7
            font.family: Theme.t.fontMono; font.pixelSize: 13; renderType: Text.NativeRendering
            text: { var n = editor.lineCount, all = new Array(n); for (var i = 0; i < n; i++) all[i] = i + 1; return all.join("\n") } }
        TextEdit { id: editor; objectName: "editor"; x: win.wrap ? 18 : gutter.width + 16; y: 10; focus: true
            width: win.wrap ? scroll.width - 36 : Math.max(contentWidth + 20, scroll.width - x - 10)
            readonly property string before: text.substring(0, cursorPosition)
            readonly property int line: before.split("\n").length
            readonly property int column: cursorPosition - before.lastIndexOf("\n")
            color: Theme.t.text; selectionColor: Theme.t.accent; selectedTextColor: Theme.t.onAccent; font.family: Theme.t.fontMono; font.pixelSize: 13
            wrapMode: win.wrap ? TextEdit.Wrap : TextEdit.NoWrap; textFormat: TextEdit.PlainText; readOnly: Backend.readOnly; selectByMouse: true; persistentSelection: true
            tabStopDistance: 4 * widest.advanceWidth
            onTextChanged: if (!win.loading) Backend.edit(text)
            onCursorRectangleChanged: scroll.follow(cursorRectangle)
            Keys.onPressed: function (e) {            // Enter keeps the line's indent
                if ((e.key !== Qt.Key_Return && e.key !== Qt.Key_Enter) || (e.modifiers & (Qt.ControlModifier | Qt.ShiftModifier)) || readOnly) return
                var start = text.lastIndexOf("\n", cursorPosition - 1) + 1, indent = /^[ \t]*/.exec(text.substring(start, cursorPosition))[0]
                if (indent) { remove(selectionStart, selectionEnd); insert(cursorPosition, "\n" + indent); e.accepted = true } }
            TextMetrics { id: widest; font: editor.font; text: " " } }
        MouseArea { y: editor.y + editor.height; width: scroll.contentWidth; height: Math.max(0, scroll.height - y); onClicked: { editor.forceActiveFocus(); editor.cursorPosition = editor.length } } }
    // ---------------- A PDF: read it
    PdfMultiPageView { id: view; anchors.fill: parent; document: doc; visible: win.isPdf && doc.status === PdfDocument.Ready
        onWidthChanged: fit.restart() }
    Timer { id: fit; interval: 120; onTriggered: if (doc.status === PdfDocument.Ready) view.scaleToWidth(view.width - 30, view.height) }
    Connections { target: doc; function onStatusChanged() { if (doc.status === PdfDocument.Ready) fit.restart() } }
    Column { visible: !win.isText && !(win.isPdf && doc.status === PdfDocument.Ready); anchors.verticalCenter: parent.verticalCenter; x: win.middleX(width, parent.y + y, height) - parent.x; spacing: 8; width: 400
        Item { width: 230; height: 170; anchors.horizontalCenter: parent.horizontalCenter      // a PDF and a text file, side by side on the desk
            Rectangle { x: 8; y: 14; width: 108; height: 142; radius: 6; rotation: -6; color: Theme.t.dark ? "#F4F1EA" : "#FFFFFF"; border.width: 1; border.color: Theme.t.islandLine
                Rectangle { x: 12; y: 14; width: 34; height: 16; radius: 4; color: Theme.t.accent; Label { anchors.centerIn: parent; text: "PDF"; color: Theme.t.onAccent; font.pixelSize: 9; font.weight: Font.Bold } }
                Rectangle { x: 12; y: 42; width: 84; height: 44; radius: 3; color: "#22000000" }
                Repeater { model: [80, 72, 54]; Rectangle { required property int modelData; required property int index; x: 12; y: 96 + index * 11; width: modelData; height: 4; radius: 2; color: "#33000000" } } }
            Rectangle { x: 112; y: 22; width: 108; height: 142; radius: 6; rotation: 5; color: Theme.t.island; border.width: 1; border.color: Theme.t.islandLine
                Repeater { model: [60, 84, 76, 84, 40, 80, 66]; Rectangle { required property int modelData; required property int index; x: 12; y: 18 + index * 13; width: modelData; height: 4; radius: 2; color: index === 0 ? Theme.t.accent : Theme.t.text_secondary; opacity: index === 0 ? 1 : 0.45 } } } }
        Label { anchors.horizontalCenter: parent.horizontalCenter; font.pixelSize: 17; font.weight: Font.DemiBold
            text: Backend.current === "" ? "No document open" : win.isPdf && doc.status === PdfDocument.Loading ? "Opening…" : "This file couldn't be opened" }
        Label { width: parent.width; horizontalAlignment: Text.AlignHCenter; wrapMode: Text.WordWrap; secondary: true
            text: Backend.current === "" ? "Open a PDF or a text file from Files, pick one on the left, or start a new text file."
                : !win.isPdf ? Backend.why
                : doc.status === PdfDocument.Error ? (doc.error === PdfDocument.IncorrectPasswordError ? "It is protected by a password, which isn't supported yet." : "The file may be damaged or isn't a PDF.") : "" } }
    // ---------------- Before unsaved changes are lost, or someone else's are overwritten: ask
    Rectangle { visible: win.asking !== null; anchors { fill: parent; topMargin: -58; leftMargin: -220 } radius: win.r; color: "#66000000"; z: 30; MouseArea { anchors.fill: parent } }
    Rectangle { visible: win.asking !== null; z: 31; anchors.centerIn: parent; width: 440; height: 168; radius: 16; color: Theme.t.menu_bg; border.width: 1; border.color: Theme.t.menu_border
        readonly property bool clash: !!win.asking && win.asking.what === "changed"
        Label { x: 22; y: 20; width: parent.width - 44; elide: Text.ElideMiddle; font.pixelSize: 16; font.weight: Font.DemiBold
            text: parent.clash ? "This file was changed by another program" : "Save your changes to “" + Backend.title + "”?" }
        Label { x: 22; y: 50; width: parent.width - 44; wrapMode: Text.WordWrap; secondary: true
            text: parent.clash ? "Since you opened it, something else saved a different version. Saving yours replaces theirs." : "If you don't save, what you changed is lost." }
        Row { anchors { right: parent.right; rightMargin: 22; bottom: parent.bottom; bottomMargin: 20 } spacing: 8
            Btn { visible: !parent.parent.clash; text: "Don't Save"; danger: true; onClicked: { var t = win.asking.then; Backend.revert(); win.carryOn(t) } }
            Btn { visible: parent.parent.clash; text: "Load Theirs"; onClicked: { Backend.revert(); win.asking = null } }
            Btn { text: "Cancel"; onClicked: win.asking = null }
            Btn { primary: true; text: parent.parent.clash ? "Save Mine" : "Save"
                onClicked: { var t = win.asking.then
                    if (parent.parent.clash) { if (Backend.save(true) === "") win.carryOn(t); else win.asking = null }
                    else if (win.save(t)) win.carryOn(t) } } } }
}
