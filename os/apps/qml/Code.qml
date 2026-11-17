import QtQuick

// Code, "the workbench": the project down the left in one tall island (files, search, Git, problems), the open
// files as tabs floating across the top, and the code itself on a dark, quiet slab that takes up the rest. The
// terminal slides up under the slab; the status runs along the bottom edge. Everything has a key, and the palette
// (Ctrl+P, or Ctrl+Shift+P for every command) reaches all of it.
GlassWindow {
    id: win
    title: "Code"; heading: Backend.rootName; width: 1280; height: 820; minimumWidth: 900; minimumHeight: 560; glow: "left"
    visible: true
    property string panel: "files"
    property bool side: true
    property bool term: false
    property string bottom: "terminal"                     // what the bottom panel shows: terminal or debug
    property bool split: false                             // two editors side by side
    property bool blameOn: false                           // who changed each line, beside the code
    property string gitView: "changes"                     // changes | history
    property var historyRows: []
    property int otherTab: -1                              // the tab in the pane that hasn't got the keyboard
    property int pane: 0                                   // which side has the keyboard: 0 left, 1 right
    property int lastCurrent: -1
    readonly property var dbg: Backend.debug ? Backend.debug : idleDbg
    QtObject { id: idleDbg                                   // stands in while the window closes
        signal changed()
        property string state: "idle"; property bool active: false; property string reason: ""; property string adapter: ""
        property var frames: []; property int frame: -1; property var variables: []; property var output: []
        property string whereFile: ""; property int whereLine: -1
        function resume() {} function pause() {} function stepOver() {} function stepIn() {} function stepOut() {} function restart() {} function stop() {}
        function selectFrame(f) {} function expand(r) {} function evaluate(x) {} function clearConsole() {} }
    property var sheet: null
    property bool palOpen: false
    property bool finding: false
    property bool replacing: false
    property var comp: []
    property var compAll: []
    property int compAt: 0
    property string compPrefix: ""
    property string tip: ""
    property var sig: null                         // the call being typed: {label, a, b, doc}
    property var fixMenu: null                     // quick fixes for the cursor's line: {items, k}
    property bool mdPreview: false                 // Markdown shown as it reads, beside its text
    property var outlineRows: []
    property var matches: []
    property int matchAt: -1
    property int curLine: 1
    property int curCol: 1
    property var menuFor: null
    property string browseAt: Backend.home
    readonly property int sideW: side ? 280 : 0
    readonly property string mono: Qt.fontFamilies().indexOf(Theme.t.fontMono) >= 0 ? Theme.t.fontMono : Qt.fontFamilies().indexOf("DejaVu Sans Mono") >= 0 ? "DejaVu Sans Mono" : "monospace"
    readonly property var tab: Backend.current >= 0 && Backend.current < Backend.tabs.length ? Backend.tabs[Backend.current] : null
    readonly property color slab: Theme.t.dark ? "#111318" : "#FCFCFE"
    readonly property color gutterInk: Theme.t.dark ? "#5A6170" : "#A3A9B4"
    readonly property color lineGlow: Theme.t.dark ? "#1A1D24" : "#F1F2F8"
    readonly property color addInk: "#3FB950"
    readonly property color modInk: "#4D8DFF"
    readonly property color delInk: "#F85149"
    readonly property string unit: Backend.status.indentText || "    "
    function colours() {
        return { key: Theme.t.dark ? "#C792EA" : "#7C3AED", comment: Theme.t.dark ? "#6B7385" : "#8A909C", string: Theme.t.dark ? "#A5D6A7" : "#2E7D32",
                 number: Theme.t.dark ? "#F78C6C" : "#C2410C", type: Theme.t.dark ? "#7FDBCA" : "#0F766E", func: Theme.t.dark ? "#82AAFF" : "#1D4ED8",
                 deco: Theme.t.dark ? "#FF8FA3" : "#BE185D", head: Theme.t.accent }
    }
    function view() { return docs.itemAt(Backend.current) }
    function ask(kind, extra) { var s = extra || {}; s.kind = kind; sheet = s }
    function closeTab(i) { if (Backend.close(i, false) === "dirty") ask("dirty", { tab: i, name: Backend.tabs[i].name }) }
    function save() { if (Backend.current < 0) return; if (Backend.save(Backend.current, false) === "changed") ask("clash", { tab: Backend.current }) }
    function openPalette(prefix) { palBox.text = prefix; palList.model = paletteRows(prefix); palOpen = true; palBox.forceActiveFocus(); palBox.cursorPosition = prefix.length; palList.currentIndex = 0 }
    function closeOverlays() { palOpen = false; comp = []; tip = ""; sig = null; fixMenu = null; menuFor = null; var v = view(); if (v) v.focusEditor() }
    function refreshOutline() { outlineRows = Backend.current >= 0 ? Backend.outline(Backend.current) : [] }
    function showPanel(p) { side = true; panel = p; if (p === "outline") refreshOutline(); if (p === "search") Qt.callLater(function () { searchBox.forceActiveFocus() }); if (p === "tests" && Backend.tests.length === 0 && Backend.testBusy === "") Backend.discoverTests() }
    function syncDocs() {
        var tabs = Backend.tabs, i, j, k
        for (i = docModel.count - 1; i >= 0; i--) {
            var p = docModel.get(i).path, keep = false
            for (j = 0; j < tabs.length; j++) if (tabs[j].path === p) keep = true
            if (!keep) docModel.remove(i)
        }
        for (j = 0; j < tabs.length; j++) {
            var at = -1
            for (k = j; k < docModel.count; k++) if (docModel.get(k).path === tabs[j].path) { at = k; break }
            if (at < 0) docModel.insert(j, { path: tabs[j].path })
            else if (at !== j) docModel.move(at, j, 1)
        }
    }
    readonly property var commands: [
        { name: "Save", key: "Ctrl+S", run: function () { win.save() } },
        { name: "Save All", key: "Ctrl+Alt+S", run: function () { toast.say(Backend.saveAll() + " saved", false) } },
        { name: "Close Tab", key: "Ctrl+W", run: function () { if (Backend.current >= 0) win.closeTab(Backend.current) } },
        { name: "Quick Open a File", key: "Ctrl+P", run: function () { win.openPalette("") } },
        { name: "Go to Line…", key: "Ctrl+G", run: function () { win.openPalette(":") } },
        { name: "Go to Symbol…", key: "Ctrl+Shift+O", run: function () { win.openPalette("@") } },
        { name: "Go to Definition", key: "F12", run: function () { var v = win.view(); if (v) v.definition() } },
        { name: "Show Information Here", key: "Ctrl+I", run: function () { var v = win.view(); if (v) v.hover() } },
        { name: "Suggest", key: "Ctrl+Space", run: function () { var v = win.view(); if (v) v.suggest() } },
        { name: "Find", key: "Ctrl+F", run: function () { win.startFind(false) } },
        { name: "Replace", key: "Ctrl+H", run: function () { win.startFind(true) } },
        { name: "Search the Project", key: "Ctrl+Shift+F", run: function () { win.showPanel("search") } },
        { name: "Show Files", key: "Ctrl+Shift+E", run: function () { win.showPanel("files") } },
        { name: "Show Changes (Git)", key: "Ctrl+Shift+G", run: function () { win.showPanel("git") } },
        { name: "Show Problems", key: "Ctrl+Shift+M", run: function () { win.showPanel("problems") } },
        { name: "Show Tests", key: "Ctrl+Shift+T", run: function () { win.showPanel("tests") } },
        { name: "Run All Tests", key: "", run: function () { win.showPanel("tests"); Backend.runTests([]) } },
        { name: "Git: Blame (Who Changed Each Line)", key: "Ctrl+Alt+B", run: function () { win.blameOn = !win.blameOn } },
        { name: "Git: History", key: "", run: function () { win.showPanel("git"); win.gitView = "history"; win.historyRows = Backend.history("") } },
        { name: "Git: This File's History", key: "", run: function () { var v = win.view(); if (v) { win.showPanel("git"); win.gitView = "history"; win.historyRows = Backend.history(Backend.relOf ? Backend.relOf(Backend.current) : "") } } },
        { name: "Toggle the Side Panel", key: "Ctrl+B", run: function () { win.side = !win.side } },
        { name: "Toggle the Terminal", key: "Ctrl+`", run: function () { win.toggleTerm() } },
        { name: "Start Debugging / Continue", key: "F5", run: function () { win.debugIt() } },
        { name: "Run Without Debugging", key: "Ctrl+F5", run: function () { win.runIt() } },
        { name: "Stop Debugging", key: "Shift+F5", run: function () { win.dbg.stop() } },
        { name: "Step Over", key: "F10", run: function () { win.dbg.stepOver() } },
        { name: "Step Into", key: "F11", run: function () { win.dbg.stepIn() } },
        { name: "Step Out", key: "Shift+F11", run: function () { win.dbg.stepOut() } },
        { name: "Toggle Breakpoint", key: "F9", run: function () { var v = win.view(); if (v) { var lc = v.lineCol(); Backend.toggleBreakpoint(Backend.current, lc[0]) } } },
        { name: "Rename Symbol…", key: "F2", run: function () { var v = win.view(); if (v) v.renameHere() } },
        { name: "Find All References", key: "Shift+F12", run: function () { var v = win.view(); if (v) v.referencesHere() } },
        { name: "Split the Editor", key: "Ctrl+\\", run: function () { win.toggleSplit() } },
        { name: "Toggle the Minimap", key: "", run: function () { Backend.setMinimap(!Backend.minimap) } },
        { name: "Show the Debug Console", key: "", run: function () { win.bottom = "debug"; win.term = true } },
        { name: "Set the Run Command…", key: "", run: function () { win.ask("run", { now: Backend.runCommand() }) } },
        { name: "Format Document", key: "Ctrl+Shift+I", run: function () { if (Backend.current >= 0) Backend.format(Backend.current) } },
        { name: "Quick Fix…", key: "Ctrl+.", run: function () { var v = win.view(); if (v) v.fixHere() } },
        { name: "Add the Next Match to the Selection (another cursor)", key: "Ctrl+D", run: function () { var v = win.view(); if (v) v.addNext() } },
        { name: "Select Every Match (a cursor on each)", key: "Ctrl+Shift+L", run: function () { var v = win.view(); if (v) v.selectEvery() } },
        { name: "Add a Cursor Below", key: "Ctrl+Alt+Down", run: function () { var v = win.view(); if (v) v.addVertical(1) } },
        { name: "Add a Cursor Above", key: "Ctrl+Alt+Up", run: function () { var v = win.view(); if (v) v.addVertical(-1) } },
        { name: "Markdown: Show How It Reads", key: "Ctrl+Shift+V", run: function () { win.mdPreview = !win.mdPreview } },
        { name: "Show the Outline", key: "", run: function () { win.showPanel("outline") } },
        { name: (Backend.options.formatOnSave ? "Stop Formatting When Saving" : "Format When Saving"), key: "", run: function () { Backend.setOption("formatOnSave", !Backend.options.formatOnSave) } },
        { name: (Backend.options.trimOnSave ? "Stop Tidying Line Ends When Saving" : "Tidy Line Ends When Saving"), key: "", run: function () { Backend.setOption("trimOnSave", !Backend.options.trimOnSave) } },
        { name: "Merge: Keep Ours Everywhere in This File", key: "", run: function () { if (Backend.current >= 0) Backend.resolveConflict(Backend.current, -1, "ours") } },
        { name: "Merge: Keep Theirs Everywhere in This File", key: "", run: function () { if (Backend.current >= 0) Backend.resolveConflict(Backend.current, -1, "theirs") } },
        { name: "Comment or Uncomment Lines", key: "Ctrl+/", run: function () { var v = win.view(); if (v) v.toggleComment() } },
        { name: "Toggle Word Wrap", key: "Alt+Z", run: function () { Backend.setWrap(!Backend.wrap) } },
        { name: "Bigger Text", key: "Ctrl+=", run: function () { Backend.setSize(Backend.size + 1) } },
        { name: "Smaller Text", key: "Ctrl+-", run: function () { Backend.setSize(Backend.size - 1) } },
        { name: "New File", key: "Ctrl+N", run: function () { win.ask("new", { folder: Backend.root, dir: false }) } },
        { name: "New Folder", key: "", run: function () { win.ask("new", { folder: Backend.root, dir: true }) } },
        { name: "Open Folder…", key: "Ctrl+O", run: function () { win.browseAt = Backend.root || Backend.home; win.ask("open") } },
        { name: "Close Folder", key: "", run: function () { Backend.closeFolder() } },
        { name: "Reload This File from Disk", key: "", run: function () { if (Backend.current >= 0) Backend.reload(Backend.current) } },
        { name: "Show This File in Files", key: "", run: function () { if (win.tab) Backend.reveal(win.tab.path) } },
        { name: "Git: Commit…", key: "", run: function () { win.showPanel("git"); commitBox.focusIn() } },
        { name: "Git: Stage Everything", key: "", run: function () { Backend.stageAll() } },
        { name: "Git: Pull", key: "", run: function () { Backend.sync("pull") } },
        { name: "Git: Push", key: "", run: function () { Backend.sync("push") } },
        { name: "Git: Pull, Then Push", key: "", run: function () { Backend.sync("sync") } },
        { name: "Git: Make This Folder a Repository", key: "", run: function () { Backend.initRepo() } }
    ]
    function toggleTerm() { term = !term; if (term) Qt.callLater(function () { termKeys.forceActiveFocus() }); else { var v = view(); if (v) v.focusEditor() } }
    function runIt() { bottom = "terminal"; term = true; Backend.run(""); Qt.callLater(function () { termKeys.forceActiveFocus() }) }
    function debugIt() { if (dbg.active) { dbg.resume(); return } bottom = "debug"; term = true; Backend.startDebug("") }
    function toggleSplit() {
        if (split) { split = false; return }
        if (Backend.tabs.length < 2) { toast.say("Open another file to see two side by side.", false); return }
        otherTab = lastCurrent >= 0 && lastCurrent !== Backend.current && lastCurrent < Backend.tabs.length ? lastCurrent : (Backend.current + 1) % Backend.tabs.length
        pane = 0; split = true }
    Connections { target: Backend
        function onChanged() {
            if (Backend.current !== win.lastCurrent) {
                if (win.split && Backend.current === win.otherTab) win.otherTab = win.lastCurrent          // picked the other pane's tab: they swap
                win.lastCurrent = Backend.current }
            if (win.split && (win.otherTab < 0 || win.otherTab >= Backend.tabs.length || win.otherTab === Backend.current)) win.split = false }
        function onAskProgram(guess) { win.ask("debugprog", { now: guess }) } }
    function startFind(rep) {
        finding = true; replacing = rep
        var v = view()
        if (v && v.selected() && v.selected().indexOf("\n") < 0) findBox.text = v.selected()
        findBox.forceActiveFocus(); findBox.selectAll(); refind()
    }
    function pattern() {
        var q = findBox.text
        if (!q) return null
        try {
            var src = matchRe.on ? q : q.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")
            if (matchWord.on) src = "\\b" + src + "\\b"
            return new RegExp(src, matchCase.on ? "g" : "gi")
        } catch (e) { return null }
    }
    function refind() {
        var v = view(), re = pattern(), out = []
        if (!v || !re) { matches = []; matchAt = -1; return }
        var text = v.allText(), m
        while ((m = re.exec(text)) !== null && out.length < 5000) { if (m[0].length === 0) { re.lastIndex++; continue } out.push([m.index, m.index + m[0].length]) }
        matches = out
        var from = v.cursor(), best = 0
        for (var i = 0; i < out.length; i++) if (out[i][0] >= from - (out[i][1] - out[i][0])) { best = i; break }
        matchAt = out.length ? best : -1
        if (matchAt >= 0) v.selectRange(out[matchAt][0], out[matchAt][1])
    }
    function step(d) { if (!matches.length) return; matchAt = (matchAt + d + matches.length) % matches.length; view().selectRange(matches[matchAt][0], matches[matchAt][1]) }
    function replaceOne() {
        var v = view(); if (!v || matchAt < 0) return
        var m = matches[matchAt]; v.replaceRange(m[0], m[1], replaceBox.text); refind()
    }
    function replaceEvery() {
        var v = view(); if (!v || !matches.length) return
        var n = matches.length
        for (var i = matches.length - 1; i >= 0; i--) v.replaceRange(matches[i][0], matches[i][1], replaceBox.text)
        refind(); toast.say("Replaced " + n, false)
    }
    function paletteRows(text) {
        var out = [], q = text.toLowerCase(), i
        if (text.charAt(0) === ">") {
            q = q.substring(1).trim()
            for (i = 0; i < commands.length; i++) if (commands[i].name.toLowerCase().indexOf(q) >= 0) out.push({ label: commands[i].name, detail: commands[i].key, act: "cmd", n: i })
            return out
        }
        if (text.charAt(0) === ":") {
            var n = parseInt(text.substring(1))
            return [{ label: isNaN(n) ? "Type a line number" : "Go to line " + n, detail: win.view() ? win.view().lines() + " lines" : "", act: "line", n: isNaN(n) ? -1 : n }]
        }
        if (text.charAt(0) === "@") {
            q = q.substring(1).trim()
            var syms = Backend.symbols(Backend.current)
            for (i = 0; i < syms.length; i++) if (!q || syms[i].name.toLowerCase().indexOf(q) >= 0) out.push({ label: syms[i].name, detail: syms[i].kind + " · line " + (syms[i].line + 1), act: "sym", n: syms[i].line, depth: syms[i].depth })
            return out
        }
        var files = Backend.quickOpen(text)
        for (i = 0; i < files.length; i++) out.push({ label: files[i].name, detail: files[i].where, act: "file", rel: files[i].rel })
        return out
    }
    function choose(row) {
        palOpen = false
        if (!row) return
        if (row.act === "cmd") commands[row.n].run()
        else if (row.act === "file") Backend.openRel(row.rel, -1, 0)
        else if (row.act === "line" && row.n > 0) { var v = view(); if (v) v.goTo(row.n - 1, 0) }
        else if (row.act === "sym") { var w = view(); if (w) w.goTo(row.n, 0) }
        if (row.act !== "cmd") Qt.callLater(function () { var x = win.view(); if (x) x.focusEditor() })
    }
    function searchRows(results) {
        var out = [], last = ""
        for (var i = 0; i < results.length; i++) {
            var r = results[i]
            if (r.path !== last) { out.push({ header: true, path: r.path, count: 0 }); last = r.path }
            out.push({ header: false, path: r.path, line: r.line, col: r.col, length: r.length, text: r.text })
        }
        for (var j = 0, h = -1; j < out.length; j++) { if (out[j].header) h = j; else out[h].count++ }
        return out
    }
    function gitInk(kind) { return kind === "new" || kind === "added" ? addInk : kind === "deleted" ? delInk : kind === "conflict" ? "#E3B341" : kind === "inside" ? Theme.t.text_secondary : modInk }
    function gitLetter(kind) { return ({ "new": "U", "added": "A", "deleted": "D", "renamed": "R", "conflict": "!", "changed": "M", "inside": "•" })[kind] || "" }
    function langInk(lang) {
        return ({ "Python": "#4B8BBE", "JavaScript": "#E8C547", "TypeScript": "#3178C6", "C": "#8C9EFF", "C++": "#F06292", "Rust": "#DEA584", "Go": "#00ADD8", "QML": "#41CD52",
                  "Shell": "#89E051", "JSON": "#CBA34A", "Markdown": "#8E9AAF", "HTML": "#E44D26", "CSS": "#2965F1", "YAML": "#CB171E", "TOML": "#9C4221", "Java": "#B07219", "C#": "#178600", "Lua": "#000080" })[lang] || Theme.t.text_secondary
    }

    ListModel { id: docModel }
    Connections {
        target: Backend
        function onChanged() { win.syncDocs() }
        function onSaid(msg, wrong) { toast.say(msg, wrong) }
        function onTextLoaded(i) { var v = docs.itemAt(i); if (v) v.reload() }
        function onJump(i, line, col) { Backend.select(i); Qt.callLater(function () { var v = docs.itemAt(i); if (v) v.goTo(line, col) }) }
        function onCompletions(i, items) { var v = docs.itemAt(i); if (i === Backend.current && v) v.offer(items) }
        function onHoverText(i, text) { if (i === Backend.current) win.tip = text }
        function onSignature(i, label, a, b, doc) { if (i === Backend.current) win.sig = label ? { label: label, a: a, b: b, doc: doc } : null }
        function onFixesFound(i, items) { if (i !== Backend.current) return; if (items.length) win.fixMenu = { items: items, k: 0 }; else toast.say("Nothing to fix on this line", false) }
        function onShown() { win.show(); win.raise(); win.requestActivate() }
    }
    Component.onCompleted: syncDocs()

    Shortcut { sequence: "Ctrl+S"; onActivated: win.save() }
    Shortcut { sequence: "Ctrl+Alt+S"; onActivated: toast.say(Backend.saveAll() + " saved", false) }
    Shortcut { sequence: "Ctrl+W"; onActivated: if (Backend.current >= 0) win.closeTab(Backend.current) }
    Shortcut { sequence: "Ctrl+P"; onActivated: win.openPalette("") }
    Shortcut { sequence: "Ctrl+Shift+P"; onActivated: win.openPalette(">") }
    Shortcut { sequence: "Ctrl+G"; onActivated: win.openPalette(":") }
    Shortcut { sequence: "Ctrl+Shift+O"; onActivated: win.openPalette("@") }
    Shortcut { sequence: "Ctrl+F"; onActivated: win.startFind(false) }
    Shortcut { sequence: "Ctrl+H"; onActivated: win.startFind(true) }
    Shortcut { sequence: "Ctrl+Shift+F"; onActivated: win.showPanel("search") }
    Shortcut { sequence: "Ctrl+Shift+E"; onActivated: win.showPanel("files") }
    Shortcut { sequence: "Ctrl+Shift+G"; onActivated: win.showPanel("git") }
    Shortcut { sequence: "Ctrl+Shift+M"; onActivated: win.showPanel("problems") }
    Shortcut { sequence: "Ctrl+Shift+T"; onActivated: win.showPanel("tests") }
    Shortcut { sequence: "Ctrl+Alt+B"; onActivated: win.blameOn = !win.blameOn }
    function showCommit(sha, title) { if (!sha) return; var info = Backend.commitInfo(sha); win.ask("diff", { rel: "", staged: false, commit: info, rows: Backend.commitRows(sha, "") }) }
    Shortcut { sequence: "Ctrl+B"; onActivated: win.side = !win.side }
    Shortcut { sequence: "Ctrl+`"; onActivated: win.toggleTerm() }
    Shortcut { sequence: "F5"; onActivated: win.debugIt() }
    Shortcut { sequence: "Ctrl+F5"; onActivated: win.runIt() }
    Shortcut { sequence: "Shift+F5"; onActivated: win.dbg.stop() }
    Shortcut { sequence: "F6"; onActivated: win.dbg.pause() }
    Shortcut { sequence: "F10"; onActivated: win.dbg.stepOver() }
    Shortcut { sequence: "F11"; onActivated: win.dbg.stepIn() }
    Shortcut { sequence: "Shift+F11"; onActivated: win.dbg.stepOut() }
    Shortcut { sequence: "Ctrl+\\"; onActivated: win.toggleSplit() }
    Shortcut { sequence: "Ctrl+N"; onActivated: win.ask("new", { folder: Backend.root, dir: false }) }
    Shortcut { sequence: "Ctrl+O"; onActivated: { win.browseAt = Backend.root || Backend.home; win.ask("open") } }
    Shortcut { sequence: "Ctrl+Shift+I"; onActivated: if (Backend.current >= 0) Backend.format(Backend.current) }
    Shortcut { sequence: "Ctrl+Shift+V"; onActivated: win.mdPreview = !win.mdPreview }
    Shortcut { sequence: "Alt+Z"; onActivated: Backend.setWrap(!Backend.wrap) }
    Shortcut { sequences: ["Ctrl+=", "Ctrl++"]; onActivated: Backend.setSize(Backend.size + 1) }
    Shortcut { sequence: "Ctrl+-"; onActivated: Backend.setSize(Backend.size - 1) }
    Shortcut { sequence: "Ctrl+Tab"; onActivated: if (Backend.tabs.length) Backend.select((Backend.current + 1) % Backend.tabs.length) }
    Shortcut { sequence: "Ctrl+Shift+Tab"; onActivated: if (Backend.tabs.length) Backend.select((Backend.current - 1 + Backend.tabs.length) % Backend.tabs.length) }
    Shortcut { sequence: "Escape"; enabled: win.palOpen || win.finding || win.tip !== "" || win.comp.length > 0 || win.menuFor !== null || win.sheet !== null || win.sig !== null || win.fixMenu !== null
        onActivated: { if (win.sheet) win.sheet = null; else if (win.palOpen || win.tip || win.comp.length || win.menuFor || win.sig || win.fixMenu) win.closeOverlays(); else { win.finding = false; var v = win.view(); if (v) v.focusEditor() } } }

    islands: [
        // the open files, floating across the top
        Item { id: tabsBar; objectName: "tabsBar"; x: win.sideW + 24; y: 12; height: 40; width: win.width - x - toolBox.width - 26; visible: Backend.tabs.length > 0
            ListView { id: tabList; anchors.fill: parent; orientation: ListView.Horizontal; spacing: 6; clip: true; model: Backend.tabs; boundsBehavior: Flickable.StopAtBounds
                currentIndex: Backend.current
                onCurrentIndexChanged: positionViewAtIndex(currentIndex, ListView.Contain)
                delegate: Pressable { id: tabPill; required property var modelData; required property int index; readonly property bool on: index === Backend.current
                    width: Math.min(230, tabRow.width + 26); height: 36; y: 2; radius: 18
                    color: on ? win.slab : hovered ? Theme.t.hover : Theme.t.island; border.width: 1; border.color: on ? Theme.t.accent : Theme.t.islandLine
                    onClicked: Backend.select(index)
                    Row { id: tabRow; x: 12; anchors.verticalCenter: parent.verticalCenter; spacing: 7
                        Rectangle { width: 8; height: 8; radius: 4; anchors.verticalCenter: parent.verticalCenter; color: win.langInk(tabPill.modelData.lang) }
                        Label { text: tabPill.modelData.name; font.pixelSize: 12; font.weight: tabPill.on ? Font.DemiBold : Font.Normal; width: Math.min(implicitWidth, 150); elide: Text.ElideMiddle
                            color: tabPill.modelData.errors > 0 ? win.delInk : Theme.t.text }
                        Item { width: 16; height: 16; anchors.verticalCenter: parent.verticalCenter
                            Rectangle { visible: tabPill.modelData.dirty && !closeX.hovered; anchors.centerIn: parent; width: 8; height: 8; radius: 4; color: Theme.t.text }
                            Pressable { id: closeX; anchors.fill: parent; radius: 8; color: hovered ? Theme.t.hover : "transparent"; visible: !tabPill.modelData.dirty || hovered || tabPill.hovered
                                onClicked: win.closeTab(tabPill.index)
                                Glyph { anchors.centerIn: parent; name: "x"; size: 10; visible: !tabPill.modelData.dirty || closeX.hovered } } } } } } },
        Island { id: toolBox; anchors { right: parent.right; rightMargin: 12 } y: 12
            Seg { icon: "search"; tip: "Go to a file or command (Ctrl+P)"; onClicked: win.openPalette("") }
            Seg { icon: "play"; text: "Run"; tip: "Run (Ctrl+F5): " + (Backend.runCommand() || "nothing yet"); onClicked: win.runIt() }
            Seg { icon: "bug"; text: win.dbg.active ? "Debugging" : "Debug"; on: win.dbg.active; tip: "Debug (F5)"; onClicked: win.debugIt() }
            Seg { icon: "split"; tip: "Two editors side by side (Ctrl+\\)"; on: win.split; onClicked: win.toggleSplit() }
            Seg { icon: "apps"; tip: "Terminal (Ctrl+`)"; on: win.term; onClicked: win.toggleTerm() } },
        Toast { id: toast; anchors { horizontalCenter: parent.horizontalCenter; bottom: parent.bottom; bottomMargin: 56 } },

        // the palette: files, commands (>), lines (:) and symbols (@)
        Item { anchors.fill: parent; z: 30; visible: win.palOpen
            MouseArea { anchors.fill: parent; onClicked: win.closeOverlays() }
            Rectangle { objectName: "palette"; x: (parent.width - width) / 2; y: 58; width: Math.min(640, parent.width - 80); height: 66 + Math.min(10, palList.count) * 40; radius: 16
                color: Theme.t.menu_bg; border.width: 1; border.color: Theme.t.menu_border
                MouseArea { anchors.fill: parent }
                TextInput { id: palBox; objectName: "palBox"; x: 18; y: 18; width: parent.width - 36; font.pixelSize: 16; color: Theme.t.text; clip: true; selectByMouse: true
                    onTextChanged: { palList.model = win.paletteRows(text); palList.currentIndex = 0 }
                    Keys.onPressed: function (e) {
                        if (e.key === Qt.Key_Down) { palList.currentIndex = Math.min(palList.count - 1, palList.currentIndex + 1); e.accepted = true }
                        else if (e.key === Qt.Key_Up) { palList.currentIndex = Math.max(0, palList.currentIndex - 1); e.accepted = true }
                        else if (e.key === Qt.Key_Return || e.key === Qt.Key_Enter) { win.choose(palList.model[palList.currentIndex]); e.accepted = true }
                        else if (e.key === Qt.Key_Escape) { win.closeOverlays(); e.accepted = true } }
                    Text { visible: !palBox.text; text: "Type a file's name · > for commands · : for a line · @ for a symbol"; font: palBox.font; color: Theme.t.text_secondary } }
                ListView { id: palList; x: 8; y: 54; width: parent.width - 16; height: parent.height - 62; clip: true; boundsBehavior: Flickable.StopAtBounds; highlightMoveDuration: 0
                    delegate: Pressable { required property var modelData; required property int index; width: palList.width; height: 40; radius: 10
                        color: index === palList.currentIndex ? Qt.alpha(Theme.t.accent, 0.22) : hovered ? Theme.t.hover : "transparent"
                        onClicked: win.choose(modelData)
                        Label { x: 12 + (modelData.depth || 0) * 12; width: parent.width * 0.6; elide: Text.ElideRight; anchors.verticalCenter: parent.verticalCenter; text: modelData.label; font.weight: Font.DemiBold }
                        Label { anchors { right: parent.right; rightMargin: 12; verticalCenter: parent.verticalCenter } width: Math.min(implicitWidth, parent.width * 0.38); elide: Text.ElideLeft
                            text: modelData.detail || ""; secondary: true; font.pixelSize: 11; font.family: modelData.act === "cmd" ? win.mono : Theme.t.font } } } } },

        // a right-click menu in the files list
        Item { anchors.fill: parent; z: 28; visible: win.menuFor !== null
            MouseArea { anchors.fill: parent; acceptedButtons: Qt.AllButtons; onClicked: win.menuFor = null }
            Rectangle { x: win.menuFor ? Math.min(win.menuFor.x, win.width - width - 8) : 0; y: win.menuFor ? Math.min(win.menuFor.y, win.height - height - 8) : 0; width: 210; height: menuCol.height + 12; radius: 12
                color: Theme.t.menu_bg; border.width: 1; border.color: Theme.t.menu_border
                Column { id: menuCol; x: 6; y: 6; width: parent.width - 12
                    Repeater { model: win.menuFor ? (win.menuFor.dir ? ["New File Here", "New Folder Here", "Rename…", "Show in Files", "Move to Trash"] : ["Open", "Rename…", "Show in Files", "Move to Trash"]) : []
                        Pressable { required property string modelData; width: menuCol.width; height: 32; radius: 8; color: hovered ? Theme.t.hover : "transparent"
                            onClicked: { var f = win.menuFor; win.menuFor = null
                                if (modelData === "Open") Backend.openFile(f.path)
                                else if (modelData === "New File Here") win.ask("new", { folder: f.path, dir: false })
                                else if (modelData === "New Folder Here") win.ask("new", { folder: f.path, dir: true })
                                else if (modelData === "Rename…") win.ask("rename", { path: f.path, name: f.name })
                                else if (modelData === "Show in Files") Backend.reveal(f.path)
                                else win.ask("trash", { path: f.path, name: f.name }) }
                            Label { x: 10; anchors.verticalCenter: parent.verticalCenter; text: modelData; font.pixelSize: 12; color: modelData === "Move to Trash" ? Theme.t.danger : Theme.t.text } } } } } },

        // sheets: open a folder, unsaved changes, a clash on disk, names, the Run command, a diff
        Item { anchors.fill: parent; z: 32; visible: win.sheet !== null
            Rectangle { anchors.fill: parent; radius: win.r; color: "#77000000"; MouseArea { anchors.fill: parent; acceptedButtons: Qt.AllButtons; onClicked: if (win.sheet && win.sheet.kind !== "dirty") win.sheet = null } }
            Rectangle { id: card; anchors.centerIn: parent; radius: 18; color: Theme.t.menu_bg; border.width: 1; border.color: Theme.t.menu_border
                readonly property string kind: win.sheet ? win.sheet.kind : ""
                width: kind === "diff" ? win.width - 120 : kind === "open" ? 560 : 470
                height: kind === "diff" ? win.height - 100 : kind === "open" ? Math.min(win.height - 80, 520) : kind === "dirty" || kind === "clash" || kind === "trash" || kind === "discard" ? 170 : 200
                MouseArea { anchors.fill: parent }
                Label { x: 24; y: 20; width: parent.width - 48; elide: Text.ElideMiddle; font.pixelSize: 17; font.weight: Font.DemiBold
                    text: ({ "open": "Open a folder", "dirty": "Save changes to “" + (win.sheet ? win.sheet.name : "") + "”?", "clash": "This file changed on disk",
                             "new": win.sheet && win.sheet.dir ? "New folder" : "New file", "rename": "Rename “" + (win.sheet ? win.sheet.name : "") + "”",
                             "trash": "Move “" + (win.sheet ? win.sheet.name : "") + "” to the Trash?", "renamesym": "Rename “" + (win.sheet ? win.sheet.name : "") + "” everywhere", "debugprog": "Which program should be debugged?", "run": "What Run does", "discard": "Throw away the changes to “" + (win.sheet ? win.sheet.rel : "") + "”?",
                             "diff": (win.sheet ? win.sheet.rel : "") + (win.sheet && win.sheet.staged ? "  ·  staged" : "") })[card.kind] || "" }
                Label { visible: ["dirty", "clash", "trash", "discard"].indexOf(card.kind) >= 0; x: 24; y: 52; width: parent.width - 48; wrapMode: Text.WordWrap; secondary: true
                    text: card.kind === "dirty" ? "If you don't save, your changes are lost." : card.kind === "clash" ? "Something else changed it since you opened it. Keep yours (overwrite) or take what's on disk?"
                        : card.kind === "trash" ? "You can put it back from the Trash in Files." : "This can't be undone: the file goes back to how it was at the last commit." }
                TextBox { id: nameBox; objectName: "nameBox"; visible: ["new", "rename", "run", "renamesym", "debugprog"].indexOf(card.kind) >= 0; x: 24; y: 58; width: parent.width - 48; mono: card.kind === "run" || card.kind === "renamesym" || card.kind === "debugprog"
                    placeholder: card.kind === "run" ? "for example: python3 -m aurora" : card.kind === "renamesym" ? "new name" : card.kind === "debugprog" ? "build/myprogram" : card.kind === "new" ? (win.sheet && win.sheet.dir ? "folder name" : "name.py, or folder/name.py") : ""
                    onAccepted: sheetOk.clicked() }
                Label { visible: card.kind === "run" || card.kind === "debugprog" || card.kind === "renamesym"; x: 24; y: 100; width: parent.width - 48; wrapMode: Text.WordWrap; secondary: true; font.pixelSize: 11
                    text: card.kind === "run" ? "Kept in the project as .huginn-run, so it travels with it." : card.kind === "debugprog" ? "The program you built, with debugging information (gcc -g, cargo build). Kept in the project as .huginn-debug."
                        : "Every place it's used changes, in every file (the language helper finds them). Open files change but aren't saved." }
                // the folder picker
                Item { visible: card.kind === "open"; x: 16; y: 54; width: parent.width - 32; height: parent.height - 120
                    Row { id: crumbs; x: 8; spacing: 6; height: 30
                        Seg { icon: "up"; tip: "Up a folder"; onClicked: { var p = win.browseAt.replace(/\/[^\/]+\/?$/, ""); win.browseAt = p || "/" } }
                        Label { anchors.verticalCenter: parent.verticalCenter; text: win.browseAt.replace(Backend.home, "~"); width: card.width - 120; elide: Text.ElideLeft; font.family: win.mono; font.pixelSize: 12 } }
                    ListView { id: folders; y: 36; width: parent.width; height: parent.height - 36; clip: true; boundsBehavior: Flickable.StopAtBounds
                        model: card.kind === "open" ? (Backend.recent.length && win.browseAt === Backend.home ? Backend.recent.map(function (r) { return { name: r.name, path: r.path, git: false, recent: r.where } }).concat(Backend.browse(win.browseAt)) : Backend.browse(win.browseAt)) : []
                        delegate: Pressable { required property var modelData; width: folders.width; height: 38; radius: 9; color: hovered ? Theme.t.hover : "transparent"
                            onClicked: win.browseAt = modelData.path
                            onDoubleClicked: { win.sheet = null; Backend.openFolder(modelData.path) }
                            Glyph { x: 10; anchors.verticalCenter: parent.verticalCenter; name: modelData.recent ? "history" : "folder"; size: 15; ink: modelData.recent ? Theme.t.accent : Theme.t.icon }
                            Label { x: 36; width: parent.width - 180; elide: Text.ElideRight; anchors.verticalCenter: parent.verticalCenter; text: modelData.name }
                            Label { anchors { right: parent.right; rightMargin: 10; verticalCenter: parent.verticalCenter } font.pixelSize: 11; secondary: true
                                text: modelData.recent ? "recent · " + modelData.recent : modelData.git ? "Git" : "" } } } }
                // a diff
                ListView { id: diffList; visible: card.kind === "diff"; x: 12; y: 56; width: parent.width - 24; height: parent.height - 120; clip: true; boundsBehavior: Flickable.StopAtBounds
                    model: card.kind === "diff" ? win.sheet.rows : []
                    header: Column { visible: !!(win.sheet && win.sheet.commit && win.sheet.commit.sha); width: diffList.width; spacing: 2; bottomPadding: visible ? 10 : 0
                        height: visible ? implicitHeight : 0
                        Label { width: parent.width; wrapMode: Text.WordWrap; text: win.sheet && win.sheet.commit ? win.sheet.commit.message || "" : ""; font.pixelSize: 13; font.weight: Font.DemiBold }
                        Label { text: win.sheet && win.sheet.commit ? (win.sheet.commit.sha || "").substring(0, 10) + "  ·  " + win.sheet.commit.author + "  ·  " + win.sheet.commit.when + "  ·  " + (win.sheet.commit.files || []).length + " files" : ""
                            font.pixelSize: 11; secondary: true; font.family: win.mono } }
                    delegate: Rectangle { required property var modelData; width: diffList.width; height: modelData.kind === "hunk" ? 30 : modelData.kind === "file" ? 32 : 20
                        color: modelData.kind === "add" ? Qt.rgba(0.25, 0.73, 0.31, 0.16) : modelData.kind === "del" ? Qt.rgba(0.97, 0.32, 0.29, 0.16) : modelData.kind === "hunk" ? Theme.t.hover : modelData.kind === "file" ? Qt.alpha(Theme.t.accent, 0.14) : "transparent"
                        Text { x: 6; width: 34; horizontalAlignment: Text.AlignRight; anchors.verticalCenter: parent.verticalCenter; text: modelData.old; color: win.gutterInk; font.family: win.mono; font.pixelSize: 11 }
                        Text { x: 44; width: 34; horizontalAlignment: Text.AlignRight; anchors.verticalCenter: parent.verticalCenter; text: modelData.new; color: win.gutterInk; font.family: win.mono; font.pixelSize: 11 }
                        Text { x: modelData.kind === "file" ? 10 : 86; anchors.verticalCenter: parent.verticalCenter; text: (modelData.kind === "add" ? "+ " : modelData.kind === "del" ? "− " : modelData.kind === "hunk" || modelData.kind === "file" ? "" : "  ") + modelData.text
                            color: modelData.kind === "hunk" ? Theme.t.text_secondary : Theme.t.text; font.family: win.mono; font.pixelSize: 12; font.weight: modelData.kind === "file" ? Font.Bold : Font.Normal; textFormat: Text.PlainText } } }
                Label { visible: card.kind === "diff" && diffList.count === 0; anchors.centerIn: parent; secondary: true; text: "No differences" }
                Row { anchors { right: parent.right; rightMargin: 20; bottom: parent.bottom; bottomMargin: 18 } spacing: 8
                    Btn { visible: card.kind === "dirty"; text: "Don't Save"; onClicked: { var t = win.sheet.tab; win.sheet = null; Backend.close(t, true) } }
                    Btn { text: card.kind === "diff" ? "Done" : "Cancel"; onClicked: win.sheet = null }
                    Btn { visible: card.kind === "diff" && !win.sheet.staged && !!win.sheet.canStage; text: "Stage"; onClicked: { Backend.stage(win.sheet.rel); win.sheet = null } }
                    Btn { visible: card.kind === "clash"; text: "Take Theirs"; onClicked: { var t = win.sheet.tab; win.sheet = null; Backend.reload(t) } }
                    Btn { id: sheetOk; visible: card.kind !== "diff"; primary: card.kind !== "trash" && card.kind !== "discard"; danger: card.kind === "trash" || card.kind === "discard"
                        text: ({ "open": "Open This Folder", "dirty": "Save", "clash": "Keep Mine", "new": "Make", "rename": "Rename", "trash": "Move to Trash", "run": "Use It", "discard": "Throw Away", "renamesym": "Rename", "debugprog": "Debug" })[card.kind] || "OK"
                        onClicked: {
                            var s = win.sheet, why = ""
                            if (s.kind === "open") { win.sheet = null; Backend.openFolder(win.browseAt); return }
                            if (s.kind === "dirty") { if (Backend.save(s.tab, false) === "") { win.sheet = null; Backend.close(s.tab, true) } return }
                            if (s.kind === "clash") { win.sheet = null; Backend.save(s.tab, true); return }
                            if (s.kind === "new") why = Backend.create(s.folder, nameBox.text, s.dir)
                            else if (s.kind === "rename") why = Backend.rename(s.path, nameBox.text)
                            else if (s.kind === "trash") why = Backend.remove(s.path)
                            else if (s.kind === "discard") why = Backend.discard(s.rel)
                            else if (s.kind === "run") { Backend.setRun(nameBox.text); win.sheet = null; return }
                            else if (s.kind === "renamesym") { win.sheet = null; Backend.renameSymbol(s.tab, s.line, s.col, nameBox.text); return }
                            else if (s.kind === "debugprog") { win.sheet = null; win.bottom = "debug"; win.term = true; Backend.startDebug(nameBox.text); return }
                            if (why) toast.say(why, true); else win.sheet = null } } } } }
    ]
    onSheetChanged: if (sheet && ["new", "rename", "run", "renamesym", "debugprog"].indexOf(sheet.kind) >= 0) {
        nameBox.text = sheet.kind === "rename" || sheet.kind === "renamesym" ? sheet.name : sheet.kind === "run" || sheet.kind === "debugprog" ? (sheet.now || "") : ""; nameBox.focusIn(); nameBox.input.selectAll() }

    // ================================================================ the side island
    Rectangle { id: sideBox; visible: win.side; x: 12; y: 64; width: win.sideW; height: parent.height - y - 12; radius: 18; color: Theme.t.island; border.width: 1; border.color: Theme.t.islandLine; clip: true
        Row { id: panes; x: 10; y: 10; spacing: 4
            Repeater { model: [["files", "folder", "Files (Ctrl+Shift+E)"], ["search", "search", "Search (Ctrl+Shift+F)"], ["git", "route", "Changes (Ctrl+Shift+G)"], ["problems", "info", "Problems (Ctrl+Shift+M)"], ["tests", "check", "Tests (Ctrl+Shift+T)"], ["outline", "list", "Outline"]]
                Seg { required property var modelData; icon: modelData[1]; tip: modelData[2]; on: win.panel === modelData[0]; onClicked: win.showPanel(modelData[0])
                    Rectangle { visible: (modelData[0] === "git" && Backend.changes.length > 0) || (modelData[0] === "problems" && Backend.problems.length > 0)
                                         || (modelData[0] === "tests" && Backend.tests.some(function (t) { return t.status === "failed" }))
                        anchors { right: parent.right; top: parent.top } width: 8; height: 8; radius: 4; color: modelData[0] === "git" ? win.modInk : win.delInk } } } }

        // ---- files
        Item { visible: win.panel === "files"; x: 0; y: 52; width: parent.width; height: parent.height - 52
            Row { x: 14; width: parent.width - 28; height: 28; spacing: 4
                Label { width: parent.width - 96; elide: Text.ElideRight; anchors.verticalCenter: parent.verticalCenter; text: (Backend.rootName || "No folder").toUpperCase(); font.pixelSize: 11; font.weight: Font.Bold; font.letterSpacing: 1; secondary: true }
                Seg { visible: !!Backend.root; icon: "plus"; tip: "New file"; onClicked: win.ask("new", { folder: Backend.root, dir: false }) }
                Seg { visible: !!Backend.root; icon: "folder"; tip: "New folder"; onClicked: win.ask("new", { folder: Backend.root, dir: true }) } }
            ListView { id: explorer; objectName: "explorer"; y: 32; width: parent.width; height: parent.height - 32; clip: true; model: Backend.tree; boundsBehavior: Flickable.StopAtBounds; reuseItems: true
                delegate: Pressable { id: row; required property var modelData; width: explorer.width - 12; x: 6; height: 26; radius: 7
                    readonly property bool on: !!win.tab && win.tab.path === modelData.path
                    color: on ? Qt.alpha(Theme.t.accent, 0.2) : hovered ? Theme.t.hover : "transparent"
                    onClicked: modelData.dir ? Backend.toggle(modelData.path) : Backend.openFile(modelData.path)
                    MouseArea { anchors.fill: parent; acceptedButtons: Qt.RightButton
                        onClicked: function (m) { var p = row.mapToItem(win.contentItem, m.x, m.y); win.menuFor = { path: row.modelData.path, name: row.modelData.name, dir: row.modelData.dir, x: p.x, y: p.y } } }
                    Text { x: 8 + row.modelData.depth * 14; width: 12; anchors.verticalCenter: parent.verticalCenter; text: row.modelData.dir ? (row.modelData.open ? "▾" : "▸") : ""; color: Theme.t.text_secondary; font.pixelSize: 11 }
                    Rectangle { visible: !row.modelData.dir; x: 11 + row.modelData.depth * 14; anchors.verticalCenter: parent.verticalCenter; width: 7; height: 7; radius: 2; color: win.langInk(row.modelData.lang) }
                    Label { x: 24 + row.modelData.depth * 14; width: parent.width - x - 24; elide: Text.ElideRight; anchors.verticalCenter: parent.verticalCenter; text: row.modelData.name; font.pixelSize: 12
                        opacity: row.modelData.dim ? 0.55 : 1; color: row.modelData.git && row.modelData.git !== "inside" ? win.gitInk(row.modelData.git) : Theme.t.text }
                    Label { anchors { right: parent.right; rightMargin: 8; verticalCenter: parent.verticalCenter } text: win.gitLetter(row.modelData.git); font.pixelSize: 11; font.weight: Font.Bold; color: win.gitInk(row.modelData.git) } }
                Column { visible: !Backend.root; anchors.centerIn: parent; spacing: 10; width: parent.width - 40
                    Label { width: parent.width; wrapMode: Text.WordWrap; horizontalAlignment: Text.AlignHCenter; secondary: true; text: "Open a folder to see its files here." }
                    Btn { anchors.horizontalCenter: parent.horizontalCenter; primary: true; text: "Open Folder…"; onClicked: { win.browseAt = Backend.home; win.ask("open") } } } } }

        // ---- search
        Item { visible: win.panel === "search"; x: 12; y: 52; width: parent.width - 24; height: parent.height - 52
            Column { id: sCol; width: parent.width; spacing: 8
                TextBox { id: searchBox; objectName: "searchBox"; width: parent.width; placeholder: "Search the project"; onAccepted: win.runSearch(); onEdited: searchTimer.restart() }
                Row { spacing: 4
                    Seg { id: sCase; text: "Aa"; tip: "Match case"; property bool on2: false; on: on2; onClicked: { on2 = !on2; win.runSearch() } }
                    Seg { id: sWord; text: "W"; tip: "Whole words"; property bool on2: false; on: on2; onClicked: { on2 = !on2; win.runSearch() } }
                    Seg { id: sRe; text: ".*"; tip: "Pattern (regular expression)"; property bool on2: false; on: on2; onClicked: { on2 = !on2; win.runSearch() } } }
                TextBox { id: sReplace; width: parent.width; placeholder: "Replace with (optional)" }
                Row { spacing: 8
                    Label { anchors.verticalCenter: parent.verticalCenter; font.pixelSize: 11; secondary: true
                        text: Backend.resultsTitle !== "" ? Backend.resultsTitle : Backend.searching ? "Searching…" : Backend.results.length === 1 ? "1 match" : Backend.results.length ? Backend.results.length + (Backend.results.length >= 2000 ? "+" : "") + " matches" : searchBox.text ? "No matches" : "" }
                    Btn { visible: Backend.results.length > 0 && sReplace.text !== ""; text: "Replace All"; onClicked: toast.say("Replaced " + Backend.replaceAll(searchBox.text, sReplace.text, sCase.on2, sRe.on2, sWord.on2) + " places", false) } } }
            ListView { id: hits; objectName: "hits"; y: sCol.height + 10; width: parent.width; height: parent.height - y; clip: true; boundsBehavior: Flickable.StopAtBounds; reuseItems: true
                model: win.searchRows(Backend.results)
                delegate: Pressable { required property var modelData; width: hits.width; height: modelData.header ? 28 : 24; radius: 6; color: hovered && !modelData.header ? Theme.t.hover : "transparent"
                    onClicked: if (!modelData.header && modelData.line >= 0) Backend.openRel(modelData.path, modelData.line, modelData.col)
                    Label { visible: modelData.header; x: 2; anchors.verticalCenter: parent.verticalCenter; width: parent.width - 30; elide: Text.ElideLeft; text: modelData.path; font.pixelSize: 11; font.weight: Font.Bold }
                    Label { visible: modelData.header; anchors { right: parent.right; rightMargin: 4; verticalCenter: parent.verticalCenter } text: modelData.count || ""; font.pixelSize: 10; secondary: true }
                    Text { visible: !modelData.header; x: 12; width: parent.width - 16; anchors.verticalCenter: parent.verticalCenter; elide: Text.ElideRight; textFormat: Text.StyledText; font.family: win.mono; font.pixelSize: 11; color: Theme.t.text
                        text: { if (modelData.header) return ""; var t = modelData.text || "", c = modelData.col || 0, n = modelData.length || 0, s = Math.max(0, c - 24)
                            function esc(x) { return x.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;") }
                            return (s ? "…" : "") + esc(t.substring(s, c).replace(/^\s+/, "")) + "<b><font color='" + Theme.t.accent + "'>" + esc(t.substr(c, n)) + "</font></b>" + esc(t.substring(c + n, c + n + 80)) } } } } }

        // ---- changes (Git)
        Item { id: gitPanel; objectName: "gitPanel"; visible: win.panel === "git"; x: 12; y: 52; width: parent.width - 24; height: parent.height - 52
            Column { visible: !Backend.isGit; width: parent.width; spacing: 10; y: 20
                Label { width: parent.width; wrapMode: Text.WordWrap; secondary: true; text: Backend.root ? "This folder isn't a Git repository yet." : "Open a folder first." }
                Btn { visible: !!Backend.root; text: "Make It a Repository"; onClicked: Backend.initRepo() } }
            Row { id: gSwitch; visible: Backend.isGit; spacing: 2; height: 30
                Seg { text: "Changes"; on: win.gitView === "changes"; onClicked: win.gitView = "changes" }
                Seg { objectName: "historyTab"; text: "History"; on: win.gitView === "history"; onClicked: { win.gitView = "history"; win.historyRows = Backend.history("") } } }
            // the history: commits with their graph; click one to see what it changed
            ListView { id: histList; objectName: "histList"; visible: Backend.isGit && win.gitView === "history"; y: 38; width: parent.width; height: parent.height - 38; clip: true
                model: win.historyRows; boundsBehavior: Flickable.StopAtBounds
                delegate: Pressable { id: hc; required property var modelData; required property int index; width: histList.width; height: 44; radius: 8; color: hovered ? Theme.t.hover : "transparent"
                    onClicked: win.showCommit(modelData.sha, modelData.subject)
                    readonly property real lw: 12
                    Canvas { id: graph; x: 4; width: Math.max(1, hc.modelData.width) * hc.lw + 6; height: parent.height
                        onPaint: { var c = getContext("2d"); c.reset(); var cols = ["#7C9CFF", "#3DDC84", "#F5B83D", "#FF6FAE", "#43D9B8", "#B57BFF"]
                            var m = hc.modelData, mid = height / 2
                            for (var k = 0; k < (m.down || []).length; k++) { var a = m.down[k][0], b = m.down[k][1]; c.strokeStyle = cols[a % cols.length]; c.lineWidth = 2; c.beginPath()
                                c.moveTo(6 + a * hc.lw, a === m.lane ? mid : 0); c.bezierCurveTo(6 + a * hc.lw, height * 0.85, 6 + b * hc.lw, height * 0.85, 6 + b * hc.lw, height); c.stroke() }
                            for (var j = 0; j < m.width; j++) if (j !== m.lane && (m.down || []).some(function (d) { return d[0] === j })) { c.strokeStyle = cols[j % cols.length]; c.beginPath(); c.moveTo(6 + j * hc.lw, 0); c.lineTo(6 + j * hc.lw, mid); c.stroke() }
                            if (hc.index !== 0) { c.strokeStyle = cols[m.lane % cols.length]; c.beginPath(); c.moveTo(6 + m.lane * hc.lw, 0); c.lineTo(6 + m.lane * hc.lw, mid); c.stroke() }
                            c.fillStyle = cols[m.lane % cols.length]; c.beginPath(); c.arc(6 + m.lane * hc.lw, mid, 4.5, 0, Math.PI * 2); c.fill() } }
                    Column { x: graph.width + 10; anchors.verticalCenter: parent.verticalCenter; width: parent.width - x - 8
                        Row { spacing: 6; width: parent.width
                            Rectangle { visible: !!hc.modelData.refs; height: 15; width: refL.width + 10; radius: 7; color: Qt.alpha(Theme.t.accent, 0.25); anchors.verticalCenter: parent.verticalCenter
                                Label { id: refL; anchors.centerIn: parent; text: (hc.modelData.refs || "").replace("HEAD -> ", "").split(",")[0]; font.pixelSize: 9 } }
                            Label { width: parent.width - (hc.modelData.refs ? refL.width + 16 : 0); elide: Text.ElideRight; text: hc.modelData.subject; font.pixelSize: 12 } }
                        Label { text: hc.modelData.short + "  ·  " + hc.modelData.author + "  ·  " + hc.modelData.when; font.pixelSize: 10; secondary: true; font.family: win.mono } } }
                Label { visible: histList.count === 0; anchors.centerIn: parent; secondary: true; text: "No commits yet" } }
            Column { id: gCol; visible: Backend.isGit && win.gitView === "changes"; y: 38; width: parent.width; spacing: 8
                Row { spacing: 6; height: 30
                    Glyph { name: "route"; size: 14; anchors.verticalCenter: parent.verticalCenter; ink: Theme.t.accent }
                    Label { anchors.verticalCenter: parent.verticalCenter; text: Backend.branch || "no branch"; font.weight: Font.DemiBold; width: gCol.width - 120; elide: Text.ElideRight }
                    Seg { icon: "down"; tip: "Pull"; onClicked: Backend.sync("pull") }
                    Seg { icon: "up"; tip: "Push"; onClicked: Backend.sync("push") } }
                TextBox { id: commitBox; objectName: "commitBox"; width: parent.width; lines: 3; placeholder: "What changed? (the commit message)" }
                Row { spacing: 8
                    Btn { primary: true; text: "Commit"; onClicked: { var why = Backend.commit(commitBox.many); if (why) toast.say(why, true); else commitBox.many = "" } }
                    Btn { text: "Stage All"; onClicked: Backend.stageAll() }
                    Label { visible: Backend.busy !== ""; anchors.verticalCenter: parent.verticalCenter; text: Backend.busy + "…"; secondary: true; font.pixelSize: 11 } }
                Label { text: Backend.changes.length ? Backend.changes.length + " changed" : "Nothing changed since the last commit"; font.pixelSize: 11; secondary: true; topPadding: 4 } }
            ListView { id: changeList; visible: Backend.isGit && win.gitView === "changes"; y: gCol.y + gCol.height + 8; width: parent.width; height: parent.height - y; clip: true; model: Backend.changes; boundsBehavior: Flickable.StopAtBounds
                delegate: Pressable { id: ch; required property var modelData; width: changeList.width; height: 30; radius: 8; color: hovered ? Theme.t.hover : "transparent"
                    onClicked: win.ask("diff", { rel: modelData.path, staged: modelData.staged && !modelData.unstaged, rows: Backend.diff(modelData.path, modelData.staged && !modelData.unstaged), canStage: modelData.unstaged })
                    onDoubleClicked: Backend.openRel(modelData.path, -1, 0)
                    Text { x: 6; width: 14; anchors.verticalCenter: parent.verticalCenter; text: win.gitLetter(ch.modelData.kind); color: win.gitInk(ch.modelData.kind); font.weight: Font.Bold; font.pixelSize: 11 }
                    Label { x: 24; width: parent.width - 24 - (ch.hovered ? 84 : 26); elide: Text.ElideLeft; anchors.verticalCenter: parent.verticalCenter; text: ch.modelData.path; font.pixelSize: 12 }
                    Rectangle { visible: ch.modelData.staged && !ch.hovered; anchors { right: parent.right; rightMargin: 8; verticalCenter: parent.verticalCenter } width: 8; height: 8; radius: 4; color: win.addInk }
                    Row { visible: ch.hovered; anchors { right: parent.right; rightMargin: 4; verticalCenter: parent.verticalCenter } spacing: 2
                        Seg { visible: ch.modelData.kind === "conflict"; icon: "check"; tip: "Settled: mark it resolved"; onClicked: { var why = Backend.markResolved(ch.modelData.path); if (why) toast.say(why, !/resolved/.test(why)) } }
                        Seg { icon: "back"; tip: "Throw away these changes"; onClicked: win.ask("discard", { rel: ch.modelData.path }) }
                        Seg { icon: ch.modelData.staged && !ch.modelData.unstaged ? "x" : "plus"; tip: ch.modelData.staged && !ch.modelData.unstaged ? "Unstage" : "Stage"
                            onClicked: ch.modelData.staged && !ch.modelData.unstaged ? Backend.unstage(ch.modelData.path) : Backend.stage(ch.modelData.path) } } } } }

        // ---- outline: the file's functions, classes and headings
        ListView { id: outlineList; objectName: "outlineList"; visible: win.panel === "outline"; x: 10; y: 56; width: parent.width - 20; height: parent.height - 66; clip: true
            model: win.outlineRows; boundsBehavior: Flickable.StopAtBounds
            Timer { id: outlineTick; interval: 600; onTriggered: if (win.panel === "outline") win.refreshOutline() }
            Connections { target: Backend; function onChanged() { if (win.panel === "outline") outlineTick.restart() } }
            delegate: Pressable { required property var modelData; width: outlineList.width; height: 26; radius: 7
                readonly property bool here: win.curLine - 1 >= modelData.line && win.curLine - 1 <= modelData.end
                color: here ? Qt.alpha(Theme.t.accent, 0.14) : hovered ? Theme.t.hover : "transparent"
                onClicked: { var v = win.view(); if (v) v.goTo(modelData.line, 0) }
                Text { x: 8 + Math.min(6, modelData.depth) * 14; width: 16; anchors.verticalCenter: parent.verticalCenter; font.pixelSize: 11; font.bold: true
                    color: modelData.kind === "class" || modelData.kind === "struct" || modelData.kind === "interface" ? "#F0B72F" : modelData.kind === "heading" ? Theme.t.text_secondary : "#B392F0"
                    text: modelData.kind === "heading" ? "#" : modelData.kind === "class" || modelData.kind === "struct" || modelData.kind === "interface" || modelData.kind === "enum" ? "C" : "ƒ" }
                Label { x: 26 + Math.min(6, modelData.depth) * 14; width: parent.width - x - 40; elide: Text.ElideRight; anchors.verticalCenter: parent.verticalCenter; text: modelData.name; font.pixelSize: 12 }
                Label { anchors { right: parent.right; rightMargin: 8; verticalCenter: parent.verticalCenter } text: modelData.line + 1; font.pixelSize: 10; secondary: true } }
            Label { visible: outlineList.count === 0; anchors.centerIn: parent; width: parent.width - 40; wrapMode: Text.WordWrap; horizontalAlignment: Text.AlignHCenter; secondary: true
                text: "No functions, classes or headings found in this file" } }

        // ---- problems
        ListView { id: probList; objectName: "probList"; visible: win.panel === "problems"; x: 10; y: 56; width: parent.width - 20; height: parent.height - 66; clip: true; model: Backend.problems
            boundsBehavior: Flickable.StopAtBounds
            delegate: Pressable { required property var modelData; width: probList.width; height: probText.height + 26; radius: 8; color: hovered ? Theme.t.hover : "transparent"
                onClicked: { Backend.select(modelData.tab); Qt.callLater(function () { var v = docs.itemAt(modelData.tab); if (v) v.goTo(modelData.line, modelData.col) }) }
                Rectangle { x: 8; y: 9; width: 8; height: 8; radius: 4; color: modelData.severity === 1 ? win.delInk : modelData.severity === 2 ? "#E3B341" : win.modInk }
                Label { id: probText; x: 24; y: 5; width: parent.width - 30; wrapMode: Text.WordWrap; maximumLineCount: 3; elide: Text.ElideRight; text: modelData.message; font.pixelSize: 12 }
                Label { x: 24; y: probText.height + 7; text: modelData.name + "  " + (modelData.line + 1) + ":" + (modelData.col + 1) + (modelData.source ? "  ·  " + modelData.source : ""); font.pixelSize: 10; secondary: true } }
            Label { visible: probList.count === 0; anchors.centerIn: parent; secondary: true; text: "No problems in your open files" } }

        // ---- tests
        Item { id: testPanel; objectName: "testPanel"; visible: win.panel === "tests"; x: 12; y: 52; width: parent.width - 24; height: parent.height - 52
            readonly property int failed: Backend.tests.filter(function (t) { return t.status === "failed" }).length
            readonly property int passed: Backend.tests.filter(function (t) { return t.status === "passed" }).length
            Row { id: tRow; spacing: 4; height: 30
                Btn { objectName: "runAll"; primary: true; text: Backend.testBusy === "Running tests…" ? "Running…" : "Run All"; enabled: Backend.tests.length > 0 && Backend.testBusy === ""; onClicked: Backend.runTests([]) }
                Seg { visible: Backend.testBusy === "Running tests…"; icon: "stop"; tip: "Stop"; onClicked: Backend.stopTests() }
                Seg { icon: "refresh"; tip: "Find the tests again"; onClicked: Backend.discoverTests() }
                Seg { visible: Backend.testOutput !== ""; icon: "list"; tip: "What the last run printed"; onClicked: win.ask("diff", { rel: "", staged: false, rows: Backend.testOutput.split("\n").map(function (l) { return { text: l, kind: "same", old: "", new: "" } }) }) } }
            Label { y: 36; width: parent.width; wrapMode: Text.WordWrap; font.pixelSize: 11; secondary: true
                text: Backend.testBusy !== "" ? Backend.testBusy : !Backend.testKind ? "No tests found. Code runs pytest, cargo test and go test." :
                      (Backend.tests.length + " tests (" + ({ pytest: "pytest", cargo: "cargo test", go: "go test" })[Backend.testKind] + ")" + (testPanel.passed + testPanel.failed ? "  ·  " + testPanel.passed + " passed" + (testPanel.failed ? ", " + testPanel.failed + " failed" : "") : "")) }
            ListView { id: testList; objectName: "testList"; y: 60; width: parent.width; height: parent.height - 60; clip: true; model: Backend.tests; boundsBehavior: Flickable.StopAtBounds
                section.property: "group"
                section.delegate: Label { required property string section; width: testList.width; elide: Text.ElideLeft; text: section; font.pixelSize: 10; font.weight: Font.Bold; secondary: true; topPadding: 8; leftPadding: 4 }
                delegate: Pressable { id: tc; required property var modelData; width: testList.width; height: msg.visible ? 30 + msg.height + 6 : 28; radius: 8; color: hovered ? Theme.t.hover : "transparent"
                    onClicked: Backend.openTest(modelData.id)
                    Rectangle { x: 8; y: 10; width: 9; height: 9; radius: 4.5
                        color: tc.modelData.status === "passed" ? "#3DDC84" : tc.modelData.status === "failed" ? win.delInk : tc.modelData.status === "running" ? "#F5B83D" : tc.modelData.status === "skipped" ? "#9CA3AF" : Theme.t.islandLine }
                    Label { x: 24; y: 6; width: parent.width - 60; elide: Text.ElideRight; text: tc.modelData.name; font.pixelSize: 12; font.family: win.mono }
                    Seg { visible: tc.hovered; anchors { right: parent.right; rightMargin: 2 } y: 1; icon: "play"; tip: "Run this test"; onClicked: Backend.runTests([tc.modelData.id]) }
                    Text { id: msg; visible: tc.modelData.status === "failed" && tc.modelData.message !== ""; x: 24; y: 26; width: parent.width - 30; wrapMode: Text.WrapAnywhere; maximumLineCount: 6; elide: Text.ElideRight
                        text: tc.modelData.message; color: win.delInk; font.family: win.mono; font.pixelSize: 10; textFormat: Text.PlainText } } } }
    }
    Timer { id: searchTimer; interval: 350; onTriggered: win.runSearch() }
    function runSearch() { Backend.search(searchBox.text, sCase.on2, sRe.on2, sWord.on2) }

    // ================================================================ the slab: the code
    Rectangle { id: slab; objectName: "slab"; x: win.sideW + (win.side ? 24 : 12); y: 64; width: parent.width - x - 12; height: parent.height - y - 46 - (termBox.visible ? termBox.height + 10 : 0)
        radius: 18; color: win.slab; border.width: 1; border.color: Theme.t.islandLine; clip: true
        Repeater { id: docs; model: docModel
            delegate: Item { id: v; required property string path; required property int index
                readonly property int side: !win.split ? (index === Backend.current ? 0 : -1) : (index === Backend.current ? win.pane : index === win.otherTab ? 1 - win.pane : -1)
                visible: side >= 0; y: 0; height: parent.height
                x: win.split && side === 1 ? parent.width / 2 + 1 : 0; width: win.split ? parent.width / 2 - 1 : parent.width
                property var bps: []
                property string known: ""
                property var blameRows: []
                readonly property var blameNow: blameRows.length ? blameRows[Math.max(0, Math.min(blameRows.length - 1, win.curLine - 1))] || null : null
                function loadBlame() { blameRows = win.blameOn ? Backend.blame(index) : [] }
                Connections { target: win; function onBlameOnChanged() { v.loadBlame() } }
                Connections { target: Backend; function onTextLoaded(i) { if (i === v.index && win.blameOn) v.loadBlame() } }
                function renameHere() { var lc = lineCol(); var w = Backend.wordAt(index, lc[0], lc[1]); if (w) win.ask("renamesym", { tab: index, line: lc[0], col: lc[1], name: w }) }
                function referencesHere() { var lc = lineCol(); Backend.references(index, lc[0], lc[1]); win.showPanel("search") }
                property bool loading: false
                property var marks: ({})
                property var probs: []
                property var starts: [0]
                readonly property var info: index < Backend.tabs.length ? Backend.tabs[index] : ({})
                function reload() { loading = true; var at = edit.cursorPosition; known = Backend.textOf(index); edit.text = known; edit.cursorPosition = Math.min(at, edit.length); loading = false; restyle(); refresh() }
                function restyle() { Backend.style(index, { doc: edit.textDocument, colours: win.colours() }) }
                function refresh() { marks = Backend.marksOf(index); probs = Backend.problemsOf(index); bps = Backend.breakpointsOf(index); lineStarts() }
                function lineStarts() { var s = [0], t = edit.text; for (var k = t.indexOf("\n"); k >= 0; k = t.indexOf("\n", k + 1)) s.push(k + 1); starts = s }
                function posOf(line, col) { return Math.min(edit.length, (starts[Math.min(line, starts.length - 1)] || 0) + col) }
                function focusEditor() { edit.forceActiveFocus() }
                function allText() { return edit.text }
                function cursor() { return edit.cursorPosition }
                function lines() { return edit.lineCount }
                function selected() { return edit.selectedText }
                function selectRange(a, b) { edit.select(a, b); scroll.follow(edit.positionToRectangle(a)) }
                function replaceRange(a, b, text) { edit.remove(a, b); edit.insert(a, text) }
                function lineCol() { var before = edit.getText(0, edit.cursorPosition); var nl = before.lastIndexOf("\n"); return [before.split("\n").length - 1, edit.cursorPosition - nl - 1] }
                function goTo(line, col) { lineStarts(); var p = posOf(line, col); edit.cursorPosition = p; edit.forceActiveFocus(); scroll.centreOn(edit.positionToRectangle(p)) }
                function suggest() { var lc = lineCol(); Backend.complete(index, lc[0], lc[1]) }
                function definition() { var lc = lineCol(); Backend.definition(index, lc[0], lc[1]) }
                function hover() { var lc = lineCol(); Backend.hover(index, lc[0], lc[1]) }
                function wordBefore() { var t = edit.getText(Math.max(0, edit.cursorPosition - 80), edit.cursorPosition); var m = /[A-Za-z_][A-Za-z0-9_]*$/.exec(t); return m ? m[0] : "" }
                function offer(items) { win.compAll = items; filterOffer() }
                function filterOffer() {
                    var p = wordBefore(), out = [], lower = p.toLowerCase()
                    for (var k = 0; k < win.compAll.length && out.length < 50; k++) { var it = win.compAll[k]; if (!p || it.label.toLowerCase().indexOf(lower) === 0) out.push(it) }
                    if (out.length === 1 && out[0].label === p) out = []
                    win.compPrefix = p; win.comp = out; win.compAt = 0
                }
                function accept(item) {
                    var p = win.compPrefix, at = edit.cursorPosition
                    win.comp = []; win.compAll = []
                    if (item.snippet) { startSnippet(at - p.length, at, item.snippet); return }
                    edit.remove(at - p.length, at); edit.insert(at - p.length, item.insert)
                }
                // ---- snippets: places to type, Tab to the next
                property var snip: null                    // {stops: [[a, b]…], same: [[[a, b]…]…], k, len}
                function startSnippet(from, to, body) {
                    var t = edit.text, ls = t.lastIndexOf("\n", from - 1) + 1, ind = /^[ \t]*/.exec(t.substring(ls, from))[0]
                    var x = Backend.expandSnippet(index, body, ind)
                    v.multiBusy = true
                    edit.remove(from, to); edit.insert(from, x.text)
                    v.multiBusy = false
                    var stops = x.stops.map(function (r) { return [r[0] + from, r[1] + from] })
                    var same = x.same.map(function (l) { return l.map(function (r) { return [r[0] + from, r[1] + from] }) })
                    snip = stops.length > 1 ? { stops: stops, same: same, k: 0, len: edit.length } : null
                    edit.select(stops[0][0], stops[0][1])
                }
                function checkSnip() { if (!snip) return; var r = snip.stops[snip.k]; if (edit.cursorPosition < r[0] || edit.cursorPosition > r[1]) snip = null }
                function snipShift(delta) {                // the text changed by delta at the current stop
                    if (!snip) return
                    var cur = snip.stops[snip.k], at = cur[0], out = { stops: [], same: [], k: snip.k, len: edit.length }
                    function mv(r) { return r[0] > at || (r[0] === at && r !== cur && r[1] > cur[1]) ? [r[0] + delta, r[1] + delta] : r }
                    for (var n = 0; n < snip.stops.length; n++) {
                        var r = snip.stops[n]
                        out.stops.push(n === snip.k ? [r[0], Math.max(r[0], r[1] + delta)] : (r[0] > at ? [r[0] + delta, r[1] + delta] : r))
                        out.same.push(snip.same[n].map(function (q) { return q[0] > at ? [q[0] + delta, q[1] + delta] : q }))
                    }
                    snip = out
                }
                function nextStop() {
                    var cur = snip.stops[snip.k], typed = edit.getText(cur[0], cur[1]), mirrors = snip.same[snip.k]
                    if (mirrors.length) {                  // the same name again: write what was typed there too
                        var edits = mirrors.map(function (r) { return [r[0], r[1], typed] }), was = snip
                        v.multiBusy = true; Backend.multiEdit(index, edits, false); v.multiBusy = false
                        var out = { stops: [], same: [], k: was.k, len: edit.length }
                        function moved(r) { var d = 0; for (var e = 0; e < mirrors.length; e++) if (mirrors[e][0] < r[0]) d += typed.length - (mirrors[e][1] - mirrors[e][0]); return [r[0] + d, r[1] + d] }
                        for (var n = 0; n < was.stops.length; n++) { out.stops.push(moved(was.stops[n])); out.same.push(n === was.k ? [] : was.same[n].map(moved)) }
                        snip = out
                    }
                    snip.k++
                    var r = snip.stops[snip.k]
                    if (snip.k >= snip.stops.length - 1) { snip = null; if (r[1] > r[0]) edit.select(r[0], r[1]); else edit.cursorPosition = r[0]; return }
                    snip = { stops: snip.stops, same: snip.same, k: snip.k, len: edit.length }
                    edit.select(r[0], r[1])
                }
                // ---- more than one cursor
                property var extra: []                     // [{a, p}]: where each extra selection starts, and its caret
                property bool multiBusy: false
                function anchorOf() { return edit.cursorPosition === edit.selectionStart ? edit.selectionEnd : edit.selectionStart }
                function allCursors() { return [{ a: anchorOf(), p: edit.cursorPosition, main: true }].concat(extra.map(function (c) { return { a: c.a, p: c.p, main: false } })) }
                function wordBounds(at) { var t = edit.text, s = at, e = at; while (s > 0 && /\w/.test(t.charAt(s - 1))) s--; while (e < t.length && /\w/.test(t.charAt(e))) e++; return [s, e] }
                function taken(a, b) { return allCursors().some(function (c) { return Math.min(c.a, c.p) === a && Math.max(c.a, c.p) === b }) }
                function addNext() {
                    if (edit.selectionStart === edit.selectionEnd && !extra.length) { var w = wordBounds(edit.cursorPosition); if (w[1] > w[0]) edit.select(w[0], w[1]); return }
                    var word = edit.getText(edit.selectionStart, edit.selectionEnd); if (!word) return
                    var last = extra.length ? extra[extra.length - 1] : { a: edit.selectionStart, p: edit.selectionEnd }, t = edit.text
                    var from = Math.max(last.a, last.p), k = t.indexOf(word, from)
                    if (k < 0) k = t.indexOf(word)
                    while (k >= 0 && taken(k, k + word.length)) { k = t.indexOf(word, k + 1); if (k < 0) break }
                    if (k < 0) { toast.say("No more of “" + word + "”", false); return }
                    extra = extra.concat([{ a: k, p: k + word.length }]); scroll.follow(edit.positionToRectangle(k))
                }
                function selectEvery() {
                    if (edit.selectionStart === edit.selectionEnd) { var w = wordBounds(edit.cursorPosition); if (w[1] <= w[0]) return; edit.select(w[0], w[1]) }
                    var word = edit.getText(edit.selectionStart, edit.selectionEnd), t = edit.text, out = []
                    for (var k = t.indexOf(word); k >= 0; k = t.indexOf(word, k + word.length)) if (k !== edit.selectionStart) out.push({ a: k, p: k + word.length })
                    extra = out
                    toast.say((out.length + 1) + " cursors", false)
                }
                function addVertical(dir) {
                    lineStarts()
                    var cs = allCursors(), ref = cs.reduce(function (b, c) { return dir > 0 ? (c.p > b.p ? c : b) : (c.p < b.p ? c : b) })
                    var line = 0; while (line + 1 < starts.length && starts[line + 1] <= ref.p) line++
                    var col = ref.p - starts[line], to = line + dir
                    if (to < 0 || to >= starts.length) return
                    var end = to + 1 < starts.length ? starts[to + 1] - 1 : edit.length, p = Math.min(starts[to] + col, end)
                    extra = extra.concat([{ a: p, p: p }])
                }
                property bool typing: false                // the last multi-cursor change was letters: the next joins its undo step
                function typeAll(fn, letters) {   // fn(cursor) -> [from, to, text, caret offset from `from` after]
                    var cs = allCursors().slice().sort(function (x, y) { return Math.min(x.a, x.p) - Math.min(y.a, y.p) }), edits = [], shift = 0, next = [], main = 0
                    for (var n = 0; n < cs.length; n++) {
                        var r = fn(cs[n]); if (!r) { next.push({ a: cs[n].p + shift, p: cs[n].p + shift, main: cs[n].main }); continue }
                        edits.push([r[0], r[1], r[2]])
                        var at = r[0] + shift + r[3]
                        next.push({ a: at, p: at, main: cs[n].main })
                        shift += r[2].length - (r[1] - r[0])
                    }
                    multiBusy = true
                    if (edits.length) Backend.multiEdit(index, edits, !!letters && typing)
                    typing = !!letters
                    var others = []
                    for (var m = 0; m < next.length; m++) if (next[m].main) main = next[m].p; else others.push({ a: next[m].a, p: next[m].p })
                    edit.cursorPosition = main
                    extra = others
                    multiBusy = false
                }
                function moveAll(fn, keep) {   // fn(position) -> new position; keep: extend the selections
                    var cs = allCursors(), others = []
                    typing = false
                    for (var n = 0; n < cs.length; n++) {
                        var to = fn(cs[n].p, cs[n])
                        if (cs[n].main) { multiBusy = true; if (keep) edit.select(cs[n].a, to); else edit.cursorPosition = to; if (keep && to < cs[n].a) edit.select(cs[n].a, to); multiBusy = false }
                        else others.push({ a: keep ? cs[n].a : to, p: to })
                    }
                    extra = others
                }
                function multiKey(e) {   // a key with more than one cursor: true when dealt with
                    var t = edit.text, shift = (e.modifiers & Qt.ShiftModifier)
                    function sel(c) { return [Math.min(c.a, c.p), Math.max(c.a, c.p)] }
                    function lineOf(p) { return [t.lastIndexOf("\n", p - 1) + 1, (t.indexOf("\n", p) < 0 ? t.length : t.indexOf("\n", p))] }
                    if (e.key === Qt.Key_Escape) { extra = []; return true }
                    if (e.key === Qt.Key_Backspace) { typeAll(function (c) { var r = sel(c); if (r[1] > r[0]) return [r[0], r[1], "", 0]; return c.p > 0 ? [c.p - 1, c.p, "", 0] : null }); return true }
                    if (e.key === Qt.Key_Delete) { typeAll(function (c) { var r = sel(c); if (r[1] > r[0]) return [r[0], r[1], "", 0]; return c.p < t.length ? [c.p, c.p + 1, "", 0] : null }); return true }
                    if (e.key === Qt.Key_Return || e.key === Qt.Key_Enter) { typeAll(function (c) { var r = sel(c), ind = /^[ \t]*/.exec(t.substring(lineOf(r[0])[0], r[0]))[0]; return [r[0], r[1], "\n" + ind, 1 + ind.length] }); return true }
                    if (e.key === Qt.Key_Tab) { typeAll(function (c) { var r = sel(c); return [r[0], r[1], win.unit, win.unit.length] }); return true }
                    if (e.key === Qt.Key_Left) { moveAll(function (p, c) { var r = sel(c); return !shift && r[1] > r[0] ? r[0] : Math.max(0, p - 1) }, shift); return true }
                    if (e.key === Qt.Key_Right) { moveAll(function (p, c) { var r = sel(c); return !shift && r[1] > r[0] ? r[1] : Math.min(t.length, p + 1) }, shift); return true }
                    if (e.key === Qt.Key_Home) { moveAll(function (p) { var l = lineOf(p), ind = /^[ \t]*/.exec(t.substring(l[0], l[1]))[0].length; return p === l[0] + ind ? l[0] : l[0] + ind }, shift); return true }
                    if (e.key === Qt.Key_End) { moveAll(function (p) { return lineOf(p)[1] }, shift); return true }
                    if (e.key === Qt.Key_Up || e.key === Qt.Key_Down || e.key === Qt.Key_PageUp || e.key === Qt.Key_PageDown) { extra = []; return false }
                    if (e.text.length === 1 && !(e.modifiers & Qt.ControlModifier) && e.text >= " ") {
                        var ch = e.text; typeAll(function (c) { var r = sel(c); return [r[0], r[1], ch, ch.length] }, /\w/.test(ch)); return true }
                    return false
                }
                // ---- what the call wants; what can be fixed
                function fixHere() { var lc = lineCol(); win.fixMenu = null; Backend.quickFixes(index, lc[0], lc[1]) }
                function askSignature() { var lc = lineCol(); Backend.signatureAt(index, lc[0], lc[1]) }
                // ---- merge conflicts
                property var conflicts: []
                Timer { id: conflictTick; interval: 300; onTriggered: v.conflicts = Backend.conflictsOf(v.index) }
                // ---- sticky scroll: the lines that open the scopes at the top of the view
                property var sticky: []
                readonly property int topLine: Math.max(0, Math.floor((scroll.contentY - edit.y + 2) / Math.max(1, edit.cursorRectangle.height)))
                onContentYChanged: stickyTick.restart()
                readonly property real contentY: scroll.contentY
                onTopLineChanged: stickyTick.restart()
                Timer { id: stickyTick; interval: 60
                    onTriggered: {
                        v.sticky = v.topLine > 0 && !Backend.wrap ? Backend.stickyAt(v.index, v.topLine) : [] } }
                function lineRange() {   // the first and last line of the selection (or the cursor's line)
                    var a = edit.selectionStart, b = edit.selectionEnd, t = edit.text
                    var s = t.lastIndexOf("\n", a - 1) + 1
                    var e = t.indexOf("\n", b > a && t.charAt(b - 1) === "\n" ? b - 1 : b); if (e < 0) e = t.length
                    return [s, e]
                }
                function rewriteLines(fn) {
                    var r = lineRange(), old = edit.getText(r[0], r[1]), parts = old.split("\n"), now = fn(parts).join("\n")
                    if (now === old) return
                    edit.remove(r[0], r[1]); edit.insert(r[0], now); edit.select(r[0], r[0] + now.length)
                }
                function indent(out) {
                    rewriteLines(function (ls) { return ls.map(function (l) {
                        if (!out) return l.length ? win.unit + l : l
                        if (l.indexOf(win.unit) === 0) return l.substring(win.unit.length)
                        return l.replace(/^(\t| {1,4})/, "") }) })
                }
                function toggleComment() {
                    var c = Backend.status.comment
                    if (!c) { var b = Backend.status.block; if (b && b.length === 2 && edit.selectedText) { var a = edit.selectionStart, t = edit.selectedText; edit.remove(a, edit.selectionEnd); edit.insert(a, b[0] + " " + t + " " + b[1]) } return }
                    rewriteLines(function (ls) {
                        var filled = ls.filter(function (l) { return l.trim().length > 0 })
                        var all = filled.length > 0 && filled.every(function (l) { return l.trim().indexOf(c) === 0 })
                        var ind = Math.min.apply(null, filled.map(function (l) { return /^[ \t]*/.exec(l)[0].length }).concat([9999]))
                        return ls.map(function (l) {
                            if (!l.trim().length) return l
                            if (all) return l.replace(new RegExp("^([ \\t]*)" + c.replace(/[.*+?^${}()|[\]\\\/]/g, "\\$&") + " ?"), "$1")
                            return l.substring(0, ind) + c + " " + l.substring(ind) }) })
                }
                Component.onCompleted: { reload(); conflictTick.start() }
                Connections { target: Backend; function onChanged() { if (!v.loading) { v.marks = Backend.marksOf(v.index); v.probs = Backend.problemsOf(v.index); v.bps = Backend.breakpointsOf(v.index) } } }
                Connections { target: win.dbg; function onChanged() { v.bps = Backend.breakpointsOf(v.index) } }

                Text { visible: !!v.info.binary; anchors.centerIn: parent; width: 360; wrapMode: Text.WordWrap; horizontalAlignment: Text.AlignHCenter; color: Theme.t.text_secondary; text: v.info.why || "" }
                // the minimap: the whole file small, with the part on screen marked; click or drag to go there
                Item { id: mm; visible: Backend.minimap && !v.info.binary && edit.lineCount > 40 && v.width > 520
                    anchors { right: parent.right; top: parent.top; bottom: parent.bottom; rightMargin: 8; topMargin: 10; bottomMargin: 10 } width: 92
                    property int ver: 0
                    Timer { id: mmTick; interval: 700; onTriggered: mm.ver++ }
                    readonly property real full: edit.lineCount * 2
                    readonly property real k: Math.min(1, height / Math.max(1, full))
                    Image { id: mmImg; width: parent.width; height: mm.full * mm.k; fillMode: Image.Stretch; smooth: true; cache: false; asynchronous: true
                        source: mm.visible ? "image://minimap/" + v.index + "/" + mm.ver + "_" + edit.lineCount : "" }
                    Rectangle { width: parent.width; radius: 3; color: Qt.alpha(Theme.t.accent, 0.14); border.width: 1; border.color: Qt.alpha(Theme.t.accent, 0.4)
                        y: scroll.contentHeight > 0 ? scroll.contentY / scroll.contentHeight * mmImg.height : 0
                        height: Math.max(12, scroll.contentHeight > 0 ? Math.min(1, scroll.height / scroll.contentHeight) * mmImg.height : 0) }
                    MouseArea { width: parent.width; height: mmImg.height; cursorShape: Qt.PointingHandCursor
                        function go(y) { scroll.contentY = Math.max(0, Math.min(scroll.contentHeight - scroll.height, y / Math.max(1, mmImg.height) * scroll.contentHeight - scroll.height / 2)) }
                        onPressed: function (m) { go(m.y) } onPositionChanged: function (m) { go(m.y) } } }
                Flickable { id: scroll; visible: !v.info.binary; anchors { fill: parent; margins: 2; bottomMargin: findBar.visible && v.visible ? 0 : 2; rightMargin: win.mdPreview && v.info.lang === "Markdown" ? v.width / 2 + 4 : mm.visible ? 104 : 2 } clip: true; boundsBehavior: Flickable.StopAtBounds
                    contentWidth: Backend.wrap ? width : Math.max(width, edit.x + edit.contentWidth + 60); contentHeight: edit.height + height * 0.5
                    function follow(r) {
                        if (r.y + edit.y - 10 < contentY) contentY = Math.max(0, r.y + edit.y - 10); else if (r.y + edit.y + r.height + 40 > contentY + height) contentY = r.y + edit.y + r.height + 40 - height
                        if (Backend.wrap) return
                        var x = edit.x + r.x; if (x - 60 < contentX) contentX = Math.max(0, x - 60); else if (x + 40 > contentX + width) contentX = x + 40 - width }
                    function centreOn(r) { contentY = Math.max(0, Math.min(contentHeight - height, r.y + edit.y - height / 3)); follow(r) }
                    // blame: who changed each line (Ctrl+Alt+B); click one to see that commit
                    Rectangle { id: blameCol; objectName: "blameCol"; visible: win.blameOn && v.blameRows.length > 0 && !Backend.wrap; z: 4; x: scroll.contentX + scroll.width - width - 6; y: edit.y; width: 230
                        height: edit.height; color: Theme.t.dark ? "#E6111317" : "#EEF6F7F9"; radius: 6
                        Text { anchors.fill: parent; anchors.leftMargin: 8; font.family: win.mono; font.pixelSize: Math.max(9, Backend.size - 2); color: Theme.t.text_secondary; elide: Text.ElideRight
                            lineHeight: edit.cursorRectangle.height > 0 ? edit.cursorRectangle.height : 1.0; lineHeightMode: Text.FixedHeight; textFormat: Text.PlainText
                            text: v.blameRows.map(function (b) { return b.first ? (b.author.split(" ")[0] + ", " + b.when).substring(0, 30) : "" }).join("\n") }
                        MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor
                            onClicked: function (m) { var k = Math.floor(m.y / Math.max(1, edit.cursorRectangle.height)), b = v.blameRows[k]; if (b && b.sha) win.showCommit(b.sha, b.summary) } } }
                    Text { visible: win.blameOn && !Backend.wrap && v.blameRows.length > 0 && v.blameNow !== null; z: 3; x: edit.x + edit.contentWidth + 40; y: edit.y + edit.cursorRectangle.y
                        height: edit.cursorRectangle.height; verticalAlignment: Text.AlignVCenter; font.family: win.mono; font.pixelSize: Math.max(9, Backend.size - 2); color: win.gutterInk; opacity: 0.8
                        text: v.blameNow ? v.blameNow.author + ", " + v.blameNow.when + (v.blameNow.summary ? " · " + v.blameNow.summary : "") : "" }
                    // the line the cursor is on
                    Rectangle { x: 0; y: edit.y + edit.cursorRectangle.y - 1; width: scroll.contentWidth; height: edit.cursorRectangle.height + 2; color: win.lineGlow; visible: edit.activeFocus || true }
                    // merge conflicts: ours green, theirs blue, with what to keep above each
                    Repeater { model: Backend.wrap ? [] : v.conflicts
                        Item { required property var modelData; required property int index
                            readonly property real lh: edit.cursorRectangle.height
                            Rectangle { x: 0; y: edit.y + modelData.start * parent.lh; width: scroll.contentWidth; height: parent.lh; color: Qt.rgba(0.25, 0.73, 0.31, 0.32) }
                            Rectangle { x: 0; y: edit.y + (modelData.start + 1) * parent.lh; width: scroll.contentWidth; height: ((modelData.base > 0 ? modelData.base : modelData.mid) - modelData.start - 1) * parent.lh; color: Qt.rgba(0.25, 0.73, 0.31, 0.13) }
                            Rectangle { x: 0; y: edit.y + modelData.mid * parent.lh; width: scroll.contentWidth; height: parent.lh; color: Qt.rgba(0.5, 0.5, 0.5, 0.2) }
                            Rectangle { x: 0; y: edit.y + (modelData.mid + 1) * parent.lh; width: scroll.contentWidth; height: (modelData.end - modelData.mid - 1) * parent.lh; color: Qt.rgba(0.3, 0.55, 1, 0.13) }
                            Rectangle { x: 0; y: edit.y + modelData.end * parent.lh; width: scroll.contentWidth; height: parent.lh; color: Qt.rgba(0.3, 0.55, 1, 0.32) } } }
                    Repeater { model: Backend.wrap ? [] : v.conflicts      // …and what to keep, over the text so it can be clicked
                        Row { required property var modelData; required property int index; objectName: "conflictBar"; z: 8
                            readonly property int which: index
                            x: scroll.contentX + edit.x + 260; y: edit.y + modelData.start * edit.cursorRectangle.height; height: edit.cursorRectangle.height; spacing: 10
                            Repeater { model: [["ours", "Keep ours (" + parent.modelData.oursName + ")"], ["theirs", "Keep theirs (" + parent.modelData.theirsName + ")"], ["both", "Keep both"]]
                                Text { required property var modelData; anchors.verticalCenter: parent.verticalCenter; text: modelData[1]; font.pixelSize: Math.max(10, Backend.size - 3); color: Theme.t.accent; font.underline: ma.containsMouse
                                    MouseArea { id: ma; anchors.fill: parent; anchors.margins: -3; hoverEnabled: true; cursorShape: Qt.PointingHandCursor
                                        onClicked: Backend.resolveConflict(v.index, parent.parent.which, parent.modelData[0]) } } } } }

                    // the other cursors and what they've selected
                    Repeater { model: v.extra
                        Item { required property var modelData
                            readonly property rect ra: edit.positionToRectangle(Math.min(modelData.a, modelData.p))
                            readonly property rect rb: edit.positionToRectangle(Math.max(modelData.a, modelData.p))
                            readonly property rect rc: edit.positionToRectangle(modelData.p)
                            Rectangle { visible: parent.ra.y === parent.rb.y && parent.rb.x > parent.ra.x; x: edit.x + parent.ra.x; y: edit.y + parent.ra.y; width: parent.rb.x - parent.ra.x; height: parent.ra.height
                                color: Qt.alpha(Theme.t.accent, 0.35) }
                            Rectangle { x: edit.x + parent.rc.x; y: edit.y + parent.rc.y; width: 2; height: parent.rc.height; color: Theme.t.text } } }
                    // a snippet's places still to fill
                    Repeater { model: v.snip ? v.snip.stops.slice(v.snip.k + 1, v.snip.stops.length - 1) : []
                        Rectangle { required property var modelData; readonly property rect ra: edit.positionToRectangle(modelData[0]); readonly property rect rb: edit.positionToRectangle(modelData[1])
                            x: edit.x + ra.x - 1; y: edit.y + ra.y; width: Math.max(4, rb.x - ra.x + 2); height: ra.height; radius: 3; color: "transparent"; border.width: 1
                            border.color: Qt.alpha(Theme.t.accent, 0.6) } }
                    // a light when the cursor's line has a problem: click it (or Ctrl+.) for fixes
                    Text { objectName: "fixBulb"; visible: !Backend.wrap && v.probs.some(function (p) { return p.line <= win.curLine - 1 && win.curLine - 1 <= p.endLine }) && v.index === Backend.current
                        z: 6; x: 1; y: edit.y + edit.cursorRectangle.y; height: edit.cursorRectangle.height; verticalAlignment: Text.AlignVCenter; text: "💡"; font.pixelSize: Math.max(10, Backend.size - 3)
                        MouseArea { anchors.fill: parent; anchors.margins: -3; cursorShape: Qt.PointingHandCursor; onClicked: v.fixHere() } }
                    // line numbers
                    Text { id: gutter; x: 0; y: edit.y; width: gutterW; horizontalAlignment: Text.AlignRight; rightPadding: 14; color: win.gutterInk; renderType: Text.NativeRendering
                        readonly property int gutterW: 34 + String(edit.lineCount).length * Math.ceil(Backend.size * 0.62)
                        visible: !Backend.wrap; font.family: win.mono; font.pixelSize: Backend.size; lineHeight: edit.cursorRectangle.height > 0 ? edit.cursorRectangle.height : 1.0; lineHeightMode: Text.FixedHeight
                        text: { var n = edit.lineCount, all = new Array(n); for (var k = 0; k < n; k++) all[k] = k + 1; return all.join("\n") } }
                    // breakpoints: click a line number to set or clear one
                    MouseArea { visible: !Backend.wrap; x: 0; y: edit.y; width: gutter.width - 8; height: edit.height; cursorShape: Qt.PointingHandCursor
                        onClicked: function (m) { Backend.toggleBreakpoint(v.index, Math.floor(m.y / Math.max(1, edit.cursorRectangle.height))) } }
                    Repeater { model: Backend.wrap ? [] : v.bps
                        Rectangle { required property int modelData; x: 3; y: edit.y + modelData * edit.cursorRectangle.height + (edit.cursorRectangle.height - 11) / 2
                            width: 11; height: 11; radius: 5.5; color: "#E5484D"; border.width: 1; border.color: "#33000000" } }
                    // where the debugger stopped
                    Rectangle { visible: win.dbg.whereFile === v.path && win.dbg.whereLine >= 0; x: 0; y: edit.y + win.dbg.whereLine * edit.cursorRectangle.height - 1
                        width: scroll.contentWidth; height: edit.cursorRectangle.height + 2; color: Qt.rgba(1, 0.78, 0.2, 0.22)
                        Text { x: 1; anchors.verticalCenter: parent.verticalCenter; text: "➜"; color: "#F5B83D"; font.pixelSize: Backend.size; visible: !Backend.wrap } }
                    // Git's marks beside the numbers
                    Repeater { model: Backend.wrap ? [] : Object.keys(v.marks)
                        Rectangle { required property string modelData; readonly property string kind: v.marks[modelData]
                            x: gutter.width - 6; y: edit.y + (parseInt(modelData) * edit.cursorRectangle.height) + (kind === "del" ? edit.cursorRectangle.height - 3 : 0)
                            width: 3; height: kind === "del" ? 5 : edit.cursorRectangle.height; radius: 1.5; color: kind === "add" ? win.addInk : kind === "mod" ? win.modInk : win.delInk } }
                    // problems: a dot by the number and a wavy line under the words
                    Repeater { model: v.probs.slice(0, 300)
                        Item { required property var modelData
                            readonly property rect a: edit.positionToRectangle(v.posOf(modelData.line, modelData.col))
                            readonly property rect b: edit.positionToRectangle(v.posOf(modelData.endLine, Math.max(modelData.endCol, modelData.col + 1)))
                            readonly property color ink: modelData.severity === 1 ? win.delInk : modelData.severity === 2 ? "#E3B341" : win.modInk
                            Rectangle { visible: !Backend.wrap; x: 6; y: edit.y + parent.a.y + parent.a.height / 2 - 4; width: 8; height: 8; radius: 4; color: parent.ink }
                            Rectangle { x: edit.x + parent.a.x; y: edit.y + parent.a.y + parent.a.height - 2; width: Math.max(8, (parent.b.y === parent.a.y ? parent.b.x : edit.contentWidth) - parent.a.x); height: 2; color: parent.ink; opacity: 0.85 } } }
                    TextEdit { id: edit; objectName: "editor"; x: Backend.wrap ? 20 : gutter.width + 6; y: 12
                        width: Backend.wrap ? scroll.width - 40 : Math.max(contentWidth + 20, scroll.width - x - 10)
                        color: Theme.t.text; selectionColor: Qt.alpha(Theme.t.accent, 0.45); selectedTextColor: Theme.t.text
                        font.family: win.mono; font.pixelSize: Backend.size; wrapMode: Backend.wrap ? TextEdit.Wrap : TextEdit.NoWrap; textFormat: TextEdit.PlainText
                        readOnly: !!v.info.readOnly; selectByMouse: true; persistentSelection: true; tabStopDistance: 4 * widest.advanceWidth; focus: v.index === Backend.current
                        onActiveFocusChanged: if (activeFocus && win.split && v.index !== Backend.current) { var side = v.side; Backend.select(v.index); win.pane = side }
                        TextMetrics { id: widest; font: edit.font; text: " " }
                        onTextChanged: {
                            if (v.loading || text === v.known) return      // colouring touches the text too: only real typing counts
                            if (v.snip && !v.multiBusy) v.snipShift(length - v.snip.len)
                            if (!v.multiBusy && v.extra.length) v.extra = []
                            conflictTick.restart(); stickyTick.restart()
                            v.known = text
                            mmTick.restart()
                            Backend.edit(v.index, text); v.lineStarts()
                            if (win.finding) win.refind()
                            if (win.comp.length) v.filterOffer()
                            var c = getText(Math.max(0, cursorPosition - 1), cursorPosition)
                            if (/[A-Za-z_.]/.test(c)) suggestTimer.restart(); else if (!win.comp.length) suggestTimer.stop()
                        }
                        onCursorPositionChanged: { if (v.visible) { var lc = v.lineCol(); win.curLine = lc[0] + 1; win.curCol = lc[1] + 1 } if (win.tip) win.tip = ""
                            if (v.snip && !v.multiBusy) Qt.callLater(v.checkSnip)    // after the text has caught up (the cursor moves first)
                            if (win.fixMenu) win.fixMenu = null }
                        TapHandler { acceptedModifiers: Qt.AltModifier; onTapped: function (p) { var at = edit.positionAt(p.position.x, p.position.y); if (!v.taken(at, at)) v.extra = v.extra.concat([{ a: at, p: at }]) } }
                        TapHandler { acceptedModifiers: Qt.NoModifier; onTapped: if (v.extra.length) v.extra = [] }
                        onCursorRectangleChanged: if (v.visible) scroll.follow(cursorRectangle)
                        TapHandler { acceptedModifiers: Qt.ControlModifier; onTapped: function (p) { edit.cursorPosition = edit.positionAt(p.position.x, p.position.y); v.definition() } }
                        Keys.onPressed: function (e) {
                            var ctrl = (e.modifiers & Qt.ControlModifier), shift = (e.modifiers & Qt.ShiftModifier), t = edit.text, at = edit.cursorPosition
                            if (win.comp.length) {
                                if (e.key === Qt.Key_Down) { win.compAt = (win.compAt + 1) % win.comp.length; e.accepted = true; return }
                                if (e.key === Qt.Key_Up) { win.compAt = (win.compAt - 1 + win.comp.length) % win.comp.length; e.accepted = true; return }
                                if (e.key === Qt.Key_Return || e.key === Qt.Key_Enter || e.key === Qt.Key_Tab) { v.accept(win.comp[win.compAt]); e.accepted = true; return }
                                if (e.key === Qt.Key_Escape) { win.comp = []; e.accepted = true; return }
                            }
                            if (win.fixMenu && win.fixMenu.items.length) {
                                if (e.key === Qt.Key_Down) { win.fixMenu = { items: win.fixMenu.items, k: (win.fixMenu.k + 1) % win.fixMenu.items.length }; e.accepted = true; return }
                                if (e.key === Qt.Key_Up) { win.fixMenu = { items: win.fixMenu.items, k: (win.fixMenu.k - 1 + win.fixMenu.items.length) % win.fixMenu.items.length }; e.accepted = true; return }
                                if (e.key === Qt.Key_Return || e.key === Qt.Key_Enter) { Backend.applyFix(win.fixMenu.k); win.fixMenu = null; e.accepted = true; return }
                                if (e.key === Qt.Key_Escape) { win.fixMenu = null; e.accepted = true; return }
                            }
                            if (readOnly) return
                            var alt = (e.modifiers & Qt.AltModifier)
                            if (ctrl && !shift && e.key === Qt.Key_D) { v.addNext(); e.accepted = true; return }
                            if (ctrl && shift && e.key === Qt.Key_L) { v.selectEvery(); e.accepted = true; return }
                            if (ctrl && alt && (e.key === Qt.Key_Down || e.key === Qt.Key_Up)) { v.addVertical(e.key === Qt.Key_Down ? 1 : -1); e.accepted = true; return }
                            if (ctrl && e.key === Qt.Key_Period) { v.fixHere(); e.accepted = true; return }
                            if (v.snip && e.key === Qt.Key_Tab && !shift) { v.nextStop(); e.accepted = true; return }
                            if (v.snip && e.key === Qt.Key_Escape) { v.snip = null; e.accepted = true; return }
                            if (win.sig && (e.key === Qt.Key_Escape || e.text === ")")) win.sig = null
                            if (v.extra.length && v.multiKey(e)) { e.accepted = true; return }
                            if (e.text === "(" || e.text === ",") Qt.callLater(v.askSignature)
                            if (ctrl && e.key === Qt.Key_Space) { v.suggest(); e.accepted = true; return }
                            if (ctrl && (e.key === Qt.Key_Slash || e.key === Qt.Key_Question)) { v.toggleComment(); e.accepted = true; return }
                            if (ctrl && e.key === Qt.Key_I && !shift) { v.hover(); e.accepted = true; return }
                            if (e.key === Qt.Key_F12 && shift) { v.referencesHere(); e.accepted = true; return }
                            if (e.key === Qt.Key_F2) { v.renameHere(); e.accepted = true; return }
                            if (e.key === Qt.Key_F9) { var lc9 = v.lineCol(); Backend.toggleBreakpoint(v.index, lc9[0]); e.accepted = true; return }
                            if (e.key === Qt.Key_F12) { v.definition(); e.accepted = true; return }
                            if (e.key === Qt.Key_Tab && !ctrl) {
                                if (edit.selectedText.indexOf("\n") >= 0) v.indent(false); else { edit.remove(edit.selectionStart, edit.selectionEnd); edit.insert(edit.cursorPosition, win.unit) }
                                e.accepted = true; return }
                            if (e.key === Qt.Key_Backtab) { v.indent(true); e.accepted = true; return }
                            if ((e.key === Qt.Key_Return || e.key === Qt.Key_Enter) && !ctrl && !shift) {
                                var ls = t.lastIndexOf("\n", at - 1) + 1, line = t.substring(ls, at), ind = /^[ \t]*/.exec(line)[0], trimmed = line.replace(/\s+$/, "")
                                var opens = /[:{(\[]$/.test(trimmed), next = t.charAt(at), pair = { "{": "}", "(": ")", "[": "]" }[trimmed.slice(-1)]
                                edit.remove(edit.selectionStart, edit.selectionEnd)
                                if (pair && next === pair) { edit.insert(edit.cursorPosition, "\n" + ind + win.unit + "\n" + ind); edit.cursorPosition = edit.cursorPosition - 1 - ind.length }
                                else edit.insert(edit.cursorPosition, "\n" + ind + (opens ? win.unit : ""))
                                e.accepted = true; return }
                            if (e.key === Qt.Key_Backspace && !ctrl && edit.selectionStart === edit.selectionEnd && at > 0) {
                                var prev = t.charAt(at - 1), nx = t.charAt(at)
                                if (({ "(": ")", "[": "]", "{": "}", "\"": "\"", "'": "'" })[prev] === nx && nx) { edit.remove(at - 1, at + 1); e.accepted = true; return }
                                var before = t.substring(t.lastIndexOf("\n", at - 1) + 1, at)
                                if (before.length && /^ +$/.test(before) && win.unit !== "\t" && before.length % win.unit.length === 0) { edit.remove(at - win.unit.length, at); e.accepted = true; return }
                                return }
                            var ch = e.text
                            if (!ctrl && ch.length === 1) {
                                var closer = ({ "(": ")", "[": "]", "{": "}" })[ch], after = t.charAt(at), prevc = t.charAt(at - 1)
                                if (closer) {
                                    if (edit.selectedText) { var a1 = edit.selectionStart, s1 = edit.selectedText; edit.remove(a1, edit.selectionEnd); edit.insert(a1, ch + s1 + closer); edit.select(a1 + 1, a1 + 1 + s1.length); e.accepted = true; return }
                                    if (!after || /[\s)\]},;:]/.test(after)) { edit.insert(at, ch + closer); edit.cursorPosition = at + 1; e.accepted = true; return }
                                }
                                if ((ch === ")" || ch === "]" || ch === "}") && after === ch) { edit.cursorPosition = at + 1; e.accepted = true; return }
                                if (ch === "\"" || ch === "'" || ch === "`") {
                                    if (after === ch) { edit.cursorPosition = at + 1; e.accepted = true; return }
                                    if (edit.selectedText) { var a2 = edit.selectionStart, s2 = edit.selectedText; edit.remove(a2, edit.selectionEnd); edit.insert(a2, ch + s2 + ch); e.accepted = true; return }
                                    if (!/[A-Za-z0-9_]/.test(prevc) && (!after || /[\s)\]},;:]/.test(after))) { edit.insert(at, ch + ch); edit.cursorPosition = at + 1; e.accepted = true; return }
                                }
                                if (closer === undefined && ch === "}" && /^[ \t]+$/.test(t.substring(t.lastIndexOf("\n", at - 1) + 1, at))) {   // a closing brace on its own line steps back
                                    var ls2 = t.lastIndexOf("\n", at - 1) + 1, sp = t.substring(ls2, at)
                                    var shorter = sp.indexOf(win.unit) === 0 ? sp.substring(win.unit.length) : sp.replace(/^(\t| {1,4})/, "")
                                    edit.remove(ls2, at); edit.insert(ls2, shorter + "}"); e.accepted = true; return }
                            }
                        } }
                    MouseArea { y: edit.y + edit.height; width: scroll.contentWidth; height: Math.max(0, scroll.contentHeight - y); onClicked: { edit.forceActiveFocus(); edit.cursorPosition = edit.length } } }
                Timer { id: suggestTimer; interval: 260; onTriggered: { if (v.visible && edit.activeFocus) { var w = v.wordBefore(), c = edit.getText(Math.max(0, edit.cursorPosition - 1), edit.cursorPosition)
                    if (c === "." || w.length >= 2) v.suggest() } } }
                // the suggestion list, under the cursor
                Rectangle { id: compBox; visible: v.visible && v.index === Backend.current && win.comp.length > 0; z: 5; width: 380; height: Math.min(8, win.comp.length) * 30 + 10; radius: 12
                    color: Theme.t.menu_bg; border.width: 1; border.color: Theme.t.menu_border
                    readonly property point at: edit.mapToItem(v, edit.cursorRectangle.x, edit.cursorRectangle.y + edit.cursorRectangle.height)
                    x: Math.min(at.x, v.width - width - 10); y: at.y + height + 6 > v.height ? at.y - edit.cursorRectangle.height - height - 4 : at.y + 4
                    ListView { id: compList; anchors { fill: parent; margins: 5 } clip: true; model: win.comp; currentIndex: win.compAt; highlightMoveDuration: 0
                        onCurrentIndexChanged: positionViewAtIndex(currentIndex, ListView.Contain)
                        delegate: Pressable { required property var modelData; required property int index; width: compList.width; height: 30; radius: 7
                            color: index === win.compAt ? Qt.alpha(Theme.t.accent, 0.25) : hovered ? Theme.t.hover : "transparent"
                            onClicked: { v.accept(modelData); edit.forceActiveFocus() }
                            Rectangle { x: 8; anchors.verticalCenter: parent.verticalCenter; width: 16; height: 16; radius: 4
                                color: modelData.kind === 15 ? "#56D4BC" : [2, 3, 4].indexOf(modelData.kind) >= 0 ? "#B392F0" : [5, 6, 10].indexOf(modelData.kind) >= 0 ? "#79B8FF" : [7, 8, 22].indexOf(modelData.kind) >= 0 ? "#F0B72F" : modelData.kind === 14 ? "#F97583" : Theme.t.text_secondary
                                Text { anchors.centerIn: parent; text: modelData.kind === 15 ? "⌁" : [2, 3, 4].indexOf(modelData.kind) >= 0 ? "ƒ" : [5, 6, 10].indexOf(modelData.kind) >= 0 ? "v" : [7, 8, 22].indexOf(modelData.kind) >= 0 ? "C" : modelData.kind === 9 ? "m" : modelData.kind === 14 ? "k" : "a"
                                    font.pixelSize: 10; font.bold: true; color: "#111" } }
                            Text { x: 32; width: parent.width * 0.55; elide: Text.ElideRight; anchors.verticalCenter: parent.verticalCenter; font.family: win.mono; font.pixelSize: 12; color: Theme.t.text
                                textFormat: Text.StyledText; text: "<b>" + modelData.label.substring(0, win.compPrefix.length) + "</b>" + modelData.label.substring(win.compPrefix.length) }
                            Label { anchors { right: parent.right; rightMargin: 8; verticalCenter: parent.verticalCenter } width: parent.width * 0.38; elide: Text.ElideRight; horizontalAlignment: Text.AlignRight
                                text: modelData.detail; font.pixelSize: 10; secondary: true } } } }
                // sticky scroll: the scopes the top of the view is inside
                Column { objectName: "stickyRows"; visible: v.visible && v.sticky.length > 0 && !v.info.binary; z: 4; x: scroll.x; y: scroll.y; width: scroll.width
                    Repeater { model: v.sticky
                        Rectangle { required property var modelData; width: parent.width; height: edit.cursorRectangle.height + 2; color: win.slab
                            Text { x: 0; width: gutter.width; horizontalAlignment: Text.AlignRight; rightPadding: 14; anchors.verticalCenter: parent.verticalCenter; text: modelData.line + 1
                                font.family: win.mono; font.pixelSize: Backend.size; color: win.gutterInk }
                            Text { x: edit.x - scroll.contentX; anchors.verticalCenter: parent.verticalCenter; text: modelData.text; font.family: win.mono; font.pixelSize: Backend.size; color: Theme.t.text; textFormat: Text.PlainText }
                            MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: v.goTo(modelData.line, 0) } } }
                    Rectangle { width: parent.width; height: 1; color: Theme.t.islandLine } }
                // what the call being typed wants
                Rectangle { objectName: "sigTip"; visible: v.visible && v.index === Backend.current && win.sig !== null && !win.comp.length; z: 6; radius: 10
                    width: Math.min(v.width - 40, sigText.implicitWidth + 24); height: sigText.height + (sigDoc.visible ? sigDoc.height + 6 : 0) + 16
                    color: Theme.t.menu_bg; border.width: 1; border.color: Theme.t.menu_border
                    readonly property point at: edit.mapToItem(v, edit.cursorRectangle.x, edit.cursorRectangle.y)
                    x: Math.max(8, Math.min(at.x - 30, v.width - width - 10)); y: at.y - height - 6 < 0 ? at.y + edit.cursorRectangle.height + 6 : at.y - height - 6
                    function esc(t) { return t.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;") }
                    Text { id: sigText; x: 12; y: 8; font.family: win.mono; font.pixelSize: 12; color: Theme.t.text; textFormat: Text.StyledText
                        text: !win.sig ? "" : win.sig.a < 0 ? parent.esc(win.sig.label) : parent.esc(win.sig.label.substring(0, win.sig.a)) + "<b><font color='" + Theme.t.accent + "'>"
                              + parent.esc(win.sig.label.substring(win.sig.a, win.sig.b)) + "</font></b>" + parent.esc(win.sig.label.substring(win.sig.b)) }
                    Text { id: sigDoc; visible: !!win.sig && win.sig.doc !== ""; x: 12; y: sigText.height + 12; width: Math.min(520, v.width - 64); wrapMode: Text.Wrap; maximumLineCount: 4; elide: Text.ElideRight
                        font.pixelSize: 11; color: Theme.t.text_secondary; text: win.sig ? win.sig.doc : "" } }
                // quick fixes at the cursor
                Rectangle { objectName: "fixMenu"; visible: v.visible && v.index === Backend.current && win.fixMenu !== null; z: 7; width: 360; height: (win.fixMenu ? win.fixMenu.items.length : 0) * 30 + 10; radius: 12
                    color: Theme.t.menu_bg; border.width: 1; border.color: Theme.t.menu_border
                    readonly property point at: edit.mapToItem(v, edit.cursorRectangle.x, edit.cursorRectangle.y + edit.cursorRectangle.height)
                    x: Math.min(at.x, v.width - width - 10); y: at.y + height + 6 > v.height ? at.y - edit.cursorRectangle.height - height - 4 : at.y + 4
                    Column { x: 5; y: 5; width: parent.width - 10
                        Repeater { model: win.fixMenu ? win.fixMenu.items : []
                            Pressable { required property var modelData; required property int index; width: parent.width; height: 30; radius: 7
                                color: win.fixMenu && index === win.fixMenu.k ? Qt.alpha(Theme.t.accent, 0.25) : hovered ? Theme.t.hover : "transparent"
                                onClicked: { Backend.applyFix(index); win.fixMenu = null; edit.forceActiveFocus() }
                                Text { x: 10; anchors.verticalCenter: parent.verticalCenter; text: "💡"; font.pixelSize: 11 }
                                Label { x: 30; width: parent.width - 40; elide: Text.ElideRight; anchors.verticalCenter: parent.verticalCenter; text: modelData.title; font.pixelSize: 12 } } } } }
                // Markdown as it reads, beside its text
                Rectangle { objectName: "mdPreview"; visible: win.mdPreview && v.info.lang === "Markdown"; z: 3; anchors { right: parent.right; top: parent.top; bottom: parent.bottom; margins: 6 }
                    width: parent.width / 2 - 10; radius: 12; color: Theme.t.dark ? "#16181D" : "#FFFFFF"; border.width: 1; border.color: Theme.t.islandLine; clip: true
                    Flickable { id: mdFlick; anchors.fill: parent; anchors.margins: 18; contentHeight: mdText.height + 40; boundsBehavior: Flickable.StopAtBounds; clip: true
                        contentY: scroll.contentHeight > scroll.height ? Math.max(0, Math.min(contentHeight - height, scroll.contentY / (scroll.contentHeight - scroll.height) * (contentHeight - height))) : 0
                        Text { id: mdText; width: mdFlick.width; wrapMode: Text.Wrap; textFormat: Text.MarkdownText; text: edit.text; color: Theme.t.text; font.pixelSize: 14
                            baseUrl: "file://" + v.path; onLinkActivated: function (link) { Qt.openUrlExternally(link) } } } }
                // what the language server says about the word under the cursor
                Rectangle { visible: v.visible && win.tip !== ""; z: 6; width: Math.min(560, v.width - 40); height: Math.min(260, tipText.contentHeight + 24); radius: 12; clip: true
                    color: Theme.t.menu_bg; border.width: 1; border.color: Theme.t.menu_border
                    readonly property point at: edit.mapToItem(v, edit.cursorRectangle.x, edit.cursorRectangle.y)
                    x: Math.min(at.x, v.width - width - 10); y: at.y - height - 6 < 0 ? at.y + edit.cursorRectangle.height + 6 : at.y - height - 6
                    Text { id: tipText; x: 12; y: 12; width: parent.width - 24; wrapMode: Text.Wrap; textFormat: Text.MarkdownText; text: win.tip; color: Theme.t.text; font.pixelSize: 12 } }
            } }

        // find and replace, floating at the slab's top right
        Rectangle { id: findBar; objectName: "findBar"; visible: win.finding && Backend.current >= 0; z: 8; anchors { right: parent.right; rightMargin: 14; top: parent.top; topMargin: 10 } width: 430; height: win.replacing ? 84 : 46; radius: 12
            color: Theme.t.menu_bg; border.width: 1; border.color: Theme.t.menu_border
            Row { x: 8; y: 7; spacing: 4
                Rectangle { width: 190; height: 32; radius: 8; color: Theme.t.capsule; border.width: 1; border.color: findBox.activeFocus ? Theme.t.accent : Theme.t.capsule_border
                    TextInput { id: findBox; objectName: "findBox"; x: 8; width: parent.width - 16; anchors.verticalCenter: parent.verticalCenter; color: Theme.t.text; font.pixelSize: 13; clip: true; selectByMouse: true
                        onTextChanged: win.refind()
                        Keys.onPressed: function (e) { if (e.key === Qt.Key_Return || e.key === Qt.Key_Enter) { win.step((e.modifiers & Qt.ShiftModifier) ? -1 : 1); e.accepted = true } else if (e.key === Qt.Key_Escape) { win.finding = false; win.view().focusEditor(); e.accepted = true } }
                        Text { visible: !findBox.text; text: "Find"; color: Theme.t.text_secondary; font: findBox.font } } }
                Seg { id: matchCase; property bool on2: false; text: "Aa"; on: on2; tip: "Match case"; onClicked: { on2 = !on2; win.refind() } }
                Seg { id: matchWord; property bool on2: false; text: "W"; on: on2; tip: "Whole words"; onClicked: { on2 = !on2; win.refind() } }
                Seg { id: matchRe; property bool on2: false; text: ".*"; on: on2; tip: "Pattern"; onClicked: { on2 = !on2; win.refind() } }
                Label { width: 48; horizontalAlignment: Text.AlignHCenter; anchors.verticalCenter: parent.verticalCenter; font.pixelSize: 11; secondary: true
                    text: findBox.text ? (win.matches.length ? (win.matchAt + 1) + "/" + win.matches.length : "none") : "" }
                Seg { icon: "up"; tip: "Previous (Shift+Enter)"; onClicked: win.step(-1) }
                Seg { icon: "down"; tip: "Next (Enter)"; onClicked: win.step(1) } }
            Row { visible: win.replacing; x: 8; y: 46; spacing: 6
                Rectangle { width: 190; height: 30; radius: 8; color: Theme.t.capsule; border.width: 1; border.color: replaceBox.activeFocus ? Theme.t.accent : Theme.t.capsule_border
                    TextInput { id: replaceBox; x: 8; width: parent.width - 16; anchors.verticalCenter: parent.verticalCenter; color: Theme.t.text; font.pixelSize: 13; clip: true; selectByMouse: true
                        Keys.onReturnPressed: win.replaceOne()
                        Text { visible: !replaceBox.text; text: "Replace with"; color: Theme.t.text_secondary; font: replaceBox.font } } }
                Btn { text: "Replace"; onClicked: win.replaceOne() }
                Btn { text: "All"; onClicked: win.replaceEvery() } } }

        // nothing open
        Column { visible: Backend.tabs.length === 0; anchors.centerIn: parent; spacing: 14; width: 420
            Rectangle { anchors.horizontalCenter: parent.horizontalCenter; width: 76; height: 76; radius: 22; color: Theme.t.accent
                Text { anchors.centerIn: parent; text: "{ }"; color: Theme.t.onAccent; font.family: win.mono; font.pixelSize: 28; font.bold: true } }
            Label { anchors.horizontalCenter: parent.horizontalCenter; text: Backend.root ? Backend.rootName : "Code"; font.pixelSize: 26; font.weight: Font.Bold }
            Label { width: parent.width; horizontalAlignment: Text.AlignHCenter; wrapMode: Text.WordWrap; secondary: true
                text: Backend.root ? "Pick a file on the left, or press Ctrl+P and type part of its name." : "Open a project folder to start. Code reads its files, its Git history and speaks to your language's tools." }
            Row { anchors.horizontalCenter: parent.horizontalCenter; spacing: 8
                Btn { visible: !Backend.root; primary: true; text: "Open Folder…"; onClicked: { win.browseAt = Backend.home; win.ask("open") } }
                Btn { text: "New File"; onClicked: Backend.root ? win.ask("new", { folder: Backend.root, dir: false }) : Backend.newUntitled() } }
            Column { visible: !Backend.root && Backend.recent.length > 0; width: parent.width; spacing: 2; topPadding: 8
                Label { text: "RECENT"; font.pixelSize: 10; font.weight: Font.Bold; font.letterSpacing: 1.2; secondary: true }
                Repeater { model: Backend.recent.slice(0, 6)
                    Pressable { required property var modelData; width: parent.width; height: 34; radius: 9; color: hovered ? Theme.t.hover : "transparent"; onClicked: Backend.openFolder(modelData.path)
                        Label { x: 10; anchors.verticalCenter: parent.verticalCenter; text: modelData.name; font.weight: Font.DemiBold }
                        Label { anchors { right: parent.right; rightMargin: 10; verticalCenter: parent.verticalCenter } text: modelData.where; secondary: true; font.pixelSize: 11 } } } }
            Grid { anchors.horizontalCenter: parent.horizontalCenter; columns: 2; columnSpacing: 18; rowSpacing: 6; topPadding: 10
                Repeater { model: ["Ctrl+P", "Go to a file", "Ctrl+Shift+P", "Every command", "Ctrl+Shift+F", "Search the project", "Ctrl+`", "The terminal", "F5", "Run"]
                    Label { required property string modelData; required property int index; text: modelData; font.pixelSize: 12; font.family: index % 2 === 0 ? win.mono : Theme.t.font
                        color: index % 2 === 0 ? Theme.t.accent : Theme.t.text_secondary } } } }
    }

    // ================================================================ the terminal
    Rectangle { visible: win.split; z: 4; x: slab.x + slab.width / 2 - 1; y: slab.y + 8; width: 2; height: slab.height - 16; radius: 1; color: Theme.t.islandLine }
    // the debugger's controls: in the bottom panel's header, or floating at the foot of the editor when the panel is closed
    component DebugButtons: Row { spacing: 2
        Rectangle { width: 8; height: 8; radius: 4; anchors.verticalCenter: parent.verticalCenter; color: win.dbg.state === "stopped" ? "#F5B83D" : "#30A46C" }
        Label { text: win.dbg.state === "stopped" ? "Paused" : win.dbg.state === "starting" ? "Starting…" : "Running"; font.pixelSize: 11; leftPadding: 4; rightPadding: 6; anchors.verticalCenter: parent.verticalCenter }
        Seg { icon: win.dbg.state === "stopped" ? "play" : "pause"; tip: win.dbg.state === "stopped" ? "Continue (F5)" : "Pause (F6)"; onClicked: win.dbg.state === "stopped" ? win.dbg.resume() : win.dbg.pause() }
        Seg { icon: "next"; tip: "Step over (F10)"; enabled: win.dbg.state === "stopped"; opacity: enabled ? 1 : 0.4; onClicked: win.dbg.stepOver() }
        Seg { icon: "down"; tip: "Step into (F11)"; enabled: win.dbg.state === "stopped"; opacity: enabled ? 1 : 0.4; onClicked: win.dbg.stepIn() }
        Seg { icon: "up"; tip: "Step out (Shift+F11)"; enabled: win.dbg.state === "stopped"; opacity: enabled ? 1 : 0.4; onClicked: win.dbg.stepOut() }
        Seg { icon: "refresh"; tip: "Restart"; onClicked: win.dbg.restart() }
        Seg { icon: "stop"; tip: "Stop (Shift+F5)"; danger: true; onClicked: win.dbg.stop() } }
    Rectangle { id: dbgBar; objectName: "dbgBar"; visible: win.dbg.active && !win.term; z: 9; y: slab.y + slab.height - height - 12; x: slab.x + (slab.width - width) / 2; height: 40; width: dbgFloat.width + 14; radius: 16
        color: Theme.t.island; border.width: 1; border.color: Theme.t.islandLine
        DebugButtons { id: dbgFloat; x: 7; anchors.verticalCenter: parent.verticalCenter } }
    Rectangle { id: termBox; objectName: "termBox"; visible: win.term; x: slab.x; width: slab.width; height: Math.min(280, win.height * 0.34); y: slab.y + slab.height + 10; radius: 16
        color: Theme.t.dark ? "#0B0D10" : "#F7F8FA"; border.width: 1; border.color: Theme.t.islandLine; clip: true
        property var sh: win.term && win.bottom === "terminal" ? Backend.terminal : null
        Row { x: 8; y: 6; spacing: 2; z: 3
            Seg { text: "Terminal"; on: win.bottom === "terminal"; onClicked: { win.bottom = "terminal"; Qt.callLater(function () { termKeys.forceActiveFocus() }) } }
            Seg { text: "Debug" + (win.dbg.active ? " ·" : ""); on: win.bottom === "debug"; onClicked: win.bottom = "debug" } }
        DebugButtons { objectName: "dbgDock"; visible: win.dbg.active; z: 3; y: 6; height: 32; anchors.horizontalCenter: parent.horizontalCenter }
        // ---- the debugger: where it stopped, what things hold, and a console
        Item { id: dbgPanel; visible: win.bottom === "debug"; anchors { fill: parent; topMargin: 42; leftMargin: 10; rightMargin: 10; bottomMargin: 8 }
            Label { visible: !win.dbg.active && win.dbg.output.length === 0; anchors.centerIn: parent; secondary: true; width: 520; wrapMode: Text.WordWrap; horizontalAlignment: Text.AlignHCenter
                text: "Click beside a line number to set a breakpoint, then press F5. Python uses debugpy; C, C++, Rust and Go use GDB." }
            Column { id: stackCol; visible: win.dbg.active; width: parent.width * 0.28; height: parent.height; spacing: 4
                Label { text: "CALL STACK" + (win.dbg.reason ? "  ·  " + win.dbg.reason : ""); secondary: true; font.pixelSize: 10; font.weight: Font.DemiBold; width: parent.width; elide: Text.ElideRight }
                ListView { width: parent.width; height: parent.height - 20; clip: true; model: win.dbg.frames; boundsBehavior: Flickable.StopAtBounds
                    delegate: Pressable { required property var modelData; width: ListView.view.width; height: 24; radius: 6
                        color: win.dbg.frame === modelData.id ? Qt.alpha(Theme.t.accent, 0.2) : (hovered ? Theme.t.hover : "transparent")
                        onClicked: win.dbg.selectFrame(modelData.id)
                        Text { x: 6; anchors.verticalCenter: parent.verticalCenter; width: parent.width - 12; elide: Text.ElideRight; font.family: win.mono; font.pixelSize: 11; color: modelData.file ? Theme.t.text : Theme.t.text_secondary
                            text: modelData.name + "   " + modelData.short + (modelData.file ? ":" + (modelData.line + 1) : "") } } } }
            Column { visible: win.dbg.active; x: stackCol.width + 12; width: parent.width * 0.36; height: parent.height; spacing: 4
                Label { text: "VARIABLES"; secondary: true; font.pixelSize: 10; font.weight: Font.DemiBold }
                ListView { width: parent.width; height: parent.height - 20; clip: true; model: win.dbg.variables; boundsBehavior: Flickable.StopAtBounds
                    delegate: Item { required property var modelData; width: ListView.view.width; height: 22
                        Text { x: modelData.depth * 14; width: 12; anchors.verticalCenter: parent.verticalCenter; text: modelData.expandable ? (modelData.open ? "▾" : "▸") : ""; color: Theme.t.text_secondary; font.pixelSize: 11 }
                        Text { x: modelData.depth * 14 + 14; width: parent.width - x; anchors.verticalCenter: parent.verticalCenter; elide: Text.ElideRight; font.family: win.mono; font.pixelSize: 11; textFormat: Text.PlainText
                            color: modelData.scope ? Theme.t.text_secondary : Theme.t.text; font.weight: modelData.scope ? Font.DemiBold : Font.Normal
                            text: modelData.scope ? modelData.name : modelData.name + " = " + modelData.value + (modelData.type ? "   " + modelData.type : "") }
                        MouseArea { anchors.fill: parent; enabled: modelData.expandable; onClicked: win.dbg.expand(modelData.ref) } } } }
            Column { x: win.dbg.active ? stackCol.width + 12 + parent.width * 0.36 + 12 : 0; width: parent.width - x; height: parent.height; spacing: 4
                visible: win.dbg.active || win.dbg.output.length > 0
                Row { width: parent.width; spacing: 6
                    Label { text: "CONSOLE"; secondary: true; font.pixelSize: 10; font.weight: Font.DemiBold; anchors.verticalCenter: parent.verticalCenter }
                    Label { text: "Clear"; color: Theme.t.accent; font.pixelSize: 10; anchors.verticalCenter: parent.verticalCenter; MouseArea { anchors.fill: parent; onClicked: win.dbg.clearConsole() } } }
                ListView { id: dcon; width: parent.width; height: parent.height - 52; clip: true; model: win.dbg.output; boundsBehavior: Flickable.StopAtBounds; onCountChanged: positionViewAtEnd()
                    delegate: Text { required property var modelData; width: dcon.width; wrapMode: Text.WrapAnywhere; font.family: win.mono; font.pixelSize: 11; textFormat: Text.PlainText; text: modelData.text
                        color: ({ error: win.delInk, info: Theme.t.text_secondary, input: Theme.t.accent, result: win.addInk })[modelData.kind] || Theme.t.text } }
                TextBox { width: parent.width; mono: true; placeholder: win.dbg.state === "stopped" ? "Type an expression to work it out here" : "The console answers while the program is paused"
                    onAccepted: { win.dbg.evaluate(text); text = "" } } } }
        Label { visible: !termBox.sh && win.bottom === "terminal"; anchors.centerIn: parent; secondary: true; text: demo ? "The terminal opens here (Ctrl+`)." : "The terminal needs the “pyte” library." }
        TextMetrics { id: tcell; font: tprobe.font; text: "MMMMMMMMMM" }
        Text { id: tprobe; visible: false; font.family: termBox.sh ? termBox.sh.font : win.mono; font.pixelSize: 13; text: "M" }
        ListView { id: tscreen; visible: win.bottom === "terminal"; anchors { fill: parent; margins: 10; leftMargin: 14; topMargin: 42 } clip: true; model: termBox.sh ? termBox.sh.lines : []; boundsBehavior: Flickable.StopAtBounds
            onWidthChanged: trefit.restart(); onHeightChanged: trefit.restart(); onCountChanged: positionViewAtEnd()
            delegate: Text { required property string modelData; width: tscreen.width; height: tprobe.height; textFormat: Text.RichText; text: modelData; font: tprobe.font; color: Theme.t.text; renderType: Text.NativeRendering }
            MouseArea { anchors.fill: parent; acceptedButtons: Qt.LeftButton | Qt.MiddleButton; onClicked: function (m) { termKeys.forceActiveFocus(); if (m.button === Qt.MiddleButton && termBox.sh) termBox.sh.paste() } } }
        Timer { id: trefit; interval: 80; onTriggered: if (termBox.sh) termBox.sh.fit(Math.floor(tscreen.width / (tcell.advanceWidth / 10)), Math.floor(tscreen.height / tprobe.height)) }
        onShChanged: trefit.restart()
        Item { id: termKeys; focus: false
            Keys.onPressed: function (e) {
                if (!termBox.sh) return
                if ((e.modifiers & Qt.ControlModifier) && e.key === Qt.Key_QuoteLeft) { win.toggleTerm(); e.accepted = true; return }
                if ((e.modifiers & Qt.ControlModifier) && (e.modifiers & Qt.ShiftModifier)) { if (e.key === Qt.Key_V) termBox.sh.paste(); else if (e.key === Qt.Key_C) termBox.sh.copyAll(); e.accepted = true; return }
                termBox.sh.key(e.key, e.modifiers, e.text); e.accepted = true } }
        Rectangle { anchors { right: parent.right; top: parent.top; margins: 8 } width: 26; height: 26; radius: 13; color: closeTerm.containsMouse ? Theme.t.hover : "transparent"
            Glyph { anchors.centerIn: parent; name: "x"; size: 11 }
            MouseArea { id: closeTerm; anchors.fill: parent; hoverEnabled: true; onClicked: win.toggleTerm() } } }

    // ================================================================ the status line
    Item { id: statusBar; objectName: "statusBar"; x: slab.x; width: slab.width; y: parent.height - 38; height: 28
        Row { x: 6; spacing: 14; anchors.verticalCenter: parent.verticalCenter
            Pressable { visible: Backend.isGit; width: brRow.width + 12; height: 24; radius: 12; color: hovered ? Theme.t.hover : "transparent"; onClicked: win.showPanel("git")
                Row { id: brRow; x: 6; spacing: 5; anchors.verticalCenter: parent.verticalCenter
                    Glyph { name: "route"; size: 12; anchors.verticalCenter: parent.verticalCenter }
                    Label { text: Backend.branch + (Backend.changes.length ? " · " + Backend.changes.length + " changed" : ""); font.pixelSize: 11 } } }
            Pressable { width: prRow.width + 12; height: 24; radius: 12; color: hovered ? Theme.t.hover : "transparent"; onClicked: win.showPanel("problems")
                Row { id: prRow; x: 6; spacing: 5; anchors.verticalCenter: parent.verticalCenter
                    Rectangle { width: 7; height: 7; radius: 4; anchors.verticalCenter: parent.verticalCenter; color: Backend.problems.length ? win.delInk : win.addInk }
                    Label { text: Backend.problems.length ? Backend.problems.length + (Backend.problems.length === 1 ? " problem" : " problems") : "No problems"; font.pixelSize: 11 } } }
            Label { visible: Backend.busy !== ""; anchors.verticalCenter: parent.verticalCenter; text: Backend.busy + "…"; font.pixelSize: 11; secondary: true } }
        Row { visible: !!win.tab; anchors { right: parent.right; rightMargin: 6; verticalCenter: parent.verticalCenter } spacing: 16
            Label { text: "Ln " + win.curLine + ", Col " + win.curCol; font.pixelSize: 11; secondary: true }
            Label { text: Backend.status.indent || ""; font.pixelSize: 11; secondary: true }
            Label { text: Backend.status.encoding || ""; font.pixelSize: 11; secondary: true }
            Label { text: Backend.status.eol || ""; font.pixelSize: 11; secondary: true }
            Pressable { width: wrapL.width + 10; height: 22; radius: 11; color: hovered ? Theme.t.hover : "transparent"; onClicked: Backend.setWrap(!Backend.wrap)
                Label { id: wrapL; anchors.centerIn: parent; text: Backend.wrap ? "Wrap" : "No wrap"; font.pixelSize: 11; secondary: true } }
            Row { spacing: 5
                Rectangle { width: 8; height: 8; radius: 4; anchors.verticalCenter: parent.verticalCenter; color: win.tab ? win.langInk(win.tab.lang) : "transparent" }
                Label { text: (Backend.status.lang || "") + (Backend.status.server ? "  ·  " + Backend.status.server : ""); font.pixelSize: 11; font.weight: Font.DemiBold } } } }
}
