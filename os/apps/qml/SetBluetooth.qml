import QtQuick

// Bluetooth: on or off, the devices you've paired, and ones nearby to pair.
Column {
    id: pg
    width: parent ? parent.width : 600; spacing: 18
    readonly property var b: Backend.bluetooth
    readonly property bool scanning: Backend.busy.indexOf("bluetooth") >= 0
    readonly property var kinds: ({ headphones: "headphones", speaker: "speaker", keyboard: "keyboard", mouse: "mouse", gamepad: "gamepad", phone: "phone", computer: "desktop", pen: "edit", device: "bluetooth" })
    SetCard { visible: pg.b.available === false || pg.b.present === false
        SetRow { title: pg.b.available === false ? "Bluetooth isn't available here" : "No Bluetooth on this computer"; glyph: "bluetooth"
            sub: pg.b.available === false ? "BlueZ isn't installed or isn't running." : "Plug in a Bluetooth adapter and it shows up here." } }
    SetCard { visible: pg.b.available !== false && pg.b.present !== false
        SetRow { title: "Bluetooth"; glyph: "bluetooth"; tile: "#3B6CF0"
            sub: pg.b.powered ? "On · this computer shows as “" + (pg.b.name || "") + "”" : "Off"
            Toggle { on: !!pg.b.powered; onToggled: function (v) { Backend.setBluetooth(v) } } }
        SetRow { visible: !!pg.b.powered; title: "Visible to others"; sub: "Lets a phone or another computer find this one to pair"
            Toggle { on: !!pg.b.discoverable; onToggled: function (v) { Backend.setDiscoverable(v) } } } }
    SetCard { visible: !!pg.b.powered && (pg.b.devices || []).some(function (d) { return d.paired }); title: "My devices"
        Repeater { model: (pg.b.devices || []).filter(function (d) { return d.paired })
            SetRow { required property var modelData; title: modelData.name; glyph: pg.kinds[modelData.kind] || "bluetooth"; tile: modelData.connected ? "#3B6CF0" : "#7D8CA3"
                sub: (modelData.connected ? "Connected" : "Not connected") + (modelData.battery >= 0 ? " · battery " + modelData.battery + "%" : "")
                Row { spacing: 8
                    Btn { text: modelData.connected ? "Disconnect" : "Connect"; onClicked: Backend.setConnected(modelData.mac, !modelData.connected) }
                    Seg { icon: "trash"; tip: "Forget"; onClicked: { var m = modelData.mac, nm = modelData.name; win.confirm("Forget “" + nm + "”?", "To use it again you'll pair it again.", "Forget", function () { Backend.unpair(m) }) } } } } } }
    SetCard { visible: !!pg.b.powered; title: "Nearby"
        note: pg.scanning ? "Looking… put the device in pairing mode (usually by holding its button)." : "Put the device in pairing mode, then look."
        Repeater { model: (pg.b.devices || []).filter(function (d) { return !d.paired })
            SetRow { required property var modelData; title: modelData.name; glyph: pg.kinds[modelData.kind] || "bluetooth"; sub: modelData.mac
                Btn { text: "Pair"; primary: true; onClicked: Backend.pair(modelData.mac) } } }
        SetRow { title: pg.scanning ? "Looking for devices…" : "Look for devices"; chevron: !pg.scanning; onClicked: Backend.scanBluetooth() } }
}
