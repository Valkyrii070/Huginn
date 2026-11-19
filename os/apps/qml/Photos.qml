import QtQuick

// Photos, "mosaic": pictures to the edges. Moments, albums and favourites switch in the island; months or albums
// are a rail on the right, where the light is.
GlassWindow {
    id: win
    title: "Photos"; glow: "right"
    property string month: ""
    property int viewing: Backend.first
    // a picture grows out of its tile, and goes back into it (GrowFrom; Settings › Desktop & Dock › Motion)
    property var lastPic: null
    property var growRect: null
    onPicChanged: {
        if (pic) { lastPic = pic; if (!viewer.shown && viewer.pending === null) { viewer.pending = growRect || "whole"; growWait.restart() } }   // grows once it has loaded
        else if (viewer.shown) viewer.close()
        growRect = null
    }
    Timer { id: growWait; interval: 300; onTriggered: viewer.go() }
    property bool showInfo: false
    property real zoom: 1
    property string notice: ""
    property var asking: null
    property string mode: startPage === "albums" || startPage === "favourites" ? startPage : "moments"                       // moments (by month), albums (folders in Pictures) or favourites
    property string album: ""                             // the album that is open, in albums mode
    readonly property bool choosing: mode === "albums" && album === ""     // looking at the albums themselves
    readonly property bool railShown: (!pic || viewer.p < 1) && !Backend.editing && Backend.items.length > 0 && (mode === "moments" || (mode === "albums" && album !== ""))
    readonly property var shown: Backend.items.filter(function (p) {
        return mode === "favourites" ? p.fav : mode === "albums" ? p.album === album : (!month || p.day === month) })
    readonly property var pic: viewing >= 0 && viewing < shown.length ? shown[viewing] : null
    readonly property var months: { var seen = [], out = []; Backend.items.forEach(function (p) { if (seen.indexOf(p.day) < 0) { seen.push(p.day); out.push(p.day) } }); return out }
    onViewingChanged: zoom = 1
    Connections { target: Backend; function onFailed(msg) { win.notice = msg; hide.restart() } }
    Timer { id: hide; interval: 5000; onTriggered: win.notice = "" }
    islands: [
        Island {   // what you can do with the picture that is open
            visible: !!win.pic && !Backend.editing; anchors.horizontalCenter: parent.horizontalCenter; y: 12
            Seg { icon: "grid"; text: "All Pictures"; onClicked: win.viewing = -1 }
            IslandGap {}
            Label { text: win.pic ? win.pic.name : ""; font.pixelSize: 12; font.weight: Font.DemiBold; leftPadding: 6; rightPadding: 6; width: Math.min(implicitWidth, 260); elide: Text.ElideMiddle; anchors.verticalCenter: parent.verticalCenter }
            IslandGap {}
            Seg { visible: Backend.canEdit; icon: "sliders"; text: "Edit"; onClicked: Backend.beginEdit(win.pic.path) }
            Seg { icon: "rotate"; tip: "Rotate"; onClicked: Backend.rotate(win.pic.path, 90) }
            Seg { icon: "star"; tip: win.pic && win.pic.fav ? "Remove from favourites" : "Add to favourites"; on: !!win.pic && win.pic.fav
                onClicked: { var n = win.shown.length; Backend.toggleFavourite(win.pic.path); if (win.shown.length < n && win.viewing >= win.shown.length) win.viewing = win.shown.length - 1 } }
            Seg { icon: "mail"; tip: "Send by Mail"; onClicked: Backend.sendByMail(win.pic.path) }
            Seg { icon: "info"; tip: "Details"; on: win.showInfo; onClicked: win.showInfo = !win.showInfo }
            Seg { icon: "trash"; tip: "Move to Trash"; danger: true; onClicked: win.asking = win.pic }
        },
        Island {   // editing: leave, undo, compare, and finish
            visible: Backend.editing; anchors.horizontalCenter: parent.horizontalCenter; y: 12
            Seg { text: "Cancel"; onClicked: Backend.cancelEdit() }
            IslandGap {}
            Seg { icon: "undo"; tip: "Undo"; enabled: Backend.canUndo; opacity: enabled ? 1 : 0.4; onClicked: Backend.undoEdit() }
            Seg { icon: "redo"; tip: "Redo"; enabled: Backend.canRedo; opacity: enabled ? 1 : 0.4; onClicked: Backend.redoEdit() }
            Seg { icon: "eye"; tip: "Hold to see the original"; on: win.comparing
                MouseArea { anchors.fill: parent; onPressed: win.comparing = true; onReleased: win.comparing = false; onCanceled: win.comparing = false } }
            Seg { visible: Backend.hasOriginal; text: "Revert to Original"; onClicked: Backend.revertOriginal() }
            IslandGap {}
            Seg { text: Backend.saving ? "Saving…" : "Save as Copy"; enabled: !Backend.saving; onClicked: Backend.finishEdit(true) }
            Seg { text: "Done"; on: true; enabled: !Backend.saving; onClicked: Backend.finishEdit(false) }
        },
        Rail {   // months, or the albums: on the edge the light comes from
            visible: win.railShown; anchors { right: parent.right; rightMargin: 12 } y: 64; width: 176; maxHeight: win.height - 64 - 76
            Seg { visible: win.mode === "moments"; fill: true; icon: "image"; text: "All Pictures  ·  " + Backend.items.length; on: win.month === ""; onClicked: { win.month = ""; win.viewing = -1 } }
            Repeater { model: win.mode === "moments" ? win.months : []; Seg { required property string modelData; fill: true; icon: "calendar"; text: modelData; on: win.month === modelData; onClicked: { win.month = modelData; win.viewing = -1 } } }
            Seg { visible: win.mode === "albums"; fill: true; icon: "back"; text: "All Albums"; onClicked: win.album = "" }
            Repeater { model: win.mode === "albums" ? Backend.albums : []; Seg { required property var modelData; fill: true; icon: "folder"; text: modelData.name; on: win.album === modelData.name; onClicked: { win.album = modelData.name; win.viewing = -1 } } }
        },
        Island {   // the three ways to look at your pictures: the main island
            visible: !win.pic && Backend.items.length > 0; anchors { horizontalCenter: parent.horizontalCenter; bottom: parent.bottom; bottomMargin: 14 }
            Seg { icon: "image"; text: "Moments"; on: win.mode === "moments"; onClicked: win.mode = "moments" }
            Seg { icon: "folder"; text: "Albums" + (Backend.albums.length ? "  ·  " + Backend.albums.length : ""); on: win.mode === "albums"; onClicked: { win.mode = "albums"; win.album = "" } }
            Seg { icon: "star"; text: "Favourites" + (Backend.favourites ? "  ·  " + Backend.favourites : ""); on: win.mode === "favourites"; onClicked: win.mode = "favourites" }
        }
    ]
    // ---------------- Albums: one card each
    Flickable { visible: win.choosing && !win.pic && Backend.albums.length > 0; x: 0; y: 62; width: parent.width; height: parent.height - 64; contentHeight: cards.height + 90; clip: true
        Flow { id: cards; x: 14; y: 2; width: parent.width - 28; spacing: 12
            Repeater { model: win.choosing ? Backend.albums : []
                Pressable { required property var modelData; width: 204; height: 196; radius: 14; color: hovered ? Theme.t.hover : Theme.t.group; border.width: 1; border.color: Theme.t.islandLine
                    onClicked: { win.album = modelData.name; win.viewing = -1 }
                    Image { x: 8; y: 8; width: 188; height: 141; source: "image://roundthumb/" + encodeURIComponent(modelData.cover) + "?" + Backend.stamp; asynchronous: true; cache: false }
                    Label { x: 12; y: 156; width: parent.width - 70; text: modelData.name; font.weight: Font.DemiBold; elide: Text.ElideRight }
                    Label { anchors { right: parent.right; rightMargin: 12 } y: 158; text: modelData.count; secondary: true; font.pixelSize: 12 } } } } }
    Column { visible: !win.pic && Backend.items.length > 0 && ((win.choosing && Backend.albums.length === 0) || (win.mode === "favourites" && win.shown.length === 0)); anchors.centerIn: parent; spacing: 8; width: 400
        Glyph { name: win.mode === "albums" ? "folder" : "star"; size: 44; ink: Theme.t.text_secondary; anchors.horizontalCenter: parent.horizontalCenter }
        Label { text: win.mode === "albums" ? "No albums yet" : "No favourites yet"; font.pixelSize: 17; font.weight: Font.DemiBold; anchors.horizontalCenter: parent.horizontalCenter }
        Label { width: parent.width; horizontalAlignment: Text.AlignHCenter; wrapMode: Text.WordWrap; secondary: true
            text: win.mode === "albums" ? "An album is a folder inside " + Backend.folder + ". Make one in Files and put pictures in it." : "Open a picture and press the star to keep it here." } }
    Column { visible: Backend.items.length === 0; anchors.centerIn: parent; spacing: 8
        Item { width: 250; height: 164; anchors.horizontalCenter: parent.horizontalCenter      // a wall of frames waiting for pictures
            Rectangle { x: 0; y: 0; width: 120; height: 100; radius: 12; clip: true; gradient: Gradient { GradientStop { position: 0; color: Qt.rgba(tintColor.r, tintColor.g, tintColor.b, 0.55) } GradientStop { position: 1; color: Qt.rgba(tintColor.r, tintColor.g, tintColor.b, 0.15) } }
                Rectangle { x: 78; y: 16; width: 22; height: 22; radius: 11; color: "#E6FFFFFF" }
                Rectangle { x: -20; y: 62; width: 90; height: 90; rotation: 45; color: Qt.rgba(tintColor.r, tintColor.g, tintColor.b, 0.7) } Rectangle { x: 50; y: 74; width: 90; height: 90; rotation: 45; color: Theme.t.accent } }
            Rectangle { x: 128; y: 0; width: 58; height: 46; radius: 10; color: Qt.rgba(tintColor.r, tintColor.g, tintColor.b, 0.3) } Rectangle { x: 192; y: 0; width: 58; height: 46; radius: 10; color: Qt.rgba(tintColor.r, tintColor.g, tintColor.b, 0.18) }
            Rectangle { x: 128; y: 54; width: 122; height: 110; radius: 12; color: Qt.rgba(tintColor.r, tintColor.g, tintColor.b, 0.12); border.width: 1; border.color: Theme.t.islandLine; Glyph { anchors.centerIn: parent; name: "image"; size: 30; ink: Theme.t.text_secondary } }
            Rectangle { x: 0; y: 108; width: 56; height: 56; radius: 10; color: Qt.rgba(tintColor.r, tintColor.g, tintColor.b, 0.22) } Rectangle { x: 64; y: 108; width: 56; height: 56; radius: 10; color: Qt.rgba(tintColor.r, tintColor.g, tintColor.b, 0.4) } }
        Label { text: "No pictures yet"; font.pixelSize: 17; font.weight: Font.DemiBold; anchors.horizontalCenter: parent.horizontalCenter }
        Label { text: "Pictures you put in " + Backend.folderName + " appear here."; secondary: true; anchors.horizontalCenter: parent.horizontalCenter } }
    Flickable { visible: (!win.pic || viewer.p < 1) && !win.choosing && Backend.items.length > 0; x: 0; y: 62; width: parent.width - (win.railShown ? 200 : 14); height: parent.height - 64; contentHeight: wall.height + 90; clip: true
        Flow { id: wall; x: 14; y: 2; width: parent.width - 14; spacing: 6
            readonly property real cell: (width - 6 * (Math.max(2, Math.floor(width / 190)) - 1)) / Math.max(2, Math.floor(width / 190))
            Repeater { model: win.pic && viewer.p >= 1 ? [] : win.shown
                Rectangle { required property var modelData; required property int index; width: wall.cell; height: wall.cell * 0.75; radius: 10; color: Theme.t.group
                    // Cut to rounded corners by the app itself (image://roundthumb), so it needs no shader.
                    Image { anchors.fill: parent; source: "image://roundthumb/" + encodeURIComponent(modelData.path) + "?" + Backend.stamp; asynchronous: true; cache: false }
                    Rectangle { visible: modelData.fav; x: 8; y: 8; width: 24; height: 24; radius: 12; color: "#B3000000"; Glyph { anchors.centerIn: parent; name: "star"; size: 13; ink: "#FFFFFF" } }
                    Rectangle { visible: !!modelData.edited; x: parent.width - 32; y: 8; width: 24; height: 24; radius: 12; color: "#B3000000"; Glyph { anchors.centerIn: parent; name: "sliders"; size: 13; ink: "#FFFFFF" } }
                    Rectangle { anchors.fill: parent; radius: 10; color: "transparent"; border.width: hit.containsMouse ? 2 : 0; border.color: Theme.t.accent }
                    MouseArea { id: hit; anchors.fill: parent; hoverEnabled: true
                        onClicked: { var r = parent.mapToItem(viewer.parent, 0, 0); win.growRect = Qt.rect(r.x, r.y, parent.width, parent.height); win.viewing = index } } } } } }
    GrowFrom { id: viewer; visible: shown && !Backend.editing; anchors { fill: parent; topMargin: 58 }
        readonly property var pic: win.pic || win.lastPic
        property var pending: null
        function go() { if (pending === null) return; var r = pending === "whole" ? null : pending; pending = null; growWait.stop(); if (win.pic) openAt(r) }
        Component.onCompleted: if (win.pic) { shown = true; opened = true; p = 1 }
        Image { id: big; anchors.centerIn: parent; width: (parent.width - (win.showInfo ? 300 : 40)) ; height: parent.height - 40; x: 20; scale: win.zoom
            source: viewer.pic ? viewer.pic.url : ""; fillMode: Image.PreserveAspectFit; asynchronous: true; cache: false; anchors.horizontalCenterOffset: win.showInfo ? -130 : 0
            property int stamp: Backend.stamp; onStampChanged: { var u = source; source = ""; source = u }
            onStatusChanged: if (status === Image.Ready || status === Image.Error) viewer.go() }
        MouseArea { anchors.fill: parent; onWheel: function (w) { win.zoom = Math.max(1, Math.min(6, win.zoom * (w.angleDelta.y > 0 ? 1.15 : 0.87))) } onDoubleClicked: win.zoom = win.zoom > 1 ? 1 : 2 }
        Repeater { model: [[-1, "back"], [1, "forward"]]
            Pressable { required property var modelData; visible: win.viewing + modelData[0] >= 0 && win.viewing + modelData[0] < win.shown.length
                width: 40; height: 40; radius: 20; color: Theme.t.menu_bg; border.width: 1; border.color: Theme.t.menu_border; anchors.verticalCenter: parent.verticalCenter
                x: modelData[0] < 0 ? 14 : parent.width - (win.showInfo ? 314 : 54); onClicked: win.viewing += modelData[0]
                Glyph { anchors.centerIn: parent; name: modelData[1]; size: 16 } } }
        Rectangle { visible: win.showInfo; anchors { right: parent.right; rightMargin: 12 } y: 4; width: 250; height: parent.height - 18; radius: 12; color: Theme.t.island; border.width: 1; border.color: Theme.t.islandLine
            Column { x: 16; y: 16; width: parent.width - 32; spacing: 10
                Label { text: "Details"; font.pixelSize: 15; font.weight: Font.DemiBold }
                Repeater { model: viewer.pic && win.showInfo ? Backend.info(viewer.pic.path).filter(function (r) { return r.value !== "" }) : []
                    Column { required property var modelData; width: parent.width; Label { text: modelData.name; secondary: true; font.pixelSize: 11 } Label { width: parent.width; text: modelData.value; wrapMode: Text.WrapAnywhere } } } } }
        Label { anchors { bottom: parent.bottom; bottomMargin: 10; horizontalCenter: parent.horizontalCenter } text: win.notice || ((win.viewing + 1) + " of " + win.shown.length + (win.zoom > 1 ? "  ·  " + Math.round(win.zoom * 100) + "%" : "")); color: win.notice ? Theme.t.danger : Theme.t.text_secondary; font.pixelSize: 12 }
    }

    // ---------------- Editing: "darkroom". The picture fills the left; the tools are a tall island on the right.
    property string tool: "adjust"                         // adjust, filters or crop
    property bool comparing: false
    readonly property var ed: Backend.edit
    Connections { target: Backend; function onEditReady() { if (!Backend.editing) { win.tool = "adjust"; win.comparing = false } } }
    component EditSlider: Item {
        id: es
        property string key: ""
        property string label: ""
        property real lo: -1
        property real hi: 1
        property real live: win.ed[key] !== undefined ? win.ed[key] : 0
        property bool dragging: false
        readonly property real frac: (live - lo) / (hi - lo)
        readonly property real zero: (0 - lo) / (hi - lo)
        width: parent ? parent.width : 280; height: 46
        onLiveChanged: if (!dragging) {}
        Label { text: es.label; font.pixelSize: 12; y: 2
            MouseArea { anchors.fill: parent; onDoubleClicked: Backend.setEdit(es.key, es.lo < 0 ? 0 : 0) } }
        Label { anchors.right: parent.right; y: 2; text: es.lo === -45 ? (es.live > 0 ? "+" : "") + es.live.toFixed(1) + "°" : (es.live > 0 && es.lo < 0 ? "+" : "") + Math.round(es.live * 100); secondary: true; font.pixelSize: 11; font.family: Theme.t.fontMono }
        Rectangle { id: track; y: 28; width: parent.width; height: 4; radius: 2; color: Theme.t.dark ? "#26FFFFFF" : "#26141E28"
            Rectangle { x: Math.min(es.zero, es.frac) * track.width; width: Math.abs(es.frac - es.zero) * track.width; height: 4; radius: 2; color: Theme.t.accent }
            Rectangle { visible: es.lo < 0; x: es.zero * track.width - 1; y: -3; width: 2; height: 10; radius: 1; color: Theme.t.text_secondary }
            Rectangle { width: 16; height: 16; radius: 8; y: -6; x: es.frac * (track.width - 16); color: "#FFFFFF"; border.width: 1; border.color: Theme.t.capsule_border } }
        MouseArea { x: 0; y: 18; width: parent.width; height: 24
            function at(mx) { var v = es.lo + Math.max(0, Math.min(1, mx / width)) * (es.hi - es.lo); if (Math.abs(v) < (es.hi - es.lo) * 0.015) v = 0; return v }
            onPressed: function (m) { es.dragging = true; Backend.markEdit(); es.live = at(m.x); push.restart() }
            onPositionChanged: function (m) { es.live = at(m.x); if (!push.running) push.start() }
            onReleased: { es.dragging = false; push.stop(); Backend.dragEdit(es.key, es.live) }
            onDoubleClicked: Backend.setEdit(es.key, 0) }
        Timer { id: push; interval: 90; onTriggered: Backend.dragEdit(es.key, es.live) }
    }
    Item { visible: Backend.editing; anchors.fill: parent; z: 3
        // the picture: two copies take turns, so the old one stays until the new one is worked out
        Item { id: stage; x: 14; y: 62; width: parent.width - 362; height: parent.height - 76; clip: true
            property int want: Backend.editVersion
            property bool useA: true
            readonly property string src: "image://photoedit/view/" + Backend.editVersion + "/" + (win.comparing ? "orig" : win.tool === "crop" ? "0" : "1")
            onSrcChanged: if (Backend.editing) (useA ? imgB : imgA).source = src
            Image { id: imgA; anchors.fill: parent; fillMode: Image.PreserveAspectFit; asynchronous: true; cache: false; visible: stage.useA
                onStatusChanged: if (status === Image.Ready && !stage.useA && String(source) === stage.src) stage.useA = true }
            Image { id: imgB; anchors.fill: parent; fillMode: Image.PreserveAspectFit; asynchronous: true; cache: false; visible: !stage.useA
                onStatusChanged: if (status === Image.Ready && stage.useA && String(source) === stage.src) stage.useA = false }
            readonly property var shownImg: stage.useA ? imgA : imgB
            // the crop frame, over the straightened picture
            Item { id: frame; visible: win.tool === "crop" && !win.comparing && stage.shownImg.paintedWidth > 0
                readonly property real pw: stage.shownImg.paintedWidth
                readonly property real ph: stage.shownImg.paintedHeight
                x: (stage.width - pw) / 2; y: (stage.height - ph) / 2; width: pw; height: ph
                property var c: win.ed.crop || [0, 0, 1, 1]
                property real cx: c[0]; property real cy: c[1]; property real cw: c[2]; property real ch: c[3]
                readonly property real ratio: ({ free: 0, original: -1, square: 1, "4:3": 4 / 3, "3:2": 1.5, "16:9": 16 / 9, "5:4": 1.25, "9:16": 9 / 16 })[win.ed.ratio || "free"]
                readonly property real lock: ratio === 0 ? 0 : (ratio < 0 ? (cw * pw) / Math.max(1, ch * ph) : ratio)
                function send() { Backend.dragCrop(cx, cy, cw, ch) }
                Rectangle { x: 0; y: 0; width: parent.width; height: frame.cy * frame.ph; color: "#99000000" }
                Rectangle { x: 0; y: (frame.cy + frame.ch) * frame.ph; width: parent.width; height: parent.height - y; color: "#99000000" }
                Rectangle { x: 0; y: frame.cy * frame.ph; width: frame.cx * frame.pw; height: frame.ch * frame.ph; color: "#99000000" }
                Rectangle { x: (frame.cx + frame.cw) * frame.pw; y: frame.cy * frame.ph; width: parent.width - x; height: frame.ch * frame.ph; color: "#99000000" }
                Rectangle { id: box; x: frame.cx * frame.pw; y: frame.cy * frame.ph; width: frame.cw * frame.pw; height: frame.ch * frame.ph; color: "transparent"; border.width: 2; border.color: "#FFFFFF"
                    Repeater { model: 2; Rectangle { required property int index; x: box.width * (index + 1) / 3; width: 1; height: box.height; color: "#66FFFFFF" } }
                    Repeater { model: 2; Rectangle { required property int index; y: box.height * (index + 1) / 3; height: 1; width: box.width; color: "#66FFFFFF" } }
                    MouseArea { anchors.fill: parent; anchors.margins: 14; cursorShape: Qt.SizeAllCursor
                        property real sx; property real sy; property real ox; property real oy
                        onPressed: function (m) { Backend.markEdit(); sx = m.x + box.x; sy = m.y + box.y; ox = frame.cx; oy = frame.cy }
                        onPositionChanged: function (m) { frame.cx = Math.max(0, Math.min(1 - frame.cw, ox + (m.x + box.x - sx) / frame.pw)); frame.cy = Math.max(0, Math.min(1 - frame.ch, oy + (m.y + box.y - sy) / frame.ph)); tick.restart() }
                        onReleased: frame.send() }
                    Repeater { model: [[0, 0], [1, 0], [0, 1], [1, 1]]
                        Rectangle { required property var modelData; width: 22; height: 22; radius: 4; color: "transparent"; border.width: 4; border.color: "#FFFFFF"
                            x: modelData[0] * box.width - 11; y: modelData[1] * box.height - 11
                            MouseArea { anchors.fill: parent; anchors.margins: -8; cursorShape: modelData[0] === modelData[1] ? Qt.SizeFDiagCursor : Qt.SizeBDiagCursor
                                onPressed: Backend.markEdit()
                                onPositionChanged: function (m) {
                                    var p = mapToItem(frame, m.x, m.y), nx = Math.max(0, Math.min(1, p.x / frame.pw)), ny = Math.max(0, Math.min(1, p.y / frame.ph))
                                    var l = frame.cx, t = frame.cy, r = frame.cx + frame.cw, b = frame.cy + frame.ch
                                    if (modelData[0] === 0) l = Math.min(nx, r - 0.05); else r = Math.max(nx, l + 0.05)
                                    if (modelData[1] === 0) t = Math.min(ny, b - 0.05); else b = Math.max(ny, t + 0.05)
                                    if (frame.lock > 0) {   // keep the shape: the height follows the width
                                        var h = (r - l) * frame.pw / frame.lock / frame.ph
                                        if (modelData[1] === 0) t = Math.max(0, b - h); else b = Math.min(1, t + h)
                                    }
                                    frame.cx = l; frame.cy = t; frame.cw = r - l; frame.ch = b - t; tick.restart() }
                                onReleased: frame.send() } } } }
                Timer { id: tick; interval: 140; onTriggered: frame.send() } } }
        Label { visible: win.comparing; x: stage.x + 12; y: stage.y + 10; text: "ORIGINAL"; color: "#FFFFFF"; font.pixelSize: 11; font.weight: Font.Bold; style: Text.Outline; styleColor: "#66000000" }
        // the tools
        Rectangle { id: tools; x: parent.width - 338; y: 62; width: 324; height: parent.height - 76; radius: 18; color: Theme.t.island; border.width: 1; border.color: Theme.t.islandLine
            MouseArea { anchors.fill: parent }
            Row { x: 10; y: 10; spacing: 4
                Repeater { model: [["adjust", "Adjust", "sliders"], ["filters", "Filters", "sparkle"], ["crop", "Crop", "crop"]]
                    Seg { required property var modelData; icon: modelData[2]; text: modelData[1]; on: win.tool === modelData[0]; onClicked: win.tool = modelData[0] } } }
            Flickable { x: 16; y: 52; width: parent.width - 32; height: parent.height - 60; contentHeight: toolCol.height + 20; clip: true; boundsBehavior: Flickable.StopAtBounds
                Column { id: toolCol; width: parent.width; spacing: 4
                    // Adjust
                    Column { visible: win.tool === "adjust"; width: parent.width; spacing: 4
                        Btn { width: parent.width; text: "✦  Auto Enhance"; onClicked: Backend.autoEdit() }
                        Item { width: 1; height: 8 }
                        Item { width: parent.width; height: 24; Label { text: "LIGHT"; secondary: true; font.pixelSize: 11; font.weight: Font.DemiBold; anchors.bottom: parent.bottom }
                            Label { anchors { right: parent.right; bottom: parent.bottom } text: "Reset"; color: Theme.t.accent; font.pixelSize: 11; MouseArea { anchors.fill: parent; onClicked: Backend.resetEdit("light") } } }
                        EditSlider { key: "exposure"; label: "Exposure" } EditSlider { key: "brightness"; label: "Brightness" } EditSlider { key: "contrast"; label: "Contrast" }
                        EditSlider { key: "highlights"; label: "Highlights" } EditSlider { key: "shadows"; label: "Shadows" } EditSlider { key: "blacks"; label: "Black point" }
                        Item { width: parent.width; height: 30; Label { text: "COLOUR"; secondary: true; font.pixelSize: 11; font.weight: Font.DemiBold; anchors.bottom: parent.bottom }
                            Label { anchors { right: parent.right; bottom: parent.bottom } text: "Reset"; color: Theme.t.accent; font.pixelSize: 11; MouseArea { anchors.fill: parent; onClicked: Backend.resetEdit("colour") } } }
                        EditSlider { key: "saturation"; label: "Saturation" } EditSlider { key: "vibrance"; label: "Vibrance" } EditSlider { key: "warmth"; label: "Warmth" } EditSlider { key: "tint"; label: "Tint" }
                        Item { width: parent.width; height: 30; Label { text: "DETAIL"; secondary: true; font.pixelSize: 11; font.weight: Font.DemiBold; anchors.bottom: parent.bottom }
                            Label { anchors { right: parent.right; bottom: parent.bottom } text: "Reset"; color: Theme.t.accent; font.pixelSize: 11; MouseArea { anchors.fill: parent; onClicked: Backend.resetEdit("detail") } } }
                        EditSlider { key: "sharpen"; label: "Sharpen"; lo: 0 } EditSlider { key: "vignette"; label: "Vignette"; lo: 0 } EditSlider { key: "grain"; label: "Grain"; lo: 0 } EditSlider { key: "fade"; label: "Fade"; lo: 0 } }
                    // Filters
                    Column { visible: win.tool === "filters"; width: parent.width; spacing: 10
                        Grid { columns: 2; spacing: 10; width: parent.width
                            Repeater { model: win.tool === "filters" ? Backend.filters : []
                                Column { required property var modelData; spacing: 4; width: (toolCol.width - 10) / 2
                                    Rectangle { width: parent.width; height: width * 0.72; radius: 10; clip: true; color: Theme.t.group
                                        border.width: win.ed.filter === modelData.id ? 3 : 0; border.color: Theme.t.accent
                                        Image { anchors.fill: parent; anchors.margins: win.ed.filter === modelData.id ? 3 : 0; fillMode: Image.PreserveAspectCrop; asynchronous: true; cache: false
                                            source: "image://photoedit/filter/" + modelData.id + "/" + Backend.editVersion }
                                        MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: Backend.setFilter(modelData.id) } }
                                    Label { anchors.horizontalCenter: parent.horizontalCenter; text: modelData.name; font.pixelSize: 12; font.weight: win.ed.filter === modelData.id ? Font.DemiBold : Font.Normal } } } }
                        EditSlider { visible: !!win.ed.filter && win.ed.filter !== "none"; key: "amount"; label: "Strength"; lo: 0 } }
                    // Crop
                    Column { visible: win.tool === "crop"; width: parent.width; spacing: 10
                        Label { text: "SHAPE"; secondary: true; font.pixelSize: 11; font.weight: Font.DemiBold }
                        Flow { width: parent.width; spacing: 6
                            Repeater { model: [["free", "Free"], ["original", "Original"], ["square", "Square"], ["4:3", "4:3"], ["3:2", "3:2"], ["16:9", "16:9"], ["5:4", "5:4"], ["9:16", "9:16"]]
                                Seg { required property var modelData; anchors.verticalCenter: undefined; text: modelData[1]; on: (win.ed.ratio || "free") === modelData[0]; onClicked: Backend.setRatio(modelData[0]) } } }
                        Item { width: 1; height: 6 }
                        EditSlider { key: "straighten"; label: "Straighten"; lo: -45; hi: 45 }
                        Row { spacing: 8
                            Btn { text: "Turn"; onClicked: Backend.turnEdit() }
                            Btn { text: "Flip"; onClicked: Backend.flipEdit() }
                            Btn { text: "Reset"; onClicked: Backend.resetEdit("crop") } }
                        Label { width: parent.width; wrapMode: Text.WordWrap; secondary: true; font.pixelSize: 11; text: "Drag the corners, or drag inside the frame to move it. Straightening trims the edges so no empty corners show." } }
                } } }
    }
    Rectangle { visible: win.asking !== null; anchors.fill: parent; radius: win.r; color: "#66000000"; z: 30; MouseArea { anchors.fill: parent } }
    Rectangle { visible: win.asking !== null; z: 31; anchors.centerIn: parent; width: 380; height: 160; radius: Theme.t.radiusTile; color: Theme.t.menu_bg; border.width: 1; border.color: Theme.t.menu_border
        Label { x: 22; y: 20; text: "Move this picture to the Trash?"; font.pixelSize: 16; font.weight: Font.DemiBold }
        Label { x: 22; y: 50; width: parent.width - 44; wrapMode: Text.WordWrap; secondary: true; text: "You can get it back from the Trash until you empty it." }
        Row { anchors { right: parent.right; rightMargin: 22; bottom: parent.bottom; bottomMargin: 20 } spacing: 8
            Btn { text: "Cancel"; onClicked: win.asking = null } Btn { text: "Move to Trash"; danger: true; onClicked: { Backend.trash(win.asking.path); win.asking = null; if (win.viewing >= win.shown.length) win.viewing = win.shown.length - 1 } } } }
}
