import QtQuick

// Files, "places island": folders fill the window, lit from the island of places at the bottom.
// Above the places sits one island for what is going on: drives plugged in, what is selected, what is waiting to be pasted.
GlassWindow {
    id: win
    title: "Files"; glow: "bottom"
    property string filter: ""
    property var sel: []                      // paths that are selected
    property int cursor: -1                   // where the keyboard is, as a place in `shown`
    property int anchor: -1                   // where a Shift selection started
    property var menu: null                   // { x, y, items: [{ text, icon, act, danger, line, tick }] }
    property var sheet: null                  // { kind: "rename" | "goto" | "unlock" | "details" | "clash" | "sure" | "apps", ... }
    property string notice: ""
    property bool bad: false
    property string typed: ""
    property string lastPath: ""
    property real scrollY: 0                  // where the view is scrolled to, kept when the folder refreshes itself
    property var band: null                   // the rectangle being dragged out over empty space, in `area`
    property int appAt: 0
    property bool appAlways: false
    property bool inside: false               // a subfolder search also reads inside text files
    readonly property bool tabbed: Backend.tabs.length > 1
    property var shown: Backend.finding !== "" ? Backend.entries : Backend.entries.filter(function (e) { return e.name.toLowerCase().indexOf(filter.toLowerCase()) >= 0 })
    readonly property bool trash: Backend.inTrash
    readonly property bool deep: Backend.finding !== ""
    readonly property int cols: Math.max(1, Math.floor(gridView.width / 124))
    readonly property var view: Backend.grid ? gridView : listView
    readonly property color folderTint: Qt.rgba(tintColor.r, tintColor.g, tintColor.b, 0.22)
    readonly property color pickTint: Qt.rgba(tintColor.r, tintColor.g, tintColor.b, 0.26)
    readonly property var sortNames: ({ name: "Name", date: "Date", size: "Size", kind: "Kind" })

    function say(msg, wrong) { notice = msg; bad = wrong; hide.interval = !wrong && msg === Backend.undoNote ? 7000 : 4500; hide.restart() }
    Connections { target: Backend
        function onFailed(msg) { win.say(msg, true) }
        function onSaid(msg) { win.say(msg, false) }
        function onNetAsk(what) { passIn.text = ""; win.sheet = { kind: what.kind, address: what.address, needUser: !!what.needUser, name: what.user || "", again: !!what.again,
                                                                   why: what.again ? "That wasn't accepted. Try again." : "", message: what.message || "", choices: what.choices || [] } }
        function onChanged() {
            win.menu = null; win.typed = ""
            if (Backend.tab + "|" + Backend.path !== win.lastPath) {          // somewhere new: start clean, at the top
                win.lastPath = Backend.tab + "|" + Backend.path; win.sel = []; win.cursor = -1; win.anchor = -1; win.scrollY = 0; if (search.text !== "") search.text = ""
            } else {                                      // the same folder, refreshed: keep what is still here selected
                var here = {}; Backend.entries.forEach(function (e) { here[e.path] = true })
                win.sel = win.sel.filter(function (p) { return here[p] })
                if (win.cursor >= win.shown.length) win.cursor = win.shown.length - 1
            }
            Qt.callLater(win.scrollTo, win.scrollY) } }
    Timer { id: hide; interval: 4500; onTriggered: win.notice = "" }
    Timer { id: typing; interval: 900; onTriggered: win.typed = "" }
    Timer { interval: 3000; running: true; repeat: true; onTriggered: Backend.refreshDrives() }
    Component.onCompleted: { lastPath = Backend.tab + "|" + Backend.path; pickStart() }
    function pickStart() { if (Backend.startPick !== "") { var i = place(Backend.startPick); if (i >= 0) pick(i, false, false) } }

    // ---------------- scrolling (the wheel or the keyboard: dragging is for selecting and for moving files)
    function scrollTo(y) {
        var v = view, low = Backend.grid ? -10 : 0, high = Math.max(low, v.contentHeight - v.height + (Backend.grid ? 0 : 0))
        scrollY = Math.max(low, Math.min(high, y)); v.contentY = scrollY }
    function reveal(i) { view.positionViewAtIndex(i, Backend.grid ? GridView.Contain : ListView.Contain); scrollY = view.contentY }

    // ---------------- selecting
    function nameGoesOn(start) { if (start === " ") return false; for (var i = 0; i < shown.length; i++) if (shown[i].name.toLowerCase().indexOf(start) === 0) return true; return false }
    function isSel(path) { return sel.indexOf(path) >= 0 }
    function place(path) { for (var i = 0; i < shown.length; i++) if (shown[i].path === path) return i; return -1 }
    function clear() { sel = []; cursor = -1; anchor = -1 }
    function selectAll() { sel = shown.map(function (e) { return e.path }) }
    function pick(i, ctrl, shift) {           // a click, or the keyboard landing on item i
        if (i < 0 || i >= shown.length) return
        var path = shown[i].path
        if (shift && anchor >= 0) {
            var a = Math.min(anchor, i), b = Math.max(anchor, i), out = []
            for (var k = a; k <= b; k++) out.push(shown[k].path)
            sel = out
        } else if (ctrl) {
            var copy = sel.slice(), at = copy.indexOf(path)
            if (at >= 0) copy.splice(at, 1); else copy.push(path)
            sel = copy; anchor = i
        } else { sel = [path]; anchor = i }
        cursor = i; reveal(i)
    }
    function step(by, shift) {
        if (shown.length === 0) return
        var i = cursor < 0 ? (by >= shown.length ? shown.length - 1 : 0) : Math.max(0, Math.min(shown.length - 1, cursor + by))
        if (shift && anchor < 0) anchor = cursor < 0 ? 0 : cursor
        pick(i, false, shift)
    }
    function bandPick(r, keep) {              // everything the dragged-out rectangle touches
        var out = keep.slice(), i, x, y
        for (i = 0; i < shown.length; i++) {
            var hit
            if (Backend.grid) { x = gridView.x + (i % cols) * 124; y = gridView.y + Math.floor(i / cols) * 124 - gridView.contentY
                hit = x < r.x + r.width && x + 116 > r.x && y < r.y + r.height && y + 116 > r.y }
            else { y = listSheet.y + listView.y + i * 34 - listView.contentY; hit = listSheet.x < r.x + r.width && listSheet.x + listSheet.width > r.x && y < r.y + r.height && y + 34 > r.y }
            if (hit && out.indexOf(shown[i].path) < 0) out.push(shown[i].path)
        }
        sel = out
    }
    function selBytes() { var n = 0, files = true; for (var i = 0; i < shown.length; i++) if (isSel(shown[i].path)) { if (shown[i].dir) files = false; n += shown[i].bytes } return files ? n : -1 }
    function human(n) { var u = ["B", "KB", "MB", "GB", "TB"], i = 0; while (n >= 1024 && i < 4) { n /= 1024; i++ } return (i < 2 ? Math.round(n) : n.toFixed(1)) + " " + u[i] }
    function entryOf(path) { var i = place(path); return i >= 0 ? shown[i] : null }

    // ---------------- doing
    function openSel() { if (sel.length === 1) Backend.open(sel[0]); else if (sel.length > 1 && !trash) for (var i = 0; i < sel.length && i < 12; i++) { var e = entryOf(sel[i]); if (e && !e.dir) Backend.open(sel[i]) } }
    function startRename() {
        if (trash || sel.length === 0) return
        if (sel.length > 1) { var first = entryOf(ordered()[0]); sheet = { kind: "renames", name: first ? first.name.replace(/\.[^.]*$/, "").replace(/[ _-]*\d+$/, "") : "", dir: true, why: "" }; return }
        var e = entryOf(sel[0]); if (e) sheet = { kind: "rename", path: e.path, name: e.name, dir: e.dir, why: "" } }
    function ordered() { return shown.filter(function (e) { return isSel(e.path) }).map(function (e) { return e.path }) }       // the selection, in the order shown
    function look(i) { if (i < 0 || i >= shown.length) return; pick(i, false, false); var k = Backend.peek(shown[i].path); if (k.name !== undefined) sheet = { kind: "peek", data: k } }
    function paste() { if (!Backend.clipCount || !Backend.canWrite) return; var c = Backend.pasteClashes(); if (c.length) sheet = { kind: "clash", names: c, op: null }; else Backend.paste("keep") }
    function bin() { if (sel.length === 0) return; if (trash) sheet = { kind: "sure", what: "forever", paths: sel.slice() }; else Backend.trash(sel) }
    function nameNew(p) { if (p !== "") { search.text = ""; var i = place(p); if (i >= 0) { pick(i, false, false); startRename() } } }
    function openWith() { if (sel.length !== 1) return; var apps = Backend.appsFor(sel[0]); appAt = 0; appAlways = false; sheet = { kind: "apps", path: sel[0], apps: apps } }
    function dropped(d, dest) {               // files let go of over a folder, a place, a drive, the Trash or the open folder
        if (!d.hasUrls) return
        var things = []; for (var i = 0; i < d.urls.length; i++) things.push(String(d.urls[i]))
        var copy = dest !== "trash:" && (d.proposedAction === Qt.CopyAction || !Backend.dropMoves(things, dest))
        d.accept(Qt.CopyAction)                // Files does the work itself, so the app it came from must not also move anything
        var c = Backend.dropClashes(things, dest)
        if (c.length) sheet = { kind: "clash", names: c, op: { things: things, dest: dest, copy: copy } }
        else Backend.drop(things, dest, copy, "keep")
    }
    function finishClash(mode) { var op = sheet.op; sheet = null; keys.forceActiveFocus(); if (op) Backend.drop(op.things, op.dest, op.copy, mode); else Backend.paste(mode) }
    function startDrag(tile) {                // drag the selection: onto a folder here, or out to another app
        dragger.Drag.mimeData = { "text/uri-list": Backend.urls(sel).join("\r\n") + "\r\n" }
        tile.grabToImage(function (shot) { dragger.Drag.imageSource = shot.url; dragger.Drag.startDrag(Qt.CopyAction | Qt.MoveAction) })
    }
    // the top bar's menu (File, Edit, View, Go): each entry, and its key, does what the window's own controls do
    function newFolder() { run("folder") }
    function newTab() { Backend.newTab("") }
    function openSelected() { openSel() }
    function openInTab() { if (sel.length === 1) Backend.newTab(sel[0]) }
    function trashSelected() { bin() }
    function find() { search.focusInput() }
    function setGrid(on) { if (Backend.grid !== (String(on) === "true")) Backend.toggleGrid() }
    function toggleHidden() { Backend.toggleHidden() }
    function goBack() { if (Backend.canBack) Backend.back() }
    function goForward() { if (Backend.canForward) Backend.forward() }
    function goUp() { if (Backend.canUp) Backend.up() }
    function goPlace(name) {
        var want = String(name).toLowerCase()
        for (var i = 0; i < Backend.places.length; i++) {
            var pl = Backend.places[i]
            if (pl.name.toLowerCase() === want || pl.path.toLowerCase().split("/").pop() === want) { Backend.open(pl.path); return }
        }
        if (want === "home" && Backend.places.length) Backend.open(Backend.places[0].path)
    }
    function run(act) {
        menu = null
        if (act === "open") openSel()
        else if (act === "with") openWith()
        else if (act === "where") { var p = sel[0]; Backend.showIn(p); var i = place(p); if (i >= 0) pick(i, false, false) }
        else if (act === "cut") Backend.cut(sel)
        else if (act === "copy") Backend.copy(sel)
        else if (act === "paste") paste()
        else if (act === "duplicate") Backend.duplicate(sel)
        else if (act === "rename") startRename()
        else if (act === "zip") Backend.compress(sel)
        else if (act === "mail") Backend.sendByMail(sel)
        else if (act === "phone") Backend.sendToPhone(sel)
        else if (act === "print") Backend.printFile(sel[0])
        else if (act === "translate") Backend.translateFile(sel[0])
        else if (act === "details") sheet = { kind: "details", data: Backend.details(sel), path: sel.length === 1 ? sel[0] : "", acc: sel.length === 1 ? Backend.access(sel[0]) : ({}) }
        else if (act === "trash") bin()
        else if (act === "restore") Backend.restore(sel)
        else if (act === "folder") nameNew(Backend.newFolder())
        else if (act === "file") nameNew(Backend.newTextFile())
        else if (act === "all") selectAll()
        else if (act === "hidden") Backend.toggleHidden()
        else if (act === "terminal") Backend.openTerminal()
        else if (act === "undo") Backend.undo()
        else if (act === "redo") Backend.redo()
        else if (act === "look") look(place(sel[0]))
        else if (act === "pin") Backend.togglePin(sel.length === 1 && entryOf(sel[0]) && entryOf(sel[0]).dir ? sel[0] : "")
        else if (act === "tab") Backend.newTab(sel.length === 1 ? sel[0] : "")
        else if (act === "server") { Backend.scanNetwork(); sheet = { kind: "server", name: "", why: "" } }
        else if (act === "goto") sheet = { kind: "goto", name: trash || deep ? "" : Backend.path, why: "" }
        else if (act === "empty") sheet = { kind: "sure", what: "empty", paths: [] }
        else if (act.indexOf("sort:") === 0) Backend.sort(act.slice(5))
    }
    function itemMenu() {
        if (trash) return [{ text: "Put Back", icon: "back", act: "restore" }, { text: "Details", icon: "info", act: "details" }, { text: "Delete for Good", icon: "trash", act: "trash", danger: true, line: true }]
        var one = sel.length === 1, e = one ? entryOf(sel[0]) : null, m = [{ text: one ? "Open" : "Open " + sel.length + " Items", icon: "forward", act: "open" }]
        if (e && !e.dir) m.push({ text: "Open With…", icon: "apps", act: "with" })
        if (e && e.dir) m.push({ text: "Open in New Tab", icon: "plus", act: "tab" })
        if (one && deep) m.push({ text: "Show in Its Folder", icon: "folder", act: "where" })
        m.push({ text: "Cut", icon: "edit", act: "cut", line: true }); m.push({ text: "Copy", icon: "doc", act: "copy" })
        if (!deep) m.push({ text: "Duplicate", icon: "plus", act: "duplicate" })
        m.push({ text: one ? "Rename" : "Rename " + sel.length + " Items…", icon: "edit", act: "rename" })
        m.push({ text: "Compress", icon: "download", act: "zip" })
        if (sel.length <= 30 && !Backend.anyFolders(sel)) { m.push({ text: "Send by Mail", icon: "mail", act: "mail" }); m.push({ text: "Send to Phone", icon: "phone", act: "phone" }) }
        if (one && e && !e.dir && /\.(pdf|png|jpe?g|gif|txt|tiff?|bmp)$/i.test(sel[0])) m.push({ text: "Print…", icon: "printer", act: "print" })
        if (one && e && !e.dir && /\.(txt|md|text)$/i.test(sel[0])) m.push({ text: "Translate…", icon: "translate", act: "translate" })
        if (one) m.push({ text: "Quick Look", icon: "search", act: "look" })
        if (e && e.dir) m.push({ text: "Pin", icon: "star", act: "pin" })
        m.push({ text: "Details", icon: "info", act: "details" }); m.push({ text: "Move to Trash", icon: "trash", act: "trash", danger: true, line: true })
        return m
    }
    function spaceMenu() {
        if (trash) return [{ text: "Select All", icon: "grid", act: "all" }, { text: "Empty the Trash", icon: "trash", act: "empty", danger: true, line: true }]
        var m = []
        if (Backend.canUndo) m.push({ text: Backend.undoText, icon: "back", act: "undo" })
        if (Backend.canRedo) m.push({ text: Backend.redoText, icon: "forward", act: "redo" })
        if (deep) { m.push({ text: "Select All", icon: "grid", act: "all" }); return m }
        if (Backend.clipCount) m.push({ text: "Paste " + Backend.clipCount + (Backend.clipCount === 1 ? " Item" : " Items"), icon: "download", act: "paste" })
        m.push({ text: "New Folder", icon: "plus", act: "folder", line: m.length > 0 }); m.push({ text: "New Text File", icon: "doc", act: "file" }); m.push({ text: "Select All", icon: "grid", act: "all" })
        m.push({ text: "Go to a Folder…", icon: "forward", act: "goto", line: true }); m.push({ text: "Connect to a Server…", icon: "wifi", act: "server" }); m.push({ text: "Open in Terminal", icon: "cpu", act: "terminal" })
        m.push({ text: Backend.pinned ? "Unpin This Folder" : "Pin This Folder", icon: "star", act: "pin" }); m.push({ text: "Folder Details", icon: "info", act: "details" })
        m.push({ text: "Show Hidden Files", icon: "", act: "hidden", tick: Backend.showHidden, line: true })
        return m
    }
    function sortMenu() {
        var m = []; for (var k in sortNames) m.push({ text: (trash && k === "date" ? "Date Deleted" : sortNames[k]) + (Backend.sortBy === k ? (Backend.sortDown ? "  ↓" : "  ↑") : ""), icon: "", act: "sort:" + k, tick: Backend.sortBy === k })
        m.push({ text: "Show Hidden Files", icon: "", act: "hidden", tick: Backend.showHidden, line: true })
        return m
    }
    function popup(from, mx, my, items) { var p = from.mapToItem(stage, mx, my); menu = { x: p.x, y: p.y, items: items } }

    component DropSpot: DropArea {            // somewhere files can be let go of; `dest` is a folder's path or "trash:"
        property string dest: ""
        property bool on: true
        anchors.fill: parent; enabled: on && dest !== ""
        onDropped: function (d) { win.dropped(d, dest) }
        Rectangle { anchors.fill: parent; radius: parent.parent.radius || 11; visible: parent.containsDrag; color: "transparent"; border.width: 2; border.color: Theme.t.accent }
    }

    islands: [
        Island {   // where you are: back, forward, up, then the path
            anchors.horizontalCenter: parent.horizontalCenter; y: 12
            Seg { icon: "back"; tip: "Back"; opacity: Backend.canBack ? 1 : 0.4; onClicked: Backend.back() }
            Seg { icon: "forward"; tip: "Forward"; opacity: Backend.canForward ? 1 : 0.4; onClicked: Backend.forward() }
            Seg { icon: "up"; tip: "Up one folder"; opacity: Backend.canUp ? 1 : 0.4; onClicked: Backend.up() }
            IslandGap {}
            Repeater { model: Backend.crumbs.slice(win.deep ? -1 : -3)
                Row { required property var modelData; required property int index; height: parent.height; spacing: 2
                    Label { visible: index > 0; text: "›"; secondary: true; anchors.verticalCenter: parent.verticalCenter }
                    Seg { text: modelData.name.length > 20 ? modelData.name.slice(0, 19) + "…" : modelData.name; onClicked: { var p = modelData.path; search.text = ""; Backend.open(p) }
                        DropSpot { dest: modelData.path; on: !win.trash && (win.deep || modelData.path !== Backend.path) } } } }
            Label { visible: win.deep; text: "›"; secondary: true; anchors.verticalCenter: parent.verticalCenter }
            Seg { visible: win.deep; text: "Results"; on: true; tip: "Back to the folder"; onClicked: search.text = "" }
            Seg { visible: win.deep; text: "Inside files"; on: win.inside; tip: win.inside ? "Also reading inside text files" : "Also look inside text files"
                onClicked: { win.inside = !win.inside; Backend.find(search.text, win.inside) } }
        },
        Island {
            anchors { right: parent.right; rightMargin: 12 } y: 12
            IslandField { id: search; width: 160; onTextChanged: { win.filter = text; if (win.deep && text !== Backend.finding) Backend.find("", false) }
                placeholder: win.trash ? "Search the Trash" : "Search this folder"
                onAccepted: { if (text !== "" && !win.trash) Backend.find(text, win.inside); keys.forceActiveFocus() } Keys.onEscapePressed: { text = ""; keys.forceActiveFocus() } }
            Seg { icon: Backend.grid ? "list" : "grid"; tip: Backend.grid ? "Show as list" : "Show as grid"; onClicked: { win.scrollY = 0; Backend.toggleGrid() } }
            Seg { id: sortSeg; text: (win.trash && Backend.sortBy === "date" ? "Deleted" : win.sortNames[Backend.sortBy]) + (Backend.sortDown ? " ↓" : " ↑")
                onClicked: win.menu ? win.menu = null : win.popup(sortSeg, sortSeg.width - 200, sortSeg.height + 12, win.sortMenu()) }
            Seg { visible: !win.trash; icon: "plus"; tip: "New folder"; opacity: Backend.canWrite ? 1 : 0.4; onClicked: win.run("folder") }
            Seg { visible: win.trash; text: "Empty"; icon: "trash"; danger: true; opacity: Backend.trashCount ? 1 : 0.4; onClicked: if (Backend.trashCount) win.run("empty") }
        },
        Island {   // tabs: only once there is more than one
            visible: win.tabbed; objectName: "tabs"
            anchors.horizontalCenter: parent.horizontalCenter; y: 58
            Repeater { model: win.tabbed ? Backend.tabs : []
                Row { required property var modelData; required property int index; height: parent.height; spacing: 0
                    Seg { text: modelData.name.length > 16 ? modelData.name.slice(0, 15) + "…" : modelData.name; icon: modelData.path === "trash:" ? "trash" : "folder"; on: index === Backend.tab; onClicked: Backend.selectTab(index)
                        DropSpot { dest: modelData.path; on: index !== Backend.tab } }
                    Seg { visible: index === Backend.tab; icon: "x"; tip: "Close this tab"; onClicked: Backend.closeTab(index) } } }
            Seg { icon: "plus"; tip: "New tab"; onClicked: Backend.newTab("") }
        },
        Island {   // places: the app's main island, and where its light comes from
            id: placesIsland
            anchors { horizontalCenter: parent.horizontalCenter; bottom: parent.bottom; bottomMargin: 14 }
            Repeater { model: Backend.places
                Seg { required property var modelData; icon: modelData.icon; text: modelData.name; on: Backend.path === modelData.path && !win.deep; onClicked: Backend.open(modelData.path)
                    DropSpot { dest: modelData.path } } }
            IslandGap {}
            Seg { icon: "trash"; text: Backend.trashCount ? "Trash · " + Backend.trashCount : "Trash"; on: win.trash; onClicked: Backend.open("trash:")
                DropSpot { dest: "trash:" } }
        },
        Island {   // what is going on: a job, drives, the selection, something to paste
            id: doing
            objectName: "doing"
            readonly property bool pasting: Backend.clipCount > 0 && !win.trash && !win.deep
            visible: Backend.busy || Backend.drives.length > 0 || win.sel.length > 0 || pasting
            anchors { horizontalCenter: parent.horizontalCenter; bottom: placesIsland.top; bottomMargin: 8 }
            Label { visible: Backend.busy; text: Backend.jobText; font.pixelSize: 12; leftPadding: 8; anchors.verticalCenter: parent.verticalCenter }
            Rectangle { visible: Backend.busy; width: 140; height: 6; radius: 3; color: Theme.t.group; anchors.verticalCenter: parent.verticalCenter
                Rectangle { width: parent.width * Backend.progress; height: parent.height; radius: 3; color: Theme.t.accent } }
            Seg { visible: Backend.busy; text: "Stop"; onClicked: Backend.stop() }
            Repeater { model: Backend.busy ? [] : Backend.drives
                Row { required property var modelData; height: parent.height; spacing: 0
                    Seg { icon: modelData.locked ? "user" : modelData.net ? "wifi" : "disc"; text: modelData.name; on: modelData.mounted && !win.trash && (Backend.path + "/").indexOf(modelData.path + "/") === 0
                        onClicked: modelData.locked ? win.sheet = { kind: "unlock", dev: modelData.dev, name: "", title: modelData.name, why: "" } : Backend.openDrive(modelData.dev)
                        DropSpot { dest: modelData.path; on: modelData.mounted } }
                    Seg { visible: modelData.mounted; icon: modelData.net ? "x" : "up"; tip: modelData.net ? "Disconnect" : "Eject, so it is safe to unplug"; tipAbove: true; onClicked: Backend.eject(modelData.dev) } } }
            IslandGap { visible: !Backend.busy && Backend.drives.length > 0 && (win.sel.length > 0 || doing.pasting) }
            Seg { visible: !Backend.busy && win.sel.length > 0 && !win.trash; text: "Cut"; onClicked: win.run("cut") }
            Seg { visible: !Backend.busy && win.sel.length > 0 && !win.trash; text: "Copy"; onClicked: win.run("copy") }
            Seg { visible: !Backend.busy && win.sel.length > 0 && !win.trash; text: "Rename"; onClicked: win.run("rename") }
            Seg { visible: !Backend.busy && win.sel.length > 0 && win.trash; text: "Put Back"; icon: "back"; onClicked: win.run("restore") }
            Seg { visible: !Backend.busy && win.sel.length > 0; text: "Details"; onClicked: win.run("details") }
            Seg { visible: !Backend.busy && win.sel.length > 0; text: win.trash ? "Delete for Good" : "Trash"; icon: "trash"; danger: true; onClicked: win.run("trash") }
            IslandGap { visible: !Backend.busy && win.sel.length > 0 && doing.pasting }
            Seg { visible: !Backend.busy && doing.pasting; on: true; opacity: Backend.canWrite ? 1 : 0.4
                text: (Backend.clipCut ? "Move " : "Paste ") + Backend.clipCount + (Backend.clipCount === 1 ? " item here" : " items here"); onClicked: win.paste() }
            Seg { visible: !Backend.busy && doing.pasting; icon: "x"; tip: "Forget what was copied"; tipAbove: true; onClicked: Backend.forget() }
        },
        Label {   // how many, how many of them are chosen, and the room left on the drive
            anchors { left: parent.left; leftMargin: 18; bottom: parent.bottom; bottomMargin: 26 } font.pixelSize: 12; secondary: true
            width: Math.max(60, placesIsland.x - 30); elide: Text.ElideRight
            text: win.sel.length ? win.sel.length + " of " + win.shown.length + " selected" + (win.selBytes() >= 0 ? " · " + win.human(win.selBytes()) : "")
                : win.deep ? (Backend.foundTooMany ? "First " : "") + win.shown.length + " found" + (Backend.stillFinding ? "…" : "")
                : win.filter !== "" && !win.trash ? win.shown.length + " here · Enter: subfolders"
                : win.shown.length + (win.shown.length === 1 ? " item" : " items") + (Backend.free !== "" && placesIsland.x > 190 ? " · " + Backend.free : "") },
        Rectangle {   // a line about what just happened (with Undo when it can be taken back), or what went wrong
            visible: win.notice !== ""; z: 15; anchors { horizontalCenter: parent.horizontalCenter; bottom: doing.visible ? doing.top : placesIsland.top; bottomMargin: 8 } height: 32; radius: 12
            width: Math.min(said.implicitWidth + 28 + (undoBtn.visible ? undoBtn.width + 6 : 0), parent.width - 60)
            color: Theme.t.menu_bg; border.width: 1; border.color: win.bad ? Theme.t.danger : Theme.t.menu_border
            Label { id: said; x: 14; width: parent.width - 28 - (undoBtn.visible ? undoBtn.width + 6 : 0); height: parent.height; verticalAlignment: Text.AlignVCenter; elide: Text.ElideRight; text: win.notice; font.pixelSize: 12; color: win.bad ? Theme.t.danger : Theme.t.text }
            Pressable { id: undoBtn; visible: !win.bad && Backend.canUndo && win.notice === Backend.undoNote; anchors { right: parent.right; rightMargin: 4; verticalCenter: parent.verticalCenter } width: ul.width + 18; height: 24; radius: 9
                onClicked: { win.notice = ""; Backend.undo() } Label { id: ul; anchors.centerIn: parent; text: "Undo"; font.pixelSize: 12; font.weight: Font.DemiBold; color: Theme.t.accent } } },

        Item {   // menus and questions sit above everything
            id: stage; anchors.fill: parent; z: 20
            MouseArea { anchors.fill: parent; visible: win.menu !== null; acceptedButtons: Qt.LeftButton | Qt.RightButton; onPressed: win.menu = null }
            Rectangle {
                visible: win.menu !== null; x: win.menu ? Math.max(8, Math.min(win.menu.x, parent.width - width - 8)) : 0; y: win.menu ? Math.max(8, Math.min(win.menu.y, parent.height - height - 8)) : 0
                width: 210; height: menuCol.height + 10; radius: 14; color: Theme.t.menu_bg; border.width: 1; border.color: Theme.t.menu_border
                Column { id: menuCol; x: 5; y: 5; width: parent.width - 10
                    Repeater { model: win.menu ? win.menu.items : []
                        Column { required property var modelData; width: menuCol.width
                            Item { visible: !!modelData.line; width: parent.width; height: 9; Rectangle { y: 4; x: 6; width: parent.width - 12; height: 1; color: Theme.t.separator } }
                            Pressable { width: parent.width; height: 30; radius: 9; onClicked: win.run(modelData.act)
                                Glyph { visible: modelData.icon !== ""; x: 8; anchors.verticalCenter: parent.verticalCenter; name: modelData.icon || "file"; size: 15; ink: modelData.danger ? Theme.t.danger : Theme.t.icon }
                                Label { visible: modelData.icon === "" && !!modelData.tick; x: 10; anchors.verticalCenter: parent.verticalCenter; text: "✓"; color: Theme.t.accent; font.weight: Font.Bold }
                                Label { x: 32; width: parent.width - 40; elide: Text.ElideRight; anchors.verticalCenter: parent.verticalCenter; text: modelData.text; color: modelData.danger ? Theme.t.danger : Theme.t.text } } } } } }

            // ---------------- questions: a name, a path, a password, the details, a name that is taken, an app, deleting for good
            Rectangle { visible: win.sheet !== null; anchors.fill: parent; radius: win.r; color: "#66000000"; MouseArea { anchors.fill: parent; acceptedButtons: Qt.AllButtons; onWheel: function (w) {}; onClicked: if (win.sheet && win.sheet.kind === "peek") win.sheet = null } }
            Rectangle {
                id: card; objectName: "card"
                anchors.centerIn: parent; width: 440; radius: 16; color: Theme.t.menu_bg; border.width: 1; border.color: Theme.t.menu_border
                readonly property string kind: win.sheet ? win.sheet.kind : ""
                readonly property bool typing: kind === "rename" || kind === "renames" || kind === "goto" || kind === "unlock" || kind === "server" || kind === "login"
                readonly property bool both: kind === "login" && win.sheet.needUser          // a name and a password
                readonly property var acc: kind === "details" && win.sheet.acc ? win.sheet.acc : ({})
                function share(others, locked, run) { var why = Backend.setAccess(win.sheet.path, others, locked, run); if (why !== "") win.say(why, true)
                    var s0 = win.sheet; win.sheet = { kind: "details", data: Backend.details([s0.path]), path: s0.path, acc: Backend.access(s0.path) } }
                visible: win.sheet !== null && kind !== "peek"
                height: kind === "details" ? 104 + detailCol.height + accCol.height : kind === "apps" ? 150 + appList.height : kind === "server" ? 176 + recent.height + near.height : kind === "goto" ? 176 + pinCol.height
                      : kind === "choice" ? 122 + asked.height : both ? 222 : typing ? 176 : 172
                function close() { var k = kind; win.sheet = null; nameIn.text = ""; passIn.text = ""; keys.forceActiveFocus(); if (k === "login" || k === "choice") Backend.netCancel() }
                function done() { win.sheet = null; nameIn.text = ""; passIn.text = ""; keys.forceActiveFocus() }
                function again(why) { var s = win.sheet; win.sheet = { kind: s.kind, path: s.path, dev: s.dev, title: s.title, name: s.kind === "unlock" ? "" : nameIn.text, dir: s.dir, why: why, again: true } }
                function accept() {
                    var why
                    if (kind === "rename") { why = Backend.rename(win.sheet.path, nameIn.text)
                        if (why === "") { var dir = win.sheet.path.slice(0, win.sheet.path.lastIndexOf("/") + 1), now = dir + nameIn.text.trim(); close(); var i = win.place(now); if (i >= 0) win.pick(i, false, false) } else again(why) }
                    else if (kind === "renames") { why = Backend.renameMany(win.ordered(), nameIn.text); if (why === "") done(); else again(why) }
                    else if (kind === "goto") { why = Backend.goTo(nameIn.text); if (why === "") close(); else again(why) }
                    else if (kind === "unlock") { why = Backend.unlock(win.sheet.dev, nameIn.text); if (why === "") close(); else again(why) }
                    else if (kind === "server") { var a = nameIn.text; if (a.trim() === "") return; done(); Backend.connectTo(a) }
                    else if (kind === "login") { var r = { user: both ? nameIn.text : "", password: both ? passIn.text : nameIn.text }; done(); Backend.netAnswer(r) }
                }
                Label { x: 22; y: 20; width: parent.width - 44; elide: Text.ElideMiddle; font.pixelSize: 16; font.weight: Font.DemiBold
                    text: card.kind === "rename" ? "Rename" : card.kind === "renames" ? "Rename " + win.sel.length + " items" : card.kind === "goto" ? "Go to a folder" : card.kind === "server" ? "Connect to a server" : card.kind === "login" ? "Sign in to " + win.sheet.address.split("://")[1].split("/")[0]
                        : card.kind === "choice" ? "Before connecting" : card.kind === "unlock" ? "Unlock “" + win.sheet.title + "”" : card.kind === "details" ? win.sheet.data.title
                        : card.kind === "apps" ? "Open with" : card.kind === "clash" ? (win.sheet.names.length === 1 ? "“" + win.sheet.names[0] + "” is already here" : win.sheet.names.length + " of these are already here")
                        : card.kind === "sure" ? (win.sheet.what === "empty" ? "Empty the Trash?" : "Delete " + (win.sheet.paths.length === 1 ? "this" : "these " + win.sheet.paths.length) + " for good?") : "" }
                Label { visible: card.kind === "clash" || card.kind === "sure"; x: 22; y: 50; width: parent.width - 44; wrapMode: Text.WordWrap; secondary: true
                    text: card.kind === "clash" ? "Keep both and the new one gets a number. Replace swaps files for the new ones; folders are joined together."
                                                : "This can't be undone." + (card.kind === "sure" && win.sheet.what === "empty" ? " Everything in the Trash, " + Backend.trashCount + (Backend.trashCount === 1 ? " item" : " items") + ", is deleted." : "") }
                Rectangle { visible: card.typing; x: 22; y: 56; width: parent.width - 44; height: 36; radius: 10; color: Theme.t.group; border.width: 1; border.color: nameIn.activeFocus ? Theme.t.accent : Theme.t.islandLine
                    TextInput { id: nameIn; objectName: "nameIn"; anchors { fill: parent; leftMargin: 12; rightMargin: 12 } verticalAlignment: TextInput.AlignVCenter; clip: true
                        echoMode: card.kind === "unlock" || (card.kind === "login" && !card.both) ? TextInput.Password : TextInput.Normal
                        KeyNavigation.tab: passIn
                        color: Theme.t.text; font.family: Theme.t.font; font.pixelSize: 14; selectionColor: Theme.t.accent; selectedTextColor: Theme.t.onAccent
                        onAccepted: card.both ? passIn.forceActiveFocus() : card.accept(); Keys.onEscapePressed: card.close()
                        Label { visible: !nameIn.text && card.kind !== "rename"; anchors.verticalCenter: parent.verticalCenter; secondary: true
                            text: card.kind === "unlock" ? "The drive's password" : card.kind === "server" ? "smb://computer/folder or sftp://server" : card.both ? "Name" : card.kind === "login" ? "Password" : "~/Music, /media or smb://computer/folder" } } }
                Rectangle { visible: card.both; x: 22; y: 100; width: parent.width - 44; height: 36; radius: 10; color: Theme.t.group; border.width: 1; border.color: passIn.activeFocus ? Theme.t.accent : Theme.t.islandLine
                    TextInput { id: passIn; objectName: "passIn"; anchors { fill: parent; leftMargin: 12; rightMargin: 12 } verticalAlignment: TextInput.AlignVCenter; clip: true; echoMode: TextInput.Password
                        color: Theme.t.text; font.family: Theme.t.font; font.pixelSize: 14; selectionColor: Theme.t.accent; selectedTextColor: Theme.t.onAccent
                        onAccepted: card.accept(); Keys.onEscapePressed: card.close(); KeyNavigation.backtab: nameIn
                        Label { visible: !passIn.text; anchors.verticalCenter: parent.verticalCenter; secondary: true; text: "Password" } } }
                Label { id: asked; visible: card.kind === "choice"; x: 22; y: 52; width: parent.width - 44; wrapMode: Text.Wrap; secondary: true; font.pixelSize: 12; text: card.kind === "choice" ? win.sheet.message : "" }
                Column { id: recent; visible: card.kind === "server"; x: 16; y: 122; width: parent.width - 32
                    Repeater { model: card.kind === "server" ? Backend.servers : []
                        Pressable { required property var modelData; width: recent.width; height: 30; radius: 9; onClicked: { card.done(); Backend.connectTo(modelData) }
                            Glyph { x: 8; anchors.verticalCenter: parent.verticalCenter; name: "wifi"; size: 15 }
                            Label { x: 32; width: parent.width - 70; elide: Text.ElideMiddle; anchors.verticalCenter: parent.verticalCenter; text: modelData; font.pixelSize: 12 }
                            Seg { anchors { right: parent.right; verticalCenter: parent.verticalCenter } icon: "x"; tip: "Forget this address"; onClicked: Backend.forgetServer(modelData) } } } }
                Label { visible: card.typing; x: 22; y: card.both ? 142 : 98; width: parent.width - 44; elide: Text.ElideRight; font.pixelSize: 12
                    text: card.typing ? (win.sheet.why || (card.kind === "unlock" || card.kind === "login" ? "The password isn't kept anywhere." : card.kind === "renames" ? "Each gets a number and keeps its ending: " + (nameIn.text.trim() || "Name") + " 1, " + (nameIn.text.trim() || "Name") + " 2…" : "")) : ""; color: card.typing && win.sheet.why && !win.sheet.hint ? Theme.t.danger : Theme.t.text_secondary }
                Column { id: detailCol; visible: card.kind === "details"; x: 22; y: 54; width: parent.width - 44; spacing: 0
                    Repeater { model: card.kind === "details" ? win.sheet.data.rows : []
                        Item { required property var modelData; width: detailCol.width; height: Math.max(26, val.height + 8)
                            Label { text: modelData[0]; secondary: true; font.pixelSize: 12; y: 4 }
                            Label { id: val; x: 120; y: 4; width: parent.width - 120; text: modelData[1]; wrapMode: Text.WrapAnywhere; font.pixelSize: 12 } } } }
                Column { id: accCol; visible: card.kind === "details" && card.acc.owner !== undefined; x: 22; y: 58 + detailCol.height; width: parent.width - 44; spacing: 4
                    Rectangle { width: parent.width; height: 1; color: Theme.t.separator }
                    Item { width: parent.width; height: 30; visible: !!card.acc.mine
                        Label { text: "Other people"; secondary: true; font.pixelSize: 12; anchors.verticalCenter: parent.verticalCenter }
                        Row { x: 120; anchors.verticalCenter: parent.verticalCenter; spacing: 2
                            Repeater { model: [["none", "No access"], ["open", "Can open"], ["change", "Can change"]]
                                Seg { required property var modelData; text: modelData[1]; on: card.acc.others === modelData[0]; onClicked: card.share(modelData[0], card.acc.locked, card.acc.run) } } } }
                    Item { width: parent.width; height: 30; visible: !!card.acc.mine
                        Label { text: "Protect"; secondary: true; font.pixelSize: 12; anchors.verticalCenter: parent.verticalCenter }
                        Row { x: 120; anchors.verticalCenter: parent.verticalCenter; spacing: 2
                            Seg { text: "Locked"; on: !!card.acc.locked; tip: "Nobody, you included, can change it until you unlock it"; onClicked: card.share(card.acc.others, !card.acc.locked, card.acc.run) }
                            Seg { visible: !card.acc.dir; text: "Run as a program"; on: !!card.acc.run; onClicked: card.share(card.acc.others, card.acc.locked, !card.acc.run) } } }
                    Label { visible: !card.acc.mine && card.acc.owner !== undefined && !win.trash; height: 26; verticalAlignment: Text.AlignVCenter; secondary: true; font.pixelSize: 12; text: "Sharing is set by its owner, " + (card.acc.owner || "") + "." } }
                Column { id: pinCol; visible: card.kind === "goto"; x: 16; y: 122; width: parent.width - 32
                    Repeater { model: card.kind === "goto" ? Backend.pins : []
                        Pressable { required property var modelData; width: pinCol.width; height: 30; radius: 9; onClicked: { card.done(); Backend.open(modelData.path) }
                            Glyph { x: 8; anchors.verticalCenter: parent.verticalCenter; name: "star"; size: 15; ink: Theme.t.accent }
                            Label { x: 32; anchors.verticalCenter: parent.verticalCenter; text: modelData.name; font.pixelSize: 12 }
                            Label { x: 170; width: parent.width - 210; elide: Text.ElideMiddle; anchors.verticalCenter: parent.verticalCenter; text: modelData.where; secondary: true; font.pixelSize: 11 }
                            Seg { anchors { right: parent.right; verticalCenter: parent.verticalCenter } icon: "x"; tip: "Unpin"; onClicked: Backend.togglePin(modelData.path) } } } }
                Column { id: near; visible: card.kind === "server"; x: 16; y: 122 + recent.height; width: parent.width - 32
                    Label { height: 26; x: 6; verticalAlignment: Text.AlignVCenter; secondary: true; font.pixelSize: 11
                        text: Backend.scanning ? "Looking for computers on this network…" : Backend.nearby.length ? "On this network" : "No computers announced themselves. Type an address above." }
                    Repeater { model: card.kind === "server" ? Backend.nearby : []
                        Pressable { required property var modelData; width: near.width; height: 30; radius: 9
                            onClicked: { if (modelData.share) { nameIn.text = modelData.address; nameIn.forceActiveFocus(); nameIn.cursorPosition = nameIn.text.length
                                             var s0 = win.sheet; win.sheet = { kind: "server", name: modelData.address, why: "Add the shared folder's name after the last slash.", again: false, hint: true } }
                                         else { card.done(); Backend.connectTo(modelData.address) } }
                            Glyph { x: 8; anchors.verticalCenter: parent.verticalCenter; name: "display"; size: 15 }
                            Label { x: 32; anchors.verticalCenter: parent.verticalCenter; text: modelData.name; font.pixelSize: 12 }
                            Label { anchors { right: parent.right; rightMargin: 10; verticalCenter: parent.verticalCenter } text: modelData.kind; secondary: true; font.pixelSize: 11 } } } }
                ListView { id: appList; visible: card.kind === "apps"; x: 16; y: 52; width: parent.width - 32; height: Math.max(34, Math.min(count, 7) * 34); clip: true; interactive: count > 7
                    model: card.kind === "apps" ? win.sheet.apps : []
                    delegate: Pressable { required property var modelData; required property int index; width: appList.width; height: 34; radius: 9
                        color: win.appAt === index ? win.pickTint : (hovered ? Qt.rgba(0.5, 0.5, 0.5, 0.08) : "transparent"); onClicked: win.appAt = index
                        Glyph { x: 10; anchors.verticalCenter: parent.verticalCenter; name: "apps"; size: 15 }
                        Label { x: 36; anchors.verticalCenter: parent.verticalCenter; text: modelData.name }
                        Label { visible: modelData.usual; anchors { right: parent.right; rightMargin: 10; verticalCenter: parent.verticalCenter } text: "Usual"; secondary: true; font.pixelSize: 11 } }
                    Label { visible: appList.count === 0; x: 6; y: 8; secondary: true; text: "No installed app says it opens this kind of file." } }
                Pressable { visible: card.kind === "apps" && appList.count > 0; x: 16; anchors { bottom: parent.bottom; bottomMargin: 20 } width: al.width + 40; height: 30; radius: 9; color: "transparent"; onClicked: win.appAlways = !win.appAlways
                    Rectangle { x: 6; width: 16; height: 16; radius: 5; anchors.verticalCenter: parent.verticalCenter; color: win.appAlways ? Theme.t.accent : "transparent"; border.width: 1; border.color: win.appAlways ? Theme.t.accent : Theme.t.text_secondary
                        Label { visible: win.appAlways; anchors.centerIn: parent; text: "✓"; font.pixelSize: 11; font.weight: Font.Bold; color: Theme.t.onAccent } }
                    Label { id: al; x: 30; anchors.verticalCenter: parent.verticalCenter; text: "Always for this kind"; font.pixelSize: 12 } }
                Row { anchors { right: parent.right; rightMargin: 22; bottom: parent.bottom; bottomMargin: 20 } spacing: 8
                    Btn { visible: card.kind === "clash"; text: "Skip"; onClicked: win.finishClash("skip") }
                    Btn { visible: card.kind === "clash"; text: "Replace"; danger: true; onClicked: win.finishClash("replace") }
                    Repeater { model: card.kind === "choice" ? win.sheet.choices : []
                        Btn { required property var modelData; required property int index; text: modelData; primary: index === 0; onClicked: { card.done(); Backend.netAnswer({ choice: index }) } } }
                    Btn { visible: card.kind !== "details" && card.kind !== "choice"; text: "Cancel"; onClicked: card.close() }
                    Btn { visible: card.kind === "clash"; primary: true; text: "Keep Both"; onClicked: win.finishClash("keep") }
                    Btn { visible: card.typing; primary: true; text: card.kind === "rename" || card.kind === "renames" ? "Rename" : card.kind === "goto" ? "Go" : card.kind === "server" ? "Connect" : card.kind === "login" ? "Sign In" : "Unlock"; onClicked: card.accept() }
                    Btn { visible: card.kind === "apps" && appList.count > 0; primary: true; text: "Open"
                        onClicked: { var s = win.sheet, a = s.apps[win.appAt]; card.close(); Backend.openWith(s.path, a.id, win.appAlways) } }
                    Btn { visible: card.kind === "details"; primary: true; text: "Done"; onClicked: card.close() }
                    Btn { visible: card.kind === "sure"; danger: true; text: card.kind === "sure" && win.sheet.what === "empty" ? "Empty the Trash" : "Delete for Good"
                        onClicked: { var s = win.sheet; card.close(); s.what === "empty" ? Backend.emptyTrash() : Backend.deleteForever(s.paths) } } }
            }
            Rectangle {   // quick look: Space shows the thing large; the arrows move on to its neighbours
                id: looker; objectName: "looker"
                readonly property var d: win.sheet && win.sheet.kind === "peek" ? win.sheet.data : null
                visible: d !== null; anchors.centerIn: parent; width: Math.min(940, parent.width - 80); height: parent.height - 120; radius: 16; color: Theme.t.menu_bg; border.width: 1; border.color: Theme.t.menu_border
                Label { x: 22; y: 16; width: parent.width - 240; elide: Text.ElideMiddle; font.pixelSize: 15; font.weight: Font.DemiBold; text: looker.d ? looker.d.name : "" }
                Label { anchors { right: parent.right; rightMargin: 22 } y: 18; secondary: true; font.pixelSize: 12; text: looker.d ? looker.d.facts : "" }
                Item { x: 16; y: 50; width: parent.width - 32; height: parent.height - 66; clip: true
                    Image { visible: looker.d !== null && looker.d.kind === "picture"; anchors.fill: parent; fillMode: Image.PreserveAspectFit; asynchronous: true
                        horizontalAlignment: Image.AlignHCenter; verticalAlignment: looker.d && /\.pdf$/i.test(looker.d.name) ? Image.AlignTop : Image.AlignVCenter
                        source: looker.d && looker.d.kind === "picture" ? looker.d.source : "" }
                    Rectangle { visible: looker.d !== null && looker.d.kind === "text"; anchors.fill: parent; radius: 10; color: Theme.t.group
                        Text { anchors { fill: parent; margins: 12 } clip: true; text: looker.d && looker.d.kind === "text" ? looker.d.text : ""; color: Theme.t.text; font.family: Theme.t.fontMono; font.pixelSize: 12; wrapMode: Text.WrapAnywhere; textFormat: Text.PlainText } }
                    Column { visible: looker.d !== null && looker.d.kind === "facts"; anchors.centerIn: parent; spacing: 10
                        Glyph { anchors.horizontalCenter: parent.horizontalCenter; name: win.cursor >= 0 && win.shown[win.cursor] ? win.shown[win.cursor].kind : "file"; size: 56; ink: Theme.t.text_secondary }
                        Label { anchors.horizontalCenter: parent.horizontalCenter; secondary: true; text: "No preview for this kind of file. Enter opens it." } } }
            }
        }
    ]
    onSheetChanged: if (sheet && (sheet.kind === "rename" || sheet.kind === "renames" || sheet.kind === "goto" || sheet.kind === "unlock" || sheet.kind === "server" || sheet.kind === "login")) { nameIn.text = sheet.name; nameIn.forceActiveFocus()
        var dot = sheet.kind !== "rename" || sheet.dir ? -1 : sheet.name.lastIndexOf("."); if (sheet.hint) nameIn.cursorPosition = nameIn.text.length; else if (sheet.again || dot <= 0) nameIn.selectAll(); else nameIn.select(0, dot) }

    // ---------------- the keyboard
    Item { id: keys; objectName: "keys"; focus: true
        Keys.onPressed: function (e) {
            if (win.sheet) {
                var k0 = e.key, kind = win.sheet.kind, enter = k0 === Qt.Key_Return || k0 === Qt.Key_Enter
                if (kind === "peek") {
                    if (k0 === Qt.Key_Escape || k0 === Qt.Key_Space) win.sheet = null
                    else if (k0 === Qt.Key_Right || k0 === Qt.Key_Down) win.look(Math.min(win.shown.length - 1, win.cursor + 1))
                    else if (k0 === Qt.Key_Left || k0 === Qt.Key_Up) win.look(Math.max(0, win.cursor - 1))
                    else if (enter) { win.sheet = null; win.openSel() }
                }
                else if (k0 === Qt.Key_Escape || (enter && kind === "details")) card.close()
                else if (kind === "apps" && k0 === Qt.Key_Down) win.appAt = Math.min(win.sheet.apps.length - 1, win.appAt + 1)
                else if (kind === "apps" && k0 === Qt.Key_Up) win.appAt = Math.max(0, win.appAt - 1)
                else if (kind === "apps" && enter && win.sheet.apps.length) { var s = win.sheet; win.sheet = null; Backend.openWith(s.path, s.apps[win.appAt].id, win.appAlways) }
                e.accepted = true; return
            }
            var ctrl = e.modifiers & Qt.ControlModifier, shift = e.modifiers & Qt.ShiftModifier, alt = e.modifiers & Qt.AltModifier, k = e.key
            e.accepted = true
            if (ctrl || alt || e.text.length !== 1 || e.text < " ") win.typed = ""
            if (k === Qt.Key_Escape) { if (win.menu) win.menu = null; else if (win.sel.length) win.clear(); else if (search.text !== "") search.text = "" }
            else if (ctrl && k === Qt.Key_A) win.selectAll()
            else if (ctrl && k === Qt.Key_C) win.run("copy")
            else if (ctrl && k === Qt.Key_X) win.run("cut")
            else if (ctrl && k === Qt.Key_V) win.paste()
            else if (ctrl && ((shift && k === Qt.Key_Z) || k === Qt.Key_Y)) Backend.redo()
            else if (ctrl && k === Qt.Key_Z) Backend.undo()
            else if (k === Qt.Key_Space && win.sel.length === 1 && !win.nameGoesOn(win.typed + " ")) { win.typed = ""; win.look(win.place(win.sel[0])) }
            else if (ctrl && k === Qt.Key_T) Backend.newTab("")
            else if (ctrl && k === Qt.Key_W) { if (win.tabbed) Backend.closeTab(Backend.tab); else win.close() }
            else if (ctrl && (k === Qt.Key_Backtab || (shift && k === Qt.Key_Tab))) Backend.stepTab(-1)
            else if (ctrl && k === Qt.Key_Tab) Backend.stepTab(1)
            else if (ctrl && k === Qt.Key_D) { if (!win.deep) win.run("duplicate") }
            else if (ctrl && k === Qt.Key_F) search.focusInput()
            else if (ctrl && k === Qt.Key_L) win.run("goto")
            else if (ctrl && k === Qt.Key_H) Backend.toggleHidden()
            else if (ctrl && k === Qt.Key_I) win.run("details")
            else if (ctrl && shift && k === Qt.Key_N) win.run("folder")
            else if (k === Qt.Key_F2) win.startRename()
            else if (k === Qt.Key_F5) Backend.refresh()
            else if (k === Qt.Key_Delete) win.bin()
            else if (k === Qt.Key_Return || k === Qt.Key_Enter) win.openSel()
            else if ((alt && k === Qt.Key_Up) || k === Qt.Key_Backspace) { if (win.deep) search.text = ""; else Backend.up() }
            else if (alt && k === Qt.Key_Left) Backend.back()
            else if (alt && k === Qt.Key_Right) Backend.forward()
            else if (k === Qt.Key_Right) win.step(Backend.grid ? 1 : 0, shift)
            else if (k === Qt.Key_Left) win.step(Backend.grid ? -1 : 0, shift)
            else if (k === Qt.Key_Down) win.step(Backend.grid ? win.cols : 1, shift)
            else if (k === Qt.Key_Up) win.step(Backend.grid ? -win.cols : -1, shift)
            else if (k === Qt.Key_PageDown) win.step((Backend.grid ? win.cols : 1) * 4, shift)
            else if (k === Qt.Key_PageUp) win.step((Backend.grid ? win.cols : 1) * -4, shift)
            else if (k === Qt.Key_Home) win.step(-win.shown.length, shift)
            else if (k === Qt.Key_End) win.step(win.shown.length, shift)
            else if (!ctrl && !alt && e.text.length === 1 && e.text >= " ") {      // type a name to jump to it
                win.typed += e.text.toLowerCase(); typing.restart()
                for (var i = 0; i < win.shown.length; i++) if (win.shown[i].name.toLowerCase().indexOf(win.typed) === 0) { win.pick(i, false, false); break }
            } else e.accepted = false
        }
    }
    Item { id: dragger; Drag.dragType: Drag.Automatic; Drag.supportedActions: Qt.CopyAction | Qt.MoveAction; Drag.hotSpot.x: 58; Drag.hotSpot.y: 40
        Drag.onDragFinished: Backend.refresh() }

    component Entry: MouseArea {              // the clicks and drags every file and folder answers to, in both views
        property var entry
        property int at
        property Item tile
        property point from
        property bool was: false               // it was already selected when pressed
        property bool dragged: false
        anchors.fill: parent; acceptedButtons: Qt.LeftButton | Qt.RightButton | Qt.MiddleButton
        onPressed: function (m) {
            keys.forceActiveFocus(); from = Qt.point(m.x, m.y); dragged = false; was = win.isSel(entry.path)
            if (m.button === Qt.LeftButton && !was && !(m.modifiers & (Qt.ControlModifier | Qt.ShiftModifier))) win.pick(at, false, false)
        }
        onPositionChanged: function (m) {
            if (!(pressedButtons & Qt.LeftButton) || dragged || win.trash || Math.abs(m.x - from.x) + Math.abs(m.y - from.y) < 12) return
            dragged = true; if (!win.isSel(entry.path)) win.pick(at, false, false); win.startDrag(tile)
        }
        onClicked: function (m) {
            if (m.button === Qt.RightButton) { if (!win.isSel(entry.path)) win.pick(at, false, false); win.popup(this, m.x, m.y, win.itemMenu()) }
            else if (m.button === Qt.MiddleButton) { if (entry.dir && !win.trash) Backend.newTab(entry.path) }
            else if (m.modifiers & (Qt.ControlModifier | Qt.ShiftModifier)) win.pick(at, m.modifiers & Qt.ControlModifier, m.modifiers & Qt.ShiftModifier)
            else if (was && !dragged && win.sel.length > 1) win.pick(at, false, false)
        }
        onDoubleClicked: function (m) { if (m.button === Qt.LeftButton && !(m.modifiers & (Qt.ControlModifier | Qt.ShiftModifier))) { if (win.deep && entry.dir) search.text = ""; Backend.open(entry.path) } }
    }

    Item {
        id: area; x: 0; y: win.tabbed ? 104 : 62; width: parent.width; height: parent.height - y - 2; clip: true
        WheelHandler { onWheel: function (w) { win.scrollTo(win.scrollY - (w.pixelDelta.y !== 0 ? w.pixelDelta.y : w.angleDelta.y * 0.9)) } }
        MouseArea { id: space; anchors.fill: parent; acceptedButtons: Qt.LeftButton | Qt.RightButton
            property point from
            property var kept: []
            onPressed: function (m) { keys.forceActiveFocus(); from = Qt.point(m.x, m.y); kept = (m.modifiers & Qt.ControlModifier) ? win.sel.slice() : []; win.band = null }
            onPositionChanged: function (m) {
                if (!(pressedButtons & Qt.LeftButton) || (!win.band && Math.abs(m.x - from.x) + Math.abs(m.y - from.y) < 8)) return
                win.band = Qt.rect(Math.min(from.x, m.x), Math.min(from.y, m.y), Math.abs(m.x - from.x), Math.abs(m.y - from.y)); win.bandPick(win.band, kept) }
            onReleased: function (m) {
                if (win.band) { win.band = null; return }
                if (!(m.modifiers & Qt.ControlModifier)) win.clear()
                if (m.button === Qt.RightButton) win.popup(space, m.x, m.y, win.spaceMenu()); else win.menu = null } }
        DropSpot { dest: win.trash || win.deep ? "" : Backend.path; on: Backend.canWrite; z: -1 }
        GridView {
            id: gridView; visible: Backend.grid; x: 22; y: 0; width: parent.width - 36; height: parent.height - 104; topMargin: 10
            cellWidth: 124; cellHeight: 124; interactive: false; cacheBuffer: 520; model: Backend.grid ? win.shown : []
            delegate: Item {
                required property var modelData
                required property int index
                width: 124; height: 124
                Pressable {
                    id: tile
                    readonly property bool picked: win.isSel(modelData.path)
                    width: 116; height: 116; radius: 14; color: picked ? win.pickTint : (hovered ? Qt.rgba(0.5, 0.5, 0.5, 0.08) : "transparent")
                    border.width: picked || win.cursor === index ? 1 : 0; border.color: picked ? Theme.t.accent : Theme.t.islandLine
                    opacity: Backend.cutPaths.indexOf(modelData.path) >= 0 ? 0.45 : 1
                    Rectangle { visible: !thumb.visible; width: 64; height: 54; radius: 12; y: 12; anchors.horizontalCenter: parent.horizontalCenter
                        color: modelData.dir ? win.folderTint : Theme.t.group; border.width: 1; border.color: Theme.t.islandLine
                        Glyph { anchors.centerIn: parent; name: modelData.kind; size: 26; ink: modelData.dir ? Theme.t.accent : Theme.t.icon } }
                    Image { id: thumb; width: 64; height: 54; y: 12; anchors.horizontalCenter: parent.horizontalCenter; asynchronous: true; visible: status === Image.Ready && implicitWidth > 8
                        source: modelData.thumb ? "image://filethumb/" + encodeURIComponent(modelData.path) + "?" + modelData.stamp : "" }
                    Label { y: 76; width: parent.width - 12; x: 6; text: modelData.name; horizontalAlignment: Text.AlignHCenter; elide: Text.ElideMiddle; font.pixelSize: 12 }
                    Label { visible: win.trash || win.deep; y: 94; width: parent.width - 12; x: 6; text: win.deep ? (modelData.line || modelData.from) : modelData.modified; horizontalAlignment: Text.AlignHCenter; elide: modelData.line ? Text.ElideRight : Text.ElideMiddle; secondary: true; font.pixelSize: 10 }
                    Entry { entry: modelData; at: index; tile: tile }
                    DropSpot { dest: modelData.path; on: modelData.dir && !win.trash && !tile.picked }
                } }
        }
        Rectangle {   // list view: one sheet of glass
            id: listSheet
            visible: !Backend.grid && win.shown.length > 0; x: 14; y: 6; width: parent.width - 28; height: Math.min(listView.contentHeight + 38, parent.height - 110); radius: 12; color: Theme.t.group; border.width: 1; border.color: Theme.t.islandLine
            Row { x: 4; y: 4; height: 28
                Repeater { model: [["name", "Name", listView.width - 300, 44], ["date", win.trash ? "Deleted" : "Changed", 160, 0], ["size", "Size", 140, 0]]
                    Item { required property var modelData; width: modelData[2]; height: 28
                        Label { x: modelData[3]; anchors.verticalCenter: parent.verticalCenter; font.pixelSize: 11; secondary: Backend.sortBy !== modelData[0]
                            text: modelData[1] + (Backend.sortBy === modelData[0] ? (Backend.sortDown ? " ↓" : " ↑") : "") }
                        MouseArea { anchors.fill: parent; onClicked: Backend.sort(modelData[0]) } } } }
            ListView {
                id: listView; x: 4; y: 32; width: parent.width - 8; height: parent.height - 36; clip: true; interactive: false; model: Backend.grid ? [] : win.shown
                delegate: Pressable {
                    id: row
                    required property var modelData
                    required property int index
                    readonly property bool picked: win.isSel(modelData.path)
                    readonly property bool wide: win.trash || win.deep
                    width: listView.width; height: 34; radius: 9; color: picked ? win.pickTint : (hovered ? Qt.rgba(0.5, 0.5, 0.5, 0.08) : "transparent")
                    border.width: !picked && win.cursor === index ? 1 : 0; border.color: Theme.t.islandLine
                    opacity: Backend.cutPaths.indexOf(modelData.path) >= 0 ? 0.45 : 1
                    Glyph { x: 12; anchors.verticalCenter: parent.verticalCenter; name: modelData.kind; ink: modelData.dir ? Theme.t.accent : Theme.t.icon }
                    Label { x: 44; width: parent.width - 350 - (row.wide ? 170 : 0); anchors.verticalCenter: parent.verticalCenter; text: modelData.name; elide: Text.ElideMiddle }
                    Label { visible: row.wide; x: parent.width - 470; width: 160; anchors.verticalCenter: parent.verticalCenter; text: modelData.line || modelData.from; elide: modelData.line ? Text.ElideRight : Text.ElideMiddle; secondary: true; font.pixelSize: 12 }
                    Label { x: parent.width - 300; anchors.verticalCenter: parent.verticalCenter; text: modelData.modified; secondary: true; font.pixelSize: 12 }
                    Label { x: parent.width - 140; anchors.verticalCenter: parent.verticalCenter; text: modelData.dir ? "Folder" : modelData.size; secondary: true; font.pixelSize: 12 }
                    Entry { entry: modelData; at: index; tile: row }
                    DropSpot { dest: modelData.path; on: modelData.dir && !win.trash && !row.picked }
                }
            }
        }
        Rectangle { visible: win.band !== null; x: win.band ? win.band.x : 0; y: win.band ? win.band.y : 0; width: win.band ? win.band.width : 0; height: win.band ? win.band.height : 0
            radius: 6; color: Qt.rgba(win.tintColor.r, win.tintColor.g, win.tintColor.b, 0.16); border.width: 1; border.color: Theme.t.accent }
    }
    Column { visible: win.shown.length === 0; anchors.centerIn: parent; spacing: 8
        Glyph { name: win.trash ? "trash" : win.deep || win.filter ? "search" : "folder"; size: 40; ink: Theme.t.text_secondary; anchors.horizontalCenter: parent.horizontalCenter }
        Label { anchors.horizontalCenter: parent.horizontalCenter; secondary: true
            text: win.deep ? (Backend.stillFinding ? "Looking through the folders in here…" : "Nothing in here or its folders matches “" + Backend.finding + "”")
                : win.filter ? "Nothing here matches “" + win.filter + "”" + (win.trash ? "" : ". Press Enter to look in its folders too.") : win.trash ? "The Trash is empty" : "This folder is empty" } }
}
