import QtQuick

// Top Bar & Dock.
Column {
    id: pg
    width: parent ? parent.width : 600; spacing: 18
    SetCard { title: "Top bar"
        SetRow { title: "App menus open"; sub: "What happens when you click the app's name in the top bar"
            SetChoice { each: 110; options: [["dropdown", "As a list"], ["inline", "Along the bar"]]; value: Settings.menuStyle; onPicked: function (v) { Settings.set("menuStyle", v) } } }
        SetRow { title: "24-hour clock"; Toggle { on: Settings.clock24; onToggled: function (v) { Settings.set("clock24", v ? "true" : "false") } } }
        SetRow { title: "Show the date"; Toggle { on: Settings.barDate; onToggled: function (v) { Settings.set("barDate", v ? "true" : "false") } } }
        SetRow { title: "Show the battery percentage"; Toggle { on: Settings.batteryPercent; onToggled: function (v) { Settings.set("batteryPercent", v ? "true" : "false") } } } }
    SetCard { title: "Dock"
        SetRow { title: "Hide the dock when a window needs the room"; Toggle { on: Settings.dockHide; onToggled: function (v) { Settings.set("dockHide", v ? "true" : "false") } } }
        SetRow { title: "Show dots under open apps"; Toggle { on: Settings.dockDots; onToggled: function (v) { Settings.set("dockDots", v ? "true" : "false") } } } }
}
