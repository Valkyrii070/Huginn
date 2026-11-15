import QtQuick

// App Store. Layout in the spirit of the big phone and desktop stores: a featured story on top, shelves of
// apps as rows with one pill button each, and an app page that leads with pictures.
// Glass and islands: the sections of the store are the island at the bottom, where the light comes from.
GlassWindow {
    id: win
    title: "App Store"; glow: "bottom"; padTop: 60
    property string notice: ""
    property var asking: null      // the app waiting for "Remove?" to be answered
    property bool more: false
    property bool updatesView: false               // the Updates page (apps from Flathub with a newer version)
    readonly property var appUpdates: typeof Updates !== "undefined" ? Updates.items.filter(function (i) { return i.kind === "app" && !i.runtime }) : []
    readonly property var runtimeUpdates: typeof Updates !== "undefined" ? Updates.items.filter(function (i) { return i.kind === "app" && i.runtime }) : []
    readonly property var app: Backend.current
    readonly property bool detail: !!app.id
    onAppChanged: more = false
    Connections { target: Backend; function onFailed(msg) { win.notice = msg; hide.restart() } }
    Timer { id: hide; interval: 7000; onTriggered: win.notice = "" }
    readonly property var tones: ["#563AD1", "#AE4518", "#0A8071", "#2361AE", "#3A4047", "#C46A00", "#7B61FF", "#D93A3F"]
    function tone(s) { var h = 0; s = s || ""; for (var i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) % 997; return tones[h % tones.length] }

    component Icon: Rectangle { property var item; property int size: 56
        width: size; height: size; radius: item && item.web ? size / 2 : size * 0.225; color: item && item.icon ? "transparent" : win.tone(item ? item.name : "")
        Image { visible: !!(parent.item && parent.item.icon); anchors.fill: parent; source: parent.item && parent.item.icon ? parent.item.icon : ""; sourceSize.width: 256; sourceSize.height: 256; fillMode: Image.PreserveAspectFit; asynchronous: true }
        Label { visible: !(parent.item && parent.item.icon); anchors.centerIn: parent; text: parent.item && parent.item.name ? parent.item.name.charAt(0) : ""; color: "#FFFFFF"; font.weight: Font.Bold; font.pixelSize: parent.size * 0.42 } }
    // The one button: Get, Open, or what is happening right now.
    component Get: Btn { property var item; property bool strong: false
        readonly property bool working: !!item && Backend.busy === item.id
        pill: !strong; primary: strong; height: strong ? 34 : 30; radius: height / 2
        text: working ? "Working…" : (item && item.installed ? "Open" : "Get"); opacity: working ? 0.6 : 1
        onClicked: if (!working && item) item.installed ? Backend.launch(item.id) : Backend.install(item.id) }
    component Badge: Row { property var item; spacing: 4; visible: !!item && (!!item.verified || !!item.web)
        Glyph { name: parent.item && parent.item.web ? "wifi" : "star"; size: 12; ink: parent.item && parent.item.web ? Theme.t.text_secondary : Theme.t.accent; anchors.verticalCenter: parent.verticalCenter }
        Label { text: parent.item && parent.item.web ? "Web app" : "Verified developer"; color: parent.item && parent.item.web ? Theme.t.text_secondary : Theme.t.accent; font.pixelSize: 11 } }
    // An app as a row on a shelf.
    component AppRow: Item { id: row; property var item; property bool divider: true; property bool manage: false; height: 76
        MouseArea { anchors.fill: parent; onClicked: Backend.show(row.item.id) }
        Icon { anchors.verticalCenter: parent.verticalCenter; item: row.item; size: 56 }
        Label { x: 70; y: 14; width: parent.width - 70 - (row.manage ? 176 : 92); text: row.item.name; font.pixelSize: 14; font.weight: Font.DemiBold; elide: Text.ElideRight }
        Label { x: 70; y: 34; width: parent.width - 70 - (row.manage ? 176 : 92); text: row.item.summary; secondary: true; font.pixelSize: 12; elide: Text.ElideRight }
        Badge { item: row.item; x: 70; y: 53 }
        Btn { visible: row.manage && Backend.busy !== row.item.id; pill: true; anchors { right: get.left; rightMargin: 8; verticalCenter: parent.verticalCenter } text: "Remove"; onClicked: win.asking = row.item }
        Get { id: get; item: row.item; anchors { right: parent.right; verticalCenter: parent.verticalCenter } }
        Rectangle { visible: row.divider; x: 70; anchors.bottom: parent.bottom; width: parent.width - 70; height: 1; color: Theme.t.separator } }
    component Shelf: Column { id: shelf; property string title; property var items: []; property bool manage: false; width: parent.width; spacing: 4
        Label { text: shelf.title; font.pixelSize: 19; font.weight: Font.Bold; bottomPadding: 4 }
        Grid { id: sg; columns: shelf.width > 760 ? 2 : 1; columnSpacing: 36; width: shelf.width
            Repeater { model: shelf.items
                AppRow { required property var modelData; required property int index; item: modelData; manage: shelf.manage
                    width: (shelf.width - 36 * (sg.columns - 1)) / sg.columns; divider: index < shelf.items.length - sg.columns } } } }
    // A picture of the app. Sample catalogues have no pictures, so they get a drawn stand-in that says so.
    component Shot: Rectangle { id: shot; property var info: ({ url: "", caption: "" }); property var item; width: 432; height: 270; radius: 12; clip: true
        color: Theme.t.group; border.width: 1; border.color: Theme.t.separator
        Item { visible: !shot.info.url; anchors.fill: parent
            Rectangle { anchors.fill: parent; radius: 12; opacity: 0.2; color: win.tone(shot.item ? shot.item.name : "") }
            Rectangle { x: 16; y: 16; width: 110; height: parent.height - 32; radius: 8; color: Theme.t.hover }
            Column { x: 142; y: 20; spacing: 12; Repeater { model: [0.8, 0.55, 0.7, 0.4]; Rectangle { required property real modelData; width: (shot.width - 170) * modelData; height: 14; radius: 7; color: Theme.t.hover } } }
            Label { anchors { bottom: parent.bottom; right: parent.right; margins: 12 } text: "Sample image · " + (shot.info.caption || ""); secondary: true; font.pixelSize: 11 } }
        Image { id: pic; visible: !!shot.info.url; anchors.fill: parent; source: shot.info.url || ""; fillMode: Image.PreserveAspectCrop; verticalAlignment: Image.AlignTop; asynchronous: true; sourceSize.width: 900 }
        Label { visible: !!shot.info.url && pic.status !== Image.Ready; anchors.centerIn: parent; secondary: true; text: pic.status === Image.Error ? "This picture couldn't be loaded" : "Loading picture…" } }

    islands: [
        Island { anchors { right: parent.right; rightMargin: 12 } y: 12; IslandField { id: search; placeholder: "Search apps"; onTextChanged: Backend.setQuery(text) } },
        Island {   // the sections: the main island
            anchors { horizontalCenter: parent.horizontalCenter; bottom: parent.bottom; bottomMargin: 14 }
            Repeater { model: Backend.categories
                Seg { required property var modelData; required property int index; icon: index === 0 ? modelData.icon : ""; text: modelData.name
                    on: Backend.category === modelData.name && !win.detail && !win.updatesView; onClicked: { win.updatesView = false; Backend.show(""); Backend.setCategory(modelData.name) } } }
            IslandGap {}
            Seg { icon: "download"; text: "Installed" + (Backend.installedCount > 0 ? "  ·  " + Backend.installedCount : ""); on: Backend.category === "Installed" && !win.detail && !win.updatesView; onClicked: { win.updatesView = false; Backend.show(""); Backend.setCategory("Installed") } }
            Seg { visible: typeof Updates !== "undefined"; icon: "refresh"; text: "Updates" + (win.appUpdates.length > 0 ? "  ·  " + win.appUpdates.length : ""); on: win.updatesView && !win.detail
                onClicked: { Backend.show(""); win.updatesView = true; Updates.look(false) } }
        }
    ]

    Column { visible: !Backend.available; anchors.centerIn: parent; spacing: 8; width: 400
        Glyph { name: "apps"; size: 44; ink: Theme.t.text_secondary; anchors.horizontalCenter: parent.horizontalCenter }
        Label { text: "The app catalogue isn't available"; font.pixelSize: 17; font.weight: Font.DemiBold; anchors.horizontalCenter: parent.horizontalCenter }
        Label { width: parent.width; wrapMode: Text.WordWrap; horizontalAlignment: Text.AlignHCenter; secondary: true; lineHeight: 1.3; text: "App Store installs apps with Flatpak, which isn't on this computer. On Huginn OS it is built in. Start with --demo to preview the store." } }
    Label { visible: Backend.available && !Backend.ready; anchors.centerIn: parent; text: "Reading the app catalogue…"; secondary: true }
    Column { visible: Backend.available && Backend.ready && Backend.count === 0 && Backend.installedCount === 0; anchors.centerIn: parent; spacing: 8; width: 400
        Label { text: "No catalogue yet"; font.pixelSize: 17; font.weight: Font.DemiBold; anchors.horizontalCenter: parent.horizontalCenter }
        Label { width: parent.width; wrapMode: Text.WordWrap; horizontalAlignment: Text.AlignHCenter; secondary: true; lineHeight: 1.3; text: "The list of apps hasn't been downloaded. Connect to the internet and open App Store again." } }

    // ---------------- Updates
    Flickable { visible: win.updatesView && !win.detail; anchors.fill: parent; contentHeight: ups.height + 110; clip: true
        Column { id: ups; x: 28; y: 6; width: parent.width - 56; spacing: 18
            Item { width: parent.width; height: 64
                Column { anchors.verticalCenter: parent.verticalCenter; spacing: 2
                    Label { text: win.appUpdates.length ? win.appUpdates.length + (win.appUpdates.length === 1 ? " app has an update" : " apps have updates") : "Your apps are up to date"; font.pixelSize: 26; font.weight: Font.Light }
                    Label { text: typeof Updates === "undefined" ? "" : Updates.phase === "installing" ? Updates.line : Updates.phase === "checking" ? "Looking for updates…" : "Last looked " + Updates.checked.toLowerCase() + (win.runtimeUpdates.length ? " · " + win.runtimeUpdates.length + (win.runtimeUpdates.length === 1 ? " shared part too" : " shared parts too") : ""); secondary: true } }
                Row { anchors { right: parent.right; verticalCenter: parent.verticalCenter } spacing: 8
                    Btn { text: "Check Now"; visible: typeof Updates !== "undefined" && Updates.phase === "idle"; onClicked: Updates.look(true) }
                    Btn { primary: true; text: "Update All"; visible: typeof Updates !== "undefined" && (win.appUpdates.length + win.runtimeUpdates.length) > 0 && Updates.phase === "idle"; onClicked: Updates.install("app") } } }
            Meter { visible: typeof Updates !== "undefined" && Updates.phase === "installing"; width: parent.width; value: typeof Updates !== "undefined" ? Updates.progress : 0 }
            Repeater { model: win.appUpdates
                Item { required property var modelData; width: ups.width; height: 76
                    readonly property var info: Backend.info(modelData.app)
                    MouseArea { anchors.fill: parent; onClicked: if (parent.info.id) Backend.show(modelData.app) }
                    Icon { anchors.verticalCenter: parent.verticalCenter; item: parent.info.id ? parent.info : { name: modelData.name }; size: 56 }
                    Label { x: 70; y: 16; width: parent.width - 200; text: modelData.name; font.pixelSize: 14; font.weight: Font.DemiBold; elide: Text.ElideRight }
                    Label { x: 70; y: 37; width: parent.width - 200; text: (modelData.version ? "Version " + modelData.version : "A newer version") + (modelData.where === "user" ? " · just for you" : ""); secondary: true; font.pixelSize: 12 }
                    Btn { pill: true; anchors { right: parent.right; verticalCenter: parent.verticalCenter } text: "Update"; enabled: Updates.phase === "idle"; onClicked: Updates.install(modelData.id) }
                    Rectangle { anchors.bottom: parent.bottom; x: 70; width: parent.width - 70; height: 1; color: Theme.t.separator } } }
            Label { width: parent.width; wrapMode: Text.WordWrap; secondary: true; font.pixelSize: 12; lineHeight: 1.3
                text: "With automatic updates on (Settings › Software Update), apps update by themselves every few hours. Shared parts are the runtimes apps are built on; they update with them." } } }
    // ---------------- Browse
    Flickable { visible: Backend.ready && (Backend.count > 0 || Backend.installedCount > 0) && !win.detail && !win.updatesView; anchors.fill: parent; contentHeight: page.height + 110; clip: true
        Column { id: page; x: 28; y: 6; width: parent.width - 56; spacing: 26
            readonly property bool home: Backend.category === "Discover" && search.text === ""
            Rectangle {   // the featured story
                id: story; visible: page.home && !!Backend.featured.id; width: parent.width; height: 250; radius: 16; clip: true
                readonly property var item: Backend.featured
                gradient: Gradient { orientation: Gradient.Horizontal; GradientStop { position: 0; color: Theme.t.dark ? Qt.darker(Theme.t.accent, 1.5) : Theme.t.accent } GradientStop { position: 1; color: "#6B55E8" } }
                MouseArea { anchors.fill: parent; onClicked: Backend.show(story.item.id) }
                Shot { visible: story.width > 700; info: story.item.shots && story.item.shots.length ? story.item.shots[0] : ({ url: "", caption: "" }); item: story.item
                    x: parent.width - 380; y: 34; width: 420; height: 262; rotation: -3; border.color: "#33FFFFFF" }
                Label { x: 28; y: 26; text: "FEATURED TODAY"; color: "#E6FFFFFF"; font.pixelSize: 11; font.weight: Font.Bold; font.letterSpacing: 1 }
                Label { x: 28; y: 48; width: parent.width - 440; text: story.item.name || ""; color: "#FFFFFF"; font.pixelSize: 32; font.weight: Font.Light; elide: Text.ElideRight }
                Label { x: 28; y: 94; width: Math.min(parent.width - 440, 420); text: story.item.summary || ""; color: "#F2FFFFFF"; font.pixelSize: 15; wrapMode: Text.WordWrap; maximumLineCount: 2; elide: Text.ElideRight }
                Rectangle { x: 16; y: parent.height - 78; width: Math.min(360, parent.width - 32); height: 62; radius: 14; color: "#33000000"
                    Icon { x: 10; anchors.verticalCenter: parent.verticalCenter; item: story.item; size: 42 }
                    Label { x: 62; y: 12; width: parent.width - 160; text: story.item.name || ""; color: "#FFFFFF"; font.weight: Font.DemiBold; elide: Text.ElideRight }
                    Label { x: 62; y: 31; width: parent.width - 160; text: story.item.developer || ""; color: "#CCFFFFFF"; font.pixelSize: 11; elide: Text.ElideRight }
                    Btn { anchors { right: parent.right; rightMargin: 12; verticalCenter: parent.verticalCenter } width: 72; radius: 15; color: "#FFFFFF"; border.width: 0
                        textColor: "#101317"; text: story.item.installed ? "Open" : "Get"; onClicked: story.item.installed ? Backend.launch(story.item.id) : Backend.install(story.item.id) } } }
            Shelf { title: search.text ? "Results for “" + search.text + "”" : (page.home ? "Popular Picks" : Backend.category); items: page.home ? Backend.apps.slice(0, 8) : Backend.apps; manage: Backend.category === "Installed" && search.text === "" }
            Label { visible: Backend.apps.length === 0; text: Backend.category === "Installed" ? "Apps you get from the store, and web apps you install from Huginn, appear here." : "Nothing found."; secondary: true }
            Shelf { visible: page.home && Backend.fresh.length > 0; title: "From Verified Developers"; items: Backend.fresh }
            Label { visible: page.home; width: parent.width; wrapMode: Text.WordWrap; secondary: true; font.pixelSize: 12; lineHeight: 1.3
                text: "Apps come from Flathub and each runs in its own sandbox. “Verified developer” means the app is published by the people who make it." }
        } }
    // ---------------- One app
    Flickable { visible: win.detail; anchors.fill: parent; contentHeight: one.height + 120; clip: true
        Column { id: one; x: 32; y: 14; width: parent.width - 64; spacing: 20
            Pressable { width: back.width + 18; height: 28; radius: Theme.t.radiusControl; onClicked: Backend.show("")
                Row { id: back; anchors.centerIn: parent; spacing: 4; Glyph { name: "back"; size: 14; ink: Theme.t.accent; anchors.verticalCenter: parent.verticalCenter } Label { text: Backend.category; color: Theme.t.accent } } }
            Item { width: parent.width; height: 128   // header: icon, name, subtitle, the button
                Icon { item: win.app; size: 128 }
                Label { x: 150; y: 6; width: parent.width - 150; text: win.app.name || ""; font.pixelSize: 28; font.weight: Font.DemiBold; elide: Text.ElideRight }
                Label { x: 150; y: 44; width: parent.width - 150; text: win.app.summary || ""; secondary: true; font.pixelSize: 15; elide: Text.ElideRight }
                Row { x: 150; y: 88; spacing: 10
                    Get { item: win.app; strong: true; width: 96 }
                    Btn { visible: !!win.app.installed && Backend.busy !== win.app.id; pill: true; height: 34; radius: 17; text: "Remove"; onClicked: win.asking = win.app }
                    Badge { item: win.app; anchors.verticalCenter: parent.verticalCenter } } }
            Card { visible: Backend.busy === win.app.id; width: parent.width; height: 44
                Label { x: 14; anchors.verticalCenter: parent.verticalCenter; width: parent.width - 28; elide: Text.ElideRight; text: Backend.progress; font.family: Theme.t.fontMono; font.pixelSize: 12 } }
            // Facts at a glance.
            Item { id: strip; width: parent.width; height: 78
                readonly property var cells: [["CATEGORY", win.app.category || "", ""], ["DEVELOPER", win.app.developer || "", win.app.verified ? "Verified" : ""], ["SIZE", win.app.size || "", "to download"],
                                              ["VERSION", win.app.version || "", win.app.released || ""], ["CODE", win.app.web ? "" : (win.app.open ? "Open" : "Closed"), win.app.open ? "source" : "source"]].filter(function (c) { return c[1] !== "" })
                Rectangle { width: parent.width; height: 1; color: Theme.t.separator } Rectangle { y: parent.height - 1; width: parent.width; height: 1; color: Theme.t.separator }
                Row { anchors.fill: parent
                    Repeater { model: strip.cells
                        Item { required property var modelData; required property int index; width: strip.width / strip.cells.length; height: strip.height
                            Rectangle { visible: index > 0; y: 18; width: 1; height: parent.height - 36; color: Theme.t.separator }
                            Label { y: 13; width: parent.width; horizontalAlignment: Text.AlignHCenter; text: modelData[0]; color: Theme.t.text_secondary; font.pixelSize: 10; font.weight: Font.DemiBold; font.letterSpacing: 0.5 }
                            Label { y: 30; x: 8; width: parent.width - 16; horizontalAlignment: Text.AlignHCenter; text: modelData[1]; secondary: true; font.pixelSize: 16; font.weight: Font.DemiBold; elide: Text.ElideRight }
                            Label { y: 54; width: parent.width; horizontalAlignment: Text.AlignHCenter; text: modelData[2]; color: Theme.t.text_secondary; font.pixelSize: 11 } } } } }
            // Pictures first, before you decide.
            Column { visible: !!(win.app.shots && win.app.shots.length); width: parent.width; spacing: 10
                Label { text: "Preview"; font.pixelSize: 19; font.weight: Font.Bold }
                Flickable { width: parent.width; height: 270; contentWidth: gallery.width; clip: true; flickableDirection: Flickable.HorizontalFlick
                    Row { id: gallery; spacing: 14; Repeater { model: win.app.shots || []; Shot { required property var modelData; info: modelData; item: win.app } } } }
                Label { visible: !!(win.app.shots && win.app.shots.length && win.app.shots[0].url); text: "Pictures are provided by the developer and load from Flathub."; color: Theme.t.text_secondary; font.pixelSize: 11 } }
            Column { width: Math.min(parent.width, 720); spacing: 6
                Label { id: desc; width: parent.width; text: win.app.description || ""; wrapMode: Text.WordWrap; lineHeight: 1.45; maximumLineCount: win.more ? 200 : 4; elide: Text.ElideRight }
                Pressable { visible: desc.truncated || win.more; width: m.width + 4; height: 22; onClicked: win.more = !win.more; Label { id: m; anchors.verticalCenter: parent.verticalCenter; text: win.more ? "less" : "more"; color: Theme.t.accent } } }
            Column { width: parent.width; spacing: 6
                Label { text: "Information"; font.pixelSize: 19; font.weight: Font.Bold; bottomPadding: 4 }
                Grid { columns: one.width > 700 ? 2 : 1; columnSpacing: 36; width: parent.width
                    Repeater { model: [["Source", win.app.web ? "Huginn web app" : "Flathub"], ["Developer", win.app.developer || ""], ["Category", win.app.category || ""], ["Version", win.app.version || ""], ["Updated", win.app.released || ""],
                                       ["Download size", win.app.size || ""], ["Licence", win.app.license || ""], ["Runs in", win.app.web ? "Huginn" : "Its own sandbox"], ["Identifier", win.app.web ? "" : (win.app.id || "")]].filter(function (r) { return r[1] !== "" })
                        Item { required property var modelData; width: (one.width - (parent.columns > 1 ? 36 : 0)) / parent.columns; height: 40
                            Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: Theme.t.separator }
                            Label { anchors.verticalCenter: parent.verticalCenter; text: modelData[0]; secondary: true }
                            Label { anchors { right: parent.right; verticalCenter: parent.verticalCenter } width: parent.width - 130; horizontalAlignment: Text.AlignRight; elide: Text.ElideMiddle; text: modelData[1] } } } } }
        } }
    Rectangle { visible: win.asking !== null; anchors { fill: parent; topMargin: -60 } radius: win.r; color: "#66000000"; z: 30; MouseArea { anchors.fill: parent } }
    Rectangle { visible: win.asking !== null; z: 31; anchors.centerIn: parent; width: 400; height: 178; radius: Theme.t.radiusTile; color: Theme.t.menu_bg; border.width: 1; border.color: Theme.t.menu_border
        Label { x: 22; y: 20; text: "Remove “" + (win.asking ? win.asking.name : "") + "”?"; font.pixelSize: 16; font.weight: Font.DemiBold }
        Label { x: 22; y: 50; width: parent.width - 44; wrapMode: Text.WordWrap; secondary: true; lineHeight: 1.3
            text: win.asking && win.asking.web ? "It leaves the launcher and dock. The website and your account there stay as they are, and you can install it again from Huginn."
                                               : "The app is uninstalled. You can get it again from the store at any time." }
        Row { anchors { right: parent.right; rightMargin: 22; bottom: parent.bottom; bottomMargin: 20 } spacing: 8
            Btn { text: "Cancel"; onClicked: win.asking = null } Btn { text: "Remove"; danger: true; onClicked: { Backend.remove(win.asking.id); win.asking = null } } } }
    Rectangle { visible: win.notice !== ""; z: 40; anchors { bottom: parent.bottom; bottomMargin: 68; horizontalCenter: parent.horizontalCenter } width: Math.min(parent.width - 40, n.implicitWidth + 32); height: 38; radius: 19; color: Theme.t.menu_bg; border.width: 1; border.color: Theme.t.danger
        Label { id: n; anchors.centerIn: parent; width: parent.width - 32; elide: Text.ElideRight; text: win.notice; color: Theme.t.danger } }
}
