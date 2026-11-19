import QtQuick

// Print & Scan, "two trays": one window, two jobs. Paper going out on the left tab, paper coming in on the right.
GlassWindow {
    id: win
    title: "Print & Scan"; width: 940; height: 640; glow: "top"
    readonly property color pick: Qt.rgba(tintColor.r, tintColor.g, tintColor.b, 0.18)
    property string tab: Backend.file !== "" || Backend.scanners.length === 0 ? "print" : "print"
    function setTab(t) { tab = t === "scan" ? "scan" : "print" }
    property string printer: ""
    property string scanner: ""
    property int copies: 1
    property bool twoSided: false
    property bool colour: true
    property string paper: ""
    property bool grey: false
    property bool fit: false
    property bool landscape: false
    property int dpi: 300
    property bool choosing: false
    property string lastPdf: ""
    readonly property var chosenPrinter: { var p = Backend.printers; for (var i = 0; i < p.length; i++) if (p[i].name === printer) return p[i]; return {} }
    function settle() { var p = Backend.printers; if (!chosenPrinter.name && p.length) { var d = p[0]; for (var i = 0; i < p.length; i++) if (p[i]["default"]) d = p[i]; printer = d.name }
        var s = Backend.scanners; if (s.length && !s.some(function (x) { return x.id === scanner })) scanner = s[0].id }
    Connections { target: Backend; function onSaid(msg, wrong) { toast.say(msg, wrong) } function onChanged() { win.settle() } }
    Component.onCompleted: settle()

    islands: [
        Island { anchors.horizontalCenter: parent.horizontalCenter; y: 12
            Seg { icon: "printer"; text: "Print"; on: win.tab === "print"; onClicked: win.tab = "print" }
            Seg { icon: "image"; text: "Scan" + (Backend.pages.length ? " · " + Backend.pages.length : ""); on: win.tab === "scan"; onClicked: win.tab = "scan" } },
        Toast { id: toast; anchors { horizontalCenter: parent.horizontalCenter; bottom: parent.bottom; bottomMargin: 18 } },
        Item { anchors.fill: parent; z: 20; visible: win.choosing
            Rectangle { anchors.fill: parent; radius: win.r; color: "#66000000"; MouseArea { anchors.fill: parent; acceptedButtons: Qt.AllButtons; onClicked: win.choosing = false } }
            Rectangle { anchors.centerIn: parent; width: 460; height: 120 + Math.max(1, Backend.choices.length) * 36; radius: 16; color: Theme.t.menu_bg; border.width: 1; border.color: Theme.t.menu_border
                MouseArea { anchors.fill: parent }
                Label { x: 22; y: 20; font.pixelSize: 16; font.weight: Font.DemiBold; text: "What to print" }
                Column { x: 16; y: 52; width: parent.width - 32
                    Label { visible: Backend.choices.length === 0; x: 6; height: 36; verticalAlignment: Text.AlignVCenter; secondary: true; text: "No recent documents or pictures. Open one from Files with Print & Scan." }
                    Repeater { model: win.choosing ? Backend.choices : []
                        Pressable { required property var modelData; width: parent.width; height: 36; radius: 9; onClicked: { Backend.choose(modelData.path); win.choosing = false }
                            Glyph { x: 10; anchors.verticalCenter: parent.verticalCenter; name: "file"; size: 14; ink: Theme.t.text_secondary }
                            Label { x: 34; width: parent.width - 170; elide: Text.ElideMiddle; anchors.verticalCenter: parent.verticalCenter; text: modelData.name }
                            Label { anchors { right: parent.right; rightMargin: 10; verticalCenter: parent.verticalCenter } text: modelData.where + " · " + modelData.size; secondary: true; font.pixelSize: 11 } } } }
                Btn { anchors { right: parent.right; rightMargin: 22; bottom: parent.bottom; bottomMargin: 18 } text: "Cancel"; onClicked: win.choosing = false } } }
    ]

    component Chip: Pressable { property bool on: false; property alias text: cl.text; width: cl.width + 18; height: 28; radius: 9; color: on ? win.pick : "transparent"; border.width: 1; border.color: on ? Theme.t.accent : Theme.t.capsule_border
        Label { id: cl; anchors.centerIn: parent; font.pixelSize: 12 } }

    // ---------------- printing
    Item { visible: win.tab === "print"; anchors { fill: parent; topMargin: 68; leftMargin: 22; rightMargin: 22; bottomMargin: 20 }
        Column { visible: Backend.printers.length === 0; anchors.centerIn: parent; spacing: 10; width: 440
            Glyph { name: "printer"; size: 54; ink: Theme.t.accent; anchors.horizontalCenter: parent.horizontalCenter }
            Label { anchors.horizontalCenter: parent.horizontalCenter; font.pixelSize: 20; font.weight: Font.DemiBold; text: Backend.hasPrint ? "No printers yet" : "Printing isn't set up" }
            Label { width: parent.width; wrapMode: Text.WordWrap; horizontalAlignment: Text.AlignHCenter; secondary: true
                text: Backend.hasPrint ? "Switch the printer on and put it on the same network, or plug it in. Most printers made in the last ten years appear here by themselves within a minute."
                                       : "This computer has no printing system (CUPS). Install the cups package and open Print & Scan again." } }
        Row { visible: Backend.printers.length > 0; anchors.fill: parent; spacing: 18
            Column { width: 300; spacing: 8
                Label { text: "PRINTERS"; secondary: true; font.pixelSize: 10; font.weight: Font.DemiBold }
                Repeater { model: Backend.printers
                    Pressable { required property var modelData; width: 300; height: 56; radius: 12; color: win.printer === modelData.name ? win.pick : hovered ? Theme.t.hover : Theme.t.island; border.width: 1
                        border.color: win.printer === modelData.name ? Theme.t.accent : Theme.t.islandLine; onClicked: win.printer = modelData.name
                        Glyph { x: 14; anchors.verticalCenter: parent.verticalCenter; name: "printer"; size: 20; ink: modelData.ok ? Theme.t.accent : Theme.t.text_secondary }
                        Label { x: 46; y: 10; width: parent.width - 60; elide: Text.ElideRight; text: modelData.label; font.weight: Font.Medium }
                        Label { x: 46; y: 30; font.pixelSize: 11; color: modelData.ok ? Theme.t.text_secondary : Theme.t.danger; text: modelData.state + (modelData["default"] ? "  ·  the usual one" : "") } } }
                Btn { visible: !!win.chosenPrinter.name && !win.chosenPrinter["default"]; height: 28; text: "Make This the Usual One"; onClicked: Backend.makeDefault(win.printer) }
                Item { width: 1; height: 8 }
                Label { visible: Backend.jobs.length > 0; text: "WAITING TO PRINT"; secondary: true; font.pixelSize: 10; font.weight: Font.DemiBold }
                Repeater { model: Backend.jobs
                    Rectangle { required property var modelData; width: 300; height: 44; radius: 10; color: Theme.t.island; border.width: 1; border.color: Theme.t.islandLine
                        Label { x: 12; y: 6; text: modelData.printer; font.pixelSize: 12 } Label { x: 12; y: 23; text: modelData.size + (modelData.when ? "  ·  " + modelData.when : ""); secondary: true; font.pixelSize: 11 }
                        Btn { anchors { right: parent.right; rightMargin: 8; verticalCenter: parent.verticalCenter } height: 26; text: "Cancel"; onClicked: Backend.cancel(modelData.id) } } } }
            Rectangle { width: parent.width - 318; height: parent.height; radius: 16; color: Theme.t.island; border.width: 1; border.color: Theme.t.islandLine
                Column { x: 22; y: 20; width: parent.width - 44; spacing: 12
                    Label { text: "Print"; font.pixelSize: 20; font.weight: Font.Bold }
                    Pressable { width: parent.width; height: 52; radius: 12; color: hovered ? Theme.t.hover : "transparent"; border.width: 1; border.color: Theme.t.capsule_border; onClicked: win.choosing = true
                        Glyph { x: 14; anchors.verticalCenter: parent.verticalCenter; name: "file"; size: 18; ink: Theme.t.accent }
                        Label { x: 44; width: parent.width - 130; elide: Text.ElideMiddle; anchors.verticalCenter: parent.verticalCenter; text: Backend.fileName || "Choose a document or picture…"; opacity: Backend.fileName ? 1 : 0.6 }
                        Label { anchors { right: parent.right; rightMargin: 14; verticalCenter: parent.verticalCenter } text: "Change"; secondary: true; font.pixelSize: 12; visible: Backend.fileName !== "" } }
                    Row { spacing: 10; Label { text: "Copies"; width: 80; anchors.verticalCenter: parent.verticalCenter }
                        Chip { text: "–"; onClicked: win.copies = Math.max(1, win.copies - 1) } Label { text: win.copies; width: 26; horizontalAlignment: Text.AlignHCenter; anchors.verticalCenter: parent.verticalCenter; font.weight: Font.DemiBold } Chip { text: "+"; onClicked: win.copies = Math.min(99, win.copies + 1) } }
                    Row { spacing: 10; Label { text: "Paper"; width: 80; anchors.verticalCenter: parent.verticalCenter }
                        Chip { text: "One side"; on: !win.twoSided; onClicked: win.twoSided = false } Chip { text: "Both sides"; on: win.twoSided; onClicked: win.twoSided = true } }
                    Row { spacing: 6; Label { text: "Size"; width: 84; anchors.verticalCenter: parent.verticalCenter }
                        Repeater { model: [["", "Printer's own"], ["a4", "A4"], ["letter", "Letter"], ["legal", "Legal"], ["photo", "4×6 photo"]]
                            Chip { required property var modelData; text: modelData[1]; on: win.paper === modelData[0]; onClicked: win.paper = modelData[0] } } }
                    Row { spacing: 6; Label { text: "Ink"; width: 84; anchors.verticalCenter: parent.verticalCenter }
                        Chip { text: "Colour"; on: !win.grey; onClicked: win.grey = false } Chip { text: "Black only"; on: win.grey; onClicked: win.grey = true } }
                    Row { spacing: 6; Label { text: "Layout"; width: 84; anchors.verticalCenter: parent.verticalCenter }
                        Chip { text: "Upright"; on: !win.landscape; onClicked: win.landscape = false } Chip { text: "Sideways"; on: win.landscape; onClicked: win.landscape = true } Chip { text: "Fill the page"; on: win.fit; onClicked: win.fit = !win.fit } }
                    Row { spacing: 10; Label { text: "Pages"; width: 80; anchors.verticalCenter: parent.verticalCenter }
                        TextBox { id: pagesBox; objectName: "pagesBox"; width: 200; placeholder: "All, or 1-3, 5" } }
                    Btn { objectName: "goPrint"; primary: true; opacity: Backend.fileName && win.printer ? 1 : 0.5; text: "Print" + (win.chosenPrinter.label ? " on " + win.chosenPrinter.label : "")
                        onClicked: Backend.printWith(win.printer, { copies: win.copies, twoSided: win.twoSided, pages: pagesBox.text, paper: win.paper, grey: win.grey, fit: win.fit, landscape: win.landscape }) } } } } }

    // ---------------- scanning
    Item { visible: win.tab === "scan"; anchors { fill: parent; topMargin: 68; leftMargin: 22; rightMargin: 22; bottomMargin: 20 }
        Column { visible: Backend.scanners.length === 0; anchors.centerIn: parent; spacing: 10; width: 440
            Glyph { name: "image"; size: 54; ink: Theme.t.accent; anchors.horizontalCenter: parent.horizontalCenter }
            Label { anchors.horizontalCenter: parent.horizontalCenter; font.pixelSize: 20; font.weight: Font.DemiBold; text: !Backend.hasScan ? "Scanning isn't set up" : Backend.looking ? "Looking for scanners…" : "No scanner found" }
            Label { width: parent.width; wrapMode: Text.WordWrap; horizontalAlignment: Text.AlignHCenter; secondary: true
                text: Backend.hasScan ? "Switch the scanner (or the printer with a scanner on top) on, on the same network or plugged in, then look again." : "This computer has no scanning system (SANE). Install the sane-utils and sane-airscan packages." }
            Btn { visible: Backend.hasScan && !Backend.looking; anchors.horizontalCenter: parent.horizontalCenter; text: "Look Again"; onClicked: Backend.findScanners() } }
        Row { visible: Backend.scanners.length > 0; anchors.fill: parent; spacing: 18
            Column { width: 300; spacing: 10
                Label { text: "SCANNER"; secondary: true; font.pixelSize: 10; font.weight: Font.DemiBold }
                Repeater { model: Backend.scanners
                    Pressable { required property var modelData; width: 300; height: 44; radius: 12; color: win.scanner === modelData.id ? win.pick : Theme.t.island; border.width: 1; border.color: win.scanner === modelData.id ? Theme.t.accent : Theme.t.islandLine
                        onClicked: win.scanner = modelData.id; Label { x: 14; width: parent.width - 28; elide: Text.ElideRight; anchors.verticalCenter: parent.verticalCenter; text: modelData.name } } }
                Row { spacing: 8; Chip { text: "Colour"; on: win.colour; onClicked: win.colour = true } Chip { text: "Grey"; on: !win.colour; onClicked: win.colour = false } }
                Row { spacing: 8; Chip { text: "Draft"; on: win.dpi === 150; onClicked: win.dpi = 150 } Chip { text: "Normal"; on: win.dpi === 300; onClicked: win.dpi = 300 } Chip { text: "Fine"; on: win.dpi === 600; onClicked: win.dpi = 600 } }
                Btn { primary: true; opacity: Backend.scanning ? 0.5 : 1; text: Backend.scanning ? "Scanning…" : Backend.pages.length ? "Scan Another Page" : "Scan"; onClicked: Backend.scan(win.scanner, win.colour, win.dpi) }
                Item { width: 1; height: 6 }
                TextBox { id: scanName; visible: Backend.pages.length > 0; width: 300; placeholder: "Name for the PDF (optional)" }
                Row { visible: Backend.pages.length > 0; spacing: 8
                    Btn { primary: true; text: "Save as PDF"; onClicked: { win.lastPdf = Backend.savePdf(scanName.text); scanName.text = "" } } }
                Btn { visible: win.lastPdf !== "" && Backend.pages.length === 0; text: "Send It by Mail"; onClicked: Backend.mail(win.lastPdf) } }
            Rectangle { width: parent.width - 318; height: parent.height; radius: 16; color: Theme.t.island; border.width: 1; border.color: Theme.t.islandLine; clip: true
                Label { visible: Backend.pages.length === 0; anchors.centerIn: parent; secondary: true; text: Backend.scanning ? "Scanning…" : "Scanned pages appear here" }
                Flickable { anchors { fill: parent; margins: 14 } contentHeight: sheetFlow.height; clip: true
                    Flow { id: sheetFlow; width: parent.width; spacing: 12
                        Repeater { model: Backend.pages
                            Rectangle { required property var modelData; required property int index; width: 170; height: 232; radius: 8; color: "white"; border.width: 1; border.color: Theme.t.islandLine
                                Image { anchors { fill: parent; margins: 4 } source: modelData.url; fillMode: Image.PreserveAspectFit; asynchronous: true; sourceSize.width: 340 }
                                Rectangle { x: 6; y: 6; width: 22; height: 22; radius: 11; color: "#AA000000"; Label { anchors.centerIn: parent; text: index + 1; color: "white"; font.pixelSize: 11 } }
                                Pressable { anchors { right: parent.right; top: parent.top; margins: 6 } width: 24; height: 24; radius: 12; color: "#AA000000"; onClicked: Backend.dropPage(index); Glyph { anchors.centerIn: parent; name: "x"; size: 11; ink: "white" } } } } } } } } }
}
