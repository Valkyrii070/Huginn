import QtQuick

// Desktop & Dock: the dock, its stacks, the top bar, Today, windows, the Overview and spaces, the live island, motion.
// One page, with a live preview on top: a little desktop that plays whatever choice you point at.
Column {
    id: pg
    width: parent ? parent.width : 600; spacing: 18
    property string playing: "hide:" + Settings.hideStyle          // what the preview plays (pointing at a choice changes it)
    function show(what) { playing = what; stage.replay() }
    function sw(key) { return function (v) { Settings.set(key, v ? "true" : "false") } }

    // ---------------------------------------------------------------- the live preview
    Rectangle {
        id: stage
        width: parent.width; height: 190; radius: 16; clip: true
        gradient: Gradient { GradientStop { position: 0; color: Qt.darker(Theme.t.tintB, 1.4) } GradientStop { position: 1; color: Qt.darker(Theme.t.tintA, 1.2) } }
        border.width: 1; border.color: Theme.t.islandLine
        function replay() { t.restart() }
        property real p: 0
        NumberAnimation { id: t; target: stage; property: "p"; from: 0; to: 1; duration: 1600; easing.type: Easing.InOutCubic }
        Timer { interval: 2600; running: true; repeat: true; onTriggered: stage.replay() }
        readonly property string kind: pg.playing.split(":")[0]
        readonly property string how: pg.playing.split(":")[1] || ""
        Rectangle {   // the top bar
            width: parent.width; height: 16; color: Qt.rgba(0, 0, 0, 0.25)
            Row { x: 8; anchors.verticalCenter: parent.verticalCenter; spacing: 6
                Rectangle { width: 7; height: 7; radius: 4; color: Theme.t.accent; anchors.verticalCenter: parent.verticalCenter }
                Label { text: Settings.clock24 ? "14:24" : "2:24 PM"; font.pixelSize: 8; color: "white" }
                Label { visible: Settings.barDate; text: "Sun, Nov 15"; font.pixelSize: 8; color: "#C9D1D9" }
                Label { text: stage.kind === "menu" && stage.how === "row" ? "Writer   File   Edit   View" : "Writer ⌄"; font.pixelSize: 8; font.weight: Font.DemiBold; color: "white" } }
        }
        Rectangle {   // the one menu, or a row's list
            visible: stage.kind === "menu"; x: stage.how === "row" ? 120 : 64; y: 18; width: stage.how === "row" ? 70 : 120; height: 70 * Math.min(1, stage.p * 3); radius: 6; clip: true
            color: Qt.rgba(0.1, 0.11, 0.14, 0.95); border.width: 1; border.color: Qt.rgba(1, 1, 1, 0.15)
            Column { x: 6; y: 6; spacing: 4; Repeater { model: 5; Rectangle { width: index === 2 ? 40 : 55; height: 5; radius: 2; color: index === 0 ? Theme.t.accent : Qt.rgba(1, 1, 1, 0.3) } } }
        }
        // two windows: they hide into the dock, glide apart (the Overview), or one opens out of a row
        Repeater {
            model: 2
            Rectangle {
                id: mini
                required property int index
                readonly property real p: stage.p
                readonly property bool hiding: stage.kind === "hide" && index === 0
                readonly property bool spread: stage.kind === "overview"
                // home
                readonly property real hx: index === 0 ? 150 : 210
                readonly property real hy: index === 0 ? 34 : 48
                readonly property real hw: 150
                readonly property real hh: 92
                // spread apart
                readonly property real sx: index === 0 ? stage.width / 2 - 170 : stage.width / 2 + 20
                readonly property real s: spread ? 1 - 0.15 * Math.min(1, p * 2) : 1
                x: hiding ? hideX() : spread ? hx + (sx - hx) * Math.min(1, p * 2) : hx
                y: hiding ? hideY() : spread ? hy + (60 - hy) * Math.min(1, p * 2) : hy
                width: hiding ? hideW() : hw * s; height: hiding ? hideH() : hh * s
                radius: 6; color: index === 0 ? "#F2F4F7" : "#2A2F37"; border.width: 1; border.color: Qt.rgba(1, 1, 1, 0.2)
                opacity: hiding && p > 0.85 ? (1 - p) / 0.15 : 1
                visible: stage.kind !== "motion" || index === 1
                function hideX() { var t = p, cx = stage.width / 2 + 40; if (stage.how === "comet") return hx + (cx - hx) * t * t + hw / 2 * (1 - t) - 4 * t; return hx + (cx - 12 - hx) * Math.max(0, (t - 0.38) / 0.62) + (hw - hideW()) / 2 * Math.min(1, t / 0.38) * 0 }
                function hideY() { var t = p; if (stage.how === "comet") return hy + (stage.height - 30 - hy) * t * t - Math.sin(t * Math.PI) * 30; var fold = Math.min(1, t / 0.38); return hy + (hh - hideH()) / 2 + (stage.height - 34 - hy - hh / 2) * Math.max(0, (t - 0.65) / 0.35) }
                function hideW() { var t = p; if (stage.how === "comet") return Math.max(6, hw * (1 - t)); return hw + (20 - hw) * Math.max(0, Math.min(1, (t - 0.38) / 0.27)) }
                function hideH() { var t = p; if (stage.how === "comet") return Math.max(6, hh * (1 - t)); return hh + (3 - hh) * Math.min(1, t / 0.38) }
                Rectangle { anchors.fill: parent; radius: parent.radius; color: Theme.t.glowA; opacity: mini.hiding ? Math.min(0.8, mini.p * 2) : 0 }
            }
        }
        Rectangle {   // the Overview's light, sweeping up (Glide with light)
            visible: stage.kind === "overview" && stage.how === "light"
            width: parent.width; height: 80; y: stage.height - (stage.height + 80) * stage.p
            gradient: Gradient { GradientStop { position: 0; color: "transparent" } GradientStop { position: 0.5; color: Qt.rgba(Theme.t.glowA.r, Theme.t.glowA.g, Theme.t.glowA.b, 0.35) } GradientStop { position: 1; color: "transparent" } }
        }
        Column {   // in an app: a list, and the item opening out of its row (or sliding in)
            visible: stage.kind === "motion"; x: 40; y: 34; spacing: 5
            Repeater { model: 4; Rectangle { width: 110; height: 18; radius: 4; color: index === 1 ? Qt.rgba(Theme.t.accent.r, Theme.t.accent.g, Theme.t.accent.b, 0.4) : Qt.rgba(1, 1, 1, 0.12) } }
        }
        Rectangle {
            visible: stage.kind === "motion"
            readonly property real e: Math.min(1, stage.p * 1.6)
            x: stage.how === "slide" ? 40 + 260 * (1 - e) : 40 + 130 * e * 0; y: stage.how === "slide" ? 34 : 57 - 23 * e
            width: stage.how === "slide" ? 260 : 110 + 150 * e; height: stage.how === "slide" ? 110 : 18 + 92 * e; radius: 6
            color: "#F2F4F7"; opacity: stage.how === "slide" ? 1 : Math.min(1, e * 2)
        }
        Rectangle {   // the dock
            anchors { horizontalCenter: parent.horizontalCenter; bottom: parent.bottom; bottomMargin: 8 }
            width: dockRow.width + 14; height: 26; radius: 9; color: Qt.rgba(0.1, 0.11, 0.14, 0.7); border.width: 1; border.color: Qt.rgba(1, 1, 1, 0.12)
            Row { id: dockRow; anchors.centerIn: parent; spacing: 5
                Repeater { model: ["#3DD6B5", "#38B6FF", "#FF7A59", "#FF5470", "#F2C94C", "#6C63FF", "#FF5FA2"]
                    Rectangle { required property var modelData; required property int index; width: Settings.dockSize / 3; height: width; radius: 4; color: modelData
                        Rectangle { visible: index === 5 && stage.kind === "hide"; anchors.centerIn: parent; width: parent.width + 10 * stage.p; height: width; radius: width / 3; color: "transparent"
                            border.width: 1.5; border.color: Theme.t.glowA; opacity: stage.p > 0.8 ? (1 - stage.p) * 5 : 0 } } } }
        }
        Rectangle {
            anchors { right: parent.right; top: parent.top; margins: 10; topMargin: 24 }
            width: tag.width + 18; height: 22; radius: 8; color: Qt.rgba(0, 0, 0, 0.55)
            Label { id: tag; anchors.centerIn: parent; font.pixelSize: 11; font.weight: Font.DemiBold; color: "white"
                text: ({ hide: "Hiding a window · ", overview: "The Overview · ", motion: "Opening things · ", menu: "App menus · " })[stage.kind] + ({ drop: "Drop and ring", line: "Line", comet: "Comet", glide: "Glide apart", light: "Glide with light", grow: "Grow from the row", slide: "Slide", one: "One menu", row: "A row of menus" })[stage.how] }
        }
    }
    Label { text: "Point at a choice below and it plays up here."; secondary: true; font.pixelSize: 12; topPadding: -10 }

    // ---------------------------------------------------------------- the dock
    SetCard { title: "Dock"
        SetRow { title: "Size"
            SetChoice { each: 54; options: [["36", "S"], ["44", "M"], ["52", "L"], ["60", "XL"]]; value: String(Settings.dockSize); onPicked: function (v) { Settings.set("dockSize", v) } } }
        SetRow { title: "Hiding a window"; sub: "Click the app in front, or Super+↓. Point at one to see it above."
            SetChoice { each: 104; options: [["drop", "Drop and ring"], ["line", "Line"], ["comet", "Comet"]]; value: Settings.hideStyle
                onPicked: function (v) { Settings.set("hideStyle", v); pg.show("hide:" + v) }
                HoverHandler { onHoveredChanged: if (hovered) pg.show("hide:" + Settings.hideStyle) } } }
        SetRow { title: "Clicking the app in front hides it"; sub: "Click it again and it comes back."; Toggle { on: Settings.dockClickHides; onToggled: pg.sw("dockClickHides") } }
        SetRow { title: "Bars under open apps"; sub: "One bar for each window, up to three."; Toggle { on: Settings.dockDots; onToggled: pg.sw("dockDots") } }
        SetRow { title: "Make room for windows"; sub: "The dock slides away when a window needs the space."; Toggle { on: Settings.dockHide; onToggled: pg.sw("dockHide") } }
    }
    // ---------------------------------------------------------------- stacks
    SetCard { title: "Stacks"
        SetRow { title: "Downloads"; sub: "Open as"
            SetChoice { each: 70; options: [["list", "List"], ["grid", "Grid"]]; value: DeskPrefs.stacks.view || "list"; onPicked: function (v) { DeskPrefs.setStack("view", v) } } }
        SetRow { title: "Sort by"
            SetChoice { each: 92; options: [["date", "Date added"], ["name", "Name"], ["kind", "Kind"]]; value: DeskPrefs.stacks.sort || "date"; onPicked: function (v) { DeskPrefs.setStack("sort", v) } } }
        SetRow { title: "Clear out old downloads"; sub: "After 30 days they go to the Bin."; Toggle { on: DeskPrefs.stacks.clear30 === true; onToggled: function (v) { DeskPrefs.setStack("clear30", v ? "true" : "false") } } }
        SetRow { title: "Add a folder as a stack"; sub: "Drag any folder onto the end of the dock." }
    }
    // ---------------------------------------------------------------- the top bar
    SetCard { title: "Top bar"
        SetRow { title: "App menus"; sub: "What clicking the app's name opens."
            SetChoice { each: 120; options: [["one", "One menu"], ["row", "A row of menus"]]; value: Settings.menuStyle === "inline" ? "row" : Settings.menuStyle === "dropdown" ? "one" : Settings.menuStyle
                onPicked: function (v) { Settings.set("menuStyle", v); pg.show("menu:" + v) }
                HoverHandler { onHoveredChanged: if (hovered) pg.show("menu:" + (Settings.menuStyle === "row" || Settings.menuStyle === "inline" ? "row" : "one")) } } }
        SetRow { title: "24-hour clock"; Toggle { on: Settings.clock24; onToggled: pg.sw("clock24") } }
        SetRow { title: "Show the date"; Toggle { on: Settings.barDate; onToggled: pg.sw("barDate") } }
        SetRow { title: "Battery percentage"; Toggle { on: Settings.batteryPercent; onToggled: pg.sw("batteryPercent") } }
    }
    // ---------------------------------------------------------------- Today
    SetCard { title: "Today"
        SetRow { title: "What it shows"; sub: "Click the date, or Super+T." }
        Repeater {
            model: [["month", "The month"], ["weather", "Weather"], ["agenda", "What's coming"], ["clocks", "Clocks"]]
            SetRow { required property var modelData; title: modelData[1]
                Toggle { on: !DeskPrefs.today.islands || DeskPrefs.today.islands[modelData[0]] !== false; onToggled: function (v) { DeskPrefs.setIsland(modelData[0], v) } } }
        }
        SetRow { title: "Which clocks"; sub: (DeskPrefs.today.clocks || []).join(", ") || "None" }
        Flow {
            x: 16; width: parent.width - 32; spacing: 6; bottomPadding: 12
            Repeater {
                model: DeskPrefs.cities
                Rectangle {
                    required property var modelData
                    readonly property bool on: (DeskPrefs.today.clocks || []).indexOf(modelData) >= 0
                    width: cl.width + 20; height: 26; radius: 13; color: on ? Qt.rgba(Theme.t.accent.r, Theme.t.accent.g, Theme.t.accent.b, 0.2) : Theme.t.hover
                    border.width: on ? 1 : 0; border.color: Theme.t.accent
                    Label { id: cl; anchors.centerIn: parent; text: (parent.on ? "✓ " : "") + modelData; font.pixelSize: 12 }
                    MouseArea { anchors.fill: parent; onClicked: DeskPrefs.setClock(modelData, !parent.on) }
                }
            }
        }
    }
    // ---------------------------------------------------------------- windows
    SetCard { title: "Windows"
        SetRow { title: "Layouts from the fill button"; sub: "Hold the pointer on a window's fill button for halves, thirds and quarters."; Toggle { on: Settings.fillButtonLayouts; onToggled: pg.sw("fillButtonLayouts") } }
        SetRow { title: "Gaps between snapped windows"; Toggle { on: Settings.snapGaps; onToggled: pg.sw("snapGaps") } }
        SetRow { title: "Keep snapped windows together"; sub: "Bring them forward together, and see them as a pair in the Overview."; Toggle { on: Settings.keepSnapped; onToggled: pg.sw("keepSnapped") } }
        SetRow { title: "Windows open where they were"; sub: "Each app's window comes back at the size and place you left it."; Toggle { on: Settings.rememberPlaces; onToggled: pg.sw("rememberPlaces") } }
        SetRow { title: "Reopen apps when you sign in"; sub: "The apps you had open come back after signing out or restarting."; Toggle { on: Settings.reopenApps; onToggled: pg.sw("reopenApps") } }
        SetRow { title: "Adaptive sync for games and videos"; sub: "Smoother motion on screens that support FreeSync or G-Sync, while something fills the screen."
            SetChoice { each: 90; options: [["auto", "On"], ["off", "Off"]]; value: Settings.adaptiveSync; onPicked: function (v) { Settings.set("adaptiveSync", v) } } }
        SetRow { title: "Let games tear"; sub: "A game with V-Sync off shows each frame at once, for the lowest delay (where the graphics card can)."; Toggle { on: Settings.allowTearing; onToggled: pg.sw("allowTearing") } }
    }
    // ---------------------------------------------------------------- the Overview and spaces
    SetCard { title: "Overview & spaces"
        SetRow { title: "Opening"; sub: "Super+Tab, or three fingers up."
            SetChoice { each: 120; options: [["glide", "Glide apart"], ["light", "Glide with light"]]; value: Settings.overviewOpen
                onPicked: function (v) { Settings.set("overviewOpen", v); pg.show("overview:" + v) }
                HoverHandler { onHoveredChanged: if (hovered) pg.show("overview:" + Settings.overviewOpen) } } }
        SetRow { title: "Hot corner"; sub: "Push the pointer into the top-right corner for the Overview."; Toggle { on: Settings.hotCorner; onToggled: pg.sw("hotCorner") } }
        SetRow { title: "Spaces on every screen"; sub: "Switching space switches every screen together."; Toggle { on: Settings.spacesAllScreens; onToggled: pg.sw("spacesAllScreens") } }
    }
    // ---------------------------------------------------------------- motion
    SetCard { title: "Motion"
        SetRow { title: "Opening things in apps"; sub: "A message, a photo or a dialog opens out of what you clicked, or slides in from the side."
            SetChoice { each: 130; options: [["grow", "Grow from the row"], ["slide", "Slide"]]; value: Settings.inAppMotion
                onPicked: function (v) { Settings.set("inAppMotion", v); pg.show("motion:" + v) }
                HoverHandler { onHoveredChanged: if (hovered) pg.show("motion:" + Settings.inAppMotion) } } }
        SetRow { title: "Reduce Motion"; sub: "Moves become short fades. It lives in Accessibility, with the rest of seeing and moving."; chevron: true; onClicked: win.go("a11y") }
    }
}
