import QtQuick
import QtLocation
import QtPositioning

// The map itself, kept in its own file so Maps can still open (and say why) on a computer without the map parts.
Item {
    id: pane
    property var line: []                      // the route: [[lat, lon], …]
    property var pins: []                      // [{ lat, lon, name, kind: "from" | "to" | "found" | "kept" }]
    property string tiles: ""
    property color ink: "#15803D"
    signal settled(real lat, real lon, real zoom)
    signal picked(var pin)
    function look(lat, lon, zoom) { map.center = QtPositioning.coordinate(lat, lon); map.zoomLevel = zoom }
    function showAll() { if (pane.line.length > 1) map.fitViewportToGeoShape(route.geoShape, 60) }
    onLineChanged: { var p = []; for (var i = 0; i < line.length; i++) p.push(QtPositioning.coordinate(line[i][0], line[i][1])); route.path = p; if (p.length > 1) fit.restart() }
    Timer { id: fit; interval: 60; onTriggered: pane.showAll() }
    Timer { id: rest; interval: 900; onTriggered: pane.settled(map.center.latitude, map.center.longitude, map.zoomLevel) }
    Map {
        id: map
        anchors.fill: parent
        minimumZoomLevel: 2; maximumZoomLevel: 19; zoomLevel: 4
        plugin: Plugin { name: "osm"
            PluginParameter { name: "osm.useragent"; value: "Huginn Maps" }
            PluginParameter { name: "osm.mapping.providersrepository.disabled"; value: true }
            PluginParameter { name: "osm.mapping.custom.host"; value: pane.tiles }
            PluginParameter { name: "osm.mapping.highdpi_tiles"; value: false } }
        Component.onCompleted: { for (var i = 0; i < supportedMapTypes.length; i++) if (supportedMapTypes[i].style === MapType.CustomMap) activeMapType = supportedMapTypes[i] }
        onCenterChanged: rest.restart()
        onZoomLevelChanged: rest.restart()
        WheelHandler { acceptedDevices: PointerDevice.Mouse | PointerDevice.TouchPad; rotationScale: 1 / 120; property: "zoomLevel" }
        DragHandler { target: null; onTranslationChanged: function (delta) { map.pan(-delta.x, -delta.y) } }
        PinchHandler { target: null; onScaleChanged: function (delta) { map.zoomLevel += Math.log2(delta) } }
        MapPolyline { id: route; line.width: 6; line.color: pane.ink; opacity: 0.85 }
        MapItemView { model: pane.pins
            delegate: MapQuickItem { required property var modelData; coordinate: QtPositioning.coordinate(modelData.lat, modelData.lon); anchorPoint.x: 11; anchorPoint.y: 11; z: modelData.kind === "found" ? 1 : 2
                sourceItem: Rectangle { width: 22; height: 22; radius: 11; color: modelData.kind === "to" ? "#E5484D" : modelData.kind === "from" ? pane.ink : modelData.kind === "kept" ? "#F59E0B" : "#2563EB"; border.width: 3; border.color: "white"
                    MouseArea { anchors.fill: parent; onClicked: pane.picked(modelData) } } } }
    }
}
