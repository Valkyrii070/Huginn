import QtQuick

// Money, "the wallet": your accounts as cards in a wallet at the left (the front one is everything together), and
// the month to the right of it: what came in, what went out and where, a safety-net gauge, and a few plain notes.
// Activity is the statement; Plan holds budgets, goals as jars that fill, and the charges that repeat.
GlassWindow {
    id: win
    title: "Money"; width: 1120; height: 760; minimumWidth: 900; minimumHeight: 600; glow: "left"
    property var sheet: null
    property string why: ""
    function open(kind, extra) { why = ""; var s = extra || {}; s.kind = kind; sheet = s }
    function done(result) { if (result === "") { sheet = null; why = "" } else why = result }
    Connections { target: Backend; function onSaid(msg, wrong) { toast.say(msg, wrong) } }
    DropArea { anchors.fill: parent; onDropped: function (d) { if (d.hasUrls) Backend.importFile(d.urls[0], Backend.accounts.length ? Backend.accounts[0].id : "") } }

    component Panel: Rectangle { radius: 22; color: Theme.t.island; border.width: 1; border.color: Theme.t.islandLine }
    component Heading: Label { font.pixelSize: 11; font.weight: Font.Bold; font.letterSpacing: 1.2; secondary: true }
    component Bar: Item { property real share: 0; property color ink: Theme.t.accent; property real marker: -1; height: 8
        Rectangle { anchors.fill: parent; radius: height / 2; color: Theme.t.group }
        Rectangle { width: Math.max(parent.height, parent.width * Math.min(1, parent.share)); height: parent.height; radius: height / 2; color: parent.ink; visible: parent.share > 0 }
        Rectangle { visible: parent.marker >= 0; x: parent.width * Math.min(1, parent.marker) - 1; y: -3; width: 2; height: parent.height + 6; radius: 1; color: Theme.t.text } }

    islands: [
        Island { anchors { right: parent.right; rightMargin: 12 } y: 12
            Seg { objectName: "tabOverview"; text: "Overview"; on: Backend.view === "overview"; onClicked: Backend.setView("overview") }
            Seg { objectName: "tabActivity"; text: "Activity"; on: Backend.view === "activity"; onClicked: Backend.setView("activity") }
            Seg { objectName: "tabPlan"; text: "Plan"; on: Backend.view === "plan"; onClicked: Backend.setView("plan") }
            IslandGap {}
            Seg { icon: "download"; text: "Bring In a Statement"; onClicked: win.open("import", { files: Backend.statementChoices(), account: Backend.accounts.length ? Backend.accounts[0].id : "" }) }
            Seg { icon: "plus"; tip: "Add an account or a cash payment"; onClicked: win.open(Backend.accounts.length ? "cash" : "account") } },
        Toast { id: toast; anchors { horizontalCenter: parent.horizontalCenter; bottom: parent.bottom; bottomMargin: 22 } },

        // ---------------- sheets
        Item { anchors.fill: parent; z: 20; visible: win.sheet !== null
            Rectangle { anchors.fill: parent; radius: win.r; color: "#66000000"; MouseArea { anchors.fill: parent; acceptedButtons: Qt.AllButtons; onClicked: win.sheet = null } }
            Rectangle { id: card; anchors.centerIn: parent; width: 480; radius: 18; color: Theme.t.menu_bg; border.width: 1; border.color: Theme.t.menu_border
                readonly property string kind: win.sheet ? win.sheet.kind : ""
                height: kind === "import" ? Math.min(win.height - 80, 200 + Math.max(1, files.count) * 40) : kind === "category" ? 330 : kind === "account" ? 270 : kind === "goal" ? 280 : kind === "cash" ? 300 : 210
                MouseArea { anchors.fill: parent }
                Label { x: 24; y: 20; width: parent.width - 48; elide: Text.ElideRight; font.pixelSize: 17; font.weight: Font.DemiBold
                    text: ({ "account": "Add an account", "import": "Bring in a statement", "cash": "Add a payment", "category": "What was “" + (win.sheet && win.sheet.txn ? win.sheet.txn.name : "") + "”?",
                             "budget": "Budget for " + (win.sheet ? win.sheet.category : ""), "goal": "A new goal", "aside": "Set money aside for " + (win.sheet && win.sheet.goal ? win.sheet.goal.name : ""),
                             "balance": "What does the bank say?" })[card.kind] || "" }
                // add an account
                Column { visible: card.kind === "account"; x: 24; y: 56; width: parent.width - 48; spacing: 10
                    TextBox { id: aName; objectName: "aName"; width: parent.width; placeholder: "Name, like Everyday or Savings" }
                    Row { spacing: 4; property string kind: "spending"; id: aKind
                        Seg { text: "Spending"; on: aKind.kind === "spending"; onClicked: aKind.kind = "spending" }
                        Seg { text: "Savings"; on: aKind.kind === "savings"; onClicked: aKind.kind = "savings" } }
                    TextBox { id: aOpen; width: parent.width; placeholder: "Balance today (optional)" } }
                // bring in a statement
                Column { visible: card.kind === "import"; x: 16; y: 56; width: parent.width - 32; spacing: 6
                    Label { x: 8; width: parent.width - 16; wrapMode: Text.WordWrap; secondary: true; font.pixelSize: 12
                        text: files.count ? "Your bank's website can download your statement as CSV, OFX or QFX. Pick the account it belongs to, then the file:" : "Download a statement from your bank's website (CSV, OFX or QFX) into Downloads, then come back. Or drop the file onto this window." }
                    Row { x: 8; spacing: 4; visible: Backend.accounts.length > 1
                        Repeater { model: Backend.accounts; Seg { required property var modelData; text: modelData.name; on: win.sheet && win.sheet.account === modelData.id
                            onClicked: win.sheet = { kind: "import", files: win.sheet.files, account: modelData.id } } } }
                    Repeater { id: files; model: card.kind === "import" ? win.sheet.files : []
                        Pressable { required property var modelData; width: parent.width; height: 38; radius: 9; onClicked: { var a = win.sheet.account; win.sheet = null; Backend.importFile(modelData.path, a) }
                            Glyph { x: 10; anchors.verticalCenter: parent.verticalCenter; name: "doc"; size: 15 }
                            Label { x: 36; width: parent.width - 150; elide: Text.ElideMiddle; anchors.verticalCenter: parent.verticalCenter; text: modelData.name }
                            Label { anchors { right: parent.right; rightMargin: 10; verticalCenter: parent.verticalCenter } text: modelData.where + " · " + modelData.when; secondary: true; font.pixelSize: 11 } } } }
                // a cash payment
                Column { visible: card.kind === "cash"; x: 24; y: 56; width: parent.width - 48; spacing: 10
                    Row { spacing: 4; Repeater { model: Backend.accounts; Seg { required property var modelData; text: modelData.name; on: (win.sheet && win.sheet.account || (Backend.accounts.length ? Backend.accounts[0].id : "")) === modelData.id
                        onClicked: win.sheet = { kind: "cash", account: modelData.id } } } }
                    TextBox { id: cDesc; objectName: "cDesc"; width: parent.width; placeholder: "What for, like Farmers market" }
                    TextBox { id: cAmount; objectName: "cAmount"; width: parent.width; placeholder: "Amount: -12.50 spent, 40 received" }
                    TextBox { id: cDay; width: parent.width; placeholder: "Date (today if empty)" } }
                // pick a category
                Flow { visible: card.kind === "category"; x: 20; y: 58; width: parent.width - 40; spacing: 6
                    Repeater { model: Backend.allCategories
                        Pressable { required property var modelData; readonly property bool on: win.sheet && win.sheet.txn && win.sheet.txn.category === modelData.name
                            width: catRow.width + 22; height: 32; radius: 16; color: on ? modelData.colour : hovered ? Theme.t.hover : Theme.t.group
                            onClicked: { var t = win.sheet.txn; Backend.recategorise(t.id, modelData.name, always.on); win.sheet = null }
                            Row { id: catRow; anchors.centerIn: parent; spacing: 6
                                Rectangle { width: 8; height: 8; radius: 4; color: modelData.colour; anchors.verticalCenter: parent.verticalCenter }
                                Label { text: modelData.name; font.pixelSize: 12; color: parent.parent.on ? "#141414" : Theme.t.text } } } } }
                Row { visible: card.kind === "category"; anchors { left: parent.left; leftMargin: 24; bottom: parent.bottom; bottomMargin: 24 } spacing: 10
                    Toggle { id: always; on: true }
                    Label { anchors.verticalCenter: parent.verticalCenter; width: 280; wrapMode: Text.WordWrap; font.pixelSize: 12; text: "Always put " + (win.sheet && win.sheet.txn ? win.sheet.txn.name : "this") + " there" } }
                // budget, goal, setting aside, balance
                Column { visible: card.kind === "budget" || card.kind === "aside" || card.kind === "balance"; x: 24; y: 56; width: parent.width - 48; spacing: 10
                    Label { width: parent.width; wrapMode: Text.WordWrap; secondary: true; font.pixelSize: 12
                        text: card.kind === "budget" ? "The most you'd like to spend on it in a month. Leave it empty for no budget."
                            : card.kind === "aside" ? "How much you've put toward it. A minus takes money back." : "Type the balance your bank shows today. Money adjusts its starting point to match." }
                    TextBox { id: amountBox; objectName: "amountBox"; width: parent.width; placeholder: "Amount"; onAccepted: amountOk.clicked() } }
                Column { visible: card.kind === "goal"; x: 24; y: 56; width: parent.width - 48; spacing: 10
                    TextBox { id: gName; width: parent.width; placeholder: "What for, like Trip to Tromsø" }
                    TextBox { id: gTarget; width: parent.width; placeholder: "How much it costs" }
                    TextBox { id: gDue; width: parent.width; placeholder: "By when (optional, like 2027-06-01)" } }
                Label { visible: win.why !== ""; anchors { left: parent.left; leftMargin: 24; right: parent.right; rightMargin: 24; bottom: parent.bottom; bottomMargin: 62 } wrapMode: Text.WordWrap; color: Theme.t.danger; font.pixelSize: 12; text: win.why }
                Row { anchors { right: parent.right; rightMargin: 22; bottom: parent.bottom; bottomMargin: 20 } spacing: 8
                    Btn { text: card.kind === "import" || card.kind === "category" ? "Close" : "Cancel"; onClicked: win.sheet = null }
                    Btn { objectName: "accountOk"; visible: card.kind === "account"; primary: true; text: "Add"; onClicked: { win.done(Backend.addAccount(aName.text, aKind.kind, aOpen.text)); if (win.sheet === null) { aName.text = ""; aOpen.text = "" } } }
                    Btn { objectName: "cashOk"; visible: card.kind === "cash"; primary: true; text: "Add"
                        onClicked: { win.done(Backend.addTxn(win.sheet.account || Backend.accounts[0].id, cDay.text, cDesc.text, cAmount.text)); if (win.sheet === null) { cDesc.text = ""; cAmount.text = ""; cDay.text = "" } } }
                    Btn { visible: card.kind === "cash"; text: "New Account…"; onClicked: win.open("account") }
                    Btn { id: amountOk; visible: card.kind === "budget" || card.kind === "aside" || card.kind === "balance"; primary: true; text: "Save"
                        onClicked: { var s = win.sheet; var r = s.kind === "budget" ? Backend.setBudget(s.category, amountBox.text) : s.kind === "aside" ? Backend.putAside(s.goal.id, amountBox.text) : Backend.setBalance(s.account.id, amountBox.text)
                                     win.done(r); if (r === "") amountBox.text = "" } }
                    Btn { visible: card.kind === "goal"; primary: true; text: "Add Goal"; onClicked: { win.done(Backend.addGoal(gName.text, gTarget.text, gDue.text)); if (win.sheet === null) { gName.text = ""; gTarget.text = ""; gDue.text = "" } } } } } }
    ]

    // ---------------- nothing yet
    Column { visible: !Backend.overview.hasAccounts; anchors.centerIn: parent; spacing: 14; width: 460
        Rectangle { anchors.horizontalCenter: parent.horizontalCenter; width: 240; height: 150; radius: 20
            gradient: Gradient { orientation: Gradient.Horizontal; GradientStop { position: 0; color: Theme.t.accent } GradientStop { position: 1; color: Qt.darker(Theme.t.accent, 1.6) } }
            Label { x: 20; y: 18; text: "Money"; color: "#FFFFFF"; font.pixelSize: 18; font.weight: Font.Bold } Label { x: 20; anchors.bottom: parent.bottom; anchors.bottomMargin: 18; text: "•••• today"; color: "#CCFFFFFF" } }
        Label { anchors.horizontalCenter: parent.horizontalCenter; font.pixelSize: 22; font.weight: Font.Bold; text: "See where your money goes" }
        Label { width: parent.width; wrapMode: Text.WordWrap; horizontalAlignment: Text.AlignHCenter; secondary: true
            text: "Add your accounts, then bring in the statements your bank lets you download. Everything stays on this computer: no bank log-ins, nothing sent anywhere." }
        Btn { anchors.horizontalCenter: parent.horizontalCenter; primary: true; text: "Add an Account"; onClicked: win.open("account") } }

    // ================= OVERVIEW
    Item { visible: Backend.view === "overview" && Backend.overview.hasAccounts; anchors { fill: parent; topMargin: 62; margins: 16 }
        // the wallet: everything together in front, each account peeking out behind it
        Item { id: wallet; width: 360; height: parent.height
            Rectangle { id: front; objectName: "card"; width: 360; height: 226; radius: 22
                gradient: Gradient { orientation: Gradient.Horizontal
                    GradientStop { position: 0; color: Qt.hsla(0.38, 0.55, Theme.t.dark ? 0.42 : 0.38, 1) } GradientStop { position: 0.55; color: Qt.hsla(0.47, 0.6, Theme.t.dark ? 0.34 : 0.3, 1) } GradientStop { position: 1; color: Qt.hsla(0.58, 0.55, Theme.t.dark ? 0.3 : 0.28, 1) } }
                Rectangle { anchors.fill: parent; radius: parent.radius; gradient: Gradient { GradientStop { position: 0; color: "#33FFFFFF" } GradientStop { position: 0.5; color: "#00FFFFFF" } } }
                Label { x: 22; y: 20; text: "All accounts"; color: "#E6FFFFFF"; font.pixelSize: 13; font.weight: Font.DemiBold }
                Label { x: 22; y: 44; text: Backend.overview.total; color: "#FFFFFF"; font.pixelSize: 38; font.weight: Font.Bold }
                Row { x: 22; anchors { bottom: parent.bottom; bottomMargin: 20 } spacing: 26
                    Column { Label { text: "In, " + Backend.overview.month; color: "#B3FFFFFF"; font.pixelSize: 11 } Label { text: Backend.overview.income; color: "#FFFFFF"; font.pixelSize: 16; font.weight: Font.DemiBold } }
                    Column { Label { text: "Out"; color: "#B3FFFFFF"; font.pixelSize: 11 } Label { text: Backend.overview.spent; color: "#FFFFFF"; font.pixelSize: 16; font.weight: Font.DemiBold } }
                    Column { Label { text: "Left"; color: "#B3FFFFFF"; font.pixelSize: 11 } Label { text: Backend.overview.left; color: "#FFFFFF"; font.pixelSize: 16; font.weight: Font.DemiBold } } } }
            Column { y: front.height + 14; width: parent.width; spacing: 8
                Heading { text: "ACCOUNTS"; leftPadding: 4 }
                Repeater { model: Backend.accounts
                    Pressable { required property var modelData; width: wallet.width; height: 58; radius: 16; color: hovered ? Theme.t.hover : Theme.t.island; border.width: 1; border.color: Theme.t.islandLine
                        onClicked: win.open("balance", { account: modelData })
                        Rectangle { x: 14; anchors.verticalCenter: parent.verticalCenter; width: 34; height: 24; radius: 6; color: modelData.kind === "savings" ? "#10B981" : Theme.t.accent
                            Glyph { anchors.centerIn: parent; name: modelData.kind === "savings" ? "shield" : "apps"; size: 12; ink: "#FFFFFF" } }
                        Label { x: 60; y: 11; text: modelData.name; font.weight: Font.DemiBold }
                        Label { x: 60; y: 30; text: (modelData.kind === "savings" ? "Savings" : "Spending") + " · " + modelData.count + " transactions"; font.pixelSize: 11; secondary: true }
                        Label { anchors { right: parent.right; rightMargin: 16; verticalCenter: parent.verticalCenter } text: modelData.balance; font.pixelSize: 15; font.weight: Font.DemiBold } } }
                Btn { text: "Add an Account"; onClicked: win.open("account") } } }

        // the month, the safety net, the notes
        Flickable { x: wallet.width + 18; width: parent.width - wallet.width - 18; height: parent.height; contentHeight: rightCol.height + 10; clip: true; boundsBehavior: Flickable.StopAtBounds
            Column { id: rightCol; width: parent.width; spacing: 14
                Row { width: parent.width; spacing: 14
                    Panel { width: parent.width - 254 - 14; height: 258
                        Heading { x: 20; y: 18; text: Backend.overview.month.toUpperCase() + " SO FAR" }
                        Item { x: 20; y: 44; width: parent.width - 40; height: 14      // one bar, split by where it went
                            Rectangle { anchors.fill: parent; radius: 7; color: Theme.t.group }
                            Row { anchors.fill: parent; Repeater { model: Backend.categories
                                Rectangle { required property var modelData; required property int index; height: 14; color: modelData.colour
                                    width: { var t = 0; for (var i = 0; i < Backend.categories.length; i++) t += Backend.categories[i].cents; return t ? parent.width * modelData.cents / t : 0 }
                                    radius: 0 } } } }
                        Column { x: 20; y: 72; width: parent.width - 40; spacing: 9
                            Repeater { model: Backend.categories.slice(0, 6)
                                Item { required property var modelData; width: parent.width; height: 20
                                    Rectangle { y: 6; width: 8; height: 8; radius: 4; color: modelData.colour }
                                    Label { x: 16; width: 110; elide: Text.ElideRight; text: modelData.name; font.pixelSize: 12 }
                                    Bar { x: 130; y: 6; width: parent.width - 130 - 150; share: modelData.budgetCents ? modelData.share : modelData.bar; ink: modelData.over ? Theme.t.danger : modelData.colour; marker: modelData.budgetCents ? 1 : -1 }
                                    Label { anchors.right: parent.right; text: modelData.spent + (modelData.budget ? " / " + modelData.budget : ""); font.pixelSize: 12; color: modelData.over ? Theme.t.danger : Theme.t.text } } } }
                        Label { visible: Backend.categories.length === 0; x: 20; y: 80; secondary: true; text: "No spending yet this month." } }
                    Panel { objectName: "safety"; width: 254; height: 258
                        Heading { x: 20; y: 18; text: "SAFETY NET" }
                        Item { anchors.horizontalCenter: parent.horizontalCenter; y: 40; width: 132; height: 132
                            Ring { anchors.fill: parent; value: Backend.overview.coverShare; thickness: 10; ink: Backend.overview.cover >= 3 ? "#10B981" : Backend.overview.cover >= 1 ? Theme.t.accent : "#F59E0B" }
                            Label { anchors.centerIn: parent; anchors.verticalCenterOffset: -6; text: Backend.overview.cover; font.pixelSize: 32; font.weight: Font.Bold }
                            Label { anchors { horizontalCenter: parent.horizontalCenter; top: parent.verticalCenter; topMargin: 14 } text: "of 3 months"; font.pixelSize: 11; secondary: true } }
                        Label { x: 18; y: 182; width: parent.width - 36; wrapMode: Text.WordWrap; horizontalAlignment: Text.AlignHCenter; font.pixelSize: 11; secondary: true
                            text: Backend.overview.savings + " in savings. A usual month costs " + Backend.overview.usual + "; three months is " + Backend.overview.target + "." } } }
                Heading { text: "NOTES"; leftPadding: 4; visible: Backend.notes.length > 0 }
                Flow { width: parent.width; spacing: 12
                    Repeater { model: Backend.notes
                        Panel { required property var modelData; width: (rightCol.width - 12) / 2; height: noteCol.height + 30
                            Rectangle { x: 16; y: 18; width: 28; height: 28; radius: 14; color: modelData.kind === "good" ? "#10B981" : modelData.kind === "watch" ? "#F59E0B" : modelData.kind === "repeat" ? "#7C9CFF" : Theme.t.accent
                                Glyph { anchors.centerIn: parent; size: 14; ink: "#FFFFFF"; name: modelData.kind === "good" ? "check" : modelData.kind === "watch" ? "info" : modelData.kind === "repeat" ? "history" : "shield" } }
                            Column { id: noteCol; x: 56; y: 16; width: parent.width - 72; spacing: 4
                                Label { width: parent.width; wrapMode: Text.WordWrap; text: modelData.title; font.weight: Font.DemiBold }
                                Label { width: parent.width; wrapMode: Text.WordWrap; text: modelData.text; font.pixelSize: 12; secondary: true } } } } }
                Panel { visible: !Backend.overview.hasData; width: parent.width; height: 90
                    Label { x: 20; anchors.verticalCenter: parent.verticalCenter; width: parent.width - 200; wrapMode: Text.WordWrap; text: "Bring in a statement from your bank to see where the money goes." }
                    Btn { anchors { right: parent.right; rightMargin: 20; verticalCenter: parent.verticalCenter } primary: true; text: "Bring In a Statement"
                        onClicked: win.open("import", { files: Backend.statementChoices(), account: Backend.accounts[0].id }) } } } } }

    // ================= ACTIVITY
    Item { visible: Backend.view === "activity" && Backend.overview.hasAccounts; anchors { fill: parent; topMargin: 62; margins: 16 }
        Row { id: filters; width: parent.width; spacing: 6
            IslandField { width: 200; placeholder: "Search activity"; onTextChanged: Backend.search(text) }
            Seg { text: "All accounts"; on: Backend.filterAccount === ""; onClicked: Backend.filter("", Backend.filterCategory) }
            Repeater { model: Backend.accounts; Seg { required property var modelData; text: modelData.name; on: Backend.filterAccount === modelData.id; onClicked: Backend.filter(modelData.id, Backend.filterCategory) } }
            Seg { visible: Backend.filterCategory !== ""; text: Backend.filterCategory + "  ✕"; on: true; onClicked: Backend.filter(Backend.filterAccount, "") } }
        Panel { y: 50; width: parent.width; height: parent.height - 50
            ListView { id: statement; objectName: "statement"; anchors { fill: parent; margins: 8 } clip: true; model: Backend.txns; boundsBehavior: Flickable.StopAtBounds
                section.property: "day"; section.delegate: Label { required property string section; leftPadding: 12; topPadding: 12; bottomPadding: 4; font.pixelSize: 11; font.weight: Font.Bold; secondary: true
                    text: new Date(section + "T12:00:00").toLocaleDateString(Qt.locale(), "dddd d MMMM") }
                delegate: Pressable { required property var modelData; width: statement.width; height: 50; radius: 12; color: hovered ? Theme.t.hover : "transparent"
                    onClicked: win.open("category", { txn: modelData })
                    Rectangle { x: 12; anchors.verticalCenter: parent.verticalCenter; width: 32; height: 32; radius: 16; color: Qt.rgba(0, 0, 0, 0); border.width: 2; border.color: modelData.colour
                        Label { anchors.centerIn: parent; text: modelData.name.charAt(0).toUpperCase(); font.weight: Font.Bold; color: modelData.colour } }
                    Label { x: 56; y: 8; width: parent.width - 330; elide: Text.ElideRight; text: modelData.name; font.weight: Font.DemiBold }
                    Label { x: 56; y: 27; width: parent.width - 330; elide: Text.ElideRight; text: modelData.desc + (Backend.accounts.length > 1 ? " · " + modelData.account : ""); font.pixelSize: 11; secondary: true }
                    Pressable { anchors { right: amt.left; rightMargin: 16; verticalCenter: parent.verticalCenter } width: chip.width + 20; height: 24; radius: 12; color: Qt.rgba(0, 0, 0, 0); border.width: 1; border.color: modelData.colour
                        onClicked: Backend.filter(Backend.filterAccount, modelData.category)
                        Label { id: chip; anchors.centerIn: parent; text: modelData.category; font.pixelSize: 11 } }
                    Label { id: amt; anchors { right: parent.right; rightMargin: 16; verticalCenter: parent.verticalCenter } width: 110; horizontalAlignment: Text.AlignRight; text: modelData.amount
                        font.pixelSize: 14; font.weight: Font.DemiBold; color: modelData.cents > 0 ? "#10B981" : Theme.t.text } }
                Label { visible: statement.count === 0; anchors.centerIn: parent; secondary: true; text: Backend.overview.hasData ? "Nothing matches" : "No activity yet. Bring in a statement." } } } }

    // ================= PLAN
    Flickable { visible: Backend.view === "plan" && Backend.overview.hasAccounts; anchors { fill: parent; topMargin: 62; margins: 16 } contentHeight: plan.height + 10; clip: true; boundsBehavior: Flickable.StopAtBounds
        Column { id: plan; width: parent.width; spacing: 14
            Row { width: parent.width; spacing: 14
                // budgets
                Panel { objectName: "budgets"; width: (parent.width - 14) * 0.55; height: budCol.height + 60
                    Heading { x: 20; y: 18; text: "MONTHLY BUDGETS" }
                    Column { id: budCol; x: 20; y: 46; width: parent.width - 40; spacing: 4
                        Repeater { model: Backend.allCategories.filter(function (c) { return ["Income", "Savings", "Transfers"].indexOf(c.name) < 0 })
                            Pressable { required property var modelData; readonly property var stat: { var cs = Backend.categories; for (var i = 0; i < cs.length; i++) if (cs[i].name === modelData.name) return cs[i]; return null }
                                width: budCol.width; height: 36; radius: 10; color: hovered ? Theme.t.hover : "transparent"; onClicked: win.open("budget", { category: modelData.name })
                                Rectangle { x: 6; y: 14; width: 8; height: 8; radius: 4; color: modelData.colour }
                                Label { x: 22; y: 9; width: 110; elide: Text.ElideRight; text: modelData.name; font.pixelSize: 12 }
                                Bar { x: 140; y: 14; width: parent.width - 140 - 160; share: parent.stat && parent.stat.budgetCents ? parent.stat.share : 0; ink: parent.stat && parent.stat.over ? Theme.t.danger : modelData.colour; visible: !!(parent.stat && parent.stat.budgetCents) }
                                Label { anchors { right: parent.right; rightMargin: 8 } y: 9; font.pixelSize: 12; color: parent.stat && parent.stat.over ? Theme.t.danger : parent.stat && parent.stat.budgetCents ? Theme.t.text : Theme.t.text_secondary
                                    text: parent.stat && parent.stat.budgetCents ? parent.stat.spent + " of " + parent.stat.budget : parent.stat ? parent.stat.spent + " · no budget" : "Set a budget" } } } } }
                // six months, in and out
                Panel { width: (parent.width - 14) * 0.45; height: 330
                    Heading { x: 20; y: 18; text: "IN AND OUT, SIX MONTHS" }
                    Row { x: 20; y: 50; width: parent.width - 40; height: 220; spacing: 0
                        Repeater { model: Backend.months
                            Item { required property var modelData; width: parent.width / 6; height: parent.height
                                Row { anchors { bottom: parent.bottom; bottomMargin: 22; horizontalCenter: parent.horizontalCenter } spacing: 4
                                    Rectangle { width: 12; height: Math.max(2, 180 * modelData.inBar); radius: 4; color: "#10B981"; anchors.bottom: parent.bottom }
                                    Rectangle { width: 12; height: Math.max(2, 180 * modelData.outBar); radius: 4; color: "#F59E0B"; anchors.bottom: parent.bottom } }
                                Label { anchors { bottom: parent.bottom; horizontalCenter: parent.horizontalCenter } text: modelData.month; font.pixelSize: 11; secondary: true } } } }
                    Row { x: 20; anchors { bottom: parent.bottom; bottomMargin: 18 } spacing: 16
                        Row { spacing: 6; Rectangle { width: 10; height: 10; radius: 3; color: "#10B981"; anchors.verticalCenter: parent.verticalCenter } Label { text: "Came in"; font.pixelSize: 11 } }
                        Row { spacing: 6; Rectangle { width: 10; height: 10; radius: 3; color: "#F59E0B"; anchors.verticalCenter: parent.verticalCenter } Label { text: "Spent"; font.pixelSize: 11 } } } } }
            // goals, as jars
            Panel { objectName: "goals"; width: parent.width; height: 280
                Heading { x: 20; y: 18; text: "GOALS" }
                Btn { anchors { right: parent.right; rightMargin: 18 } y: 12; text: "New Goal"; onClicked: win.open("goal") }
                Row { x: 20; y: 52; spacing: 22
                    Repeater { model: Backend.goals
                        Pressable { id: jar; required property var modelData; width: 150; height: 210; radius: 16; color: hovered ? Theme.t.hover : "transparent"; onClicked: win.open("aside", { goal: modelData })
                            Rectangle { id: glass; anchors.horizontalCenter: parent.horizontalCenter; y: 8; width: 96; height: 120; radius: 24; color: Theme.t.group; border.width: 2; border.color: Theme.t.islandLine; clip: true
                                Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: parent.height * jar.modelData.share; color: jar.modelData.done ? "#10B981" : Theme.t.accent; opacity: 0.85 }
                                Label { anchors.centerIn: parent; text: Math.round(jar.modelData.share * 100) + "%"; font.pixelSize: 18; font.weight: Font.Bold } }
                            Rectangle { anchors.horizontalCenter: glass.horizontalCenter; y: 2; width: 70; height: 10; radius: 4; color: Theme.t.islandLine }
                            Label { y: 138; width: parent.width; horizontalAlignment: Text.AlignHCenter; elide: Text.ElideRight; text: jar.modelData.name; font.weight: Font.DemiBold }
                            Label { y: 157; width: parent.width; horizontalAlignment: Text.AlignHCenter; text: jar.modelData.saved + " of " + jar.modelData.target; font.pixelSize: 11; secondary: true }
                            Label { y: 174; width: parent.width; horizontalAlignment: Text.AlignHCenter; wrapMode: Text.WordWrap; maximumLineCount: 2; elide: Text.ElideRight; font.pixelSize: 10; color: Theme.t.accent
                                text: jar.modelData.done ? "Done!" : jar.modelData.plan } } }
                    Label { visible: Backend.goals.length === 0; y: 60; width: 400; wrapMode: Text.WordWrap; secondary: true; text: "Saving for something? Make it a goal and watch the jar fill as you set money aside." } } }
            // what repeats
            Panel { width: parent.width; height: 64 + Math.max(1, Backend.subscriptions.length) * 30
                Heading { x: 20; y: 18; text: "EVERY MONTH" }
                Column { x: 20; y: 44; width: parent.width - 40
                    Repeater { model: Backend.subscriptions
                        Item { required property var modelData; width: parent.width; height: 30
                            Label { text: modelData.name; font.weight: Font.Medium }
                            Label { x: 260; text: "last " + modelData.last + " · " + modelData.count + " times"; font.pixelSize: 11; secondary: true; y: 2 }
                            Label { anchors.right: parent.right; text: modelData.amountText; font.weight: Font.DemiBold } } }
                    Label { visible: Backend.subscriptions.length === 0; secondary: true; text: "Nothing that repeats monthly was found yet." } } } } }
}
