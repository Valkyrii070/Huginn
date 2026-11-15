import QtQuick

// A titled group of settings rows on one glass card. Rows draw their own dividers.
Column {
    id: sc
    property string title: ""
    property string note: ""
    default property alias rows: col.data
    width: parent ? parent.width : 400; spacing: 6
    Label { visible: sc.title !== ""; text: sc.title.toUpperCase(); secondary: true; font.pixelSize: 11; font.weight: Font.DemiBold; leftPadding: 4; font.letterSpacing: 0.4 }
    Rectangle { width: parent.width; height: col.height; radius: Theme.t.radiusCard; color: Theme.t.group; border.width: 1; border.color: Theme.t.separator; clip: true
        Column { id: col; width: parent.width } }
    Label { visible: sc.note !== ""; text: sc.note; width: parent.width; wrapMode: Text.WordWrap; secondary: true; font.pixelSize: 11; leftPadding: 4; rightPadding: 4 }
}
