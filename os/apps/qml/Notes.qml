import QtQuick

// Notes, "open page": you write straight onto the tinted window; the notes are a rail at the left, where the light is.
GlassWindow {
    id: win
    title: "Notes"; glow: "left"
    property string filter: ""
    property string notice: ""
    property var asking: null
    property bool loading: false
    // ---- the simple marks a note can hold: "# " heading, "- [ ] " something to tick off, "- " list
    property string here: ""                              // the line the cursor is on
    readonly property string look: Theme.t.accent + Theme.t.text_secondary
    onLookChanged: Backend.style(editor.textDocument, Theme.t.accent, Theme.t.text_secondary)
    function lineAt(pos) { var t = editor.text, a = t.lastIndexOf("\n", pos - 1) + 1, b = t.indexOf("\n", pos); if (b < 0) b = t.length; return { a: a, s: t.substring(a, b) } }
    function setMark(kind) {                              // put the mark on this line, or take it off if it is already there
        var L = lineAt(editor.cursorPosition), m = /^(\s*)(#{1,2} |- \[[ xX]\] |[-*] )?/.exec(L.s), had = m[2] || "", at = L.a + m[1].length
        var same = kind === "heading" ? had.charAt(0) === "#" : kind === "check" ? had.indexOf("[") > 0 : (had === "- " || had === "* ")
        if (had) editor.remove(at, at + had.length)
        if (!same) editor.insert(at, kind === "heading" ? "# " : kind === "check" ? "- [ ] " : "- ")
        editor.forceActiveFocus()
    }
    // the top bar's menu, and its keys (Ctrl+N, Ctrl+F)
    function newNote() { Backend.create(); editor.forceActiveFocus() }
    function find() { noteSearch.focusInput() }
    function apply(what) { if (Backend.current !== "") setMark({ h1: "heading", check: "check", bullets: "list" }[what] || what) }
    function tick(pos) {                                  // tick or untick the line at pos; false if it has no box
        var L = lineAt(pos), m = /^(\s*)- \[([ xX])\] /.exec(L.s); if (!m) return false
        var at = L.a + m[1].length + 3, keep = editor.cursorPosition
        editor.remove(at, at + 1); editor.insert(at, m[2] === " " ? "x" : " "); editor.cursorPosition = keep; return true
    }
    function newLine() {                                  // Enter in a list carries the list on; on an empty item it ends it
        var L = lineAt(editor.cursorPosition), m = /^(\s*)(- \[[ xX]\] |[-*] )(.*)$/.exec(L.s); if (!m) return false
        if (m[3].trim() === "") { editor.remove(L.a + m[1].length, L.a + L.s.length); return true }
        editor.insert(editor.cursorPosition, "\n" + m[1] + (m[2].indexOf("[") > 0 ? "- [ ] " : m[2])); return true
    }
    Connections { target: Backend
        function onTextLoaded() { win.loading = true; editor.text = Backend.text; win.loading = false; editor.cursorPosition = 0 }
        function onFailed(msg) { win.notice = msg; hide.restart() } }
    Timer { id: hide; interval: 5000; onTriggered: win.notice = "" }
    Component.onCompleted: { loading = true; editor.text = Backend.text; loading = false }
    onClosing: Backend.save()
    islands: [
        Toast { id: noteToast; anchors { horizontalCenter: parent.horizontalCenter; bottom: parent.bottom; bottomMargin: 18 } },
        Island {
            anchors { right: parent.right; rightMargin: 12 } y: 12
            IslandField { id: noteSearch; text: win.filter; onTextChanged: win.filter = text; placeholder: "Search notes" }
            Seg { icon: "bell"; tip: "Remind me about this line"; visible: Backend.current !== ""; onClicked: noteToast.say(Backend.remind(win.here), false) }
            Seg { icon: "mail"; tip: "Send by Mail"; visible: Backend.current !== ""; onClicked: Backend.sendByMail() }
            Seg { icon: "trash"; tip: "Move note to Trash"; visible: Backend.current !== ""; onClicked: win.asking = Backend.current }
            Seg { icon: "plus"; text: "New Note"; on: true; onClicked: { Backend.create(); editor.forceActiveFocus() } }
        },
        Rail {   // the notes: the main island
            id: notesRail; x: 12; y: 64; width: 250; maxHeight: win.height - 64 - 14
            Repeater { model: Backend.notes.filter(function (n) { return (n.title + n.preview).toLowerCase().indexOf(win.filter.toLowerCase()) >= 0 })
                Pressable { required property var modelData; readonly property bool open: Backend.current === modelData.path
                    width: parent.width; height: 54; radius: 11; color: open ? Theme.t.accent : (hovered ? Theme.t.hover : "transparent"); onClicked: Backend.open(modelData.path)
                    Label { x: 10; y: 8; width: parent.width - 70; text: modelData.title; font.weight: Font.DemiBold; elide: Text.ElideRight; color: parent.open ? Theme.t.onAccent : Theme.t.text }
                    Label { anchors { right: parent.right; rightMargin: 10 } y: 10; text: modelData.when; font.pixelSize: 11; color: parent.open ? Theme.t.onAccent : Theme.t.text_secondary }
                    Label { x: 10; y: 29; width: parent.width - 20; text: modelData.preview; font.pixelSize: 12; elide: Text.ElideRight; color: parent.open ? Theme.t.onAccent : Theme.t.text_secondary; opacity: parent.open ? 0.85 : 1 } } }
            Label { visible: Backend.notes.length === 0; padding: 10; width: parent.width; wrapMode: Text.WordWrap; secondary: true; font.pixelSize: 12; text: "No notes yet. Notes are saved as files in Documents/Notes." }
        },
        Island {   // what this line is, then saved or not and how long
            visible: Backend.current !== ""; x: 274 + (win.width - 274 - width) / 2; anchors { bottom: parent.bottom; bottomMargin: 14 }
            Seg { text: "Heading"; on: /^\s*#{1,2} /.test(win.here); onClicked: win.setMark("heading") }
            Seg { text: "Checklist"; on: /^\s*- \[[ xX]\] /.test(win.here); onClicked: win.setMark("check") }
            Seg { text: "List"; on: /^\s*[-*] (?!\[[ xX]\] )/.test(win.here); onClicked: win.setMark("list") }
            Seg { visible: /^\s*- \[[ xX]\] /.test(win.here); icon: "check"; tip: "Tick it off (Ctrl+Enter)"; onClicked: { win.tick(editor.cursorPosition); editor.forceActiveFocus() } }
            IslandGap {}
            Label { leftPadding: 4; rightPadding: 10; font.pixelSize: 12; anchors.verticalCenter: parent.verticalCenter
                color: win.notice ? Theme.t.danger : Theme.t.text_secondary
                text: win.notice || ((Backend.saved ? "Saved" : "Saving…") + "  ·  " + (Backend.checks !== "" ? Backend.checks + "  ·  " : "") + Backend.words + (Backend.words === 1 ? " word" : " words")) }
        }
    ]
    Column { visible: Backend.current === ""; x: win.middleX(width, parent.y + y, height, notesRail) - parent.x; anchors.verticalCenter: parent.verticalCenter; spacing: 10
        Item { width: 200; height: 176; anchors.horizontalCenter: parent.horizontalCenter      // a torn-off note with a ticked line and a pencil lying across it
            Rectangle { x: 20; y: 10; width: 150; height: 160; radius: 4; rotation: -4; color: Theme.t.dark ? "#F2E6A8" : "#FFF3B0"; border.width: 1; border.color: "#33000000"
                Rectangle { width: parent.width; height: 20; color: "#22000000" }
                Repeater { model: 5; Rectangle { required property int index; x: 12; y: 46 + index * 22; width: 126; height: 1; color: "#33000000" } }
                Rectangle { x: 14; y: 30; width: 11; height: 11; radius: 3; color: Theme.t.accent } Rectangle { x: 32; y: 33; width: 70; height: 5; radius: 2; color: "#66000000" }
                Rectangle { x: 14; y: 52; width: 11; height: 11; radius: 3; color: "transparent"; border.width: 1.5; border.color: "#88000000" } Rectangle { x: 32; y: 55; width: 92; height: 5; radius: 2; color: "#66000000" }
                Rectangle { x: 14; y: 77; width: 56; height: 5; radius: 2; color: "#44000000" } }
            Rectangle { x: 96; y: 104; width: 104; height: 12; radius: 3; rotation: -38; color: Theme.t.accent; Rectangle { x: -10; width: 14; height: 12; radius: 3; color: Theme.t.dark ? "#E8D9B5" : "#D9C59A" } Rectangle { x: 90; width: 14; height: 12; radius: 3; color: "#E08A8A" } } }
        Label { text: "Write something down"; font.pixelSize: 17; font.weight: Font.DemiBold; anchors.horizontalCenter: parent.horizontalCenter }
        Btn { text: "New Note"; primary: true; anchors.horizontalCenter: parent.horizontalCenter; onClicked: { Backend.create(); editor.forceActiveFocus() } } }
    Flickable { id: scroll; visible: Backend.current !== ""; x: 274; y: 64; width: parent.width - 274; height: parent.height - 66; contentHeight: editor.height + 110; clip: true
        function follow(r) { if (r.y < contentY) contentY = r.y; else if (r.y + r.height + 110 > contentY + height) contentY = r.y + r.height + 110 - height }
        TextEdit { id: editor; x: Math.max(28, (scroll.width - 720) / 2); y: 12; width: Math.min(scroll.width - 56, 720); focus: true
            color: Theme.t.text; selectionColor: Theme.t.accent; selectedTextColor: Theme.t.onAccent; font.family: Theme.t.font; font.pixelSize: 15; wrapMode: TextEdit.Wrap; textFormat: TextEdit.PlainText
            selectByMouse: true; persistentSelection: true
            objectName: "editor"
            onTextChanged: { if (!win.loading) Backend.edit(text); win.here = win.lineAt(cursorPosition).s }
            onCursorPositionChanged: win.here = win.lineAt(cursorPosition).s
            onCursorRectangleChanged: scroll.follow(cursorRectangle)
            Keys.onPressed: function (e) {
                if (e.key !== Qt.Key_Return && e.key !== Qt.Key_Enter) return
                if (e.modifiers & Qt.ControlModifier) e.accepted = win.tick(cursorPosition)
                else if (!(e.modifiers & Qt.ShiftModifier)) e.accepted = win.newLine() }
            TapHandler { onTapped: function (p) {    // a click on the box itself ticks it
                var pos = editor.positionAt(p.position.x, p.position.y), L = win.lineAt(pos), m = /^(\s*)- \[/.exec(L.s)
                if (m && pos >= L.a + m[1].length && pos <= L.a + m[1].length + 5) win.tick(pos) } }
            Label { visible: editor.text === ""; text: "Start typing. The first line becomes the title."; color: Theme.t.text_secondary; font.pixelSize: 15 } }
        MouseArea { y: editor.y + editor.height; width: scroll.width; height: Math.max(0, scroll.height - y); onClicked: { editor.forceActiveFocus(); editor.cursorPosition = editor.length } } }
    Rectangle { visible: win.asking !== null; anchors.fill: parent; radius: win.r; color: "#66000000"; z: 30; MouseArea { anchors.fill: parent } }
    Rectangle { visible: win.asking !== null; z: 31; anchors.centerIn: parent; width: 380; height: 160; radius: 16; color: Theme.t.menu_bg; border.width: 1; border.color: Theme.t.menu_border
        Label { x: 22; y: 20; text: "Move this note to the Trash?"; font.pixelSize: 16; font.weight: Font.DemiBold }
        Label { x: 22; y: 50; width: parent.width - 44; wrapMode: Text.WordWrap; secondary: true; text: "You can get it back from the Trash until you empty it." }
        Row { anchors { right: parent.right; rightMargin: 22; bottom: parent.bottom; bottomMargin: 20 } spacing: 8
            Btn { text: "Cancel"; onClicked: win.asking = null } Btn { text: "Move to Trash"; danger: true; onClicked: { Backend.trash(win.asking); win.asking = null } } } }
}
