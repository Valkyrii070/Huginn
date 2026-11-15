import QtQuick

// Terminal, "tab island": near-black with a hint of its colour; the tabs and their actions are the island.
// Ctrl+Shift+T new tab, Ctrl+Shift+W close it, Ctrl+PageUp/PageDown switch.
GlassWindow {
    id: win
    title: "Terminal"; glow: "bottom"; width: 900; height: 580; padTop: 58; padBottom: 60
    baseColor: Theme.t.dark ? Qt.rgba(0.03 + tintColor.r * 0.04, 0.035 + tintColor.g * 0.04, 0.035 + tintColor.b * 0.04, 1) : "#FBFCFA"
    Connections { target: Backend; function onClosed() { win.close() } function onChanged() { stick.restart() } }
    Timer { id: stick; interval: 1; onTriggered: if (screen.atEnd) screen.positionViewAtEnd() }
    islands: [
        Island {
            anchors { horizontalCenter: parent.horizontalCenter; bottom: parent.bottom; bottomMargin: 14 }
            Repeater { model: Backend.tabs   // the tabs
                Seg { required property string modelData; required property int index; icon: "forward"; text: modelData; on: Backend.current === index
                    onClicked: { Backend.select(index); keys.forceActiveFocus() } } }
            Seg { visible: Backend.tabs.length > 1; icon: "x"; tip: "Close this tab"; onClicked: { Backend.closeTab(Backend.current); keys.forceActiveFocus() } }
            Seg { icon: "plus"; tip: "New tab"; onClicked: { Backend.newTab(); keys.forceActiveFocus() } }
            IslandGap {}
            Label { text: Backend.size; secondary: true; font.pixelSize: 11; font.family: Theme.t.fontMono; leftPadding: 8; rightPadding: 4; anchors.verticalCenter: parent.verticalCenter }
            IslandGap {}
            Seg { icon: "doc"; text: "Copy All"; onClicked: Backend.copyAll() }
            Seg { icon: "download"; text: "Paste"; onClicked: { Backend.paste(); keys.forceActiveFocus() } }
        }
    ]
    Label { visible: !Backend.available; anchors.centerIn: parent; width: 380; wrapMode: Text.WordWrap; horizontalAlignment: Text.AlignHCenter; secondary: true; text: "Terminal needs the “pyte” Python library, which isn't installed on this computer." }
    TextMetrics { id: cell; font: probe.font; text: "MMMMMMMMMM" }
    Text { id: probe; visible: false; font.family: Backend.font; font.pixelSize: 13; text: "M" }
    ListView { id: screen; anchors { fill: parent; leftMargin: 18; rightMargin: 14 } clip: true; model: Backend.lines; boundsBehavior: Flickable.StopAtBounds
        property bool atEnd: true
        onMovementEnded: atEnd = atYEnd
        onWidthChanged: refit.restart(); onHeightChanged: refit.restart()
        delegate: Text { required property string modelData; width: screen.width; height: probe.height; textFormat: Text.RichText; text: modelData
            font: probe.font; color: Theme.t.text; renderType: Text.NativeRendering }
        MouseArea { anchors.fill: parent; acceptedButtons: Qt.LeftButton | Qt.MiddleButton; onClicked: function (m) { keys.forceActiveFocus(); if (m.button === Qt.MiddleButton) Backend.paste() }
            onWheel: function (w) { screen.contentY = Math.max(screen.originY, Math.min(screen.originY + screen.contentHeight - screen.height, screen.contentY - w.angleDelta.y)); screen.atEnd = screen.atYEnd } } }
    Timer { id: refit; interval: 60; onTriggered: Backend.fit(Math.floor(screen.width / (cell.advanceWidth / 10)), Math.floor(screen.height / probe.height)) }
    Item { id: keys; focus: true
        Keys.onPressed: function (e) {
            if ((e.modifiers & Qt.ControlModifier) && (e.modifiers & Qt.ShiftModifier)) {
                if (e.key === Qt.Key_V) Backend.paste(); else if (e.key === Qt.Key_C) Backend.copyAll()
                else if (e.key === Qt.Key_T) Backend.newTab(); else if (e.key === Qt.Key_W) Backend.closeTab(Backend.current)
                e.accepted = true; return }
            if ((e.modifiers & Qt.ControlModifier) && (e.key === Qt.Key_PageDown || e.key === Qt.Key_PageUp)) { Backend.step(e.key === Qt.Key_PageDown ? 1 : -1); e.accepted = true; return }
            screen.atEnd = true; Backend.key(e.key, e.modifiers, e.text); e.accepted = true } }
    Component.onCompleted: { refit.start(); keys.forceActiveFocus() }
}
