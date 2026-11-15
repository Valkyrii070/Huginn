# Getting started
The desktop, windows and where things are.

## Open an app
Press Super (the Windows key), or click the round orb at the left end of the dock, for the start menu: your recent apps, every app (it scrolls; the pills along the top show one group), and Lock, Sleep, Restart, Shut Down and Sign Out at the bottom. Type a few letters to find an app; press Tab to search everything instead. Right-click an app (here, in the dock or in Search) for its own island: its recent files, things it can do, and Keep in the dock. An open app has a glowing bar under its tile.

## Search everything
Press Super+Space, or click the magnifier in the top bar. Type, and apps, files, Settings pages, sums ("84.60 × 15%", "5 km in mi") and Huginn's open tabs come up; Enter opens the top one, Tab narrows it to one kind. Everything is searched on this computer; only "Search the web" sends what you typed anywhere. Before you type, it offers what you were doing last: the file you had open, the song you paused.

## The live island
At the right end of the dock, an island appears while something is going on: music or a video playing (in any app, Netflix in Huginn included), a timer in Clock, an install in App Store, files arriving in Downloads, an event starting soon, a call on your phone. When several things happen at once, the most important gets the island and up to two more wait beside it as round bubbles; click a bubble to swap it in, or scroll over the island. With two things playing, the island shows the one whose window isn't in front.

Point at the island for a moment and it opens, with all its controls and everything else going on; move away and it closes. Click it to go to the app; right-click for the app's own island. Calls and timers that go off open it by themselves. The play/pause key works on whatever the island shows.

When an app uses your screen, camera or microphone (sharing your screen in a call, say), the island says so for a few seconds, then it stays as a bubble for as long as it's on, with a coloured dot in the top bar: red for the screen, green for the camera, orange for the microphone. Those can't be hidden.

## Move and size a window
Huginn windows have no title bar. Drag a window by its top strip or by its name island in the top-left corner. Drag the bottom-right corner to resize it, and double-click the top strip to make it fill the screen.

## Close, hide or fill the screen
The three dots in the top-left island close the window (red), hide it (yellow) and fill the screen (green). The controls for each app float in islands around its edges.

## Light, dark and colour
Settings changes between light and dark and picks the realm, the colour the whole desktop leans towards. Every app keeps its own colour on top of that, so you can tell them apart at a glance. Apps that aren't Huginn's follow along too: their colours, dark or light and the font change with yours.

## Quick settings and notifications
The control centre slides out from the top bar on the right: Wi‑Fi and Bluetooth (tap the round switch to turn them on or off, the name to open Settings), Do Not Disturb, night light, dark, brightness and sound (tap the speaker to mute), and the notifications that came, with Clear. The top bar shows the app in front: its name opens a menu to get its help, hide it or close it.

## Get more apps
App Store installs apps from Flathub. Web apps you install from the Huginn browser appear alongside the others.

## Switch windows and keys to know
Hold Alt and press Tab to see your open windows; let go of Alt to go to the one picked (Shift+Tab goes back, Escape stays put). Super on its own opens the start menu, Super+Space searches everything, Super+L locks, Print saves a screenshot of the whole screen to Pictures › Screenshots, and Shift+Print (or Super+Shift+S) opens Screenshot to choose what to take. Clicking an open app in the dock brings its window forward instead of opening another.

## When an app asks
Some things apps can only do by asking you first, in a card of Huginn's own: using the camera or taking screenshots ("Allow …?", answered once), which app should open a file or a link (**Open With**, the last one you used already picked), or a colour from the screen (the screen holds still with a magnifier: click the colour). An app that asks for a screenshot holds the screen still too: drag over the part to share, or take the whole screen; Escape says no.

## Open and Save windows
Whenever any app asks for a file, Huginn's own window comes up: your places down the left, the folder as a list or as pictures, a path along the top to click back along, and search. Saving, type a name (its ending follows the type you pick), make a new folder there, and Huginn asks before replacing anything. Ctrl+H shows hidden files. It remembers how you like to look and where each app last saved.

## The preview session
At the sign-in screen, the session menu has "Huginn OS (own compositor, preview)": the same desktop, drawn by Huginn's own compositor instead of KWin. It's being built in steps: for now windows are plain (the glass, rounded corners and islands come next), and screenshots and screen sharing for apps still need the "Huginn" session. Apps made for X11 open in it like any other, and a game that fills the screen is shown directly, with FreeSync on screens that have it. If anything misbehaves, sign out and pick "Huginn" again. If the lock screen ever won't take your password, switch to a text console (Ctrl+Alt+F3), sign in there and type `loginctl unlock-sessions`.
