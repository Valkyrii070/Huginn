import QtQuick

// Language & Region: the language the system speaks, and how dates, numbers and money look (with a live sample).
Column {
    id: pg
    width: parent ? parent.width : 600; spacing: 18
    readonly property var l: Backend.language
    readonly property var pv: l.preview || ({})
    SetCard { note: "Changes take effect the next time you sign in."
        SetRow { title: "Language"; sub: "Menus, buttons and messages"; glyph: "translate"; tile: "#118C7E"
            SetPick { text: pg.l.languageLabel || ""; maxWidth: 300; onClicked: win.pick("Language", (pg.l.choices || []).map(function (c) { return { id: c.id, label: c.label, sub: c.id } }), pg.l.language, function (v) { Backend.setLocale("language", v) }) } }
        SetRow { title: "Formats"; sub: "Dates, times, numbers and money"; glyph: "calendar"; tile: "#118C7E"
            SetPick { text: pg.l.formatsLabel || ""; maxWidth: 300; onClicked: win.pick("Formats", (pg.l.choices || []).map(function (c) { var p = Backend.preview(c.id); return { id: c.id, label: c.label, sub: p.short + " · " + p.time + " · " + p.money } }), pg.l.formats,
                                                                                          function (v) { Backend.setLocale("formats", v) }) } } }
    SetCard { title: "How things will look"
        SetRow { title: "Date"; Label { text: pg.pv.date || ""; secondary: true } }
        SetRow { title: "Short date"; Label { text: pg.pv.short || ""; secondary: true } }
        SetRow { title: "Time"; Label { text: pg.pv.time || ""; secondary: true } }
        SetRow { title: "Numbers"; Label { text: pg.pv.number || ""; secondary: true } }
        SetRow { title: "Money"; Label { text: pg.pv.money || ""; secondary: true } }
        SetRow { title: "The week starts on"; Label { text: pg.pv.week || ""; secondary: true } } }
}
