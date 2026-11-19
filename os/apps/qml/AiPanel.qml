import QtQuick

// Huginn AI inside an app: an island that writes the answer as it comes in, then offers what to do with it (replace
// what was asked about, insert it, copy it, or try again). Settings › AI says where it runs; the island says too.
//
//   aiPanel.run({ task: "rewrite", text: ..., extra: { style: "shorter" }, heading: "Shorter",
//                 accept: "Replace", onAccept: function (answer) { ... return "" or why it couldn't },
//                 second: "Insert Below", onSecond: function (answer) { ... } })
Rectangle {
    id: ap
    property var job: ({})                       // what run() was given
    property int id: -1
    property string answer: ""
    property string trouble: ""
    property real maxHeight: 440
    property bool mono: false
    readonly property bool have: typeof AI !== "undefined" && AI !== null
    readonly property var st: have ? AI.state : ({})
    readonly property bool busy: id >= 0
    readonly property string who: !have ? "" : st.provider === "local" ? "On this computer" + (st.model ? " · " + st.model : "")
                                             : st.provider === "custom" ? (st.model || "Your service") : (st.label || "") + (st.model ? " · " + st.model : "")
    signal finished()
    visible: false
    width: 560; height: Math.min(maxHeight, flick.contentHeight + 110)
    radius: 18; color: Theme.t.island; border.width: 1; border.color: Theme.t.islandLine
    MouseArea { anchors.fill: parent; acceptedButtons: Qt.AllButtons }       // (clicks on it stay on it)

    function on(surface) { return have && !!st.enabled && st.provider !== "" && (!st.where || st.where[surface] !== false) }
    function run(j) {
        if (!have) return
        if (id >= 0) AI.stop(id)
        job = j; answer = ""; trouble = ""; mono = !!j.mono; visible = true
        id = AI.ask(j.task, j.text, j.extra || {})
    }
    function again() { run(job) }
    function close() { if (id >= 0) AI.stop(id); id = -1; visible = false; finished() }
    function result() { return mono ? AI.clean(answer).replace(/\s+$/, "") : answer.trim() }
    function copyIt() { out.selectAll(); out.copy(); out.deselect() }
    Connections { target: ap.have ? AI : null
        function onChunk(i, piece) { if (i === ap.id) ap.answer += piece }
        function onDone(i, why) { if (i !== ap.id) return; ap.id = -1; ap.trouble = why } }

    Row { x: 16; y: 14; spacing: 8; width: parent.width - 60
        Glyph { name: "sparkle"; size: 16; ink: Theme.t.accent; anchors.verticalCenter: parent.verticalCenter }
        Label { text: ap.job.heading || "Huginn AI"; font.weight: Font.DemiBold; anchors.verticalCenter: parent.verticalCenter }
        Label { text: ap.who; secondary: true; font.pixelSize: 11; anchors.verticalCenter: parent.verticalCenter; width: Math.min(implicitWidth, parent.width - 160); elide: Text.ElideRight } }
    Seg { anchors { right: parent.right; rightMargin: 10; top: parent.top; topMargin: 8; verticalCenter: undefined } icon: "x"; tip: "Close"; onClicked: ap.close() }

    Flickable {
        id: flick
        x: 16; y: 44; width: parent.width - 32; height: parent.height - 44 - 56; clip: true
        contentHeight: out.height; boundsBehavior: Flickable.StopAtBounds
        onContentHeightChanged: if (ap.busy && contentHeight > height) contentY = contentHeight - height     // follow the writing
        TextEdit {
            id: out
            width: parent.width; readOnly: true; selectByMouse: true; wrapMode: TextEdit.Wrap; textFormat: TextEdit.PlainText
            color: ap.trouble ? Theme.t.danger : ap.answer === "" ? Theme.t.text_secondary : Theme.t.text
            font.family: ap.mono ? Theme.t.fontMono : Theme.t.font; font.pixelSize: ap.mono ? 13 : 14
            selectionColor: Theme.t.accent; selectedTextColor: Theme.t.onAccent
            text: ap.trouble ? ap.trouble : ap.answer !== "" ? (ap.mono && !ap.busy ? ap.result() : ap.answer)
                  : ap.st.provider === "local" ? "Starting the model on this computer (the first answer takes a little longer)…" : "Writing…"
        }
    }
    Row {
        anchors { right: parent.right; rightMargin: 14; bottom: parent.bottom; bottomMargin: 14 } spacing: 8
        Btn { visible: ap.busy; text: "Stop"; onClicked: { AI.stop(ap.id); ap.id = -1 } }
        Btn { visible: !ap.busy; text: "Try Again"; onClicked: ap.again() }
        Btn { visible: !ap.busy && ap.answer !== "" && !ap.trouble; text: "Copy"; onClicked: { ap.copyIt(); if (!ap.job.accept) ap.close() } }
        Btn { visible: !ap.busy && ap.answer !== "" && !ap.trouble && !!ap.job.second; text: ap.job.second || ""
            onClicked: { var j = ap.job, a = ap.result(); ap.close(); j.onSecond(a) } }
        Btn { visible: !ap.busy && ap.answer !== "" && !ap.trouble && !!ap.job.accept; primary: true; text: ap.job.accept || ""
            onClicked: { var j = ap.job, a = ap.result(); ap.close(); j.onAccept(a) } }
    }
}
