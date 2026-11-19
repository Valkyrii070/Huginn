import QtQuick

// Settings › AI: Huginn AI, off until it's turned on. Where it runs (a model on this computer, or an account with an AI
// service), which model, where it shows, and a box to try it.
Column {
    id: pg
    width: parent ? parent.width : 600; spacing: 18
    readonly property bool have: typeof AI !== "undefined" && AI !== null
    readonly property var st: have ? AI.state : ({})
    readonly property var provs: have ? AI.providers : []
    readonly property var locals: have ? AI.localModels : []
    readonly property var cur: provs.filter(function (p) { return p.id === pg.st.provider })[0] || null
    readonly property var dl: st.download || ({})
    readonly property bool fetching: !!dl.id && !dl.error && !dl.finished
    // the services' own letters on their own colours (not their logos)
    readonly property var looks: ({ local: ["", "#4BDB97", "#109F5E"], anthropic: ["C", "#E39A6F", "#B8582F"], openai: ["O", "#3BBF9A", "#0E7A5F"],
                                    gemini: ["G", "#7FA6FF", "#5A4FE0"], github: ["GH", "#8B95A7", "#3A4352"], azure: ["Az", "#4DA3FF", "#0A5FC2"],
                                    openrouter: ["OR", "#A08BFF", "#5B3FD6"], custom: ["", "#A7B0BD", "#5A6474"] })
    property int job: -1
    property string answer: ""
    property string trouble: ""
    Component.onCompleted: if (have) AI.refresh()
    Connections { target: pg.have ? AI : null
        function onSaid(msg, bad) { win.say(msg, bad) }
        function onChunk(id, text) { if (id === pg.job) pg.answer += text }
        function onDone(id, why) { if (id !== pg.job) return; pg.job = -1; pg.trouble = why } }

    function choose(p) {
        if (p.id === "local") { AI.setProvider("local"); return }
        if (p.connected) { AI.setProvider(p.id); return }
        connect(p)
    }
    function connect(p) {
        if (p.id === "azure" || p.id === "custom") {
            win.ask(p.id === "azure" ? "Connect Azure OpenAI" : "Connect another service",
                    p.id === "azure" ? "Your resource's address (from Azure AI Foundry, under Endpoints) and one of its keys. The model is the name you gave a deployment."
                                     : "The address of a service that speaks OpenAI's API. Ollama's is http://127.0.0.1:11434/v1. Leave the key empty if it doesn't need one.",
                    [{ key: "url", label: "Address", placeholder: p.id === "azure" ? "https://name.openai.azure.com" : "http://127.0.0.1:11434/v1" },
                     { key: "key", label: p.id === "azure" ? "Key" : "Key (if it needs one)", secret: true }],
                    "Connect", function (v) { AI.setAddress(p.id, v.url); if (v.key) AI.setKey(p.id, v.key); AI.setProvider(p.id) })
            return
        }
        win.ask("Connect " + p.label, p.about + " Paste the key here: it's kept in Passwords if that's set up, else in a file only you can read.",
                [{ key: "key", label: p.id === "github" ? "GitHub token" : "API key", secret: true }], "Connect",
                function (v) { if (v.key) { AI.setKey(p.id, v.key); AI.setProvider(p.id) } })
    }
    function pickModel(p) {
        var rows = (p.models || []).map(function (m, i) { return { id: m.id, label: m.name !== m.id ? m.name : m.id, sub: m.name !== m.id ? m.id : (i === 0 ? "Suggested" : "") } })
        if (p.typed || rows.length === 0) rows.push({ id: "?", label: "Type a name…", sub: p.id === "azure" ? "Your deployment's name" : "" })
        win.pick("Model", rows, p.model, function (v) {
            if (v !== "?") { AI.setModel(p.id, v); return }
            win.ask(p.id === "azure" ? "Deployment" : "Model", "", [{ key: "m", label: p.id === "azure" ? "Deployment name" : "Model name" }], "Use It",
                    function (w) { if (w.m) AI.setModel(p.id, w.m.trim()) })
        })
    }
    function size(n) { return n >= 1e9 ? (n / 1e9).toFixed(1) + " GB" : Math.round(n / 1e6) + " MB" }

    SetCard { visible: !pg.have
        SetRow { title: "Huginn AI isn't available here"; glyph: "sparkle" } }

    SetCard { visible: pg.have
        note: "Nothing is sent anywhere until it's on and you've chosen where it runs. Then only what you ask about goes, when you ask."
        SetRow { title: "Huginn AI"; glyph: "sparkle"; tile: "#7C5CFF"
            sub: "Ask questions in Search. Rewrite, summarise and draft in Writer and Mail. Explain, fix and write code in Code."
            Toggle { on: !!pg.st.enabled; onToggled: function (v) { AI.setEnabled(v) } } } }

    // ------------------------------------------------------------------ where it runs
    SetCard { visible: pg.have && !!pg.st.enabled; title: "Where it runs"
        note: "A chat subscription (ChatGPT Plus, Claude Pro, Gemini Advanced, Copilot Pro) doesn't let other apps use it: each service sells that separately, as an API key from its developer console. Gemini's and GitHub's have free tiers."
        Flow { width: parent.width; padding: 12; spacing: 10
            Repeater { model: pg.have ? [{ id: "local", label: "On this computer", maker: "Private: nothing leaves it", connected: true }].concat(pg.provs) : []
                Pressable { id: tile; required property var modelData
                    readonly property bool chosen: pg.st.provider === modelData.id
                    width: Math.floor((pg.width - 24 - 20) / 3) - 1; height: 70; radius: 14
                    color: chosen ? Qt.alpha(Theme.t.accent, 0.16) : hovered ? Theme.t.hover : (Theme.t.dark ? "#10FFFFFF" : "#08141E28")
                    border.width: chosen ? 2 : 0; border.color: Theme.t.accent
                    onClicked: pg.choose(modelData)
                    Rectangle { x: 12; width: 40; height: 40; radius: 12; anchors.verticalCenter: parent.verticalCenter
                        gradient: Gradient { GradientStop { position: 0; color: pg.looks[tile.modelData.id][1] } GradientStop { position: 1; color: pg.looks[tile.modelData.id][2] } }
                        Label { visible: pg.looks[tile.modelData.id][0] !== ""; anchors.centerIn: parent; text: pg.looks[tile.modelData.id][0]; color: "#FFFFFF"; font.pixelSize: 16; font.weight: Font.Bold }
                        Glyph { visible: pg.looks[tile.modelData.id][0] === ""; anchors.centerIn: parent; name: tile.modelData.id === "local" ? "laptop" : "server"; size: 20; ink: "#FFFFFF" } }
                    Column { x: 62; anchors.verticalCenter: parent.verticalCenter; width: parent.width - 74; spacing: 2
                        Label { width: parent.width; text: tile.modelData.label; font.weight: Font.DemiBold; elide: Text.ElideRight }
                        Label { width: parent.width; secondary: true; font.pixelSize: 11; elide: Text.ElideRight
                            text: tile.modelData.id === "local" ? tile.modelData.maker : tile.modelData.locked ? "Unlock Passwords to use it" : tile.modelData.connected ? "Connected" : tile.modelData.maker } }
                    Glyph { visible: tile.chosen; anchors { right: parent.right; rightMargin: 10; top: parent.top; topMargin: 8 } name: "check"; size: 14; ink: Theme.t.accent } } } } }

    // ------------------------------------------------------------------ on this computer
    SetCard { visible: pg.have && !!pg.st.enabled && pg.st.provider === "local"; title: "Model on this computer"
        note: (pg.st.engine ? "" : "llama.cpp, which runs the model, is installed with the first one. ") + "Models come from Hugging Face. While one is running it uses the graphics card's memory; it stops by itself after a quarter of an hour unused."
        Repeater { model: pg.locals
            SetRow { id: lrow; required property var modelData
                readonly property bool getting: pg.fetching && pg.dl.id === modelData.id
                title: modelData.label + " · " + modelData.name; glyph: modelData.current && modelData.here ? "check" : "cpu"
                tile: modelData.current && modelData.here ? Theme.t.accent : "#5A6474"
                sub: getting ? (pg.dl.step ? pg.dl.step : pg.dl.total ? "Downloading… " + pg.size(pg.dl.done) + " of " + pg.size(pg.dl.total) : "Starting the download…")
                     : (pg.dl.id === modelData.id && pg.dl.error) ? pg.dl.error
                     : (modelData.suggested ? "Suggested for this computer. " : "") + modelData.maker + " · " + modelData.size + ". " + modelData.fits
                Row { spacing: 8
                    Rectangle { visible: lrow.getting && pg.dl.total > 0; width: 120; height: 4; radius: 2; anchors.verticalCenter: parent.verticalCenter
                        color: Theme.t.dark ? "#22FFFFFF" : "#18141E28"
                        Rectangle { width: parent.width * Math.min(1, pg.dl.done / Math.max(1, pg.dl.total)); height: parent.height; radius: 2; color: Theme.t.accent } }
                    Btn { visible: lrow.getting; text: "Stop"; onClicked: AI.stopDownload() }
                    Btn { visible: !lrow.getting && !modelData.here; text: "Download"; primary: modelData.suggested && !pg.fetching; enabled: !pg.fetching; onClicked: AI.fetch(lrow.modelData.id) }
                    Btn { visible: modelData.here && !modelData.current; text: "Use"; onClicked: AI.setLocal(lrow.modelData.id) }
                    Label { visible: modelData.here && modelData.current; text: "In use"; secondary: true; anchors.verticalCenter: parent.verticalCenter }
                    Seg { visible: modelData.here; icon: "trash"; tip: "Remove"
                        onClicked: { var m = lrow.modelData; win.confirm("Remove " + m.name + "?", "It frees " + m.size + ". You can download it again any time.", "Remove", function () { AI.remove(m.id) }) } } } } }
        SetRow { title: "Use the graphics card"; sub: "Much faster. Turn it off to keep the card free for a game."; glyph: "display"
            Toggle { on: pg.st.local ? pg.st.local.gpu !== false : true; onToggled: function (v) { AI.setGpu(v) } } } }

    // ------------------------------------------------------------------ an account with a service
    SetCard { visible: pg.have && !!pg.st.enabled && pg.cur !== null; title: pg.cur ? pg.cur.label : ""
        note: pg.cur ? pg.cur.about : ""
        SetRow { visible: pg.cur !== null && pg.cur.locked; title: "Passwords is locked"; sub: "The key is kept there. Unlocking Passwords in any Huginn app lets AI use it."; glyph: "lock"; tile: "#1479A8"
            Btn { text: "Check Again"; onClicked: AI.refresh() } }
        SetRow { visible: pg.cur !== null && (pg.cur.id === "azure" || pg.cur.id === "custom"); title: "Address"; glyph: "globe"
            sub: pg.cur && pg.cur.address ? pg.cur.address : "Not set"
            Btn { text: "Change…"; onClicked: { var p = pg.cur; win.ask("Address", "", [{ key: "url", label: "Address", placeholder: p.address }], "Save", function (v) { if (v.url) AI.setAddress(p.id, v.url) }) } } }
        SetRow { visible: pg.cur !== null && (pg.cur.needsKey || pg.cur.id === "custom"); title: pg.cur && pg.cur.id === "github" ? "Token" : "Key"; glyph: "key"
            sub: !pg.cur ? "" : pg.cur.keyEnds ? "Ends " + pg.cur.keyEnds + " · kept in " + pg.cur.where : pg.cur.locked ? "Kept in Passwords" : pg.cur.needsKey ? "Not added yet" : "None"
            Row { spacing: 8
                Btn { visible: pg.cur !== null && pg.cur.signin; text: "Sign In…"; primary: !(pg.cur && pg.cur.connected); onClicked: AI.signIn() }
                Btn { visible: pg.cur !== null && pg.cur.keysAt !== ""; text: "Get a Key"; onClicked: AI.keysPage(pg.cur.id) }
                Btn { text: pg.cur && (pg.cur.keyEnds || pg.cur.locked) ? "Change…" : "Add…"; primary: !!pg.cur && !pg.cur.connected && !pg.cur.signin; onClicked: pg.connect(pg.cur) }
                Seg { visible: !!pg.cur && (pg.cur.keyEnds !== "" || pg.cur.locked); icon: "trash"; tip: "Forget the key"
                    onClicked: { var p = pg.cur; win.confirm("Forget the " + p.label + " key?", "Huginn AI can't use " + p.label + " until a key is added again. The key itself still works elsewhere until you revoke it in " + p.label + "'s console.", "Forget", function () { AI.setKey(p.id, "") }) } } } }
        SetRow { visible: pg.cur !== null && pg.cur.connected; title: "Model"; glyph: "sparkle"
            sub: pg.cur && pg.cur.loading ? "Looking at what the account offers…" : ""
            Row { spacing: 8
                Seg { icon: "refresh"; tip: "Look again"; onClicked: AI.loadModels(pg.cur.id) }
                SetPick { text: pg.cur && pg.cur.model ? pg.cur.model : "Choose…"; onClicked: pg.pickModel(pg.cur) } } } }

    // ------------------------------------------------------------------ where it shows
    SetCard { visible: pg.have && !!pg.st.enabled; title: "Where it shows"
        Repeater { model: [["search", "Search", "search", "Ask a question from Search everything: type it, then Ctrl+Enter."],
                           ["writer", "Writer", "doc", "Rewrite, proofread, summarise or carry on what you've written."],
                           ["mail", "Mail", "mail", "Summarise a message, draft a reply, improve what you've written."],
                           ["code", "Code", "code", "Explain, fix or write code, from the command palette or the editor's menu."]]
            SetRow { required property var modelData; title: modelData[1]; glyph: modelData[2]; sub: modelData[3]
                Toggle { on: !pg.st.where || pg.st.where[modelData[0]] !== false; onToggled: function (v) { AI.setWhere(modelData[0], v) } } } } }

    // ------------------------------------------------------------------ try it
    SetCard { visible: pg.have && !!pg.st.enabled && pg.st.provider !== ""; title: "Try it"
        Item { width: parent.width; height: tryCol.height + 24
            Column { id: tryCol; x: 16; y: 12; width: parent.width - 32; spacing: 10
                Row { spacing: 8; width: parent.width
                    TextBox { id: tryBox; width: parent.width - goBtn.width - 8; placeholder: "Ask " + (pg.st.model || pg.st.label || "it") + " something"
                        onAccepted: goBtn.clicked() }
                    Btn { id: goBtn; text: pg.job >= 0 ? "Stop" : "Ask"; primary: pg.job < 0; anchors.verticalCenter: parent.verticalCenter
                        onClicked: {
                            if (pg.job >= 0) { AI.stop(pg.job); pg.job = -1; return }
                            if (tryBox.text.trim() === "") return
                            pg.answer = ""; pg.trouble = ""
                            pg.job = AI.ask("ask", tryBox.text, {})
                        } } }
                Label { visible: pg.job >= 0 && pg.answer === ""; text: pg.st.provider === "local" ? "Starting the model (the first answer takes a little longer)…" : "Thinking…"; secondary: true }
                Label { visible: pg.answer !== ""; width: parent.width; text: pg.answer; wrapMode: Text.WordWrap; textFormat: Text.PlainText }
                Label { visible: pg.trouble !== ""; width: parent.width; text: pg.trouble; wrapMode: Text.WordWrap; color: Theme.t.danger } } } }
}
