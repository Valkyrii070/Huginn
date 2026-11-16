"""Which screen to share: xdg-desktop-portal-wlr's chooser on Huginn's own compositor (chooser_type=dmenu).

The portal writes what can be shared on stdin, one per line ("Monitor: NAME DESCRIPTION", "Window: TITLE (ID)");
the line printed is what's shared, and printing nothing says no. With only one screen there's nothing to ask.
"""
import sys

QML = r"""
import QtQuick
import QtQuick.Window

Window {
    id: win
    width: 420; height: 132 + list.count * 56
    visible: true; color: "transparent"; title: "Share your screen"
    flags: Qt.Dialog
    property string picked: ""
    Rectangle {
        anchors.fill: parent; radius: 18; color: "#E61A1E24"; border.color: "#33FFFFFF"
        Text { x: 22; y: 18; text: "Share which screen?"; color: "#F2F4F7"; font.family: "Inter"; font.pixelSize: 17; font.weight: Font.DemiBold }
        Text { x: 22; y: 44; text: "An app asked to see one of your screens."; color: "#A9B1BC"; font.family: "Inter"; font.pixelSize: 13 }
        ListView {
            id: list
            x: 14; y: 72; width: parent.width - 28; height: count * 56; interactive: false
            model: choices
            delegate: Rectangle {
                width: list.width; height: 50; radius: 12
                color: hover.hovered ? "#2E3A4A" : "#22272F"; border.color: "#1FFFFFFF"
                HoverHandler { id: hover }
                TapHandler { onTapped: { win.picked = modelData.line; Qt.quit() } }
                Text { x: 14; anchors.verticalCenter: parent.verticalCenter; text: modelData.label; color: "#F2F4F7"
                       font.family: "Inter"; font.pixelSize: 14; elide: Text.ElideRight; width: parent.width - 28 }
            }
        }
        Text {
            anchors.right: parent.right; anchors.rightMargin: 22; anchors.bottom: parent.bottom; anchors.bottomMargin: 14
            text: "Don't share"; color: "#8FB8FF"; font.family: "Inter"; font.pixelSize: 14
            TapHandler { onTapped: Qt.quit() }
        }
    }
}
"""


def label(line: str) -> str:
    kind, _, rest = line.partition(": ")
    if kind == "Monitor":
        name, _, desc = rest.partition(" ")
        return f"{desc.strip() or 'Screen'} ({name})" if desc.strip() else name.replace("-", " ")
    return rest


def main() -> int:
    lines = [l.rstrip("\n") for l in sys.stdin if l.strip()]
    if not lines:
        return 1
    if len(lines) == 1:
        print(lines[0])
        return 0
    from PySide6.QtCore import QUrl  # noqa: F401
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtQml import QQmlApplicationEngine
    app = QGuiApplication(sys.argv[:1])
    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty("choices", [{"line": l, "label": label(l)} for l in lines])
    engine.loadData(QML.encode())
    if not engine.rootObjects():
        return 1
    app.exec()
    picked = engine.rootObjects()[0].property("picked")
    if picked:
        print(picked)
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
