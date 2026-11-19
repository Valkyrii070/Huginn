import QtQuick

// Calculator, "whole island": the app is one rounded island with its own light.
GlassWindow {
    id: win
    title: "Calculator"; width: 340; height: 580; minimumWidth: 300; minimumHeight: 480; corner: 24; glow: "centre"; glowY: 0.16; padTop: 58
    property string sum: ""
    property string answer: ""
    property bool showHistory: false
    function toggleHistory() { showHistory = !showHistory }
    readonly property string live: answer === "" ? Backend.preview(sum) : ""
    function press(k) {
        if (k === "C") { sum = ""; answer = "" }
        else if (k === "⌫") { if (answer !== "") { answer = "" } else sum = sum.slice(0, -1) }
        else if (k === "=") { if (sum !== "") answer = Backend.solve(sum) }
        else { if (answer !== "") { sum = /[0-9.(]/.test(k) || /[a-z]/i.test(answer) ? "" : answer.replace(/,/g, ""); answer = "" } sum += k }
    }
    toolbar: [ Seg { icon: "clock"; tip: "Earlier sums"; on: win.showHistory; onClicked: win.showHistory = !win.showHistory } ]
    Item { anchors.fill: parent; focus: true
        Keys.onPressed: function (e) {
            var map = { "*": "×", "/": "÷", "-": "−" }, t = e.text
            if (e.key === Qt.Key_Return || e.key === Qt.Key_Enter || t === "=") win.press("=")
            else if (e.key === Qt.Key_Backspace) win.press("⌫")
            else if (e.key === Qt.Key_Escape) win.press("C")
            else if ("0123456789.+()%".indexOf(t) >= 0 && t !== "") win.press(t)
            else if (map[t]) win.press(map[t])
        }
        Label { x: 16; y: 14; width: parent.width - 32; horizontalAlignment: Text.AlignRight; text: win.sum || "0"; secondary: win.answer !== ""; font.pixelSize: win.answer !== "" ? 16 : 30; font.weight: Font.Light; elide: Text.ElideLeft }
        Label { x: 16; y: 58; width: parent.width - 32; horizontalAlignment: Text.AlignRight; elide: Text.ElideLeft
            text: win.answer !== "" ? win.answer : (win.live !== "" && win.live !== win.sum ? "= " + win.live : ""); font.pixelSize: win.answer !== "" ? (win.answer.length > 14 ? 20 : 34) : 16; font.weight: Font.Light; color: win.answer !== "" ? Theme.t.text : Theme.t.text_secondary }
        Grid { id: pad; x: 12; y: 118; columns: 4; spacing: 8; width: parent.width - 24
            readonly property real cell: (width - 24) / 4
            Repeater { model: ["C", "(", ")", "÷", "7", "8", "9", "×", "4", "5", "6", "−", "1", "2", "3", "+", "0", ".", "%", "="]
                Pressable { required property string modelData; width: pad.cell; height: (win.height - 58 - 118 - 14 - 32) / 5; radius: 14
                    readonly property bool op: "÷×−+".indexOf(modelData) >= 0
                    color: modelData === "=" ? Theme.t.accent : (hovered ? Theme.t.pressed : (op || "C()%".indexOf(modelData) >= 0 ? Theme.t.hover : Theme.t.group)); border.width: 1; border.color: Theme.t.islandLine
                    onClicked: win.press(modelData)
                    Label { anchors.centerIn: parent; text: modelData; font.pixelSize: 20; color: modelData === "=" ? Theme.t.onAccent : (parent.op ? Theme.t.accent : Theme.t.text) } } } }
        Rectangle { visible: win.showHistory; anchors { fill: parent; margins: 10; topMargin: 0 } radius: 16; color: Theme.t.menu_bg; border.width: 1; border.color: Theme.t.islandLine; clip: true
            Label { visible: Backend.history.length === 0; anchors.centerIn: parent; text: "Sums you finish appear here"; secondary: true }
            Flickable { anchors.fill: parent; contentHeight: hist.height; clip: true
                Column { id: hist; width: parent.width
                    Repeater { model: Backend.history
                        Pressable { required property var modelData; width: hist.width; height: 54; radius: 0; onClicked: { win.sum = modelData.result.replace(/,/g, ""); win.answer = ""; win.showHistory = false }
                            Label { x: 16; y: 8; text: modelData.sum; secondary: true; font.pixelSize: 12 } Label { x: 16; y: 26; text: "= " + modelData.result; font.pixelSize: 16 }
                            Rectangle { anchors.bottom: parent.bottom; x: 16; width: parent.width - 16; height: 1; color: Theme.t.separator } } } } } }
    }
}
