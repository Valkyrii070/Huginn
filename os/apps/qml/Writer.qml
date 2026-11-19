import QtQuick

// Writer, "floating page": the page floats on the tint; formatting is the island under it, where the light is.
GlassWindow {
    id: win
    title: "Writer"; glow: "bottom"; width: 1180; height: 780
    property var st: ({})
    property string notice: ""
    property string exported: ""
    function refresh() { st = Backend.state(editor.selectionStart) }
    function apply(what) { Backend.style(editor.selectionStart, editor.selectionEnd, what); refresh(); editor.forceActiveFocus() }
    // Huginn AI (Settings › AI): on what's selected, or on the whole document when nothing is
    readonly property var aiChoices: [["rewrite:clearer", "Make it clearer", ""], ["rewrite:shorter", "Make it shorter", ""], ["rewrite:friendlier", "Make it friendlier", ""],
                                      ["rewrite:formal", "Make it more formal", ""], ["rewrite:simpler", "Make it simpler", ""], ["", "", ""],
                                      ["proofread", "Proofread", ""], ["summarise", "Summarise", ""], ["continue", "Carry on writing", "at the cursor"]]
    function ai(key) {
        var a = editor.selectionStart, b = editor.selectionEnd, all = a === b
        var task = key.split(":")[0], style = key.split(":")[1] || ""
        if (task === "continue") { b = a = editor.cursorPosition; all = false }
        var text = task === "continue" ? Backend.textOf(0, a > 0 ? a : editor.length) : all ? Backend.textOf(0, 0) : Backend.textOf(a, b)
        if (text.trim() === "") { win.notice = "Write something first."; hide.restart(); return }
        if (all) { a = 0; b = editor.length }
        var asked = task === "continue" ? "" : text
        function stillThere() { return task === "continue" || (all ? Backend.textOf(0, 0) : Backend.textOf(a, b)) === asked }
        function put(answer, at, till, lead) {
            if (!stillThere()) { aiPanel.copyIt(); win.notice = "The document changed meanwhile, so the answer is copied: paste it where you want it."; hide.restart(); return }
            var end = Backend.putText(at, till, (lead || "") + answer); editor.cursorPosition = end; editor.forceActiveFocus()
        }
        var head = { "rewrite": ({ clearer: "Clearer", shorter: "Shorter", friendlier: "Friendlier", formal: "More formal", simpler: "Simpler" })[style], proofread: "Proofread",
                     summarise: "Summary", "continue": "Carried on" }[task]
        if (task === "summarise") aiPanel.run({ task: task, text: text, heading: head, accept: "Insert Below", onAccept: function (t) { put(t, b, b, "\n") } })
        else if (task === "continue") aiPanel.run({ task: task, text: text, heading: head, accept: "Insert", onAccept: function (t) { put(t, a, a, a > 0 ? "\n" : "") } })
        else aiPanel.run({ task: task, text: text, extra: { style: style }, heading: head, accept: all ? "Replace the Document" : "Replace", onAccept: function (t) { put(t, a, b, "") } })
    }
    Connections { target: Backend
        function onFailed(msg) { win.notice = msg; hide.restart() }
        function onLoaded() { editor.cursorPosition = 0; win.refresh(); top.restart() } }
    Timer { id: hide; interval: 7000; onTriggered: { win.notice = ""; win.exported = "" } }
    Timer { id: top; interval: 30; onTriggered: { editor.cursorPosition = 0; scroll.contentY = 0 } }
    Component.onCompleted: { Backend.attach(editor.textDocument); refresh(); top.restart() }
    onClosing: Backend.save()
    islands: [
        Island {   // the document: its name, whether it is saved, how long it is
            visible: Backend.current !== ""; x: 256 + (win.width - 256 - width) / 2; y: 12
            Label { text: Backend.title || "Untitled"; font.pixelSize: 12; font.weight: Font.DemiBold; leftPadding: 10; width: Math.min(implicitWidth, 240); elide: Text.ElideRight; anchors.verticalCenter: parent.verticalCenter }
            Label { leftPadding: 6; rightPadding: 10; font.pixelSize: 12; anchors.verticalCenter: parent.verticalCenter; width: Math.min(implicitWidth, 380); elide: Text.ElideMiddle
                color: win.notice ? Theme.t.danger : Theme.t.text_secondary
                text: win.notice || (win.exported ? "Exported to " + win.exported : ((Backend.saved ? "Saved" : "Saving…") + "  ·  " + Backend.words + (Backend.words === 1 ? " word" : " words"))) }
            Seg { visible: win.exported !== ""; text: "Show in Files"; onClicked: Backend.reveal(win.exported) }
        },
        Island { visible: Backend.current !== ""; anchors { right: parent.right; rightMargin: 12 } y: 12; z: 8
          ExportMenu {
            choices: [["pdf", "PDF", "For sending and printing"], ["docx", "Word", "A .docx file for Microsoft Word and others"], ["odt", "OpenDocument", "An .odt file"], ["md", "Markdown", "Plain text with simple marks"]]
            onChosen: function (key) { var p = Backend.export(key); if (p) { win.exported = p; win.notice = ""; hide.restart() } } } },
        Rail { id: docRail; x: 12; y: 64; width: 232; maxHeight: win.height - 64 - 14
            DocList { newLabel: "New Document"; icon: "doc"; empty: "Documents you write appear here. Word files in your Documents folder do too." } },
        Island {   // formatting: the main island
            id: bar; visible: Backend.current !== ""; x: 256 + (win.width - 256 - width) / 2; anchors { bottom: parent.bottom; bottomMargin: 14 }
            Repeater { model: [["title", "Title", 52], ["heading", "Heading", 70], ["subheading", "Subheading", 92], ["body", "Body", 52]]
                Tool { required property var modelData; span: modelData[2]; text: modelData[1]; on: win.st.style === modelData[0]; onClicked: win.apply(modelData[0]) } }
            Gap {}
            Tool { text: "B"; tip: "Bold"; on: !!win.st.bold; onClicked: win.apply("bold") }
            Tool { text: "I"; tip: "Italic"; on: !!win.st.italic; onClicked: win.apply("italic") }
            Tool { text: "U"; tip: "Underline"; on: !!win.st.underline; onClicked: win.apply("underline") }
            Gap {}
            Tool { text: "A−"; tip: "Smaller"; span: 34; onClicked: win.apply("smaller") }
            Label { width: 26; horizontalAlignment: Text.AlignHCenter; anchors.verticalCenter: parent.verticalCenter; text: win.st.size || 11; secondary: true; font.pixelSize: 12 }
            Tool { text: "A+"; tip: "Bigger"; span: 34; onClicked: win.apply("bigger") }
            Gap {}
            Repeater { model: [["left", "alignleft", "Align left"], ["center", "aligncenter", "Centre"], ["right", "alignright", "Align right"], ["justify", "alignjustify", "Justify"]]
                Tool { required property var modelData; icon: modelData[1]; tip: modelData[2]; on: win.st.align === modelData[0]; onClicked: win.apply(modelData[0]) } }
            Gap {}
            Tool { icon: "list"; tip: "Bulleted list"; on: win.st.list === "bullet"; onClicked: win.apply("bullet") }
            Tool { icon: "numbers"; tip: "Numbered list"; on: win.st.list === "number"; onClicked: win.apply("number") }
            Gap {}
            Repeater { model: ["#15181C", "#D93A3F", "#C46A00", "#0A8071", "#2361AE", "#563AD1"]
                Rectangle { required property string modelData; width: 20; height: 20; radius: 10; color: modelData; border.width: 1; border.color: Theme.t.islandLine; anchors.verticalCenter: parent.verticalCenter
                    MouseArea { anchors.fill: parent; onClicked: win.apply(parent.modelData) } } }
            Gap { visible: aiPanel.on("writer") }
            Tool { visible: aiPanel.on("writer"); icon: "sparkle"; tip: aiMenu.visible || aiPanel.visible ? "" : "Huginn AI"; on: aiMenu.visible || aiPanel.visible; onClicked: aiMenu.visible = !aiMenu.visible }
            Item { width: 2; height: 1 }
        },
        AiMenu { id: aiMenu; z: 9; items: win.aiChoices; anchors { right: bar.right; bottom: bar.top; bottomMargin: 8 }
            note: editor.selectedText !== "" ? "On what's selected." : "On the whole document (select some to work on just that)."
            onChosen: function (key) { win.ai(key) } },
        AiPanel { id: aiPanel; z: 9; x: bar.x + (bar.width - width) / 2; anchors { bottom: bar.top; bottomMargin: 8 } maxHeight: win.height * 0.55 }
    ]
    component Tool: Pressable { id: t; property string icon: ""; property string text: ""; property bool on: false; property string tip: ""; property int span: 30
        width: span; height: 30; radius: 11; anchors.verticalCenter: parent ? parent.verticalCenter : undefined; color: on ? Theme.t.accent : (hovered ? Theme.t.hover : "transparent")
        Glyph { visible: t.icon !== ""; anchors.centerIn: parent; name: t.icon; size: 16; ink: t.on ? Theme.t.onAccent : Theme.t.icon }
        Label { visible: t.text !== ""; anchors.centerIn: parent; text: t.text; color: t.on ? Theme.t.onAccent : Theme.t.text; font.pixelSize: 13; font.weight: Font.DemiBold }
        Rectangle { visible: t.hovered && t.tip !== ""; z: 9; color: Theme.t.tooltip_bg; border.width: 1; border.color: Theme.t.menu_border; radius: 6; width: tt.width + 14; height: 24; anchors { bottom: parent.top; bottomMargin: 10; horizontalCenter: parent.horizontalCenter }
            Label { id: tt; anchors.centerIn: parent; text: t.tip; font.pixelSize: 11 } } }
    component Gap: Item { width: 9; height: 30; anchors.verticalCenter: parent ? parent.verticalCenter : undefined; Rectangle { anchors.centerIn: parent; width: 1; height: 16; color: Theme.t.islandLine } }

    Column { visible: Backend.current === ""; x: win.middleX(width, parent.y + y, height, docRail) - parent.x; anchors.verticalCenter: parent.verticalCenter; spacing: 10
        Item { width: 190; height: 214; anchors.horizontalCenter: parent.horizontalCenter      // a sheet of paper with the first lines already on it
            Rectangle { x: 30; y: 14; width: 150; height: 196; radius: 6; color: Theme.t.island; border.width: 1; border.color: Theme.t.islandLine; rotation: 5; opacity: 0.6 }
            Rectangle { x: 20; y: 6; width: 150; height: 196; radius: 6; color: Theme.t.dark ? "#F4F1EA" : "#FFFFFF"; border.width: 1; border.color: Theme.t.islandLine
                Rectangle { x: 18; y: 22; width: 76; height: 9; radius: 3; color: Theme.t.accent }
                Repeater { model: [112, 104, 114, 92, 110, 60]; Rectangle { required property int modelData; required property int index; x: 18; y: 46 + index * 14; width: modelData; height: 4; radius: 2; color: "#33000000" } }
                Rectangle { x: 82; y: 113; width: 2; height: 12; color: Theme.t.accent; SequentialAnimation on opacity { loops: Animation.Infinite; NumberAnimation { to: 0; duration: 500 } NumberAnimation { to: 1; duration: 500 } } } } }
        Label { text: "Start a document"; font.pixelSize: 17; font.weight: Font.DemiBold; anchors.horizontalCenter: parent.horizontalCenter }
        Btn { text: "New Document"; primary: true; anchors.horizontalCenter: parent.horizontalCenter; onClicked: Backend.create() } }
    Item { visible: Backend.current !== ""; x: 256; y: 60; width: parent.width - 256; height: parent.height - 62
        Flickable { id: scroll; width: parent.width; height: parent.height; clip: true; contentHeight: paper.height + 120 + note.height
            function follow(r) { var top = paper.y + 76 + r.y; if (top < contentY + 20) contentY = Math.max(0, top - 20); else if (top + r.height + 110 > contentY + height) contentY = top + r.height + 110 - height }
            ImportNote { id: note; x: paper.x; y: 14; width: paper.width; file: Backend.importedFile; dropped: Backend.importedDropped; onDismissed: Backend.dismissNote() }
            Rectangle { id: paper; x: Math.max(20, (scroll.width - width) / 2); y: note.visible ? note.height + 28 : 24; width: Math.min(794, scroll.width - 40); height: Math.max(1000, editor.height + 160)
                color: "#FFFFFF"; radius: 6; border.width: 1; border.color: Theme.t.dark ? "#000000" : "#CBD0D6"
                TextEdit { id: editor; x: 76; y: 76; width: parent.width - 152; focus: true; textFormat: TextEdit.RichText; wrapMode: TextEdit.Wrap
                    color: "#15181C"; selectionColor: Theme.t.accent; selectedTextColor: "#FFFFFF"; font.family: Theme.t.font; font.pointSize: 11; selectByMouse: true; persistentSelection: true
                    onCursorPositionChanged: win.refresh(); onSelectionStartChanged: win.refresh(); onCursorRectangleChanged: scroll.follow(cursorRectangle)
                    Keys.onPressed: function (e) { if (e.modifiers & Qt.ControlModifier) { var k = { [Qt.Key_B]: "bold", [Qt.Key_I]: "italic", [Qt.Key_U]: "underline" }[e.key]; if (k) { win.apply(k); e.accepted = true } } } }
                MouseArea { x: 0; y: editor.y + editor.height; width: parent.width; height: Math.max(0, parent.height - y); onClicked: { editor.forceActiveFocus(); editor.cursorPosition = editor.length } } } }
    }
}
