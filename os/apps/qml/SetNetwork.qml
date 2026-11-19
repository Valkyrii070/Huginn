import QtQuick

// Wi‑Fi & Network: the radio, the networks in range, wired, VPN, hotspot and saved networks.
Column {
    id: pg
    width: parent ? parent.width : 600; spacing: 18
    readonly property var n: Backend.network
    // The network in use: Wi‑Fi if it's connected, else the cable. Its addresses stay hidden until asked for
    // (anyone looking over your shoulder or at a shared screen sees dots), and hide again when you leave the page.
    readonly property bool onWifi: !!(n.details && n.wifiDevice && n.details[n.wifiDevice])
    readonly property bool onCable: !!(n.wired && n.wired.state === "connected" && n.details && n.details[n.wired.device])
    readonly property var here: onWifi ? n.details[n.wifiDevice] : onCable ? n.details[n.wired.device] : null
    readonly property string hereName: onWifi ? (n.current || "Wi‑Fi") : onCable ? (n.wired.connection || "Ethernet") : ""
    property bool reveal: false
    onVisibleChanged: if (!visible) reveal = false
    function hidden(text) { return reveal || !text ? (text || "—") : String(text).replace(/[0-9A-Fa-f]/g, "•") }
    function join(w) {
        if (w.inUse) return
        if (w.saved) Backend.joinSaved(w.ssid)
        else if (w.secure) win.ask("Join “" + w.ssid + "”", "Type the network's password. It's kept by the system, so you only type it once.",
                                   [{ key: "pw", label: "Password", secret: true }], "Join", function (v) { Backend.joinWifi(w.ssid, v.pw) })
        else win.confirm("Join “" + w.ssid + "”?", "This network has no password, so others nearby could see what you send that isn't encrypted. Huginn's pages use HTTPS where they can.", "Join",
                         function () { Backend.joinWifi(w.ssid, "") }, false)
    }
    component Bars: Row { property int n: 0; spacing: 2; height: 14
        Repeater { model: 4; Rectangle { required property int index; width: 3; height: 4 + index * 3; radius: 1; anchors.bottom: parent.bottom
            color: index < n ? Theme.t.text : (Theme.t.dark ? "#33FFFFFF" : "#33141E28") } } }

    SetCard { visible: pg.n.available === false
        SetRow { title: "Networking isn't available here"; sub: "NetworkManager isn't installed or isn't running, so networks can't be listed."; glyph: "wifi" } }
    SetCard { visible: pg.n.available !== false
        SetRow { title: "Wi‑Fi"; glyph: "wifi"; tile: "#3B8DF0"
            sub: !pg.n.hasWifi ? "This computer has no Wi‑Fi" : pg.n.current ? "Connected to " + pg.n.current : pg.n.wifiOn ? "On, not connected" : "Off"
            Toggle { visible: !!pg.n.hasWifi; on: !!pg.n.wifiOn; onToggled: function (v) { Backend.setWifi(v) } } }
        SetRow { title: "Airplane mode"; sub: "Wi‑Fi and Bluetooth off, for flights and quiet"; glyph: "send"; tile: "#F08C3B"
            Toggle { on: !!pg.n.airplane; onToggled: function (v) { Backend.setAirplane(v) } } }
        SetRow { visible: !!pg.n.wired; title: "Ethernet"; glyph: "route"; tile: "#5A6474"
            sub: pg.n.wired ? (pg.n.wired.state === "connected" ? "Connected to " + (pg.n.wired.connection || "the network") : pg.n.wired.state === "unavailable" ? "No cable plugged in" : "Not connected") : "" } }

    SetCard { visible: !!pg.here; title: "This network"
        SetRow { title: pg.hereName; sub: pg.onWifi ? "Wi‑Fi" : "Ethernet"; glyph: pg.onWifi ? "wifi" : "ethernet"; tile: pg.onWifi ? "#3B8DF0" : "#5A6474"
            Btn { text: pg.reveal ? "Hide addresses" : "Show addresses"; onClicked: pg.reveal = !pg.reveal } }
        SetRow { title: "IP address"; Label { text: pg.hidden(pg.here ? pg.here.ip : ""); secondary: true; font.family: Theme.t.fontMono } }
        SetRow { title: "Router"; Label { text: pg.hidden(pg.here ? pg.here.gateway : ""); secondary: true; font.family: Theme.t.fontMono } }
        SetRow { title: "DNS"; Label { text: pg.hidden(pg.here ? pg.here.dns : ""); secondary: true; font.family: Theme.t.fontMono } }
        SetRow { title: "Hardware address"; sub: "Some routers use it to recognise this computer"; Label { text: pg.hidden(pg.here ? pg.here.mac : ""); secondary: true; font.family: Theme.t.fontMono } }
        SetRow { visible: pg.onWifi; title: ""; Row { spacing: 8
            Btn { text: "Disconnect"; onClicked: Backend.disconnect(pg.n.wifiDevice) }
            Btn { text: "Forget This Network"; danger: true; onClicked: { var s = pg.n.current; win.confirm("Forget “" + s + "”?", "This computer won't join it by itself any more, and you'll need its password again.", "Forget", function () { Backend.forgetNetwork(s) }) } } } } }

    SetCard { visible: pg.n.available !== false && !!pg.n.wifiOn && !!pg.n.hasWifi; title: "Networks nearby"
        note: (pg.n.networks || []).length ? "" : "Looking for networks…"
        Repeater { model: pg.n.networks || []
            SetRow { required property var modelData; title: modelData.ssid; chevron: !modelData.inUse
                sub: (modelData.inUse ? "Connected" : modelData.saved ? "Saved · joins by itself" : modelData.secure ? modelData.security : "Open network, no password") + (modelData.band ? " · " + modelData.band : "")
                onClicked: pg.join(modelData)
                Row { spacing: 10
                    Glyph { visible: modelData.secure; name: "lock"; size: 13; ink: Theme.t.text_secondary; anchors.verticalCenter: parent.verticalCenter }
                    Bars { n: modelData.bars; anchors.verticalCenter: parent.verticalCenter }
                    Glyph { visible: modelData.inUse; name: "check"; size: 16; ink: Theme.t.accent; anchors.verticalCenter: parent.verticalCenter } } } }
        SetRow { title: "Join another network…"; sub: "For a network that doesn't show its name"; chevron: true
            onClicked: win.ask("Join a hidden network", "", [{ key: "ssid", label: "Network name" }, { key: "pw", label: "Password (leave empty if there isn't one)", secret: true }], "Join",
                               function (v) { if (v.ssid.trim()) Backend.joinWifi(v.ssid.trim(), v.pw) }) } }

    SetCard { visible: pg.n.available !== false; title: "VPN"; note: "A VPN sends your traffic through another network first. Add one from the file your VPN provider gave you (WireGuard .conf or OpenVPN .ovpn)."
        Repeater { model: pg.n.vpns || []
            SetRow { required property var modelData; title: modelData.name; sub: (modelData.wireguard ? "WireGuard" : "VPN") + (modelData.active ? " · connected" : ""); glyph: "shield"; tile: modelData.active ? "#27A35A" : "#7D8CA3"
                Row { spacing: 10
                    Seg { icon: "trash"; tip: "Remove"; onClicked: { var u = modelData.uuid, nm = modelData.name; win.confirm("Remove “" + nm + "”?", "You can add it again from its file.", "Remove", function () { Backend.forget(u) }) } }
                    Toggle { on: modelData.active; anchors.verticalCenter: parent.verticalCenter; onToggled: function (v) { Backend.setVpn(modelData.uuid, v) } } } } }
        SetRow { title: "Add a VPN…"; chevron: true
            onClicked: { var files = Backend.vpnFiles(); if (files.length) win.pick("Add a VPN from a file", files, "", function (p) { Backend.importVpn(p) })
                         else win.ask("Add a VPN", "No VPN files were found in Downloads. Type where the file is.", [{ key: "path", label: "File", placeholder: "~/Documents/work.conf" }], "Add",
                                      function (v) { Backend.importVpn(v.path) }) } } }

    SetCard { visible: pg.n.available !== false && !!pg.n.hasWifi; title: "Share this connection"
        SetRow { title: "Personal hotspot"; sub: pg.n.hotspot ? "On: other devices can join this computer's Wi‑Fi" : "Lets a phone or tablet use this computer's wired connection"; glyph: "share"; tile: "#27A35A"
            Toggle { on: !!pg.n.hotspot; onToggled: function (v) { Backend.setHotspot(v) } } } }

    SetCard { visible: (pg.n.saved || []).length > 0; title: "Saved networks"; note: "These join by themselves when they're in range."
        Repeater { model: pg.n.saved || []
            SetRow { required property var modelData; title: modelData.name; sub: modelData.active ? "Connected now" : ""
                Btn { text: "Forget"; onClicked: { var u = modelData.uuid, nm = modelData.name; win.confirm("Forget “" + nm + "”?", "You'll need its password again to join.", "Forget", function () { Backend.forget(u) }) } } } } }
}
