import QtQuick

Pressable {
    id: b
    property string text: ""
    property bool primary: false
    property bool danger: false
    property var textColor: null   // set to override the label colour (for buttons on coloured artwork)
    property bool pill: false      // store-style capsule: tinted background, accent text
    width: Math.max(pill ? 72 : 0, l.width + 30); height: 30; radius: pill ? 15 : Theme.t.radiusControl
    color: danger ? Theme.t.danger : primary ? Theme.t.accent : (hovered ? Theme.t.hover : Theme.t.capsule)
    border.width: primary || danger ? 0 : 1; border.color: Theme.t.capsule_border
    Label { id: l; anchors.centerIn: parent; text: b.text; font.weight: Font.DemiBold; font.pixelSize: 12
        color: b.textColor ? b.textColor : b.danger ? "#FFFFFF" : b.primary ? Theme.t.onAccent : (b.pill ? Theme.t.accent : Theme.t.text) }
}
