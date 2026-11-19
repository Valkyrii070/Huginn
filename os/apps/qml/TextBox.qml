import QtQuick

// A box to type in: one line, or several with `lines` above 1. `secret` hides what is typed.
Rectangle {
    id: box
    property alias text: one.text
    property alias input: one
    property string placeholder: ""
    property bool secret: false
    property bool mono: false
    property int lines: 1
    property string many: ""                    // the text, when lines > 1
    signal accepted()
    signal edited()
    function focusIn() { (lines > 1 ? area : one).forceActiveFocus() }
    width: 280; height: lines > 1 ? 16 + lines * 18 : 36; radius: 10; color: Theme.t.group
    border.width: 1; border.color: one.activeFocus || area.activeFocus ? Theme.t.accent : Theme.t.islandLine
    TextInput { id: one; visible: box.lines === 1; anchors { fill: parent; leftMargin: 12; rightMargin: 12 } verticalAlignment: TextInput.AlignVCenter; clip: true
        echoMode: box.secret ? TextInput.Password : TextInput.Normal; color: Theme.t.text; font.family: box.mono ? Theme.t.fontMono : Theme.t.font; font.pixelSize: 14
        selectionColor: Theme.t.accent; selectedTextColor: Theme.t.onAccent; selectByMouse: true; onAccepted: box.accepted(); onTextEdited: box.edited() }
    Flickable { visible: box.lines > 1; anchors { fill: parent; margins: 8 } clip: true; contentHeight: area.height
        TextEdit { id: area; width: parent.width; text: box.many; onTextChanged: if (box.many !== text) { box.many = text; box.edited() } wrapMode: TextEdit.Wrap; color: Theme.t.text
            font.family: Theme.t.font; font.pixelSize: 13; selectionColor: Theme.t.accent; selectedTextColor: Theme.t.onAccent; selectByMouse: true } }
    Label { visible: box.lines === 1 ? !one.text : !box.many; x: 12; y: box.lines > 1 ? 9 : (parent.height - height) / 2; secondary: true; text: box.placeholder }
}
