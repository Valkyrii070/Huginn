# Clips
Edit video the way the professionals' editors do: footage in a library, tracks on a timeline, colour, titles, sound and transitions, and what you see is exactly what you get.

## Bring in footage
Press Import, or drop files or folders on the window. They go into the library on the left, sorted into bins (Footage, Music). 4K clips can get light stand-in copies: press Make Proxies and editing stays smooth; the finished video always uses the originals.

## Put clips on the timeline
Drag from the library onto a track, or double-click to add to the end of V1 (the main track) or the music track. Video tracks stack: V2 and above sit over V1, for picture-in-picture, logos and titles. Sound tracks sit underneath.

## Move, trim and cut
Drag a clip to move it (it snaps to cuts, markers and the playhead). Drag either end to trim it. With Ripple on, what follows moves up to close the gap. B is the blade: click a clip to cut it there; S cuts everything under the playhead. Delete removes; Shift+Delete closes the gap too. Ctrl+D duplicates; Ctrl+Z undoes.

## Play and find your place
Space plays and pauses (J, K and L too). The arrow keys step a frame, Shift+arrows a second, Up and Down jump between cuts. M drops a marker.

## Place: size, position, see-through, keyframes
Pick a clip and use Place: size, position, turn, see-through, crop, fades. Press ◆ beside a setting to keep its value at the playhead; move the playhead, change it and press ◆ again, and it animates between them.

## Colour
Exposure, contrast, colour strength, warmth and tint, three colour wheels (shadows, midtones, highlights), a LUT (any .cube file in Videos/LUTs, Downloads or Documents) and scopes (waveform, vectorscope, histogram) for the frame under the playhead.

Curves (under the scopes' neighbour in Colour) bend the brightness of everything, or of red, green or blue alone: click to add a point and drag it, double-click a point to take it away. Lifting the middle brightens the midtones; an S shape adds contrast.

## Effects and speed
Blur, sharpen, vignette, black and white, mirror, upside down and grain clean-up. Speed from ¼× to 8×, keeping voices natural.
Steady shaky footage (in Effects) smooths a handheld shot. A quick version plays at once; meanwhile Clips works out how the camera moved and makes a carefully steadied copy, which the viewer and the export use as soon as it's ready. Stronger follows the camera's path less closely and zooms in a little more to hide the edges.

## Sound
Volume (with keyframes), fades, silence and clean-up of background noise per clip. In the project's settings (click empty timeline), the music can turn itself down whenever someone talks, and the finished video's loudness can be evened out for the web.

## The mixer
Mixer (in the timeline's bar) puts a channel for every track where the library was: a fader for the whole track's level, pan from left to right, M to mute it and S to solo it (hear only the soloed tracks). The meters show how loud each track is under the playhead. Double-click a fader or pan to put it back. The export hears exactly what the mixer does.

## Captions
Captions sit on their own track at the top, as words in a box at the bottom of the picture. Captions in the timeline's bar adds one at the playhead, brings in an .srt or .vtt file, or saves them as .srt or .vtt (for video sites). When you make the video, they're burned in and saved beside it as an .srt file too.
Write Them from Speech listens to the film and writes the captions for you, on this computer (nothing is sent anywhere). It needs whisper.cpp with a speech model, or the faster-whisper package. Read them through afterwards: names and quiet words get misheard.

## Titles
T (or Title) adds words on a layer at the playhead: lower third, big title, heading or subtitle, with size, colour, placement, a band behind and a shadow.

## Transitions
Pick a clip and choose how it goes into the next: cross dissolve, wipes, circle, clock, barn door or diagonal, and how long. A transition uses a little footage from beyond the cut; if there isn't any, the clips overlap and the film gets that much shorter.

## Make the video
Export (Ctrl+E): Best for sharing (H.264), Smaller file (H.265), For the web (AV1), Editing master (ProRes 422 HQ) or sound only, at the project's size or another, in high, medium or small quality. It goes to Videos/Clips, never over another file. Save as an MLT Project hands the edit to Shotcut or Kdenlive.

## Easing
Between keyframes, things can start slowly, end slowly, both, or hold still and jump: pick it under Between Keyframes on the Place tab.

## Sound effects
On the Sound tab: Clear Voice takes away rumble, adds a little presence and evens the level; the compressor evens out loud and quiet; low, middle and high change the tone; and an echo.

## Multicam
Filmed the same moment with two to four cameras? Pick their clips (Ctrl-click) and press Multicam: Clips lines them up by their sound. Play it, and press 1 to 4 (or click an angle) to cut to that camera. Pick which camera's sound to use. Flatten turns it back into ordinary clips.

## Following something that moves
On the Effects tab, press Draw a Box Round It and draw a box round something in the picture: Clips follows it as it moves. Pixelate it (faces, number plates), or add a title that moves with it. A title or picture above can follow it too, from its Place tab.
