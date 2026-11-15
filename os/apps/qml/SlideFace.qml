import QtQuick

// One slide drawn at 960 x 540 and scaled to whatever size it is given. Editable in the main view, static elsewhere.
Item {
    id: face
    property var slide: ({ layout: "content", title: "", body: "" })
    property string theme: "realm"
    property bool editable: false
    signal edited(string field, string text)
    readonly property real k: width / 960
    readonly property bool centred: slide.layout === "title" || slide.layout === "section"
    readonly property color ink: theme === "paper" ? "#101317" : "#ECEFF3"
    readonly property color accent: theme === "paper" ? "#0A8071" : theme === "night" ? "#7CC4FF" : "#43D9B8"
    height: width * 9 / 16; clip: true
    Rectangle { anchors.fill: parent; color: face.theme === "paper" ? "#FFFFFF" : "#101317"
        gradient: face.theme === "realm" ? realm : null
        Gradient { id: realm; orientation: Gradient.Horizontal; GradientStop { position: 0; color: "#0F2624" } GradientStop { position: 1; color: "#17192C" } } }
    Rectangle { visible: face.theme === "realm"; width: parent.width * 0.5; height: width; radius: width / 2; x: parent.width * 0.68; y: -parent.height * 0.45; color: "#3DD6B5"; opacity: 0.10 }
    Rectangle { visible: !face.centred && face.slide.layout !== "blank"; x: 64 * face.k; y: 132 * face.k; width: 56 * face.k; height: Math.max(1, 4 * face.k); radius: height / 2; color: face.accent }
    Item { width: 960; height: 540; scale: face.k; transformOrigin: Item.TopLeft
        TextEdit { id: title; visible: face.slide.layout !== "blank"; readOnly: !face.editable; selectByMouse: face.editable; activeFocusOnPress: face.editable
            x: 64; width: 832; y: face.centred ? (face.slide.layout === "section" ? 220 : 170) : 52; wrapMode: TextEdit.Wrap; textFormat: TextEdit.PlainText
            horizontalAlignment: face.centred ? TextEdit.AlignHCenter : TextEdit.AlignLeft
            color: face.ink; font.family: Theme.t.font; font.pixelSize: face.centred ? 58 : 40; font.weight: face.centred ? Font.Light : Font.DemiBold; selectionColor: face.accent
            onTextChanged: if (face.editable && activeFocus) face.edited("title", text)
            Text { visible: face.editable && title.text === ""; width: parent.width; horizontalAlignment: parent.horizontalAlignment; text: "Click to add a title"; color: face.ink; opacity: 0.35; font: parent.font } }
        TextEdit { id: body; visible: face.slide.layout === "content" || face.slide.layout === "title"; readOnly: !face.editable; selectByMouse: face.editable; activeFocusOnPress: face.editable
            x: 64; width: 832; y: face.slide.layout === "title" ? title.y + Math.max(70, title.height) + 18 : 160; wrapMode: TextEdit.Wrap; textFormat: TextEdit.PlainText
            horizontalAlignment: face.centred ? TextEdit.AlignHCenter : TextEdit.AlignLeft
            color: face.ink; opacity: face.centred ? 0.75 : 0.92; font.family: Theme.t.font; font.pixelSize: face.centred ? 24 : 26; selectionColor: face.accent
            onTextChanged: if (face.editable && activeFocus) face.edited("body", text)
            Text { visible: face.editable && body.text === ""; width: parent.width; horizontalAlignment: parent.horizontalAlignment; text: face.centred ? "Click to add a subtitle" : "Click to add text"; color: face.ink; opacity: 0.35; font: parent.font } } }
    function load() { if (!title.activeFocus) title.text = slide.title || ""; if (!body.activeFocus) body.text = slide.body || "" }
    onSlideChanged: load()
    Component.onCompleted: load()
}
