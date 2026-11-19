import QtQuick

// Mail, "letter cards": each message is its own glass card; mailboxes and replies are two islands.
GlassWindow {
    id: win
    title: "Mail"; width: 1060; height: 700; glow: "bottom"
    readonly property color pick: Qt.rgba(tintColor.r, tintColor.g, tintColor.b, 0.18)
    readonly property var cur: Backend.current
    property var sheet: null                   // { kind: "accounts" | "sure" | "more" }
    property bool composing: false
    property var files: []                     // attachments on the message being written: [{ name, path, size }]
    property var reply: ({})                   // what the message being written answers
    property var offers: []                    // addresses offered while typing
    property string signWhy: ""
    property var hint: ({})
    property bool manual: false
    property bool addingAnother: false
    property var again: null                   // an account that's here already, being signed in afresh
    readonly property string gate: Backend.vaultOld ? "old" : !Backend.vaultExists ? "new" : Backend.vaultLocked ? "locked" : ""     // what stands between you and the vault
    readonly property bool viaWindow: !!win.hint.oauth && !!win.hint.oauthReady
    function unlock(box, why) { var w = Backend.unlockVault(box.text); box.text = ""; why.text = w; if (w === "" && sheet && sheet.kind === "unlock") sheet = null }
    function compose(d) { reply = d; cTo.text = d.to || ""; cCc.text = d.cc || ""; cSubject.text = d.subject || ""; cBody.many = (d.body || "") + (d.title === undefined ? Backend.signatureBlock : ""); files = (d.files || []).map(function (p) { return Backend.fileInfo(p) }).filter(function (f) { return f.name })
        cWhy.text = ""; composing = true; if (cTo.text === "") cTo.focusIn(); else cBody.focusIn() }
    // Huginn AI (Settings › AI): summarise the message, draft a reply, or improve what's being written
    function aiMessage() { var c = win.cur; return "From: " + (c.from || "") + " <" + (c.addr || "") + ">\nSubject: " + (c.subject || "") + "\n\n" + (c.body || "") }
    function ownPart(body) {     // what's being written: before the signature and the quoted message
        var cut = body.length, sig = body.indexOf("\n-- \n"), quote = body.search(/\n\nOn [^\n]*wrote:\n/)
        if (sig >= 0) cut = Math.min(cut, sig)
        if (quote >= 0) cut = Math.min(cut, quote)
        return [body.slice(0, cut), body.slice(cut)]
    }
    function ai(key) {
        if (!win.cur.id || win.cur.loading) return
        var id = win.cur.id, task = key.split(":")[0], want = key.split(":")[1] || ""
        if (task === "summarise") { aiPanel.run({ task: "summarise", text: aiMessage(), heading: "Summary" }); return }
        var says = ({ yes: "yes, gladly", no: "no, kindly", later: "that I need a little more time and will answer properly soon" })[want] || ""
        aiPanel.run({ task: "reply", text: aiMessage(), extra: { intent: says }, heading: "Reply", accept: "Use It",
                      onAccept: function (t) { var d = Backend.replyDraft(id, false); d.body = t + (d.body || ""); win.compose(d) } })
    }
    function improve() {
        var parts = ownPart(cBody.many)
        if (parts[0].trim() === "") { toast.say("Write something first, then Improve makes it clearer.", false); return }
        aiPanel.run({ task: "improve", text: parts[0], heading: "Improved", accept: "Use It",
                      onAccept: function (t) { var now = ownPart(cBody.many); if (now[0] !== parts[0]) { aiPanel.copyIt(); toast.say("It changed meanwhile, so the improved text is copied: paste it in.", false); return }
                                               cBody.many = t + now[1] } })
    }
    function form() { return { to: cTo.text, cc: cCc.text, subject: cSubject.text, body: cBody.many, files: files.map(function (f) { return f.path }), replyId: reply.replyId || "", refs: reply.refs || "", replyTo: reply.replyTo || "", title: reply.title || "New message", event: reply.event || null } }
    function attach(path) { var f = Backend.fileInfo(path); if (f.name && !files.some(function (x) { return x.path === f.path })) files = files.concat([f]) }
    function step(by) { var m = Backend.messages; if (!m.length) return; var at = -1; for (var i = 0; i < m.length; i++) if (m[i].id === Backend.openId) at = i
        var to = Math.max(0, Math.min(m.length - 1, at + by)); Backend.read(m[to].id); list.positionViewAtIndex(to, ListView.Contain) }
    function signIn(window) { signWhy = ""; Backend.signIn({ email: sEmail.text, password: sPass.text, name: sName.text, user: sUser.text, imap_host: sImap.text, imap_port: sImapPort.text, smtp_host: sSmtp.text, smtp_port: sSmtpPort.text,
                                                              window: !!window, again: again ? again.id : "" }) }
    function typed(text) { hint = Backend.guess(text); sImap.text = hint.imap_host || ""; sSmtp.text = hint.smtp_host || ""; sUser.text = text; sImapPort.text = String(hint.imap_port || 993); sSmtpPort.text = String(hint.smtp_port || 465)
        if (hint.blocked) manual = false }
    function editSignature(id) { var t = Backend.signatureOf(id); sheet = { kind: "signature", id: id }; sigBox.many = t; sigBox.focusIn() }
    function signAgain(a) { leaveForm(); again = a; addingAnother = true; sEmail.text = a.email; typed(a.email); sheet = null }
    function leaveForm() { addingAnother = false; again = null; manual = false; signWhy = ""; sPass.text = ""; sEmail.text = ""; hint = ({}) }
    Connections { target: Backend
        function onFailed(msg) { toast.say(msg, true) }
        function onSaid(msg) { toast.say(msg, false) }
        function onSignedIn(ok, why) { if (ok) { win.leaveForm(); if (why) toast.say(why, false) } else { win.signWhy = why; sPass.text = "" } }
        function onWasSent(ok, why) { if (ok) { win.composing = false; win.files = []; toast.say(why === "queued" ? "You're offline: it's in the Outbox and will go when Mail can reach the server." : "Sent.", false) } else cWhy.text = why } }
    Timer { interval: 4000; running: win.composing; repeat: true; onTriggered: Backend.keepDraft(win.form()) }
    onComposingChanged: if (!composing) list.forceActiveFocus()        // the keyboard goes back to the list, so Delete and the arrows work
    onSheetChanged: if (sheet === null && !composing) list.forceActiveFocus()
    function handed(d) { win.show(); win.raise(); win.requestActivate(); if (!Backend.hasAccount || !(d.to || d.cc || d.subject || d.body || d.files || d.event)) return; if (composing && (cBody.many !== "" || cTo.text !== "")) { (d.files || []).forEach(attach); toast.say("Added to the message you're writing.", false) } else compose(d) }
    visible: !(typeof startHidden !== "undefined" && startHidden)
    onClosing: function (close) { if (Backend.hasAccount && Backend.stayOn && !demo) { close.accepted = false; win.hide() } else Qt.quit() }
    Shortcut { sequence: "Ctrl+Q"; onActivated: Qt.quit() }
    Connections { target: Backend; function onAsked(d) { win.handed(d) } }
    Component.onCompleted: { var sd = Backend.startDraft; if ((sd.to || sd.subject || sd.body || sd.files) && Backend.hasAccount) { compose(sd); return }
        var d = Backend.draft(); if (d.body !== undefined && (d.body || d.to || d.subject)) { compose(d); toast.say("Your unsent message is back.", false) } }

    islands: [
        Island { visible: Backend.hasAccount && !win.addingAnother
            anchors { right: parent.right; rightMargin: 12 } y: 12
            IslandField { id: search; placeholder: "Search this mailbox"; onTextChanged: Backend.search(text) }
            Seg { icon: "history"; tip: Backend.syncing ? "Checking…" : "Check for mail"; opacity: Backend.syncing ? 0.45 : 1; onClicked: Backend.refresh() }
            Seg { visible: Backend.outbox.length > 0; icon: "history"; text: "Outbox · " + Backend.outbox.length; tip: "Written offline, waiting to be sent"; onClicked: win.sheet = { kind: "outbox" } }
            Seg { visible: Backend.vaultLocked; icon: "key"; text: "Unlock"; tip: "Passwords is locked, so Mail can't check for mail"; onClicked: win.sheet = { kind: "unlock" } }
            Seg { icon: "user"; tip: "Accounts"; onClicked: win.sheet = { kind: "accounts" } }
            Seg { icon: "edit"; text: "New Message"; on: true; onClicked: win.compose({}) }
        },
        Island { visible: Backend.accounts.length > 1 && !win.addingAnother; anchors.horizontalCenter: parent.horizontalCenter; y: 12
            Repeater { model: Backend.accounts
                Seg { required property var modelData; text: modelData.email; on: Backend.account === modelData.id; onClicked: Backend.setAccount(modelData.id) } } },
        Island {   // mailboxes: the main island
            id: boxes; visible: Backend.hasAccount && !win.addingAnother; anchors { left: parent.left; leftMargin: 14; bottom: parent.bottom; bottomMargin: 14 }
            readonly property var main: Backend.folders.filter(function (f) { return f.role !== "" }).slice(0, win.width > 1180 ? 7 : 5)
            readonly property var rest: Backend.folders.filter(function (f) { return boxes.main.indexOf(f) < 0 && !boxes.main.some(function (m) { return m.name === f.name }) })
            Repeater { model: boxes.main
                Seg { required property var modelData; icon: modelData.icon; text: modelData.label + (modelData.unread > 0 ? " · " + modelData.unread : ""); on: Backend.folder === modelData.name; onClicked: Backend.setFolder(modelData.name) } }
            Seg { visible: boxes.rest.length > 0; icon: "folder"; text: boxes.rest.some(function (f) { return f.name === Backend.folder }) ? Backend.folder.split("/").pop() : "More"
                on: boxes.rest.some(function (f) { return f.name === Backend.folder }); onClicked: win.sheet = { kind: "more", boxes: boxes.rest } }
        },
        Island {
            visible: Backend.hasAccount && !!win.cur.id && !win.addingAnother; anchors { right: parent.right; rightMargin: 14; bottom: parent.bottom; bottomMargin: 14 }
            Seg { text: "Reply"; on: true; onClicked: win.compose(Backend.replyDraft(win.cur.id, false)) }
            Seg { text: "Reply All"; onClicked: win.compose(Backend.replyDraft(win.cur.id, true)) }
            Seg { text: "Forward"; onClicked: win.compose(Backend.forwardDraft(win.cur.id)) }
            Seg { visible: aiPanel.on("mail"); icon: "sparkle"; tip: mailAi.visible ? "" : "Huginn AI"; tipAbove: true; on: mailAi.visible; onClicked: mailAi.visible = !mailAi.visible }
            IslandGap {}
            Seg { icon: "star"; on: !!win.cur.starred; tip: win.cur.starred ? "Remove the star" : "Star"; tipAbove: true; onClicked: Backend.toggleStar(win.cur.id) }
            Seg { icon: "mail"; tip: "Mark as unread"; tipAbove: true; onClicked: Backend.markUnread(win.cur.id) }
            Seg { visible: !win.cur.inTrash; icon: "download"; tip: "Archive"; tipAbove: true; onClicked: Backend.archive(win.cur.id) }
            Seg { visible: !win.cur.inTrash; icon: "x"; tip: "It's junk"; tipAbove: true; onClicked: Backend.junk(win.cur.id) }
            Seg { icon: "trash"; danger: true; tip: win.cur.inTrash ? "Delete for good" : "Move to Trash"; tipAbove: true
                onClicked: win.cur.inTrash ? win.sheet = { kind: "sure", id: win.cur.id } : Backend.trash(win.cur.id) }
        },
        Toast { id: toast; anchors { horizontalCenter: parent.horizontalCenter; bottom: parent.bottom; bottomMargin: 64 } },

        // ---------------- small questions
        Item { anchors.fill: parent; z: 20; visible: win.sheet !== null
            Rectangle { anchors.fill: parent; radius: win.r; color: "#66000000"; MouseArea { anchors.fill: parent; acceptedButtons: Qt.AllButtons; onClicked: win.sheet = null } }
            Rectangle { id: card; anchors.centerIn: parent; width: kind === "accounts" ? 560 : 440; radius: 16; color: Theme.t.menu_bg; border.width: 1; border.color: Theme.t.menu_border
                readonly property string kind: win.sheet ? win.sheet.kind : ""
                height: kind === "accounts" ? 132 + Backend.accounts.length * 44 : kind === "outbox" ? 120 + Math.max(1, Backend.outbox.length) * 44 : kind === "signature" ? 262 : kind === "more" ? 110 + (win.sheet.boxes.length) * 34 : kind === "unlock" ? 214 : 160
                onKindChanged: if (kind === "unlock") { uWhy.text = ""; uBox.text = ""; uBox.focusIn() }
                MouseArea { anchors.fill: parent }
                Label { x: 22; y: 20; font.pixelSize: 16; font.weight: Font.DemiBold; text: card.kind === "accounts" ? "Accounts" : card.kind === "more" ? "More mailboxes" : card.kind === "unlock" ? "Unlock Passwords" : card.kind === "outbox" ? "Outbox" : card.kind === "signature" ? "Signature" : "Delete this message for good?" }
                Column { visible: card.kind === "outbox"; x: 16; y: 54; width: parent.width - 32
                    Label { visible: Backend.outbox.length === 0; x: 6; secondary: true; text: "Nothing is waiting." }
                    Repeater { model: card.kind === "outbox" ? Backend.outbox : []
                        Item { required property var modelData; width: parent.width; height: 44
                            Label { x: 6; y: 5; width: parent.width - 110; elide: Text.ElideRight; text: modelData.subject; font.weight: Font.Medium }
                            Label { visible: !modelData.held; x: 6; y: 23; width: parent.width - 110; elide: Text.ElideRight; text: "to " + modelData.to + "  ·  " + modelData.time; secondary: true; font.pixelSize: 11 }
                            Label { visible: modelData.held; x: 6; y: 23; width: parent.width - 200; elide: Text.ElideRight; text: "May already have gone: the connection dropped mid-send"; color: Theme.t.danger; font.pixelSize: 11 }
                            Row { anchors { right: parent.right; verticalCenter: parent.verticalCenter } spacing: 6
                                Btn { visible: modelData.held; height: 26; text: "Send Anyway"; onClicked: Backend.sendAnyway(modelData.id) }
                                Btn { height: 26; text: "Don't Send"; onClicked: Backend.dropQueued(modelData.id) } } } } }
                Column { visible: card.kind === "signature"; x: 22; y: 50; width: parent.width - 44; spacing: 8
                    Label { width: parent.width; wrapMode: Text.WordWrap; secondary: true; font.pixelSize: 12; text: "Added under new messages and replies from this account. Leave it empty for none." }
                    TextBox { id: sigBox; objectName: "sigBox"; width: parent.width; lines: 5; placeholder: "Your name\nWhat you do" } }
                Column { visible: card.kind === "unlock"; x: 22; y: 50; width: parent.width - 44; spacing: 8
                    Label { width: parent.width; wrapMode: Text.WordWrap; secondary: true; font.pixelSize: 12; text: "Mail keeps each account's sign-in in Passwords. The mail already on this computer stays readable; unlocking lets Mail fetch and send." }
                    TextBox { id: uBox; objectName: "uBox"; width: parent.width; secret: true; placeholder: "Master password"; onAccepted: win.unlock(uBox, uWhy) }
                    Label { id: uWhy; width: parent.width; wrapMode: Text.WordWrap; font.pixelSize: 12; color: Theme.t.danger; visible: text !== "" } }
                Label { visible: card.kind === "sure"; x: 22; y: 52; secondary: true; text: "It will be gone from the server too. This can't be undone." }
                Column { visible: card.kind === "accounts"; x: 16; y: 54; width: parent.width - 32
                    Repeater { model: card.kind === "accounts" ? Backend.accounts : []
                        Item { required property var modelData; width: parent.width; height: 44
                            Label { x: 6; y: 5; text: modelData.name || modelData.email; font.weight: Font.Medium } Label { x: 6; y: 23; text: modelData.email + (modelData.window ? " · signed in with " + modelData.window : ""); secondary: true; font.pixelSize: 11 }
                            Row { anchors { right: parent.right; verticalCenter: parent.verticalCenter } spacing: 6
                                Btn { height: 26; text: "Signature"; onClicked: win.editSignature(modelData.id) }
                                Btn { height: 26; text: "Sign In Again"; onClicked: win.signAgain(modelData) }
                                Btn { height: 26; text: "Remove"; onClicked: Backend.removeAccount(modelData.id) } } } } }
                Column { visible: card.kind === "more"; x: 16; y: 52; width: parent.width - 32
                    Repeater { model: card.kind === "more" ? win.sheet.boxes : []
                        Pressable { required property var modelData; width: parent.width; height: 34; radius: 9; onClicked: { var n = modelData.name; win.sheet = null; Backend.setFolder(n) }
                            Glyph { x: 10; anchors.verticalCenter: parent.verticalCenter; name: modelData.icon; size: 15 }
                            Label { x: 36; width: parent.width - 90; elide: Text.ElideMiddle; anchors.verticalCenter: parent.verticalCenter; text: modelData.name }
                            Label { visible: modelData.unread > 0; anchors { right: parent.right; rightMargin: 10; verticalCenter: parent.verticalCenter } text: modelData.unread; color: Theme.t.accent; font.pixelSize: 12 } } } }
                Row { anchors { right: parent.right; rightMargin: 22; bottom: parent.bottom; bottomMargin: 20 } spacing: 8
                    Btn { visible: card.kind === "accounts"; text: Backend.stayOn ? "Check when closed: On" : "Check when closed: Off"; onClicked: Backend.setStayOn(!Backend.stayOn) }
                    Btn { visible: card.kind === "accounts"; text: Backend.grouped ? "Conversations: On" : "Conversations: Off"; onClicked: Backend.setGrouped(!Backend.grouped) }
                    Btn { visible: card.kind === "outbox" && Backend.outbox.length > 0; primary: true; text: "Try Now"; onClicked: { Backend.flushOutbox(); win.sheet = null } }
                    Btn { visible: card.kind === "signature"; primary: true; text: "Save"; onClicked: { Backend.setSignature(win.sheet.id, sigBox.many); win.sheet = null } }
                    Btn { visible: card.kind === "accounts"; text: "Add Another"; onClicked: { win.sheet = null; win.leaveForm(); win.addingAnother = true; sEmail.focusIn() } }
                    Btn { text: card.kind === "sure" || card.kind === "unlock" || card.kind === "signature" ? "Cancel" : "Done"; onClicked: win.sheet = null }
                    Btn { visible: card.kind === "unlock"; primary: true; text: "Unlock"; onClicked: win.unlock(uBox, uWhy) }
                    Btn { visible: card.kind === "sure"; danger: true; text: "Delete"; onClicked: { var id = win.sheet.id; win.sheet = null; Backend.deleteForGood(id) } } } } },

        // ---------------- writing a message
        Item { anchors.fill: parent; z: 18; visible: win.composing
            Rectangle { anchors.fill: parent; radius: win.r; color: "#66000000"; MouseArea { anchors.fill: parent; acceptedButtons: Qt.AllButtons } }
            Rectangle { id: letterCard; anchors.centerIn: parent; width: Math.min(720, parent.width - 60); height: parent.height - 70; radius: 16; color: Theme.t.menu_bg; border.width: 1; border.color: Theme.t.menu_border
                DropArea { anchors.fill: parent; onDropped: function (d) { if (d.hasUrls) { for (var i = 0; i < d.urls.length; i++) win.attach(String(d.urls[i])); d.accept(Qt.CopyAction) } }
                    Rectangle { anchors.fill: parent; radius: 16; visible: parent.containsDrag; color: "transparent"; border.width: 2; border.color: Theme.t.accent } }
                Label { x: 22; y: 18; font.pixelSize: 16; font.weight: Font.DemiBold; text: win.reply.title || "New message" }
                Column { x: 22; y: 50; width: parent.width - 44; spacing: 7
                    TextBox { id: cTo; objectName: "cTo"; width: parent.width; placeholder: "To"; onEdited: win.offers = Backend.suggest(text.split(/[;,]/).pop()); onAccepted: cSubject.focusIn() }
                    Row { visible: win.offers.length > 0 && cTo.input.activeFocus; spacing: 4; width: parent.width; clip: true; height: 30
                        Repeater { model: win.offers
                            Seg { required property var modelData; anchors.verticalCenter: undefined; text: modelData.name === modelData.addr ? modelData.addr : modelData.name + "  " + modelData.addr
                                onClicked: { var parts = cTo.text.split(/[;,]/); parts.pop(); parts.push(" " + modelData.addr); cTo.text = parts.join(",").replace(/^[ ,]+/, "") + ", "; win.offers = []; cTo.focusIn(); cTo.input.cursorPosition = cTo.text.length } } } }
                    TextBox { id: cCc; width: parent.width; placeholder: "Cc (optional)" }
                    TextBox { id: cSubject; width: parent.width; placeholder: "Subject"; onAccepted: cBody.focusIn() } }
                TextBox { id: cBody; objectName: "cBody"; x: 22; y: 50 + (win.offers.length > 0 && cTo.input.activeFocus ? 37 : 0) + 129; width: parent.width - 44; lines: Math.max(4, Math.floor((letterCard.height - y - 120 - attached.height) / 18)) }
                Flow { id: attached; x: 22; anchors { bottom: parent.bottom; bottomMargin: 62 } width: parent.width - 44; spacing: 6
                    Repeater { model: win.files
                        Rectangle { required property var modelData; required property int index; height: 28; radius: 9; width: fl.width + 44; color: Theme.t.group; border.width: 1; border.color: Theme.t.islandLine
                            Label { id: fl; x: 10; anchors.verticalCenter: parent.verticalCenter; text: modelData.name + "  ·  " + modelData.size; font.pixelSize: 12 }
                            Seg { anchors { right: parent.right; verticalCenter: parent.verticalCenter } icon: "x"; onClicked: { var f = win.files.slice(); f.splice(index, 1); win.files = f } } } } }
                Label { visible: !!win.reply.event && cWhy.text === ""; x: 22; anchors { bottom: parent.bottom; bottomMargin: 26 } width: parent.width - 330; elide: Text.ElideRight; font.pixelSize: 12; color: Theme.t.accent
                    text: win.reply.event ? "Goes as an invitation: " + win.reply.event.title + ". Everyone in To and Cc can answer." : "" }
                Label { id: cWhy; x: 22; anchors { bottom: parent.bottom; bottomMargin: 26 } width: parent.width - 330; elide: Text.ElideRight; color: Theme.t.danger; font.pixelSize: 12 }
                Row { anchors { right: parent.right; rightMargin: 22; bottom: parent.bottom; bottomMargin: 18 } spacing: 8
                    Btn { visible: aiPanel.on("mail"); text: "Improve"; onClicked: win.improve() }
                    Btn { text: "Attach"; onClicked: picker.visible = !picker.visible }
                    Btn { text: "Discard"; onClicked: { win.composing = false; win.files = []; Backend.clearDraft() } }
                    Btn { text: "Later"; onClicked: { Backend.keepDraft(win.form()); win.composing = false; toast.say("Kept. It comes back when you open Mail or press New Message.", false) } }
                    Btn { objectName: "sendBtn"; primary: true; text: Backend.syncing ? "Sending…" : "Send"; onClicked: { cWhy.text = ""; Backend.send(win.form()) } } }
                Rectangle { id: picker; visible: false; anchors { right: parent.right; rightMargin: 22; bottom: parent.bottom; bottomMargin: 58 } width: 380; height: 58 + pickCol.height; radius: 14; color: Theme.t.island; border.width: 1; border.color: Theme.t.islandLine
                    property var choices: visible ? Backend.attachChoices() : []
                    Label { x: 14; y: 10; width: parent.width - 28; wrapMode: Text.WordWrap; secondary: true; font.pixelSize: 11; text: "Lately saved files. Any other file: drag it here from Files." }
                    Column { id: pickCol; x: 6; y: 46; width: parent.width - 12
                        Repeater { model: picker.choices
                            Pressable { required property var modelData; width: parent.width; height: 30; radius: 8; onClicked: { win.attach(modelData.path); picker.visible = false }
                                Label { x: 8; width: parent.width - 130; elide: Text.ElideMiddle; anchors.verticalCenter: parent.verticalCenter; text: modelData.name; font.pixelSize: 12 }
                                Label { anchors { right: parent.right; rightMargin: 8; verticalCenter: parent.verticalCenter } text: modelData.where + " · " + modelData.size; secondary: true; font.pixelSize: 10 } } } } } } },
        AiMenu { id: mailAi; z: 25; anchors { right: parent.right; rightMargin: 14; bottom: parent.bottom; bottomMargin: 62 }
            items: [["summarise", "Summarise this message", ""], ["", "", ""], ["reply", "Draft a reply", ""], ["reply:yes", "Draft a reply saying yes", ""],
                    ["reply:no", "Draft a reply saying no", ""], ["reply:later", "Draft a reply asking for time", ""]]
            onChosen: function (key) { win.ai(key) } },
        AiPanel { id: aiPanel; z: 30; x: (win.width - width) / 2; anchors { bottom: parent.bottom; bottomMargin: win.composing ? 112 : 62 } maxHeight: win.height * 0.6 }
    ]

    // ---------------- signing in
    Column { visible: !Backend.hasAccount || win.addingAnother; anchors.centerIn: parent; anchors.verticalCenterOffset: -10; spacing: 9; width: 400
        Glyph { name: win.gate === "" ? "mail" : "key"; size: 44; ink: Theme.t.accent; anchors.horizontalCenter: parent.horizontalCenter }
        Label { anchors.horizontalCenter: parent.horizontalCenter; font.pixelSize: 20; font.weight: Font.DemiBold
            text: win.gate === "new" ? "First, a master password" : win.gate === "locked" ? "Unlock Passwords" : win.gate === "old" ? "Open Passwords once"
                : win.again ? "Sign in again" : win.addingAnother ? "Add another account" : "Add your mail account" }

        // no vault yet, or it's locked: Mail keeps nothing of its own, so that comes first
        Column { visible: win.gate !== ""; width: parent.width; spacing: 9
            Label { width: parent.width; wrapMode: Text.WordWrap; horizontalAlignment: Text.AlignHCenter; secondary: true; font.pixelSize: 12
                text: win.gate === "new" ? "Mail keeps each account's sign-in in Passwords, with your website logins, locked by one master password. Nobody can recover it if it's forgotten."
                    : win.gate === "old" ? "Your vault was made by an earlier Passwords app. Open Passwords and unlock it once; it moves itself, and Mail carries on from here."
                    : "Mail keeps each account's sign-in in Passwords. Unlock it to add an account." }
            TextBox { id: gPass; objectName: "gPass"; visible: win.gate !== "old"; width: parent.width; secret: true; placeholder: "Master password"
                onAccepted: win.gate === "new" ? gAgain.focusIn() : win.unlock(gPass, gWhy) }
            TextBox { id: gAgain; objectName: "gAgain"; visible: win.gate === "new"; width: parent.width; secret: true; placeholder: "Once more"; onAccepted: gMake.clicked() }
            Label { id: gWhy; width: parent.width; wrapMode: Text.WordWrap; font.pixelSize: 12; color: Theme.t.danger; visible: text !== "" }
            Row { anchors.horizontalCenter: parent.horizontalCenter; spacing: 8
                Btn { visible: win.addingAnother; text: "Cancel"; onClicked: win.leaveForm() }
                Btn { id: gMake; visible: win.gate === "new"; primary: true; text: "Create"; onClicked: { gWhy.text = Backend.createVault(gPass.text, gAgain.text); if (gWhy.text === "") { gPass.text = ""; gAgain.text = ""; sEmail.focusIn() } } }
                Btn { visible: win.gate === "locked"; primary: true; text: "Unlock"; onClicked: win.unlock(gPass, gWhy) } } }

        // waiting for the provider's own page
        Column { visible: win.gate === "" && Backend.waiting !== ""; width: parent.width; spacing: 12
            Label { width: parent.width; wrapMode: Text.WordWrap; horizontalAlignment: Text.AlignHCenter; font.pixelSize: 13
                text: Backend.waiting + "'s sign-in page is open in your browser. Sign in there and come back; Mail never sees that password." }
            Btn { anchors.horizontalCenter: parent.horizontalCenter; text: "Cancel"; onClicked: Backend.cancelSignIn() } }

        Column { visible: win.gate === "" && Backend.waiting === ""; width: parent.width; spacing: 9
            TextBox { id: sEmail; objectName: "sEmail"; width: parent.width; placeholder: "Email address"; enabled: !win.again; opacity: win.again ? 0.6 : 1
                onAccepted: win.viaWindow && !win.hint.passwordToo ? win.signIn(true) : sPass.focusIn(); onEdited: win.typed(text) }
            Btn { objectName: "sWindow"; visible: win.viaWindow; width: parent.width; primary: true; opacity: Backend.adding ? 0.6 : 1
                text: "Sign in with " + (win.hint.oauthName || ""); onClicked: win.signIn(true) }
            TextBox { id: sPass; objectName: "sPass"; visible: !win.hint.oauth || !!win.hint.passwordToo; width: parent.width; secret: true
                placeholder: win.viaWindow ? "…or an app password" : win.hint.oauth ? "App password" : "Password, or app password"; onAccepted: win.signIn(false) }
            TextBox { id: sName; visible: !win.again; width: parent.width; placeholder: "Your name, as people will see it (optional)"; onAccepted: win.viaWindow && sPass.text === "" ? win.signIn(true) : win.signIn(false) }
            Label { width: parent.width; wrapMode: Text.WordWrap; font.pixelSize: 12; visible: text !== ""; color: win.signWhy ? Theme.t.danger : Theme.t.text_secondary; text: win.signWhy || win.hint.note || "" }
            Column { visible: win.manual && !win.again; width: parent.width; spacing: 7
                TextBox { id: sUser; width: parent.width; placeholder: "Sign-in name (usually the address)" }
                Row { spacing: 7; TextBox { id: sImap; width: 304; placeholder: "Incoming (IMAP) server" } TextBox { id: sImapPort; width: 89; placeholder: "993" } }
                Row { spacing: 7; TextBox { id: sSmtp; width: 304; placeholder: "Outgoing (SMTP) server" } TextBox { id: sSmtpPort; width: 89; placeholder: "465" } } }
            Row { anchors.horizontalCenter: parent.horizontalCenter; spacing: 8
                Btn { visible: win.addingAnother; text: "Cancel"; onClicked: win.leaveForm() }
                Btn { visible: !win.again && !win.hint.blocked; text: win.manual ? "Hide Server Settings" : "Server Settings"; onClicked: win.manual = !win.manual }
                Btn { objectName: "sGo"; visible: sPass.visible && !win.hint.blocked; primary: !win.viaWindow; text: Backend.adding ? "Signing in…" : "Sign In"; opacity: Backend.adding ? 0.6 : 1; onClicked: win.signIn(false) } }
            Label { width: parent.width; wrapMode: Text.WordWrap; horizontalAlignment: Text.AlignHCenter; secondary: true; font.pixelSize: 11
                text: "The sign-in is kept in Passwords, under your master password. Mail only talks to your provider over an encrypted connection it has checked, and never loads pictures or trackers." } }
    }

    // ---------------- reading
    Item { visible: Backend.hasAccount && !win.addingAnother; anchors { fill: parent; topMargin: 64; bottomMargin: 2 }
        ListView { id: list; x: 14; width: 340; height: parent.height - 66; clip: true; spacing: 8; model: Backend.messages
            delegate: Pressable { required property var modelData; readonly property bool open: Backend.openId === modelData.id
                width: list.width; height: 80; radius: 12; color: open ? win.pick : (hovered ? Theme.t.hover : Theme.t.group)
                border.width: 1; border.color: open ? Theme.t.accent : Theme.t.islandLine; onClicked: Backend.read(modelData.id)
                Rectangle { visible: modelData.unread; x: 12; y: 17; width: 8; height: 8; radius: 4; color: Theme.t.accent }
                Label { x: modelData.unread ? 28 : 14; y: 11; width: parent.width - 120; text: modelData.from + (modelData.count > 1 ? "   " + modelData.count : ""); font.weight: modelData.unread ? Font.Bold : Font.DemiBold; elide: Text.ElideRight }
                Row { anchors { right: parent.right; rightMargin: 12 } y: 12; spacing: 5
                    Label { visible: modelData.starred; text: "★"; color: Theme.t.accent; font.pixelSize: 12 }
                    Label { visible: modelData.attach; text: "⊙"; secondary: true; font.pixelSize: 11 }
                    Label { visible: modelData.answered; text: "↩"; secondary: true; font.pixelSize: 11 }
                    Label { text: modelData.time; secondary: true; font.pixelSize: 11 } }
                Label { x: 14; y: 32; width: parent.width - 28; text: modelData.subject; elide: Text.ElideRight; font.pixelSize: 12; font.weight: modelData.unread ? Font.DemiBold : Font.Normal }
                Label { x: 14; y: 52; width: parent.width - 28; text: modelData.snippet; elide: Text.ElideRight; secondary: true; font.pixelSize: 12 } }
            Label { visible: list.count === 0; anchors.centerIn: parent; width: parent.width - 40; horizontalAlignment: Text.AlignHCenter; wrapMode: Text.WordWrap; secondary: true
                text: Backend.query ? "Nothing here matches" : Backend.syncing ? "Fetching your mail…" : Backend.offline ? Backend.offline : "Nothing here" } }
        Rectangle { x: 366; width: parent.width - 366 - 14; height: parent.height - 66; radius: 12; color: Theme.t.group; border.width: 1; border.color: Theme.t.islandLine; clip: true
            MouseArea { anchors.fill: parent }
            Label { visible: !win.cur.id; anchors.centerIn: parent; text: "No message selected"; secondary: true }
            Flickable { visible: !!win.cur.id; anchors.fill: parent; contentHeight: letter.height + 48; clip: true
                Column { id: letter; x: 26; y: 22; width: parent.width - 52; spacing: 6
                    Label { width: parent.width; text: win.cur.subject || ""; font.pixelSize: 20; font.weight: Font.DemiBold; wrapMode: Text.WordWrap }
                    Row { spacing: 10; topPadding: 6
                        Rectangle { width: 34; height: 34; radius: 17; color: Theme.t.accent; Label { anchors.centerIn: parent; text: (win.cur.from || "?").charAt(0).toUpperCase(); color: Theme.t.onAccent; font.weight: Font.Bold } }
                        Column { anchors.verticalCenter: parent.verticalCenter; width: letter.width - 50 - 88
                            Label { width: parent.width; elide: Text.ElideRight; text: (win.cur.from || "") + (win.cur.addr && win.cur.addr !== win.cur.from ? "  ·  " + win.cur.addr : ""); font.weight: Font.DemiBold }
                            Label { width: parent.width; elide: Text.ElideRight; text: "to " + (win.cur.to || "you") + (win.cur.cc ? ", cc " + win.cur.cc : "") + "  ·  " + (win.cur.date || ""); secondary: true; font.pixelSize: 11 } }
                        Seg { icon: "bell"; tip: "Remind me about this"; anchors.verticalCenter: undefined; onClicked: Backend.remind(win.cur.id) }
                        Seg { icon: "user"; tip: "Add to Contacts"; anchors.verticalCenter: undefined; onClicked: { Backend.addSender(win.cur.id); toast.say("Opening Contacts…", false) } } }
                    Flow { visible: Backend.conversation.length > 1; width: parent.width; spacing: 5; topPadding: 4
                        Label { text: Backend.conversation.length + " in this conversation"; secondary: true; font.pixelSize: 11; height: 24; verticalAlignment: Text.AlignVCenter }
                        Repeater { model: Backend.conversation
                            Pressable { required property var modelData; height: 24; radius: 8; width: cl.width + 16; color: modelData.open ? win.pick : "transparent"; border.width: 1; border.color: modelData.open ? Theme.t.accent : Theme.t.islandLine
                                onClicked: Backend.read(modelData.id)
                                Label { id: cl; x: 8; anchors.verticalCenter: parent.verticalCenter; font.pixelSize: 11; font.weight: modelData.unread ? Font.Bold : Font.Normal; text: modelData.from + "  ·  " + modelData.time } } } }
                    Rectangle { visible: !!(win.cur.invite && win.cur.invite.title); width: parent.width; height: inv.height + 22; radius: 12; color: win.pick; border.width: 1; border.color: Theme.t.accent
                        Column { id: inv; x: 14; y: 11; width: parent.width - 28; spacing: 6
                            Label { width: parent.width; elide: Text.ElideRight; font.weight: Font.DemiBold; readonly property var i: win.cur.invite || {}
                                text: i.answer ? i.from + " " + i.answer + " “" + i.title + "”" : (i.cancelled ? "Cancelled: " : "Invitation: ") + (i.title || "") }
                            Label { width: parent.width; wrapMode: Text.WordWrap; secondary: true; font.pixelSize: 12; visible: !(win.cur.invite || {}).answer
                                text: [(win.cur.invite || {}).when, (win.cur.invite || {}).where, "from " + ((win.cur.invite || {}).from || "")].filter(function (x) { return x }).join("  ·  ") }
                            Row { spacing: 6; visible: !(win.cur.invite || {}).answer && !(win.cur.invite || {}).cancelled
                                Btn { height: 26; primary: true; text: "Accept"; onClicked: Backend.answerInvite(win.cur.id, win.cur.invite.index, "accept") }
                                Btn { height: 26; text: "Maybe"; onClicked: Backend.answerInvite(win.cur.id, win.cur.invite.index, "maybe") }
                                Btn { height: 26; text: "Decline"; onClicked: Backend.answerInvite(win.cur.id, win.cur.invite.index, "decline") } }
                            Btn { visible: !!(win.cur.invite || {}).cancelled; height: 26; text: "Remove from Calendar"; onClicked: Backend.openAttachment(win.cur.id, win.cur.invite.index + ":calendar") } } }
                    Flow { visible: (win.cur.files || []).length > 0; width: parent.width; spacing: 6; topPadding: 4
                        Repeater { model: win.cur.files || []
                            Pressable { required property var modelData; height: 30; radius: 9; width: al.width + 24; color: hovered ? Theme.t.hover : Theme.t.island; border.width: 1; border.color: Theme.t.islandLine
                                readonly property string goes: /\.(vcf|vcard)$/i.test(modelData.name) ? "contacts" : /\.ics$/i.test(modelData.name) ? "calendar" : ""
                                onClicked: goes ? Backend.openAttachment(win.cur.id, modelData.index + ":" + goes) : Backend.saveAttachment(win.cur.id, modelData.index)
                                Label { id: al; x: 12; anchors.verticalCenter: parent.verticalCenter; font.pixelSize: 12
                                    text: modelData.name.split("/").pop() + "  ·  " + modelData.size + "  ·  " + (parent.goes === "contacts" ? "Add to Contacts" : parent.goes === "calendar" ? "Add to Calendar" : "Save") } } } }
                    Rectangle { width: parent.width; height: 1; color: Theme.t.separator }
                    Label { visible: !!win.cur.wasHtml; width: parent.width; secondary: true; font.pixelSize: 11; text: "Shown as text. Its pictures and trackers were not loaded." }
                    TextEdit { width: parent.width; topPadding: 8; readOnly: true; selectByMouse: true; wrapMode: TextEdit.Wrap; textFormat: TextEdit.PlainText; color: Theme.t.text; selectionColor: Theme.t.accent
                        font.family: Theme.t.font; font.pixelSize: 14; text: win.cur.loading ? "Fetching this message…" : (win.cur.body || "") } } } }
    }
    Shortcut { sequence: "Ctrl+N"; enabled: Backend.hasAccount && !win.composing; onActivated: win.compose({}) }
    Shortcut { sequence: "Ctrl+R"; enabled: !!win.cur.id && !win.composing; onActivated: win.compose(Backend.replyDraft(win.cur.id, false)) }
    Shortcut { sequence: "Ctrl+Return"; enabled: win.composing; onActivated: { cWhy.text = ""; Backend.send(win.form()) } }
    Shortcut { sequence: "Ctrl+F"; enabled: Backend.hasAccount && !win.composing; onActivated: search.focusInput() }
    Shortcut { sequence: "F5"; onActivated: Backend.refresh() }
    Shortcut { sequence: "Down"; enabled: !win.composing && win.sheet === null && Backend.hasAccount; onActivated: win.step(1) }
    Shortcut { sequence: "Up"; enabled: !win.composing && win.sheet === null && Backend.hasAccount; onActivated: win.step(-1) }
    Shortcut { sequence: "Delete"; enabled: !!win.cur.id && !win.composing && win.sheet === null; onActivated: win.cur.inTrash ? win.sheet = { kind: "sure", id: win.cur.id } : Backend.trash(win.cur.id) }
    Shortcut { sequence: "Escape"; enabled: win.sheet !== null; onActivated: win.sheet = null }
}
