import QtQuick

// Keyboard & Mouse: layouts and typing, then each touchpad and mouse with its own settings.
Column {
    id: pg
    width: parent ? parent.width : 600; spacing: 18
    readonly property var k: Backend.input
    SetCard { title: "Keyboard"
        SetRow { title: "Layouts"; sub: (pg.k.layouts || []).length > 1 ? "Switch with Meta+Space, or from the top bar" : "Add another to type in more languages"
            Row { spacing: 6
                Repeater { model: pg.k.layouts || []
                    Rectangle { required property var modelData; required property int index; height: 26; width: lab.width + (pg.k.layouts.length > 1 ? 38 : 20); radius: 9; color: Theme.t.dark ? "#22FFFFFF" : "#14141E28"; anchors.verticalCenter: parent.verticalCenter
                        Label { id: lab; x: 10; anchors.verticalCenter: parent.verticalCenter; text: modelData.id.toUpperCase(); font.pixelSize: 11; font.weight: Font.DemiBold }
                        Glyph { visible: pg.k.layouts.length > 1; x: lab.width + 16; anchors.verticalCenter: parent.verticalCenter; name: "x"; size: 11; ink: Theme.t.text_secondary
                            MouseArea { anchors.fill: parent; anchors.margins: -4; onClicked: Backend.setKeyboard("layouts", pg.k.layouts.filter(function (l, i) { return i !== index }).map(function (l) { return l.id })) } } } }
                Seg { icon: "plus"; tip: "Add a layout"; onClicked: win.pick("Add a keyboard layout", Backend.layoutChoices.map(function (l) { return { id: l.id, label: l.label, sub: l.id } }), "",
                                                                            function (v) { Backend.setKeyboard("layouts", pg.k.layouts.map(function (l) { return l.id }).concat([v])) }) } } }
        SetRow { title: "Caps Lock key works as"; SetPick { text: (pg.k.capsChoices || []).filter(function (c) { return c.id === pg.k.caps })[0] ? pg.k.capsChoices.filter(function (c) { return c.id === pg.k.caps })[0].label : "Caps Lock"
            onClicked: win.pick("Caps Lock works as", pg.k.capsChoices, pg.k.caps, function (v) { Backend.setKeyboard("caps", v) }) } }
        SetRow { title: "Compose key"; sub: "Right Alt, then two keys, makes a character: ' then e is é"; Toggle { on: !!pg.k.compose; onToggled: function (v) { Backend.setKeyboard("compose", v) } } }
        SetRow { title: "Repeat keys when held"; Toggle { on: pg.k.repeat !== false; onToggled: function (v) { Backend.setKeyboard("repeat", v) } } }
        SetRow { visible: pg.k.repeat !== false; title: "Delay before repeating"
            SetSlider { width: 240; lowText: "Short"; highText: "Long"; value: ((pg.k.delay || 600) - 150) / 850; onMoved: function (v) { Backend.setKeyboard("delay", Math.round(150 + v * 850)) } } }
        SetRow { visible: pg.k.repeat !== false; title: "Repeat speed"
            SetSlider { width: 240; lowText: "Slow"; highText: "Fast"; value: ((pg.k.rate || 25) - 5) / 55; onMoved: function (v) { Backend.setKeyboard("rate", Math.round(5 + v * 55)) } } } }
    Repeater { model: pg.k.pointers || []
        SetCard { required property var modelData; title: modelData.touchpad ? "Touchpad · " + modelData.name : "Mouse · " + modelData.name
            SetRow { title: "Pointer speed"
                SetSlider { width: 240; lowText: "Slow"; highText: "Fast"; value: (modelData.speed + 1) / 2; onMoved: function (v) { Backend.setPointer(modelData.sys, "speed", v * 2 - 1) } } }
            SetRow { title: "Natural scrolling"; sub: "The content moves with your fingers, like a phone"; Toggle { on: modelData.natural; onToggled: function (v) { Backend.setPointer(modelData.sys, "natural", v) } } }
            SetRow { visible: modelData.touchpad && modelData.canTap; title: "Tap to click"; sub: "Two fingers is a right-click"; Toggle { on: modelData.tap; onToggled: function (v) { Backend.setPointer(modelData.sys, "tap", v) } } }
            SetRow { visible: modelData.touchpad && modelData.canDwt; title: "Ignore the touchpad while typing"; Toggle { on: modelData.dwt; onToggled: function (v) { Backend.setPointer(modelData.sys, "dwt", v) } } }
            SetRow { visible: !modelData.touchpad; title: "Left-handed"; sub: "Swaps the buttons"; Toggle { on: modelData.left; onToggled: function (v) { Backend.setPointer(modelData.sys, "left", v) } } } } }
    SetCard { visible: (pg.k.pointers || []).length === 0; title: "Touchpad and mouse"
        SetRow { title: "No pointing devices found"; sub: "They show here when Huginn's session is running (KWin tells Settings about them)." } }
}
