import QtQuick
import QtMultimedia

// The real playback engine (Qt Multimedia). Kept in its own file so previews with sample content never load it.
Item {
    property alias player: mp
    property alias audio: out
    property bool hasVideo: mp.hasVideo
    signal ended()
    MediaPlayer { id: mp; videoOutput: screen; audioOutput: AudioOutput { id: out; volume: 0.75 }
        onMediaStatusChanged: if (mediaStatus === MediaPlayer.EndOfMedia) parent.ended() }
    VideoOutput { id: screen; anchors.fill: parent }
}
