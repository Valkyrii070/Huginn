import QtQuick

// A realm's live wallpaper: the realm's own scene (Aurora's northern lights, Bifröst's bridge, Muspelheim's fire,
// Niflheim's ice), painted on the graphics card and moving slowly. Set `moving: false` and it eases to a stop rather
// than freezing; set it back and it eases off again. Without a graphics card, or when drawing it is too slow (software
// drawing, most virtual machines), it shows the same scene as a still, painted at the moment it starts from.
// The sign-in screen, the arrival after it and the desktop all use this one file.
Item {
    id: lw
    property string realm: "aurora"
    // each realm's own colours at night (tokens.json); a caller can pass its own (the desktop's light appearance does)
    readonly property var realms: ({
        aurora:     { tintA: "#0F2624", tintB: "#17192C", glowA: "#3DD6B5", glowB: "#7B61FF" },
        bifrost:    { tintA: "#1D1932", tintB: "#2A1727", glowA: "#8E7BFF", glowB: "#FF7AB8" },
        muspelheim: { tintA: "#2C1912", tintB: "#1F1718", glowA: "#FF8A4C", glowB: "#FFC857" },
        niflheim:   { tintA: "#12212F", tintB: "#171A20", glowA: "#7CC4FF", glowB: "#CFEAFF" } })
    readonly property var own: realms[realm] || realms.aurora
    property color tintA: own.tintA
    property color tintB: own.tintB
    property color glowA: own.glowA
    property color glowB: own.glowB
    property real day: 0                 // 0 night … 1 day (the light appearance)
    property bool moving: true
    property real pace: 1.0              // how fast it goes when moving: the sign-in screen 1, the desktop slower
    property real time: 30.0             // where in its motion it is; the stills are painted at 30
    property real speed: moving ? 1 : 0  // eases toward `moving` (1 or 0) frame by frame
    readonly property bool gpu: [GraphicsInfo.OpenGL, GraphicsInfo.Vulkan, GraphicsInfo.Metal, GraphicsInfo.Direct3D11,
                                 GraphicsInfo.Direct3D12].indexOf(GraphicsInfo.api) >= 0
    // Drawing in software (no graphics driver, most virtual machines) the scene is far too slow to move, and redrawing
    // it holds up everything else on screen: after its first second, at fewer than 12 frames a second, it settles
    // on the still for good.
    property bool slow: false
    property real minFps: 12
    property int frames: 0
    property real spent: 0
    readonly property bool still: !gpu || slow || shader.status === ShaderEffect.Error
    readonly property bool resting: speed === 0
    readonly property url stillSource: Qt.resolvedUrl("stills/" + realm + ".jpg")

    FrameAnimation {
        running: lw.visible && !lw.still && (lw.moving || lw.speed > 0)
        onTriggered: {
            lw.frames += 1
            if (lw.frames > 2) {                     // (the first frames carry the shader's start-up)
                lw.spent += frameTime
                if (lw.spent > 1.0 && (lw.frames - 2) / lw.spent < lw.minFps)
                    lw.slow = true
            }
            var dt = Math.min(frameTime, 0.1)
            lw.speed += ((lw.moving ? 1 : 0) - lw.speed) * Math.min(1, dt * 1.1)
            if (!lw.moving && lw.speed < 0.002)
                lw.speed = 0
            lw.time += dt * lw.speed * lw.pace
        }
    }
    // the still: shown until the graphics card is ready, and for good without one
    Image {
        anchors.fill: parent
        visible: lw.still || shader.status !== ShaderEffect.Compiled
        source: lw.stillSource
        fillMode: Image.PreserveAspectCrop
        sourceSize.width: 2560
        cache: true
    }
    ShaderEffect {
        id: shader
        anchors.fill: parent
        visible: !lw.still
        fragmentShader: Qt.resolvedUrl(lw.realm + ".frag.qsb")
        property real time: lw.time
        property real day: lw.day
        property size res: Qt.size(width, height)
        property color tintA: lw.tintA
        property color tintB: lw.tintB
        property color glowA: lw.glowA
        property color glowB: lw.glowB
    }
}
