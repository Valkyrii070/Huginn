import QtQuick

// Settings, "tiles": every page has its own colour. It shows as a small tile in the rail, as a big tile in the page's
// header, and as the light in the window, which comes from the left where the rail is. Search finds any setting.
GlassWindow {
    id: win
    title: "Settings"; glow: "left"; width: 1180; height: 780; minimumWidth: 860
    property string page: keyOf(startPage) || "appearance"
    property string query: ""
    property var sheet: null                     // {kind: "pick" | "ask" | "confirm", title, ...}
    readonly property var pages: [
        { id: "appearance", label: "Appearance", glyph: "palette", a: "#9B8BFF", b: "#5A3FE0", group: "YOU", sub: "Light or dark, and the colour of everything." },
        { id: "desktop", label: "Desktop & Dock", glyph: "desktop", a: "#6AB4FF", b: "#2563EB", group: "YOU", sub: "The dock, the top bar, Today, windows, spaces and motion." },
        { id: "notifications", label: "Notifications", glyph: "bell", a: "#FF7A7A", b: "#D6336C", group: "YOU", sub: "Which apps may tell you things, and quiet hours." },
        { id: "a11y", label: "Accessibility", glyph: "eye", a: "#5EC8FF", b: "#1A73E8", group: "YOU", sub: "Seeing, hearing, typing and moving, made easier." },
        { id: "network", label: "Wi‑Fi & Network", glyph: "wifi", a: "#4DB0FF", b: "#1D63D1", group: "CONNECTIONS", sub: "Wireless and wired networks, VPN and hotspot." },
        { id: "bluetooth", label: "Bluetooth", glyph: "bluetooth", a: "#5B9BFF", b: "#2B4FD6", group: "CONNECTIONS", sub: "Headphones, keyboards, mice and speakers." },
        { id: "accounts", label: "Online Accounts", glyph: "cloud", a: "#40CFE0", b: "#1479A8", group: "CONNECTIONS", sub: "Sign in once for mail, calendars, contacts and files." },
        { id: "ai", label: "AI", glyph: "sparkle", a: "#A48BFF", b: "#6D3FE0", group: "CONNECTIONS", sub: "Huginn AI: a model on this computer, or your account with Claude, OpenAI, Gemini or Copilot's models." },
        { id: "displays", label: "Displays", glyph: "display", a: "#6D7BFF", b: "#3640C9", group: "THIS COMPUTER", sub: "Resolution, size, arrangement and night light." },
        { id: "sound", label: "Sound", glyph: "volume", a: "#FF6E97", b: "#C2185B", group: "THIS COMPUTER", sub: "Speakers, headphones, microphones and each app's volume." },
        { id: "power", label: "Battery & Power", glyph: "battery", a: "#4BDB97", b: "#109F5E", group: "THIS COMPUTER", sub: "Battery health, power mode and when to sleep." },
        { id: "input", label: "Keyboard & Mouse", glyph: "keyboard", a: "#A7B0BD", b: "#5A6474", group: "THIS COMPUTER", sub: "Layouts, typing, the touchpad and the mouse." },
        { id: "time", label: "Date & Time", glyph: "clock", a: "#FFAA55", b: "#E8590C", group: "SYSTEM", sub: "Time zone and how the clock is set." },
        { id: "language", label: "Language & Region", glyph: "globe", a: "#3DD1C3", b: "#118C7E", group: "SYSTEM", sub: "The language of the system and how dates and numbers look." },
        { id: "users", label: "Users", glyph: "user", a: "#B39BFF", b: "#6D28D9", group: "SYSTEM", sub: "Your account, and other people who use this computer." },
        { id: "defaults", label: "Default Apps", glyph: "apps", a: "#FFC060", b: "#D97706", group: "SYSTEM", sub: "Which app opens what, and what starts when you sign in." },
        { id: "privacy", label: "Privacy & Security", glyph: "shield", a: "#7D8CA3", b: "#334155", group: "SYSTEM", sub: "Firewall, app permissions, screen lock and history." },
        { id: "updates", label: "Software Update", glyph: "refresh", a: "#4C8DFF", b: "#1E40AF", group: "SYSTEM", sub: "Keep the system, your apps and Huginn up to date." },
        { id: "about", label: "About", glyph: "info", a: "#A3B1C4", b: "#475569", group: "SYSTEM", sub: "This computer and the version of Huginn OS." }
    ]
    readonly property var files: ({ appearance: "SetAppearance", desktop: "SetDesktop", notifications: "SetNotifications", network: "SetNetwork", bluetooth: "SetBluetooth",
                                    accounts: "SetAccounts", ai: "SetAI", displays: "SetDisplays", sound: "SetSound", power: "SetPower", input: "SetInput", time: "SetTime",
                                    language: "SetLanguage", users: "SetUsers", defaults: "SetDefaults", privacy: "SetPrivacy", updates: "SetUpdates", about: "SetAbout",
                                    a11y: "SetAccessibility" })
    readonly property var index: [
        ["a11y", "Screen reader", "orca blind read aloud speech voice spoken accessibility"], ["a11y", "Zoom", "magnifier magnify enlarge screen accessibility"],
        ["a11y", "Make everything bigger", "large text size font scale accessibility"], ["a11y", "High contrast", "contrast low vision accessibility"],
        ["a11y", "Solid surfaces", "transparency glass blur opaque accessibility"], ["a11y", "Colour filter", "color blind colour blindness protanopia deuteranopia tritanopia invert accessibility"],
        ["a11y", "Pointer size", "cursor mouse big large accessibility"], ["a11y", "Reduce motion", "animation still movement vestibular accessibility"],
        ["a11y", "On-screen keyboard", "virtual keyboard touch tablet accessibility"], ["a11y", "Sticky keys", "modifier one hand shortcut accessibility"],
        ["a11y", "Slow keys", "typing accidental accessibility"], ["a11y", "Bounce keys", "tremor repeat accessibility"],
        ["a11y", "Mouse keys", "number pad pointer keyboard accessibility"], ["a11y", "Flash the screen", "deaf hearing beep bell alert visual accessibility"],
        ["appearance", "Dark mode", "light theme night"], ["appearance", "Realm", "accent colour color wallpaper tint"],
        ["desktop", "App menus", "top bar menu one menu row"], ["desktop", "Clock", "24-hour time seconds top bar"], ["desktop", "Battery percentage", "top bar"],
        ["desktop", "Dock size", "dock bigger smaller icons"], ["desktop", "Hiding a window", "minimise minimize hide dock drop line comet"],
        ["desktop", "Stacks", "downloads folder dock stack"], ["desktop", "Today", "date calendar weather clocks world time agenda"],
        ["desktop", "Snapping windows", "snap layout halves thirds quarters tile fill button gaps"], ["desktop", "Overview", "spaces workspaces virtual desktops hot corner mission control"],
        ["desktop", "Opening things in apps", "motion animation grow slide"],
        ["notifications", "Do Not Disturb", "quiet silence focus hours"], ["notifications", "App notifications", "banners sounds alerts badges"], ["notifications", "Previews", "lock screen private"],
        ["network", "Wi‑Fi", "wireless internet join password network"], ["network", "Airplane mode", "flight offline radio"], ["network", "VPN", "wireguard openvpn private network"],
        ["network", "Hotspot", "share internet tether"], ["network", "IP address", "mac address dns gateway details"], ["network", "Ethernet", "wired cable lan"],
        ["bluetooth", "Bluetooth", "pair headphones keyboard mouse speaker devices"],
        ["accounts", "Online Accounts", "google microsoft icloud nextcloud sign in sync calendar contacts mail files"],
        ["ai", "Huginn AI", "artificial intelligence assistant chat llm model claude anthropic openai chatgpt gpt gemini google copilot github azure openrouter ollama llama local"],
        ["ai", "Model on this computer", "local offline private llama.cpp gemma gpt-oss download graphics card gpu"],
        ["ai", "API key", "claude openai gemini copilot github token key connect account"],
        ["displays", "Resolution", "screen size monitor pixels"], ["displays", "Scale", "bigger text size zoom hidpi"], ["displays", "Refresh rate", "hz smooth"],
        ["displays", "Night light", "blue light warm evening colour temperature"], ["displays", "Brightness", "dim screen"], ["displays", "Arrange screens", "multiple monitors position main primary rotate"],
        ["sound", "Output", "speakers headphones volume"], ["sound", "Input", "microphone mic recording"], ["sound", "App volume", "per app mixer"],
        ["power", "Battery", "charge health percentage cycles"], ["power", "Power mode", "performance balanced power saver"], ["power", "Sleep", "suspend idle screen off lid power button"],
        ["input", "Keyboard layout", "language typing input source"], ["input", "Key repeat", "delay rate typing"], ["input", "Caps Lock", "control escape compose"],
        ["input", "Touchpad", "tap to click natural scrolling trackpad"], ["input", "Mouse", "pointer speed left-handed"],
        ["time", "Time zone", "clock region city"], ["time", "Set time automatically", "ntp network time"],
        ["language", "Language", "translation"], ["language", "Formats", "date numbers currency region week"],
        ["users", "Your name", "account full name"], ["users", "Picture", "avatar photo"], ["users", "Password", "change password security"],
        ["users", "Other people", "add user account family admin administrator"],
        ["defaults", "Default apps", "browser mail open with file types"], ["defaults", "Start-up apps", "autostart login sign in"],
        ["privacy", "Firewall", "ufw block incoming"], ["privacy", "App permissions", "camera microphone location flatpak"], ["privacy", "Screen lock", "lock password idle"],
        ["privacy", "Recent files", "history forget"], ["privacy", "Empty the Trash", "days automatically"],
        ["updates", "Software Update", "upgrade security patches flatpak automatic huginn browser"],
        ["about", "About this computer", "model processor memory storage version graphics"]
    ]
    readonly property var results: {
        var q = query.trim().toLowerCase()
        if (q === "") return []
        var out = [], words = q.split(/\s+/)
        for (var i = 0; i < index.length; i++) {
            var p = info(index[i][0]), title = index[i][1].toLowerCase(), hay = (title + " " + index[i][2] + " " + p.label).toLowerCase(), ok = true, score = 0
            for (var w = 0; w < words.length; w++) {
                if (hay.indexOf(words[w]) < 0) { ok = false; break }
                score += title.indexOf(words[w]) >= 0 ? 3 : 1                    // a word in the setting's own name counts most
            }
            if (title === q) score += 10
            if (ok) out.push({ page: index[i][0], title: index[i][1], where: p.label, a: p.a, b: p.b, glyph: p.glyph, score: score })
        }
        return out.sort(function (a, b) { return b.score - a.score })
    }
    function info(id) { for (var i = 0; i < pages.length; i++) if (pages[i].id === id) return pages[i]; return pages[0] }
    function keyOf(name) {
        var n = String(name || "").toLowerCase()
        if (n === "bar" || n === "dock" || n === "top bar & dock") n = "desktop"   // older links
        for (var i = 0; i < pages.length; i++) if (pages[i].id === n || pages[i].label.toLowerCase() === n) return pages[i].id
        return ""
    }
    function go(id) { query = ""; search.text = ""; page = id }
    // sheets the pages use: a list to choose from, questions to answer, or a yes/no
    function pick(title, choices, current, done) { sheet = { kind: "pick", title: title, choices: choices, current: current, done: done }; pickFilter.text = "" }
    function ask(title, message, fields, button, done, danger) { sheet = { kind: "ask", title: title, message: message || "", fields: fields, button: button || "OK", done: done, danger: !!danger } }
    function confirm(title, message, button, done, danger) { sheet = { kind: "confirm", title: title, message: message || "", button: button, done: done, danger: danger !== false } }
    function say(msg, bad) { toast.say(msg, bad) }
    tintColor: info(page).a
    onPageChanged: refresh()
    Component.onCompleted: refresh()
    function refresh() {
        if (["network", "bluetooth", "displays", "sound", "notifications", "power", "input", "time", "language", "users", "defaults", "privacy", "about", "a11y"].indexOf(page) >= 0) Backend.load(page)
        if (page === "accounts" && typeof Accounts !== "undefined") Accounts.refresh()
        if (page === "ai" && typeof AI !== "undefined" && AI) AI.refresh()
        if (page === "updates" && typeof Updates !== "undefined") Updates.look(false)
    }
    Timer {   // pages that change by themselves are read again while they're open
        running: win.visible && ["network", "bluetooth", "sound", "power"].indexOf(win.page) >= 0 && win.sheet === null
        interval: win.page === "sound" ? 4000 : win.page === "power" ? 30000 : 12000; repeat: true
        onTriggered: Backend.load(win.page)
    }
    Connections { target: Backend; function onSaid(msg, bad) { toast.say(msg, bad) } }

    islands: [
        Island { anchors { right: parent.right; rightMargin: 12 } y: 12
            IslandField { id: search; placeholder: "Search settings"; width: 240; onTextChanged: win.query = text
                onAccepted: if (win.results.length) win.go(win.results[0].page) } },
        Rail {
            x: 12; y: 64; width: 236; maxHeight: win.height - 64 - 14
            Repeater { model: win.pages
                Column { required property var modelData; required property int index; width: parent.width
                    SideTitle { visible: index === 0 || win.pages[index - 1].group !== modelData.group; text: modelData.group; height: visible ? implicitHeight : 0 }
                    Pressable { width: parent.width; height: 34; radius: 11; active: false
                        color: win.page === modelData.id && win.query === "" ? Qt.alpha(Theme.t.accent, 0.18) : (hovered ? Theme.t.hover : "transparent")
                        onClicked: win.go(modelData.id)
                        Rectangle { x: 6; width: 22; height: 22; radius: 7; anchors.verticalCenter: parent.verticalCenter
                            gradient: Gradient { GradientStop { position: 0; color: modelData.a } GradientStop { position: 1; color: modelData.b } }
                            Glyph { anchors.centerIn: parent; name: modelData.glyph; size: 14; ink: "#FFFFFF" } }
                        Label { x: 38; anchors.verticalCenter: parent.verticalCenter; text: modelData.label; font.pixelSize: 13
                            font.weight: win.page === modelData.id && win.query === "" ? Font.DemiBold : Font.Normal }
                        Rectangle { visible: modelData.id === "updates" && typeof Updates !== "undefined" && Updates.count > 0; width: 20; height: 18; radius: 9; color: Theme.t.danger
                            anchors { right: parent.right; rightMargin: 8; verticalCenter: parent.verticalCenter }
                            Label { anchors.centerIn: parent; text: typeof Updates !== "undefined" ? Updates.count : ""; color: "#FFFFFF"; font.pixelSize: 10; font.weight: Font.DemiBold } } } } }
        },
        Toast { id: toast; anchors { horizontalCenter: parent.horizontalCenter; horizontalCenterOffset: 120; bottom: parent.bottom; bottomMargin: 22 } }
    ]

    Flickable { id: flick; x: 260; y: 58; width: parent.width - 260; height: parent.height - 60; contentHeight: body.height + 60; clip: true
        boundsBehavior: Flickable.StopAtBounds
        Column { id: body; x: 18; y: 8; width: Math.min(flick.width - 40, 780); spacing: 20
            // search results
            Column { visible: win.query !== ""; width: parent.width; spacing: 12
                Label { text: win.results.length ? "Settings that match" : "Nothing matches “" + win.query + "”"; font.pixelSize: 22; font.weight: Font.Light }
                SetCard { visible: win.results.length > 0
                    Repeater { model: win.results
                        SetRow { required property var modelData; title: modelData.title; sub: modelData.where; glyph: modelData.glyph; tile: modelData.a; chevron: true
                            onClicked: win.go(modelData.page) } } } }
            // the page: its big tile, its name, and what it's for
            Row { visible: win.query === ""; spacing: 16
                Rectangle { width: 54; height: 54; radius: 16
                    gradient: Gradient { GradientStop { position: 0; color: win.info(win.page).a } GradientStop { position: 1; color: win.info(win.page).b } }
                    Glyph { anchors.centerIn: parent; name: win.info(win.page).glyph; size: 30; ink: "#FFFFFF" } }
                Column { anchors.verticalCenter: parent.verticalCenter; spacing: 2
                    Label { text: win.info(win.page).label; font.pixelSize: 26; font.weight: Font.Light }
                    Label { text: win.info(win.page).sub; secondary: true } } }
            Loader { id: pageLoader; visible: win.query === ""; width: parent.width; source: win.files[win.page] + ".qml"
                onStatusChanged: if (status === Loader.Error) console.warn("Settings page failed:", source) }
        } }

    // ---------------------------------------------------------------- sheets
    Item { anchors.fill: parent; z: 40; visible: win.sheet !== null
        Rectangle { anchors.fill: parent; radius: win.r; color: "#77000000"; MouseArea { anchors.fill: parent; acceptedButtons: Qt.AllButtons; onClicked: win.sheet = null } }
        Rectangle { id: card; anchors.centerIn: parent; radius: 20; color: Theme.t.menu_bg; border.width: 1; border.color: Theme.t.menu_border
            readonly property string kind: win.sheet ? win.sheet.kind : ""
            width: kind === "pick" ? 480 : 460
            height: kind === "pick" ? Math.min(win.height - 90, 120 + Math.min(10, (win.sheet.choices || []).length) * 44 + (pickFilter.visible ? 46 : 0))
                  : kind === "ask" ? 150 + askCol.height + (askMsg.visible ? askMsg.height + 8 : 0) : 150 + confirmMsg.height
            MouseArea { anchors.fill: parent }
            Label { id: sheetTitle; x: 24; y: 20; width: parent.width - 48; text: win.sheet ? win.sheet.title : ""; font.pixelSize: 17; font.weight: Font.DemiBold; elide: Text.ElideRight }
            // a choice
            TextBox { id: pickFilter; visible: card.kind === "pick" && (win.sheet.choices || []).length > 10; x: 20; y: 54; width: parent.width - 40; placeholder: "Search"
                onAccepted: if (pickList.count) { var c = pickList.model[0]; var d = win.sheet.done; win.sheet = null; d(c.id) } }
            ListView { id: pickList; visible: card.kind === "pick"; x: 12; y: pickFilter.visible ? 100 : 56; width: parent.width - 24; height: parent.height - y - 64; clip: true
                boundsBehavior: Flickable.StopAtBounds
                model: card.kind === "pick" ? win.sheet.choices.filter(function (c) { var q = pickFilter.text.trim().toLowerCase(); return q === "" || (c.label + " " + (c.sub || "") + " " + c.id).toLowerCase().indexOf(q) >= 0 }) : []
                delegate: Pressable { required property var modelData; width: pickList.width; height: 44; radius: 10
                    color: hovered ? Theme.t.hover : "transparent"
                    onClicked: { var d = win.sheet.done, id = modelData.id; win.sheet = null; d(id) }
                    Image { id: pic; visible: !!modelData.icon; x: 10; width: 24; height: 24; source: modelData.icon || ""; sourceSize: Qt.size(48, 48); anchors.verticalCenter: parent.verticalCenter }
                    Column { x: pic.visible ? 44 : 14; width: parent.width - x - 40; anchors.verticalCenter: parent.verticalCenter
                        Label { width: parent.width; text: modelData.label; elide: Text.ElideRight; font.weight: win.sheet && String(win.sheet.current) === String(modelData.id) ? Font.DemiBold : Font.Normal }
                        Label { visible: !!modelData.sub; width: parent.width; text: modelData.sub || ""; secondary: true; font.pixelSize: 11; elide: Text.ElideRight } }
                    Glyph { visible: win.sheet && String(win.sheet.current) === String(modelData.id); anchors { right: parent.right; rightMargin: 12; verticalCenter: parent.verticalCenter } name: "check"; size: 16; ink: Theme.t.accent } } }
            // questions
            Label { id: askMsg; visible: card.kind !== "pick" && win.sheet !== null && win.sheet.message !== ""; x: 24; y: 50; width: parent.width - 48; wrapMode: Text.WordWrap; secondary: true
                text: win.sheet && win.sheet.message ? win.sheet.message : "" }
            Label { id: confirmMsg; visible: false; width: askMsg.width; wrapMode: Text.WordWrap; text: askMsg.text }
            Column { id: askCol; visible: card.kind === "ask"; x: 24; y: askMsg.visible ? askMsg.y + askMsg.height + 14 : 56; width: parent.width - 48; spacing: 10
                Repeater { id: askFields; model: card.kind === "ask" ? win.sheet.fields : []
                    Column { required property var modelData; required property int index; width: askCol.width; spacing: 4
                        property alias box: tb
                        property bool flag: !!modelData.on
                        Label { visible: !modelData.toggle; text: modelData.label; font.pixelSize: 11; secondary: true }
                        TextBox { id: tb; visible: !modelData.toggle; width: parent.width; secret: !!modelData.secret; text: modelData.text || ""; placeholder: modelData.placeholder || ""
                            Component.onCompleted: if (index === 0) focusIn()
                            onAccepted: askOk.clicked() }
                        Item { visible: !!modelData.toggle; width: parent.width; height: 30
                            Label { anchors.verticalCenter: parent.verticalCenter; text: modelData.label }
                            Toggle { anchors { right: parent.right; verticalCenter: parent.verticalCenter } on: parent.parent.flag; onToggled: function (v) { parent.parent.flag = v } } } } } }
            Row { anchors { right: parent.right; rightMargin: 20; bottom: parent.bottom; bottomMargin: 18 } spacing: 8
                Btn { text: card.kind === "pick" ? "Close" : "Cancel"; onClicked: win.sheet = null }
                Btn { id: askOk; visible: card.kind !== "pick"; primary: !(win.sheet && win.sheet.danger); danger: !!(win.sheet && win.sheet.danger); text: win.sheet && win.sheet.button ? win.sheet.button : "OK"
                    onClicked: {
                        var s = win.sheet
                        if (!s) return
                        if (s.kind === "ask") {
                            var values = {}
                            for (var i = 0; i < askFields.count; i++) { var f = s.fields[i], it = askFields.itemAt(i); values[f.key] = f.toggle ? it.flag : it.box.text }
                            win.sheet = null; s.done(values)
                        } else { win.sheet = null; s.done() }
                    } } }
        } }
}
