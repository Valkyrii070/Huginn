import QtQuick

// Scan, "the light table": the page you're working on lies in the middle on a pool of warm light, the document's
// pages run down a strip at the left like paper on a desk, and the right island is the scanner itself, with its big
// amber button. Photos of pages are straightened by dragging four corners; Read Text and Save make a searchable PDF.
GlassWindow {
    id: win
    title: "Scan"; heading: Backend.name; glow: "centre"; glowX: 0.47; glowY: 0.46; width: 1240; height: 820; minimumWidth: 940; minimumHeight: 600
    property string sheet: ""                       // photos, rename
    property string side: "scan"                    // scan | text | save
    property bool edges: false                      // dragging the page's corners
    readonly property var pg: Backend.page
    readonly property bool hasPage: !!pg.id
    readonly property color amber: Theme.t.accent
    Connections { target: Backend; function onSaid(msg, bad) { toast.say(msg, bad) } }
    Shortcut { sequence: "Ctrl+S"; onActivated: Backend.savePdf() }
    Shortcut { sequence: "Delete"; enabled: win.hasPage && win.sheet === ""; onActivated: Backend.remove(Backend.current) }
    Shortcut { sequence: "Ctrl+R"; onActivated: if (win.hasPage) Backend.turn(Backend.current, 90) }
    DropArea { anchors.fill: parent; onDropped: function (d) { if (d.hasUrls) Backend.addFiles(d.urls) } }

    toolbar: [
        Seg { icon: "type"; text: "Read Text"; enabled: Backend.canRead && Backend.pages.length > 0; opacity: enabled ? 1 : 0.45; onClicked: { win.side = "text"; Backend.readPage(-1) } },
        Seg { objectName: "savePdf"; icon: "download"; text: "Save PDF"; enabled: Backend.pages.length > 0 && !Backend.busy; opacity: enabled ? 1 : 0.45; onClicked: Backend.savePdf() },
        Seg { icon: "edit"; tip: "Rename"; onClicked: { nameBox.text = Backend.name; win.sheet = "rename"; nameBox.focusIn() } }
    ]

    // ---------------------------------------------------------------- the pages, down the left
    Rectangle { id: strip; objectName: "strip"; x: 12; y: 64; width: 150; height: parent.height - 76; radius: 18; color: Theme.t.island; border.width: 1; border.color: Theme.t.islandLine
        Label { x: 14; y: 12; text: Backend.pages.length === 1 ? "1 page" : Backend.pages.length + " pages"; font.pixelSize: 11; secondary: true; font.weight: Font.DemiBold }
        ListView { id: pagesList; objectName: "pagesList"; x: 10; y: 34; width: parent.width - 20; height: parent.height - 34 - 58; clip: true; spacing: 12; model: Backend.pages
            boundsBehavior: Flickable.StopAtBounds
            delegate: Item { id: tile; required property var modelData; required property int index; width: pagesList.width; height: 168
                readonly property bool on: Backend.current === index
                Rectangle { anchors.horizontalCenter: parent.horizontalCenter; y: 4; width: 112; height: 146; radius: 4; color: "#33000000"; x: 3 }
                Rectangle { id: paper; anchors.horizontalCenter: parent.horizontalCenter; width: 112; height: 146; radius: 4; color: "#FFFFFF"; clip: true
                    border.width: tile.on ? 3 : 0; border.color: win.amber
                    Image { anchors { fill: parent; margins: tile.on ? 3 : 0 } source: tile.modelData.src; sourceSize: Qt.size(240, 320); fillMode: Image.PreserveAspectFit; asynchronous: true; cache: false } }
                Rectangle { visible: tile.modelData.hasText; anchors { right: paper.right; bottom: paper.bottom; margins: 5 } width: 20; height: 20; radius: 10; color: win.amber
                    Glyph { anchors.centerIn: parent; name: "type"; size: 11; ink: Theme.t.onAccent } }
                Label { anchors { horizontalCenter: parent.horizontalCenter; top: paper.bottom; topMargin: 3 } text: tile.index + 1; font.pixelSize: 11; font.weight: tile.on ? Font.Bold : Font.Normal; secondary: !tile.on }
                MouseArea { anchors.fill: paper; onClicked: Backend.select(tile.index) }
                Row { visible: tile.on && Backend.pages.length > 1; anchors { left: paper.left; top: paper.top; margins: 4 } spacing: 2
                    Pressable { visible: tile.index > 0; width: 22; height: 22; radius: 6; color: "#CC111111"; onClicked: Backend.move(tile.index, tile.index - 1)
                        Glyph { anchors.centerIn: parent; name: "up"; size: 11; ink: "#FFFFFF" } }
                    Pressable { visible: tile.index < Backend.pages.length - 1; width: 22; height: 22; radius: 6; color: "#CC111111"; onClicked: Backend.move(tile.index, tile.index + 1)
                        Glyph { anchors.centerIn: parent; name: "down"; size: 11; ink: "#FFFFFF" } } } } }
        Pressable { anchors { horizontalCenter: parent.horizontalCenter; bottom: parent.bottom; bottomMargin: 12 } width: parent.width - 20; height: 38; radius: 12
            color: hovered ? Theme.t.hover : (Theme.t.dark ? "#14FFFFFF" : "#0C141E28"); onClicked: { photoList.model = Backend.photoChoices(); win.sheet = "photos" }
            Row { anchors.centerIn: parent; spacing: 6; Glyph { name: "image"; size: 14; anchors.verticalCenter: parent.verticalCenter } Label { text: "Add photos"; font.pixelSize: 12; anchors.verticalCenter: parent.verticalCenter } } } }

    // ---------------------------------------------------------------- the light table
    Item { id: table; objectName: "table"; x: strip.width + 24; y: 64; width: sideIsland.x - x - 12; height: parent.height - 64 - 76
        // a pool of light under the page
        Rectangle { anchors.centerIn: parent; width: parent.width * 0.86; height: parent.height * 0.92; radius: width / 2; opacity: Theme.t.dark ? 0.16 : 0.22
            gradient: Gradient { GradientStop { position: 0; color: "transparent" } GradientStop { position: 0.5; color: win.amber } GradientStop { position: 1; color: "transparent" } } }
        // the page as it'll be saved
        Item { id: sheetArea; visible: win.hasPage && !win.edges; anchors.fill: parent; anchors.margins: 18
            readonly property real ar: bigPage.status === Image.Ready ? bigPage.implicitWidth / Math.max(1, bigPage.implicitHeight) : 0.72
            readonly property real pw: Math.min(width, height * ar)
            Rectangle { x: (parent.width - sheetArea.pw) / 2 + 6; y: (parent.height - sheetArea.pw / sheetArea.ar) / 2 + 10; width: sheetArea.pw; height: sheetArea.pw / sheetArea.ar; radius: 3; color: "#40000000" }
            Rectangle { x: (parent.width - sheetArea.pw) / 2; y: (parent.height - sheetArea.pw / sheetArea.ar) / 2; width: sheetArea.pw; height: sheetArea.pw / sheetArea.ar; radius: 3; color: "#FFFFFF"; clip: true
                Image { id: bigPage; objectName: "bigPage"; anchors.fill: parent; source: win.hasPage ? Backend.pages[Backend.current].src : ""; sourceSize: Qt.size(1800, 1800)
                    fillMode: Image.PreserveAspectFit; asynchronous: true; cache: false; smooth: true; mipmap: true } } }
        // the photo as it came, with the four corners to drag
        Item { id: edgeArea; objectName: "edgeArea"; visible: win.hasPage && win.edges; anchors.fill: parent; anchors.margins: 18
            readonly property real ar: (win.pg.width || 3) / Math.max(1, win.pg.height || 4)
            readonly property real iw: Math.min(width, height * ar)
            readonly property real ih: iw / ar
            readonly property real ox: (width - iw) / 2
            readonly property real oy: (height - ih) / 2
            property var pts: win.pg.corners || [[0, 0], [1, 0], [1, 1], [0, 1]]
            Connections { target: Backend; function onChanged() { edgeArea.pts = win.pg.corners || [[0, 0], [1, 0], [1, 1], [0, 1]]; outline.requestPaint() } }
            Image { x: edgeArea.ox; y: edgeArea.oy; width: edgeArea.iw; height: edgeArea.ih; source: win.edges && win.hasPage ? win.pg.original : ""; fillMode: Image.Stretch; asynchronous: true; cache: false }
            Canvas { id: outline; anchors.fill: parent
                onPaint: { var c = getContext("2d"); c.reset(); var p = edgeArea.pts; if (!p || p.length < 4) return
                    function at(k) { return [edgeArea.ox + p[k][0] * edgeArea.iw, edgeArea.oy + p[k][1] * edgeArea.ih] }
                    c.fillStyle = "rgba(0,0,0,0.45)"; c.beginPath(); c.rect(0, 0, width, height)
                    c.moveTo(at(0)[0], at(0)[1]); for (var k = 3; k >= 0; k--) c.lineTo(at(k)[0], at(k)[1]); c.closePath(); c.fill("evenodd")
                    c.strokeStyle = win.amber; c.lineWidth = 2.5; c.beginPath(); c.moveTo(at(0)[0], at(0)[1]); for (var j = 1; j < 4; j++) c.lineTo(at(j)[0], at(j)[1]); c.closePath(); c.stroke() } }
            Repeater { model: 4
                Rectangle { id: knob; required property int index; width: 30; height: 30; radius: 15; color: "#E6FFFFFF"; border.width: 3; border.color: win.amber
                    x: edgeArea.ox + edgeArea.pts[index][0] * edgeArea.iw - 15; y: edgeArea.oy + edgeArea.pts[index][1] * edgeArea.ih - 15
                    MouseArea { anchors.fill: parent; anchors.margins: -8; preventStealing: true; cursorShape: Qt.SizeAllCursor
                        onPositionChanged: function (m) { var q = mapToItem(edgeArea, m.x, m.y), p = edgeArea.pts.slice()
                            p[knob.index] = [Math.max(0, Math.min(1, (q.x - edgeArea.ox) / edgeArea.iw)), Math.max(0, Math.min(1, (q.y - edgeArea.oy) / edgeArea.ih))]
                            edgeArea.pts = p; outline.requestPaint() }
                        onReleased: Backend.setCorners(Backend.current, edgeArea.pts) } } } }
        // nothing yet
        Column { visible: !win.hasPage; anchors.centerIn: parent; spacing: 14; width: Math.min(460, parent.width - 40)
            Item { width: 180; height: 150; anchors.horizontalCenter: parent.horizontalCenter
                Rectangle { x: 52; y: 10; width: 96; height: 128; radius: 4; color: "#FFFFFF"; rotation: 8; opacity: 0.5 }
                Rectangle { x: 34; y: 14; width: 96; height: 128; radius: 4; color: "#FFFFFF"
                    Column { x: 14; y: 18; spacing: 9; Repeater { model: 7; Rectangle { required property int index; width: index === 0 ? 50 : 68 - (index % 3) * 10; height: index === 0 ? 7 : 4; radius: 2; color: index === 0 ? "#2B2B30" : "#B5B5BD" } } } } }
            Label { anchors.horizontalCenter: parent.horizontalCenter; text: "Nothing scanned yet"; font.pixelSize: 19; font.weight: Font.DemiBold }
            Label { width: parent.width; horizontalAlignment: Text.AlignHCenter; wrapMode: Text.WordWrap; secondary: true
                text: "Put a page on the scanner and press Scan, or drop photos of pages here: Scan finds the paper and straightens it." }
            Column { visible: Backend.recent.length > 0; width: parent.width; spacing: 4; topPadding: 10
                Label { text: "RECENT SCANS"; font.pixelSize: 10; font.weight: Font.Bold; font.letterSpacing: 1.2; secondary: true }
                Repeater { model: Backend.recent.slice(0, 4)
                    Pressable { required property var modelData; width: parent.width; height: 40; radius: 10; color: hovered ? Theme.t.hover : "transparent"; onClicked: Backend.open(modelData.path)
                        Glyph { x: 10; anchors.verticalCenter: parent.verticalCenter; name: "doc"; size: 16 }
                        Label { x: 36; anchors.verticalCenter: parent.verticalCenter; width: parent.width - 170; elide: Text.ElideRight; text: modelData.name }
                        Label { anchors { right: parent.right; rightMargin: 10; verticalCenter: parent.verticalCenter } text: modelData.when + "  ·  " + modelData.size; font.pixelSize: 11; secondary: true } } } } } }

    // ---------------------------------------------------------------- the page's tools, under the table
    Rectangle { id: tools; objectName: "pageTools"; visible: win.hasPage; height: 48; width: toolRow.width + 20; radius: 18; color: Theme.t.island; border.width: 1; border.color: Theme.t.islandLine
        x: table.x + (table.width - width) / 2; y: table.y + table.height + 14
        Row { id: toolRow; x: 10; anchors.verticalCenter: parent.verticalCenter; spacing: 3
            Seg { icon: "undo"; tip: "Turn left"; onClicked: Backend.turn(Backend.current, -90) }
            Seg { icon: "redo"; tip: "Turn right (Ctrl+R)"; onClicked: Backend.turn(Backend.current, 90) }
            IslandGap {}
            Seg { objectName: "edgesBtn"; icon: "crop"; text: win.edges ? "Done" : "Edges"; on: win.edges; tip: "Drag the page's four corners"; onClicked: win.edges = !win.edges }
            Seg { visible: win.edges; text: "Find Again"; onClicked: Backend.findEdges(Backend.current) }
            Seg { visible: win.edges; text: "Whole Picture"; onClicked: Backend.wholePicture(Backend.current) }
            IslandGap {}
            Repeater { model: Backend.modes
                Seg { required property var modelData; text: modelData.name; on: win.pg.mode === modelData.id; onClicked: Backend.setMode(Backend.current, modelData.id) } }
            Seg { visible: Backend.pages.length > 1; text: "All Pages"; tip: "Clean up every page this way"; onClicked: Backend.setMode(-1, win.pg.mode) }
            IslandGap {}
            Seg { icon: "trash"; tip: "Remove this page (Delete)"; danger: true; onClicked: Backend.remove(Backend.current) } } }

    // ---------------------------------------------------------------- the scanner, the text and saving
    Rectangle { id: sideIsland; objectName: "sideIsland"; x: parent.width - width - 12; y: 64; width: 300; height: parent.height - 76; radius: 18; color: Theme.t.island; border.width: 1; border.color: Theme.t.islandLine; clip: true
        Row { id: tabs; x: 12; y: 12; spacing: 2
            Seg { text: "Scanner"; on: win.side === "scan"; onClicked: win.side = "scan" }
            Seg { text: "Text"; on: win.side === "text"; onClicked: win.side = "text" }
            Seg { text: "Save"; on: win.side === "save"; onClicked: win.side = "save" } }
        Flickable { x: 16; y: 56; width: parent.width - 32; height: parent.height - 56 - 12; contentHeight: sideCol.height + 10; clip: true; boundsBehavior: Flickable.StopAtBounds
            Column { id: sideCol; width: parent.width; spacing: 10
                // ---- the scanner
                Column { visible: win.side === "scan"; width: parent.width; spacing: 10
                    Item { width: parent.width; height: 168
                        // the big round button, with a ring that fills as the page goes through
                        Canvas { id: ring; anchors.centerIn: btn; width: 148; height: 148; property real v: Backend.share; onVChanged: requestPaint()
                            onPaint: { var c = getContext("2d"); c.reset(); c.lineWidth = 6; c.strokeStyle = Theme.t.dark ? "rgba(255,255,255,0.08)" : "rgba(0,0,0,0.08)"
                                c.beginPath(); c.arc(74, 74, 70, 0, Math.PI * 2); c.stroke()
                                if (Backend.busy) { c.strokeStyle = win.amber; c.beginPath(); c.arc(74, 74, 70, -Math.PI / 2, -Math.PI / 2 + Math.PI * 2 * Math.max(0.03, v)); c.stroke() } } }
                        Pressable { id: btn; objectName: "scanBtn"; anchors.centerIn: parent; width: 124; height: 124; radius: 62; enabled: !Backend.busy || Backend.busy === "Scanning…"
                            color: hovered ? Qt.lighter(win.amber, 1.08) : win.amber
                            onClicked: Backend.busy === "Scanning…" ? Backend.stop() : Backend.scan()
                            Column { anchors.centerIn: parent; spacing: 2
                                Glyph { anchors.horizontalCenter: parent.horizontalCenter; name: Backend.busy === "Scanning…" ? "stop" : "doc"; size: 26; ink: Theme.t.onAccent }
                                Text { anchors.horizontalCenter: parent.horizontalCenter; text: Backend.busy === "Scanning…" ? "Stop" : "Scan"; color: Theme.t.onAccent; font.pixelSize: 16; font.weight: Font.Bold } } } }
                    Label { width: parent.width; horizontalAlignment: Text.AlignHCenter; wrapMode: Text.WordWrap; secondary: true; font.pixelSize: 11
                        text: Backend.busy ? Backend.busy + (Backend.share > 0 ? " " + Math.round(Backend.share * 100) + "%" : "") : Backend.scanners.length ? "" : "No scanner found. You can still add photos of pages." }
                    Label { visible: Backend.scanners.length > 0; text: "SCANNER"; font.pixelSize: 10; font.weight: Font.Bold; font.letterSpacing: 1.2; secondary: true }
                    Repeater { model: Backend.scanners
                        Pressable { required property var modelData; width: sideCol.width; height: 44; radius: 12
                            readonly property bool on: Backend.scanner === modelData.id
                            color: on ? Qt.rgba(win.amber.r, win.amber.g, win.amber.b, 0.18) : hovered ? Theme.t.hover : "transparent"; border.width: on ? 1 : 0; border.color: win.amber
                            onClicked: Backend.chooseScanner(modelData.id)
                            Glyph { x: 10; anchors.verticalCenter: parent.verticalCenter; name: "printer"; size: 16 }
                            Column { x: 36; anchors.verticalCenter: parent.verticalCenter; width: parent.width - 46
                                Label { width: parent.width; elide: Text.ElideRight; text: modelData.name; font.pixelSize: 12; font.weight: Font.DemiBold }
                                Label { width: parent.width; elide: Text.ElideRight; text: modelData.kind; font.pixelSize: 10; secondary: true } } } }
                    Btn { text: "Look Again"; onClicked: Backend.refresh() }
                    Label { visible: (Backend.options.sources || []).length > 0; text: "FROM"; font.pixelSize: 10; font.weight: Font.Bold; font.letterSpacing: 1.2; secondary: true }
                    Flow { width: parent.width; spacing: 4; visible: (Backend.options.sources || []).length > 0
                        Repeater { model: Backend.options.sources || []
                            Seg { required property string modelData; anchors.verticalCenter: undefined
                                text: /duplex/i.test(modelData) ? "Feeder, both sides" : /adf|feeder/i.test(modelData) ? "Feeder" : /flatbed/i.test(modelData) ? "Glass" : modelData
                                on: Backend.choice.source === modelData; onClicked: Backend.setChoice("source", modelData) } } }
                    Label { visible: (Backend.options.modes || []).length > 0; text: "COLOUR"; font.pixelSize: 10; font.weight: Font.Bold; font.letterSpacing: 1.2; secondary: true }
                    Flow { width: parent.width; spacing: 4
                        Repeater { model: Backend.options.modes || []
                            Seg { required property string modelData; anchors.verticalCenter: undefined
                                text: /color|colour/i.test(modelData) ? "Colour" : /gray|grey/i.test(modelData) ? "Grey" : /lineart|binary|black/i.test(modelData) ? "Black and white" : modelData
                                on: Backend.choice.mode === modelData; onClicked: Backend.setChoice("mode", modelData) } } }
                    Label { visible: (Backend.options.resolutions || []).length > 0; text: "DETAIL"; font.pixelSize: 10; font.weight: Font.Bold; font.letterSpacing: 1.2; secondary: true }
                    Flow { width: parent.width; spacing: 4
                        Repeater { model: Backend.options.resolutions || []
                            Seg { required property int modelData; anchors.verticalCenter: undefined; text: modelData + (modelData === 300 ? " (best for text)" : "")
                                on: Backend.choice.dpi === modelData; onClicked: Backend.setChoice("dpi", modelData) } } } }
                // ---- the words
                Column { visible: win.side === "text"; width: parent.width; spacing: 10
                    Label { width: parent.width; wrapMode: Text.WordWrap; secondary: true; font.pixelSize: 11
                        text: Backend.canRead ? "Scan reads the words on the pages (Tesseract, on this computer) so the PDF can be searched, and you can copy them." : "Reading text needs Tesseract." }
                    Flow { visible: Backend.canRead; width: parent.width; spacing: 4
                        Repeater { model: Backend.languages.slice(0, 12)
                            Seg { required property string modelData; anchors.verticalCenter: undefined; text: Qt.locale(modelData.substring(0, 2)).nativeLanguageName || modelData
                                on: Backend.choice.lang === modelData; onClicked: Backend.setChoice("lang", modelData) } } }
                    Row { spacing: 6; visible: Backend.canRead
                        Btn { text: "Read This Page"; enabled: win.hasPage && !Backend.busy; onClicked: Backend.readPage(Backend.current) }
                        Btn { text: "Read All"; enabled: Backend.pages.length > 0 && !Backend.busy; onClicked: Backend.readPage(-1) } }
                    Label { visible: Backend.busy !== "" && win.side === "text"; text: Backend.busy + " " + Math.round(Backend.share * 100) + "%"; secondary: true; font.pixelSize: 11 }
                    Rectangle { visible: win.hasPage && win.pg.text !== ""; width: parent.width; height: Math.max(120, words.contentHeight + 24); radius: 12; color: Theme.t.dark ? "#18000000" : "#0A000000"
                        TextEdit { id: words; objectName: "words"; x: 12; y: 12; width: parent.width - 24; readOnly: true; selectByMouse: true; wrapMode: TextEdit.Wrap; text: win.pg.text || ""
                            color: Theme.t.text; font.pixelSize: 12; selectionColor: win.amber } }
                    Btn { visible: win.hasPage && win.pg.text !== ""; text: "Copy All the Text"; onClicked: { copier.text = Backend.allText(); copier.selectAll(); copier.copy(); toast.say("Copied", false) } }
                    TextEdit { id: copier; visible: false } }
                // ---- saving
                Column { visible: win.side === "save"; width: parent.width; spacing: 10
                    Label { text: "PAPER"; font.pixelSize: 10; font.weight: Font.Bold; font.letterSpacing: 1.2; secondary: true }
                    Flow { width: parent.width; spacing: 4
                        Repeater { model: Backend.papers
                            Seg { required property var modelData; anchors.verticalCenter: undefined; text: modelData.name; on: Backend.choice.paper === modelData.id; onClicked: Backend.setChoice("paper", modelData.id) } } }
                    Row { spacing: 10; height: 36; visible: Backend.canRead
                        Toggle { anchors.verticalCenter: parent.verticalCenter; on: !!Backend.choice.searchable; onToggled: function (v) { Backend.setChoice("searchable", v) } }
                        Label { anchors.verticalCenter: parent.verticalCenter; text: "Text you can search and copy"; font.pixelSize: 12 } }
                    Btn { primary: true; width: parent.width; text: Backend.busy === "Making the PDF…" ? "Making the PDF…" : "Save as PDF"; enabled: Backend.pages.length > 0 && !Backend.busy; onClicked: Backend.savePdf() }
                    Btn { width: parent.width; text: "Save as Pictures"; enabled: Backend.pages.length > 0 && !Backend.busy; onClicked: Backend.saveImages() }
                    Label { width: parent.width; wrapMode: Text.WordWrap; secondary: true; font.pixelSize: 11; text: "Saved in Documents/Scans, never over another file." }
                    Seg { anchors.verticalCenter: undefined; text: "Show the Scans Folder"; onClicked: Backend.showFolder() }
                    Label { visible: Backend.recent.length > 0; text: "RECENT"; font.pixelSize: 10; font.weight: Font.Bold; font.letterSpacing: 1.2; secondary: true; topPadding: 6 }
                    Repeater { model: Backend.recent
                        Pressable { required property var modelData; width: sideCol.width; height: 40; radius: 10; color: hovered ? Theme.t.hover : "transparent"; onClicked: Backend.open(modelData.path)
                            Glyph { x: 8; anchors.verticalCenter: parent.verticalCenter; name: "doc"; size: 15 }
                            Column { x: 32; anchors.verticalCenter: parent.verticalCenter; width: parent.width - 40
                                Label { width: parent.width; elide: Text.ElideRight; text: modelData.name; font.pixelSize: 12 }
                                Label { text: modelData.when + "  ·  " + modelData.size; font.pixelSize: 10; secondary: true } } } }
                    Item { width: 1; height: 8 }
                    Seg { anchors.verticalCenter: undefined; text: "Start a New Document"; danger: true; onClicked: Backend.startOver() } } } } }

    Toast { id: toast; z: 50; anchors { horizontalCenter: parent.horizontalCenter; bottom: parent.bottom; bottomMargin: 80 } }

    // ---------------------------------------------------------------- sheets
    Item { anchors.fill: parent; z: 40; visible: win.sheet !== ""
        Rectangle { anchors.fill: parent; radius: win.r; color: "#77000000"; MouseArea { anchors.fill: parent; onClicked: win.sheet = "" } }
        Rectangle { anchors.centerIn: parent; width: 600; height: win.sheet === "rename" ? 170 : Math.min(win.height - 100, 520); radius: 18; color: Theme.t.menu_bg; border.width: 1; border.color: Theme.t.menu_border
            MouseArea { anchors.fill: parent }
            Label { x: 24; y: 20; font.pixelSize: 17; font.weight: Font.DemiBold; text: win.sheet === "rename" ? "Name this document" : "Add photos of pages" }
            TextBox { id: nameBox; visible: win.sheet === "rename"; x: 24; y: 62; width: parent.width - 48; onAccepted: { Backend.rename(text); win.sheet = "" } }
            Label { visible: win.sheet === "photos"; x: 24; y: 48; width: parent.width - 48; wrapMode: Text.WordWrap; secondary: true; font.pixelSize: 12
                text: photoList.count ? "From Pictures and Downloads. Pick as many as you like; you can also drop pictures on the window." : "No pictures in Pictures or Downloads. Drop photos of pages on the window instead." }
            GridView { id: photoList; visible: win.sheet === "photos"; x: 20; y: 80; width: parent.width - 40; height: parent.height - 80 - 64; clip: true; cellWidth: width / 4; cellHeight: 150
                property var chosen: []
                delegate: Item { required property var modelData; width: photoList.cellWidth; height: photoList.cellHeight
                    readonly property bool on: photoList.chosen.indexOf(modelData.url) >= 0
                    Rectangle { anchors { fill: parent; margins: 6 } radius: 10; color: Theme.t.dark ? "#22FFFFFF" : "#11000000"; border.width: parent.on ? 3 : 0; border.color: win.amber; clip: true
                        Image { anchors { fill: parent; margins: 3 } source: modelData.url; sourceSize: Qt.size(220, 220); fillMode: Image.PreserveAspectCrop; asynchronous: true } }
                    MouseArea { anchors.fill: parent; onClicked: { var c = photoList.chosen.slice(), k = c.indexOf(modelData.url); if (k >= 0) c.splice(k, 1); else c.push(modelData.url); photoList.chosen = c } } } }
            Row { anchors { right: parent.right; rightMargin: 20; bottom: parent.bottom; bottomMargin: 16 } spacing: 8
                Btn { text: "Cancel"; onClicked: win.sheet = "" }
                Btn { primary: true; text: win.sheet === "rename" ? "Rename" : photoList.chosen.length ? "Add " + photoList.chosen.length : "Add"
                    enabled: win.sheet === "rename" || photoList.chosen.length > 0
                    onClicked: { if (win.sheet === "rename") Backend.rename(nameBox.text); else { Backend.addFiles(photoList.chosen); photoList.chosen = [] } win.sheet = "" } } } } }
}
