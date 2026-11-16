# Huginn OS build kit (Phase 1)

Reproducible ISO build for Huginn OS on Ubuntu 26.04 LTS ("resolute").

## Quick start (Ubuntu 24.04 or 26.04 host, ~25 GB free)

    sudo scripts/00-host-setup.sh        # once
    sudo scripts/build.sh --check        # bootstrap + verify every package name resolves
    sudo scripts/build.sh                # full build -> out/huginn-os-0.1-<date>-amd64.iso
    scripts/test-qemu.sh                 # boot it (UEFI); add --bios for legacy boot

Faster iterations:

    sudo scripts/build.sh --from rootfs  # skip debootstrap, reinstall packages
    sudo scripts/build.sh --from image   # only repack squashfs + ISO
    sudo scripts/build.sh --from customise   # reuse the installed chroot: overlay, apps and hooks again, then repack
    SQUASHFS_COMP=lz4 in config/build.conf for quick dev images

In the Huginn repository this kit is the `os/` folder: run the same commands from there (`sudo os/scripts/build.sh`).
Every change to it is checked by GitHub Actions (`.github/workflows/huginn-os.yml`: flake8 and shell syntax, and
`scripts/ci-smoke.py`, which opens every app and the shell headless; the package lists against Ubuntu 26.04 by hand).
Huginn's own compositor (`compositor/`, Rust) is built inside the image: the build puts Rust and the headers in only
while it builds, then takes them out. Its crates are fetched with `cargo` on the build computer when it has one (kept
in the work folder), otherwise inside the image.

Local settings that stay out of the repository go in `config/build.local.conf` (sourced after `build.conf`): a nearer
mirror, `SNAPSHOT=""` for the live archive, faster compression, or `APT_PROXY` / `APT_CA` for a machine that only
reaches the archive through an HTTPS proxy (used during the build only; removed before the image is packed).

## Layout

    config/build.conf            suite, snapshot date, names, compression
    config/package-lists/*.list  one package per line, # comments
    config/overlay/              copied onto the root filesystem as-is
    config/hooks/*.sh            optional scripts run inside the chroot, in name order
    apps/                        the apps: one Python host + QML per app, the shared kit, the portal backends
    shell/                       Huginn Shell: Python host + QML (top bar, dock, launcher, control centre, widgets)
    tokens/tokens.json           design tokens (single source of truth, shared with Huginn)
    tokens/gen_theme.py          tokens -> KDE colour schemes, GTK colours, Kvantum styles, QML singleton
    scripts/                     host setup, build, QEMU test, CI smoke test, xwayland-satellite
    patches/                     small patches to software built from source (xwayland-satellite)
    mockups/                     design previews rendered from the tokens

## Try the shell without building an ISO

On any machine with Python 3:

    pip install PySide6
    python3 shell/huginn_shell.py --preview            # add --light, --realm bifrost, --open cc

The dock buttons, control centre, realm picker, dark toggle and launcher search all work in the preview.

## The apps

Twenty apps share the shell's theme, settings and component kit (`apps/qml`). Run any of them on any machine with PySide6:

    python3 apps/huginn_app.py files            # also: calendar, mail, settings, monitor, store, video, music,
                                                # notes, photos, documents, calculator, clock, terminal, screenshot, archives, welcome
    python3 apps/huginn_app.py music --demo     # --demo fills calendar, mail, store, music and video with sample content

| App | Works now | Not yet |
| --- | --- | --- |
| Files | Browse, back/forward/up, breadcrumbs, grid and list (only the rows in view are drawn, so big folders stay quick), thumbnails for pictures, videos and PDFs (cached); tabs (Ctrl+T, Ctrl+W, Ctrl+Tab, middle-click a folder); search this folder as you type, Enter to search its subfolders, and "Inside files" to read inside text files, PDFs and office files too; select several (Ctrl/Shift click, drag a rectangle, arrows, Ctrl+A, type a name); rename one, or several at once with a shared name and numbers; quick look with Space (pictures, videos, PDFs, text), arrows to move on; cut, copy, paste, duplicate, and drag and drop (onto folders, places, drives, the Trash, and to and from other apps) with a choice when a name is taken, off the window's thread with progress and Stop; undo for the last rename, move, copy, new folder or move to Trash (Ctrl+Z), and redo (Ctrl+Shift+Z); sort by name, date, size or kind; Trash view with Put Back, Delete for Good and Empty; drives you plug in (open, eject), locked ones with their password; network places (smb, sftp, ftp, dav, nfs) with sign-in, remembered addresses and a list of computers that announce themselves on the network; Open With, with "always"; Compress to .zip; New Text File; Go to a Folder (Ctrl+L) with pinned folders; Open in Terminal; Details, with who else may open or change a thing, Locked, and Run as a program; refreshes by itself when another app changes the folder | Listing a Windows PC's shared folders (you type the folder name after its address), applying sharing to everything inside a folder, changing the owner, a pane to play video or sound in quick look. Dragging the file area no longer moves the window (it selects); the top strip still does |
| Calendar | Month view, pick a day, add and remove events (saved locally), coming-up list | Week view, repeating events, online calendars |
| Mail | Real accounts over IMAP and SMTP, always in TLS with the certificate checked; sign-in that knows the common providers, with Google and Microsoft accounts signed in on the provider's own page (OAuth 2 with PKCE, see "Mail sign-in" below) and app passwords for iCloud, Yahoo, AOL, Fastmail; every account's sign-in kept in the Passwords vault under the master password, never in a file of Mail's own; mailboxes with their roles worked out; newest 400 per mailbox with previews; read, star, unread, archive, junk, Trash, delete for good; search; write, reply, reply all, forward with quoting and threading headers; attachments both ways; address suggestions from Contacts and past mail; several accounts; an unsent message survives closing; opens email links; a local cache so it opens at once and reads offline. HTML mail is shown as text and nothing in a message is ever fetched, so trackers never load | Google and Microsoft sign-in until this copy of Huginn is registered with each (a free, one-time step only the distributor can do; see below). Tuta (it offers no IMAP); Proton only through its Bridge. Exchange without IMAP. HTML shown as designed, server-side drafts, push (it checks every 3 minutes), rules |
| Settings | Light/dark, realm, top-bar menu style, About | Network, Displays, Sound, Notifications, Apps, Users pages |
| System Monitor | Ring gauges and two-minute graphs for processor, memory and swap, network and disk; sortable process list with per-program processor, memory and disk use; right-click to end, pause, resume, force stop, show location or see properties | Network use per program (Linux does not expose it without extra tooling), start-up apps |
| App Store | A featured app, shelves of app rows, search, and an app page with facts at a glance and a picture gallery (developer screenshots, loaded from Flathub when you open the page); Get / Open / Remove through Flatpak with live progress, Verified marks from Flathub. Installed list also shows web apps installed from Huginn (any .desktop file with `X-Huginn-WebApp=true`), with Open and a confirmed Remove | Updates page. Flathub has no ratings, so none are shown. The catalogue reader is tested on a hand-made file in Flathub's format, not on the real catalogue; installing through Flatpak is untested |
| Media Player | Library from Videos, play/pause, seek, volume, full screen | Subtitles, playlists. Playback itself is untested (see below) |
| Music | Library from Music, albums, search, queue through the list, seek, volume | Tags from files, artwork, playlists. Playback itself is untested |

| Notes | Notes as Markdown or text files in Documents/Notes; saves as you type (safely, via a temporary file); search; move to trash | Formatting buttons, Markdown preview, sync |
| Photos | Grid from Pictures, by month; viewer with zoom, next/previous, details; rotate and save; move to trash | Crop and other edits, albums |
| Documents | PDF reading with page thumbnails, find, zoom, fit width. Plain-text and code editing: line numbers, colouring for common languages, find, auto-indent, word wrap; saves safely and keeps the file's encoding and line endings; warns before overwriting a file something else changed | Password-protected PDFs, annotations, printing, find and replace, several files open at once. First page fit is rough |
| Calculator | Exact decimal sums with brackets and %, live preview, keyboard entry, history | Scientific functions, unit conversion |
| Clock | World clock, stopwatch with laps, timer | Alarms and sound: they need a background service, so the timer only runs while Clock is open |
| Terminal | Your shell with colours, scrollback, resize, paste, Copy All (screen logic from the `pyte` library) | Selecting text with the mouse, tabs, profiles. Redraw is slower than a native terminal |
| Screenshot | Whole screen, or let the desktop ask for a window or area; delay; pen, box and highlighter in six colours; undo; save, copy | Crop, text labels. Capturing on Wayland (through the desktop portal), saving and copying are untested |
| Archives | Look inside zip and tar files, unpack all or one item into a new folder; refuses entries that try to write outside it | Creating archives, 7z and rar, passwords |
| Welcome | Five-step tour with a live realm and light/dark choice; shows itself once at first login | |
| Passwords | The same vault the Huginn browser fills from and saves to (one file, one master password): a login saved in the browser appears here and the other way round, with both open at once. Unlock once: unlocking either app, or Mail, unlocks the others until Lock is pressed in any of them or an hour passes unused (a switch in Passwords turns this off). Holds Mail's sign-ins too. AES-256-GCM, key from the master password by scrypt; the master password is never stored. Entries with name, password, website, notes; random passwords and word passphrases; strength meter; weak and reused flags; copy with the clipboard wiped after 30 seconds; locks itself after 5 idle minutes; slows down repeated wrong tries; import and export browser .csv; change master password; a spare of the last file | Passkeys, syncing between computers, fingerprint unlock, attachments |
| Contacts | An ordinary .vcf file any phone or app can read; alphabet index, favourites, search; names, numbers, emails, address, birthday (with "in 3 days"), website, notes; import (skips people already here) and export; fields Huginn has no box for (photos, nicknames) are carried through untouched; opens .vcf files; feeds Mail's address suggestions | Photos shown, groups, syncing with a phone or CardDAV, more than two numbers or emails editable (extra ones are kept) |
| Weather | Places you pick by name; now, 24 hours, 8 days; °F/°C; the last forecast stays readable offline. Nothing works out where you are: only the chosen place's coordinates are sent, to open-meteo.com (no account, no key; free for non-commercial use) | Radar and maps, alerts, a shell widget |
| Backup | Dated copies of Home on another drive or server; unchanged files are shared between copies (hard links), so each backup looks complete but only changes take room; daily or weekly by a systemd user timer; browse any backup and bring files back, never over what you have now; keeps the newest 30; checks free room first; stopping leaves nothing half-done | Encrypting the backup, choosing folders to leave out, restoring a whole system, cloud services |
| Disks | Every drive with how it is divided and how full; open, close, eject; rename; erase to exFAT, ext4 or FAT with a typed name and a tick to confirm. The drive Huginn runs from can't be changed, whatever is asked | Changing partitions, health (SMART) readings, disk images, encrypting a drive |
| Camera | Viewfinder, photo and video, 3 and 10 second timer, thirds grid, several cameras, last shot thumbnail; saves to Pictures/Camera and Videos/Camera | Not run with a real camera yet. Zoom, filters, resolution choice |
| Voice Recorder | One-button recording with pause, to Music/Recordings (.m4a); list with play, rename, show in Files, Trash | Not run with a real microphone yet. Level meter, trimming, choosing the microphone |

Tested without a display: the calculator's arithmetic, notes (create, save, trash), archives (including two hostile archives, both refused
with nothing written), photo rotation, the world clock, and the terminal running real shell commands. Tested only as rendered pictures:
every screen. Not tested: anything needing a click or a real desktop session.

## Huginn Office: Writer, Sheets, Slides

    python3 apps/huginn_app.py writer            # also: sheets, slides; add a file to open it

| App | Works now | Not yet |
| --- | --- | --- |
| Writer | Page view; title, heading, subheading and body styles; bold, italic, underline; size; colour; alignment; bulleted and numbered lists; saves as you type; export to PDF, Word, OpenDocument, Markdown | Pictures, tables you can edit, page breaks, headers and footers, spell-check, printing |
| Sheets | 26 x 200 grid; numbers, text, percentages; formulas with cell and range references and 20 functions (SUM, AVERAGE, MIN, MAX, COUNT, ROUND, IF ...); clear error marks; column summary; export to Excel and CSV | Several sheets, cell formatting, charts, sorting and filtering, selecting a range with the mouse, column resizing |
| Slides | Four layouts, three themes, slide navigator, add / delete / reorder, speaker notes, full-screen presenting, export to PDF and PowerPoint | Pictures, free text boxes, bullets, transitions, presenter view with notes on a second screen |

Each app keeps its own work in an open format: Writer in HTML, Sheets and Slides in JSON (`.hsheet`, `.hslides`).

### Other suites' files (the hybrid)

- `.docx`, `.xlsx` and `.pptx` are read and written by our own converters (`apps/huginn_convert.py`, Python standard library only).
- Older or rarer formats (`.doc`, `.odt`, `.rtf`, `.xls`, `.ods`, `.ppt`, `.odp`) appear only if LibreOffice is installed. It runs invisibly to
  turn them into the modern format, and our converters take it from there. LibreOffice's window never opens, and it is not in the package lists.
- A foreign file always opens as a copy in our format; the original is never written to. A notice lists what was not carried over.

What was tested, on the machine these were written on:

- Our converters against independent open-source libraries (python-docx, openpyxl, python-pptx): they read what we write, and we read what
  they write. 21 checks pass, including a file with an XML entity trick and a non-zip file, both refused.
- LibreOffice 's own reader opens the .docx, .xlsx and .pptx we write, and recalculates the spreadsheet correctly.
- The LibreOffice route for real: .odt, .doc, .ods and .odp each opened inside Writer, Sheets and Slides.
- The spreadsheet arithmetic (22 formula checks), document editing and saving, and Slides' PDF export end to end.
- NOT tested: opening our files in Microsoft Office itself, and anything that needs clicking in the real windows.

Playback uses Qt Multimedia. The machine these were written on has no sound system, and Qt Multimedia crashed there on load,
so real playback has not been heard or seen yet. The previews with `--demo` do not load it.

The App Store's `--demo` catalogue is illustrative: the app names are real Flathub apps, but the summaries, sizes and Verified
marks shown are sample values, not read from Flathub.

## Reproducibility

- Every apt source is pinned to snapshot.ubuntu.com at the SNAPSHOT timestamp in build.conf.
  If the build host cannot reach that timestamp, pick a valid one or set SNAPSHOT="" to use the live archive.
- SOURCE_DATE_EPOCH comes from the last git commit, so file times in the squashfs and ISO are stable.
- out/*.manifest lists every package and version in the image; diff two manifests to see what changed.

## Known limits of Phase 1

- Scripts are syntax-checked and the package lists are verified against the 26.04 archive,
  but the first end-to-end build has not been run yet. Expect small fixes.
- grub-mkrescue images boot on BIOS and UEFI but not with Secure Boot enabled. Phase 2 moves to the signed shim layout.
- (Phase 1 offered two sessions, KWin + Huginn Shell and Plasma. Both are gone: the sign-in screen and the session
  are Huginn's own compositor, see "KWin's gone" below.)
- Huginn itself is not in the image yet. It already runs on Linux through its per-user installer; Phase 2 wraps that as a system package.

## App style: glass and islands

Every app uses one style, chosen from four mockup rounds (the "D" set): no title bar, a rounded window tinted with the
app's own colour, light in that colour coming from the app's main island, and controls floating in islands like the
dock's. Each app has its own colour (`tokens.json`, `apps`; Welcome takes the realm's) and puts its main island where
its job needs it.

- Shared parts: `GlassWindow.qml` (frame, tint, glow, drag, window buttons), `Island.qml`, `Rail.qml`, `Seg.qml`,
  `IslandField.qml`. An app can also just list a `sidebar` and a `toolbar`: they show as a rail and an island.
- The glow is one gradient, not a blur, so it costs nothing to draw; a light grain (`grain.png`) over it hides the
  rings a soft gradient would otherwise show. Photos rounds its pictures in the app (`image://roundthumb`), not with
  a shader. Nothing in the apps needs a graphics card.
- All twenty apps are rebuilt.
- Built since, to match the mockups: Calendar's week view (events placed by time, clashes side by side); Terminal
  tabs (Ctrl+Shift+T, Ctrl+Shift+W, Ctrl+PageUp/PageDown; a new tab opens where the last one was); Notes headings,
  checklists and lists (plain marks in a plain file: "# ", "- [ ] ", "- "); Photos albums (folders inside Pictures) and
  favourites; Screenshot's frame (the screen freezes, you drag a frame, Enter captures); several sheets in one Sheets
  file, kept through Excel import and export.
- Known limits of those: a Sheets formula cannot read from another sheet; a CSV file holds one sheet; Calendar events
  have a start time but no length (drawn as one hour); Notes shows the marks as text, coloured, not as drawn boxes.
- Documents is also the text and code editor, and the default app for text files (Markdown stays with Notes). Files
  now covers the everyday jobs of a file manager. The Trash follows the freedesktop.org layout, so other file managers
  see the same Trash. Drives use `lsblk` to list and `udisksctl` to open and eject (`udisks2` is in the package list).
  A locked drive's password is piped straight to `udisksctl` and is not kept. "Always open with" is written to the
  user's `~/.config/mimeapps.list`. Thumbnails are kept in `~/.cache/huginn/thumbs` (trimmed past 5000).
  Video thumbnails need `ffmpeg`; network places need `gvfs-backends` and `gvfs-fuse` (all three are in the package
  list). Files talks to `gio mount` and answers its questions; a server's password goes down a pipe and is not kept,
  only the address is remembered. Computers on the network are found with `avahi-browse` (`avahi-utils`, in the
  package list); a Windows PC that doesn't announce itself that way won't be listed, but its address still works.
  Kate and Dolphin are still in the image until both apps have been used on the real desktop; then remove `kate` and
  `dolphin` from `config/package-lists/20-desktop.list`.
- Not built yet: the halo a window casts on the desktop (the window manager's job, not the app's), and edge resizing
  (only the bottom-right corner resizes). A playing video is not cut to the window's rounded corners.
- Files and the Documents editor are also tested by scripts that press keys and click in the off-screen window
  (208 checks of what Files does, 104 of its screen; 26 + 14 for Documents). Not tested, because they need a real
  desktop: the drag gesture itself (what a drop does is tested), a real USB stick and a real locked drive (the drive
  list and `udisksctl` were stood in for), Open in Terminal, and real network places: connecting was tested against a stand-in for `gio mount` that asks
  the same questions, so a real SMB or SFTP server is the first thing to try.
- The second set of apps (`apps/huginn_more.py`) and Mail (`apps/huginn_mail.py`) are tested the same way: 80 + 61 checks of
  the engines, 23 of their screens, 36 of the shared vault (against the browser's own vault code, both directions), and for Mail 131 + 31 against a small IMAP and SMTP server run on localhost over
  real TLS. Not tested, because the sandbox has none: a real mail provider, a real camera and microphone, a real
  format (the system calls were stood in for and checked), the systemd timer firing, and a live Open-Meteo reply
  (sample replies in its documented shape were used).
- One vault for the browser, Passwords and Mail (`apps/huginn_vault.py`; the browser side is its pull request #3,
  already in `vendor/huginn`). The file is the browser's own, `~/.local/share/SafariQt/SafariQt/passwords.vault`.
  Each program merges with what is on disk before it writes, under a file lock, so two of them open together don't
  undo each other. "Unlock once" works through a small helper that holds the vault key in memory only, on a socket in
  your login's runtime folder: it answers only your own user, and only programs run from the installed, root-owned
  Huginn files. What that does and doesn't protect against: another person's account can't use it; a program
  already running as you could, in principle, read a running app's memory with or without this helper. Turn
  "Unlock once" off in Passwords to have each app ask for itself.
- Mail holds its sign-ins in memory while it runs so it can keep checking for mail; the session going quiet after
  an hour doesn't stop that, pressing Lock in Passwords or the browser does (the mail already fetched stays readable).
- The helper's trust check needs the installed layout (`/usr/share/huginn-apps`, `/opt/huginn`): run from a source
  checkout, each app simply asks for the master password itself.
- Tested by rendering every app off-screen in dark and light, with no warnings. Not yet run on the desktop in the VM,
  so clicking, dragging, scrolling and full screen are untested.

## Icons and looks

- **App icons** (redrawn 2026-11-15, chosen on the design canvas: "smoked glass, all together, without the spark").
  Every app's icon is a tile of smoked glass (a squircle) with a picture of what the app is for, glowing in the
  app's own colour: the colour rises from deep at its foot to light at its top, glossy across its upper half, with
  a soft halo on the glass. The tile is thick glass (a lit top edge, a darker foot, a shadow under it), and a thin
  line of the app's colour runs along its bottom edge, as the dock's Ring. The apps seen most have richer pictures
  (the calendar's date, the clock's ticks, the lens's rings, papers in the folder). `scripts/make-icons.py` draws
  all 51 from the colours in `tokens/tokens.json` (SVG, plus PNG at 256, 128, 64 and 48) into
  `config/overlay/usr/share/icons/hicolor/`, named `huginn-<app>`; the `.desktop` files and the dock use them.
  Change a picture in that script and run it again.
- **Folders and files.** The same script writes the **Huginn icon theme** (`usr/share/icons/Huginn`, inheriting
  Breeze for everything else, set for KDE's parts and GTK): folders as smoked glass tinted with Files' blue with what
  they hold glowing on the front (Documents, Downloads, Music, Pictures, Videos, Desktop, Home, Templates, Public),
  and the common kinds of file as smoked-glass pages with their kind glowing on them and a label in its colour (text,
  PDF, pictures, music, video, archives, documents, sheets, slides, code, web pages, programs). Lists get plainer
  drawings at 24 and 16 pixels.
- **The two marks.** `branding/huginn-os.svg` is the system's logo (a white raven on a vivid aurora tile; shown in
  Welcome) and `branding/huginn-browser.svg` the browser's (the same raven in deep indigo on a pale aurora tile). The
  raven is a soft, rounded drawing made for these icons. The browser carries its icon itself (pull request #4).
- **Layouts.** Apps no longer share one "list on the left, detail on the right" screen. Reminders is four counters
  over a ruled page with the lists as tabs; Phone is the phone itself with its actions around it; Games is a console-style carousel that takes the colour of the game in front; Podcasts is a
  shelf of covers with a floating player; Translate is stacked, with the languages on the fold; Passwords is a
  cabinet of tiles that open into a card; Contacts is a wall of round portraits under their letters. Writer,
  Sheets, Slides, Documents, Archives, Notes and Photos each open on their own drawn start screen.
- **The browser's Islands look.** Optional, off by default: Settings > Appearance > Window Look in the browser
  (pull request #4, already in `vendor/huginn`). It gives the browser the same glass-and-islands frame as these apps,
  with close, minimise and zoom together in a pill like every other toolbar group.

## The third set of apps

`apps/huginn_reminders.py` (Reminders) and `apps/huginn_extra.py` (the rest). Each is a front for something the
system already does; when that thing isn't installed or reachable the app says so in plain words.

| App | What it does | What it leans on | Not yet |
|---|---|---|---|
| Reminders | Lists; Today, Scheduled, All, Flagged, Done; a new one typed as you'd say it ("Call Sam tomorrow 9am", "rent 1 dec", "in 2 weeks at noon"); notes, repeats (ticking one off moves it to next time); details sheet. The shell announces a reminder when it comes due whether or not the app is open. Calendar shows reminders that have a day; Notes ("remind me about this line") and Mail ("remind me about this") add to it; the dock shows how many are due Search across every list; put one off (an hour, this evening, tomorrow, next week) | Nothing: one JSON file, locked while written | Subtasks, sharing a list, snoozing from the notification itself, location-based |
| Phone | Devices near you; pair (confirmed on the phone), send files (also "Send to Phone" in Files), send the clipboard, send a note or a web address (a link opens on the phone), ring a lost phone, ping, battery level | KDE Connect (`kdeconnect-cli`); the phone needs its free app, same network | Reading and answering texts, notifications from the phone shown here, browsing the phone's files, using the phone as a remote |
| Print & Scan | Printers with their state and the usual one; print a file with copies, both sides, page ranges, paper size, black-only, sideways, fill-the-page ("Print…" in Files); the queue, with cancel. Scanners: scan pages one after another in colour or grey at three qualities, drop a bad page, save all as one PDF at the paper's true size in Documents/Scans, then send it by Mail | CUPS (`lpstat`, `lp`) and SANE (`scanimage`); driverless network and USB devices appear by themselves | Adding a printer that needs a driver or an address typed in, which tray, ink levels, document feeders and both-sides scanning, text recognition (OCR) |
| Maps | A map you can drag and zoom; search for a place or address; kept places; directions by car, bike or foot with the route drawn and each turn written out; km or miles; opens `geo:` links. Huginn never works out where you are | OpenStreetMap: its tile, search (Nominatim) and routing servers. These are run by volunteers for light use: for a distro with many users, point `/etc/huginn/maps.json` at your own (`{"tiles": …, "search": …, "driving": …, "cycling": …, "walking": …}`) | Offline maps, public transport, live traffic, "where am I", satellite pictures |
| Podcasts | Follow shows by name or feed address; episodes newest first; play, skip back 15 / forward 30, seek; playing speed (0.8× to 2×); keep an episode in `~/Podcasts` to play offline; remembers where you stopped and what you've played; checks for new episodes | Each show's own feed. Finding a show by name asks Apple's public podcast directory (only the words typed are sent) | A queue, chapters, keeping new episodes automatically, playing on in the background with the window closed |
| Books | A shelf of your EPUB books (from `~/Books`, Downloads, Documents) with covers and how far you are; a clean reading column; letter size; glass, sepia, white or black paper; a contents list from each part's heading; the book's own pictures, scaled to the column; reopens where you stopped. Opening a book can't fetch or run anything: only pictures from inside the book file are shown, and links, styles and scripts are dropped | Nothing (reads the files itself) | Search, highlights and notes, books locked by a shop (DRM), PDF (that's Documents), MOBI |
| Translate | Type or paste on the left, read on the right; swap; copy; earlier translations (kept in a file only you can read, with Clear and Don't Keep); translate a whole text file into a new file beside it ("Translate…" in Files); a language-pack manager that can also add a pack from a file you already have. Nothing typed ever leaves the computer; fetching a pack is the only network use | Argos Translate, which Ubuntu doesn't package: `config/hooks/30-translate.sh` puts it in the image from PyPI, asking for the CPU-only build of PyTorch (the ordinary one brought graphics-card libraries and measured 5.5 GB here; the CPU-only size wasn't measurable from the sandbox, expect 1 to 2 GB). If it can't be fetched the image is built without it and the app says so. Delete that file to leave Translate out | Detecting the language, translating files or web pages, speaking the result |
| Screenshot: Record a Video | Records a screen or a window, with what the computer is playing ("Sound: On/Off"; it carries on silently if sound can't be captured), to a video in Videos/Screen Recordings; the desktop's own picker asks what to share, so nothing is captured unasked | The desktop's screen-sharing service (xdg-desktop-portal), PipeWire and GStreamer, driven by `apps/huginn_screencast.py` | The microphone, recording just an area, a pause button, showing clicks |
| Games | Installed games from Steam, and from Epic, GOG and Amazon through Heroic, appear by themselves (name, cover, size, hours, last played); add your own Windows or Linux games by picking the program or dropping it in; a rail to see one shop at a time or what's running; Play / Stop; a profile per game of your own: compatibility layer (any Proton Steam has, Wine, or run directly), launch arguments, environment variables, performance overlay (MangoHud), GameMode, sync mode, the game's language, skip in-game videos, DLL preferences; each Windows game gets its own bottle; Steam accounts with what each has played here, and switching between them |

### Games

"The big screen": one game at a time stands large in the middle of the window, with the next ones peeking in from
the sides like a console's home screen, and the whole window takes on the colour of the game in front. Under it are
its name and one Play button. The shops are chips above (Everything, Steam, Epic, GOG, Amazon, Yours, each with its
count); a film strip along the bottom jumps to any game. Left and Right move, Enter plays, the wheel turns the reel.
A game's profile is an island that slides in on the right. A game with no cover from its shop gets a poster drawn
from its name, so no two look alike; nothing uses shader effects, so it also draws without graphics acceleration.

- **Steam games** are started by Steam (`steam://rungameid/…`), so Steam's own Proton, cloud saves and overlay keep
  working. A profile for a Steam game can't be pushed into Steam from outside, so the profile makes the Launch
  Options line (`… gamemoderun mangohud %command% -args`) with a Copy button and a button that opens the game's
  properties in Steam.
- **Epic, GOG and Amazon games** come through [Heroic](https://heroicgameslauncher.com), the free launcher that signs
  in to those three shops. Games reads Heroic's own lists (`legendaryConfig/legendary/installed.json`,
  `gog_store/installed.json`, `nile_config/nile/installed.json`, names from `store_cache/*_library.json`, play time
  from `store/timestamp.json`, covers from Heroic's `images-cache` when Heroic has already saved them) in
  `~/.config/heroic` or the Flatpak's folder, and starts a game with `heroic --no-gui heroic://launch/<shop>/<id>`
  (`legendary`, `gog` or `nile`). Heroic keeps those games' settings, so their profile only says so and opens Heroic.
  Signing in to the shops happens in Heroic; Games never sees those accounts.
- **Your own games**: a Windows program runs with the newest Proton that Steam has installed (through `umu-run` if
  that is installed, otherwise Proton's own `proton run`), or with Wine; a Linux program runs directly. Each Windows
  game's bottle is `~/.local/share/huginn/games/bottles/<id>`; what a game printed is in `games/logs/<id>.log`.
- **Steam accounts**: read from Steam's `loginusers.vdf` and each account's `localconfig.vdf`. Switching closes Steam
  (`steam -shutdown`), marks the other account as the most recent one (and `AutoLoginUser` in `registry.vdf`), and
  starts Steam again; the first change keeps a copy as `loginusers.vdf.before-huginn`. **Games never sees or stores a
  Steam password**: if Steam doesn't remember the account, Steam asks in its own window.
- Nothing is asked of any shop's servers, so games you own but haven't installed, and an account's worth, aren't shown.
- **Not in the image**: Steam (`steam-installer`, from Ubuntu's multiverse with 32-bit packages), Heroic (on Flathub
  as `com.heroicgameslauncher.hgl`; not in Ubuntu's archive) and Wine. Install any of them and Games picks it up.
  `mangohud` and `gamemode` are in (`46-huginn-games.list`).
- Tested (116 + 27 checks, dark and light): against a made-up Steam folder (libraries, manifests, cover cache,
  accounts, play time, four Protons), a made-up Heroic folder (all three shops, DLC, broken files), and stand-ins for
  `steam`, `heroic`, `wine`, `mangohud` and `pgrep`; starting, stopping, a game that fails at once, and account
  switching all ran for real against those. **No real Steam, Heroic, Proton or Wine, and no real game has been
  started.** Heroic's file layout and launch address are as its own project and other launchers document them, not
  seen on a real install. First things to check on a real computer: that Heroic's lists are read and its games
  start, that `proton run` starts a game outside Steam on this image, and that Steam honours the account switch.

What was and wasn't tested (102 + 32 checks, plus every screen rendered in dark and light):

- Reminders: everything, including the typed-line parser (16 phrasings), two windows at once, and the links to
  Calendar and Notes. The shell's announcement was tested as a function; the notification itself appearing was not.
- Phone, Print & Scan: against stand-ins for `kdeconnect-cli`, `lpstat`/`lp`/`cancel` and `scanimage` that answer in
  the real tools' formats as I know them. **No real phone, printer or scanner.** The first thing to check on real
  hardware is whether those formats match; KDE Connect also needs ports 1714-1764 open if a firewall is on.
- Maps, Podcasts: against a small web server on localhost answering in the shapes of Nominatim, OSRM, Apple's
  directory and an RSS feed. **No live server**, and the map tiles have never been seen drawing (the sandbox is
  offline). The map uses Qt's own map component with OpenStreetMap's tile server set as a custom host.
- Books: against EPUB files made by the test. No real shop-bought or library book.
- Translate: the app's own features against a stand-in translator, **and the real Argos Translate, installed in the
  sandbox, through the app's wrapper**: it loads, reports no languages, fetches the real list of 100 packs, and refuses
  a file that isn't a pack. What the sandbox's network blocked was downloading a pack (argos-net.com), so **no real
  sentence has been translated here**.
- Record a Video: only the app's side (start, stop, cancel, failure) against a stand-in recorder.
  **`huginn_screencast.py` has never run**: the sandbox has no desktop session, PipeWire or python3-gi. It is written
  to the portal's published interface and is the piece most likely to need a fix on first use.
- `config/package-lists/45-huginn-more-apps.list` holds the packages these need. Checked against Ubuntu 26.04's
  archive: `python3-pyside6.qtlocation` and `qml6-module-qtlocation` exist there, and `qt6-location-plugins` (the
  OpenStreetMap map plugin, which Maps needs) was added. The others are long-standing Ubuntu names but weren't each
  looked up; if the build stops on one, that line is the one to fix.

## The fourth set of apps

Eleven more, each with a layout of its own and its own colour (`tokens/tokens.json`). Plain text and code open in Code (below); anything with formatting belongs in Writer.

| App | The look | What it does | Leans on |
|---|---|---|---|
| Messages | "The people strip": faces along the top, the conversation as a river of bubbles, one floating writing island | Chat over [Matrix](https://matrix.org) with anyone on any Matrix app or server. Sign in with your Matrix address; the sign-in (an access token, never the password) and this device's encryption keys are locked in the Passwords vault. Chats you start are end-to-end encrypted; files are encrypted too in encrypted chats; invitations with Join / No; earlier messages; `/me`; leave a chat. A notice for a new message says only who it's from unless you turn on the words. Like Mail, it keeps listening with the window closed (switch in Account) and the session starts it at login | `python3-matrix-nio`, `python3-olm` |
| Authenticator | "The dial wall": a round countdown dial per account | Two-factor codes (TOTP and HOTP). Add by scanning the screen while a site shows its QR code, by pasting an `otpauth://` link or a QR picture, by dropping a picture, by typing the key, or a whole Google Authenticator export at once. Codes live in the vault (drawer `otp`), so one unlock opens Passwords and Authenticator together, and Passwords shows a site's current code on its login | `zbar-tools` (reading QR codes) |
| Privacy Report | "A week in ink", in black and white | Four lanes for the last seven days (camera, microphone, screen sharing, location), what is in use right now, which programs connected to other computers and to how many places (with Look Up), and how many trackers the Huginn browser stopped. A small notebook started at login writes it down; kept 30 days in `~/.local/state/huginn`, never sent anywhere | PipeWire (`pw-dump`), `ss`, GeoClue over D-Bus, the browser's own tracker log |
| Feeds | "The magazine": every story a card in a grid, each site with its own colour band and chip, the newest unread story as the big card; plain, large type on solid cards; a story opens as one wide, calm column with A− / A+ letter size (remembered) | Follow a site by its address (its feed is found for you: RSS, Atom, JSON Feed), Today / Everything / Starred / one site at a time, minutes to read, stars, read and unread, OPML in and out, checks every 30 minutes and asks only for what changed. Pictures, scripts and styles in a story are never loaded | Nothing (each site's own feed) |
| Money | "The wallet" | Your banks' own statement files (CSV in the usual layouts, OFX, QFX), skipping ones already in; categories guessed, with your own "always put this shop here" rules; monthly budgets; goals as jars; what comes round every month; a "safety net" ring of how many months your savings cover. One file only you can read. It never signs in to a bank, on purpose | Nothing |
| Shortcuts | "Recipe cards" | When: pressed, at a time on chosen days, at login, a drive or phone plugged in, joining a Wi-Fi network, battery low. Do: open an app, site or file, a notice, wait, copy new photos into Pictures/Imported, a backup, the volume, Wi-Fi on or off, a command. Six ready-made ones. A shortcut can sit in the apps menu. A light watcher started at login runs them | `wpctl`, `nmcli` |
| Clips | "The cutting room" (see "Code and Clips Pro" below) | A multi-track video editor on MLT | MLT (`melt`, `python3-mlt`), ffmpeg |
| Characters | "The type case": drawers on the left, a tray of characters, a big lens above | Every emoji, with skin tones and their names, and arrows, maths, money, punctuation, accented letters, Greek, shapes and signs; search by name; click to copy; recent and starred | Unicode's emoji list from `unicode-data`, or the copy bundled in `apps/data/emoji.json` (from [unicode-emoji-json](https://github.com/muan/unicode-emoji-json) 0.9.0, MIT, licence beside it); Python's Unicode database for the rest |
| Fonts | "The proof sheet": a sheet of warm paper with every family setting your words on a ruled line | Your own words and size on every font; a specimen page with every style, a size waterfall and the letters; try a .ttf, .otf or a font site's .zip before installing it; install for yourself (no password) into `~/.local/share/fonts`; remove what you installed; stars; monospace view | `fontconfig` (`fc-list`, `fc-query`, `fc-cache`) |
| Screen Sharing | "Two doors": this computer on the left, someone else's on the right | One button shares this screen with a fresh one-time password (12 letters, none that look alike), its address written large to read out over the phone, who is connected, which screen to show, a new password, and Stop. Sharing never outlives the window. Any Remote Desktop app can connect (Windows' own, Microsoft's Windows App on a Mac or phone, FreeRDP). The other door opens another computer's screen, remembering addresses and names but never passwords | KDE's RDP server `krdpserver` (`krdp`), FreeRDP's viewer `sdl-freerdp` (`freerdp-sdl`) |
| Help | "The field guide": one big question in the middle, guides on shelves with each app's icon, and the window turns the colour of the app you're reading about | 48 short guides (`apps/help/*.md`), one per app plus "Getting started" and "What goes online", searchable in your own words, each with a button that opens its app. `huginn_app.py help mail` opens straight at Mail's | Nothing |

New glyphs (`chat`, `bolt`, `wallet`, `smile`, `type`, `help`) are drawn in both `Glyph.qml` files, the eleven icons in
`scripts/make-icons.py`, and the packages are in `config/package-lists/47-huginn-new-apps.list`. At login,
`huginn-session-apps` now also starts Messages in the background (it leaves at once without an account), Shortcuts'
watcher and Privacy Report's notebook. Fonts opens font files, Feeds `feed:` links and feed files, and Money
statement files by default (`/etc/xdg/mimeapps.list`). The build now also installs Help's guides, the emoji list and
the windows' grain picture (`qml/grain.png`, which the image had been missing).

What was and wasn't tested (all on this sandbox, every screen rendered in dark and light with no QML warnings):

- **Messages** (41 checks) against a **real Matrix server** (Synapse) on this machine, with a second person played
  by a separate Matrix client: signing in (bad address, wrong password, new vault), starting an encrypted chat, the
  other person joining, messages decrypted both ways, encrypted files both ways and decrypted into Downloads,
  invitations, notices without the words, restart and unlock from the vault, sign-out. One more check: if this
  device's keys aren't ready, a message to an encrypted chat is refused with a reason, never sent in the clear.
  **Not tested against matrix.org or any public server.** Not yet: verifying the other person's device (emoji
  check, cross-signing), reading messages encrypted before this device signed in (key backup), servers that only
  allow signing in through a web page, replies, reactions and edits, calls.
- **Authenticator** (47 checks): code arithmetic against RFC 4226 and 6238's own test values, every way of adding,
  a hand-made Google Authenticator export, the vault, and Passwords showing the code. Reading a real QR code needs
  `zbarimg`, which wasn't in the sandbox, so only its output handling was tested. Not yet: the browser filling codes
  in for you, Steam Guard codes.
- **Privacy Report** (20 checks): against recorded `pw-dump`, `ss` and `/proc` output. **Not run on a live desktop**:
  the first thing to check is that PipeWire's own words for camera, microphone and screen streams match. The
  location service only says when location is in use, not by whom.
- **Feeds** (49), **Money** (51), **Shortcuts** (55): against a local web server (RSS, Atom with XHTML, JSON Feed,
  discovery, not-modified answers, OPML), statements in four banks' layouts and OFX (SGML and XML), and simulated clocks,
  drives, phones, Wi-Fi and battery. Shortcuts' watcher was never left running through a real login.
- **Clips** (44): a **real export through ffmpeg** of clips of different sizes, an upright one and a silent one, with
  soft cuts and captions, checked with ffprobe (length, sound, size); a second export doesn't overwrite, Stop leaves
  nothing behind. Playing in the window (QtMultimedia) was not tested: it can't run off-screen.
- **Characters, Fonts, Screen Sharing, Help** (74 checks + 45 on-screen): Unicode's emoji-test format and the bundled
  list, tones, copying and the clipboard; Fonts installing a real font and a font site's .zip (paths inside the zip
  are never trusted, Mac junk skipped), listed by fontconfig, then removed, with system fonts refused; Screen Sharing
  against **stand-ins** for `krdpserver` and `sdl-freerdp` (the server's arguments, a password handed to the viewer
  on its input so it never shows in the process list, a port already in use, a server that fails at once, sharing
  ending with the window). **No real remote-desktop connection has been made.** The "who is connected" readout uses
  `ss`, which the sandbox lacked, so only its reading of `ss` output was tested. `krdpserver` takes its password on
  its command line, so while sharing it is visible to your other programs; it is a one-time password and changes
  with every share. KDE's server streams the picture and takes mouse and keyboard; no sound. The first share asks
  the desktop's permission. If you turn on the firewall (`ufw`, installed but off), allow port 3389.
- Help: every app has a guide and every guide's app exists (checked by the test), and the guides' button names were
  checked against the apps' own.

## Code and Clips Pro (round 1 of several)

**Code** (`apps/huginn_code.py`, `qml/Code.qml`), "the workbench": the project in one tall island on the left (files,
project search, Git, problems), open files as tabs floating across the top, the code on a dark slab, a terminal that
slides up beneath it, and a status line. Text and code files open here by default (`mimeapps.list`); Documents now
reads PDFs only and hands anything else to Code. One Code at a time: opening a file while it runs sends it to the open
window.
- Editing: per-tab undo, syntax colouring for ~25 languages (block comments, Python's triple quotes, decorators,
  types, function names), the file's own indentation, Enter keeps and adds indent, brackets and quotes close
  themselves, Tab / Shift+Tab indent lines, Ctrl+/ comments, find and replace with case / whole word / pattern,
  word wrap, letter size, the file's encoding and line endings kept, a file changed on disk is taken in when nothing
  was typed here and asks first when something was.
- Getting around: Ctrl+P quick open (fuzzy, honours `.gitignore`), `>` commands, `:` line, `@` symbol; a command
  palette (Ctrl+Shift+P) with every action and its key.
- Project: a file tree with Git colours, new / rename / Trash, search across the project with ripgrep, replace in
  every file it found (open files change in their tab, undoably).
- Git: branch, changes, a diff for each file, stage / unstage / throw away (asks first; a new file goes to the
  Trash), commit (stages everything when nothing is), pull and push (a sign-in prompt can't appear, so it says to
  run the command once in the terminal), change bars beside the line numbers.
- Language servers, the same ones VS Code uses, over LSP: completions as you type, problems underlined and listed,
  hover (Ctrl+I), go to definition (F12, Ctrl+click, across files), format. Python's (pylsp) is in the image, quiet
  about style (pyflakes on, pycodestyle off); clangd, rust-analyzer, gopls, typescript-language-server,
  bash-language-server and others are used when installed. Without one: word completions and Python / JSON checks.
- Run (F5): saves, then runs the project its usual way (make, cargo run, go run ., npm run dev/start, CMake,
  Django) or the file in front, in the terminal; `.huginn-run` holds your own command.
- Tested (69 + 23 checks): against a real Git repository, ripgrep and a **real Python language server** (pylsp:
  problems, completions, hover, definition in another file, problems following your typing), the hand-over to a
  running Code, and on screen: typing helpers, palette, find, commit, project search and a real shell in the
  terminal. Not yet: a debugger (DAP), rename and references, multiple cursors, split editors, a minimap, extensions.

**Clips Pro** (`apps/huginn_clips.py`, `qml/Clips.qml`), "the cutting room", now on **MLT**, the engine behind Kdenlive
and Shotcut. The project is JSON; Clips writes it as an MLT project that both the viewer and the export read, so the
picture is exactly what will be made. The first Clips' projects are carried over.
- Library with bins, thumbnails, durations, 4K badges and **proxies** (540-line stand-ins for smooth 4K editing;
  exports use the originals).
- Timeline: as many video tracks (stacked, for picture-in-picture, logos and titles) and sound tracks as you like,
  with hide / mute / lock; drag to move with snapping, drag ends to trim, ripple, blade tool and cut at playhead,
  duplicate, markers, zoom, undo and redo; waveforms on sound and thumbnails on video.
- Place: size, position, turn, see-through, crop, fades, **keyframes** (◆ at the playhead) for size, position,
  see-through and volume.
- Colour: exposure, contrast, saturation, white balance, tint, shadows / midtones / highlights **colour wheels**,
  **LUTs** (.cube), and scopes (waveform, vectorscope, histogram) of the current frame.
- Effects: blur, sharpen, vignette, black and white, mirror, flip, video denoise. Speed ¼× to 8× with pitch kept.
- Sound: volume and fades per clip, noise clean-up, **music ducking under voices**, loudness evened out for the web
  (EBU R128, −16 LUFS) when making the video.
- Titles: lower third, big title, heading, subtitle; size, colour, alignment, placement, band and shadow.
- Transitions on the same track: cross dissolve and eight wipes (patterns drawn for Huginn, `apps/data/lumas`); they
  borrow footage beyond the cut, and where there is none the clips overlap, as Final Cut does.
- Export presets: H.264, H.265, AV1, ProRes 422 HQ, AAC and WAV, at the project's size, 4K, 1080p, 720p or half, in
  three qualities, never over another file, stoppable. Save as an MLT project for Shotcut or Kdenlive.
- Viewer: frames pulled through MLT's Python bindings at the project's rate on their own thread (late frames are
  skipped), sound through MLT's audio output started at the same moment. Without the bindings, the viewer shows the
  exact frame under the playhead rendered by `melt`, and says that playing needs `python3-mlt`.
- Tested (54 checks without the bindings, 56 with; 16 on screen): with real footage, the model (blade with
  keyframes, ripple, snapping, overlaps refused, the transition overlap), the MLT project (every filter it uses
  present, ducking keyframes on the music), **real exports through melt** checked with ffprobe (size, length, sound,
  the black-and-white grade visible in the pixels), sound-only export, stopping, saving the .mlt; the live viewer
  rendering and playing at about 26 frames a second on this 2-core sandbox, dragging and the blade on screen.
  **Not heard**: the sandbox has no sound device, so playback sound (MLT's `sdl2_audio`) is untested; picture and
  sound are started together and kept by the clock, not locked to each other, so long plays may drift slightly.
  Not yet (later rounds): multicam, motion tracking, stabilising, speech-to-text captions, curves, masks, nested
  timelines, audio mixer and effects, GPU effects.

## Settings, Software Update, Online Accounts, photo editing and Easel

**Settings** is now the whole system's settings: 17 pages in a rail of coloured tiles, each page in its own colour
(the window's light takes it on), and a search that finds any setting. Each page talks to the tool the system already
uses, so changes made elsewhere show here too:

| Page | Tool | What it does |
|---|---|---|
| Wi‑Fi & Network | NetworkManager (`nmcli`) | networks in range, join (password on stdin, never in the process list), hidden networks, details, VPN from WireGuard/OpenVPN files, hotspot, airplane mode, saved networks |
| Bluetooth | BlueZ (`bluetoothctl`) | power, visibility, scan, pair, connect, forget, battery levels |
| Online Accounts | `huginn_accounts.py` | see below |
| Displays | KWin (`kscreen-doctor`, `kwinrc`) | a map to drag screens, resolution, scaling, refresh, rotation, main screen, brightness (`brightnessctl`), night light |
| Sound | PipeWire (`pactl`) | output and input devices and levels, a test sound, every app's own volume |
| Battery & Power | UPower, power-profiles-daemon, PowerDevil (`powerdevilrc`) | charge, health, cycles, power mode, screen-off and sleep times, lid and power button |
| Keyboard & Mouse | KWin's input devices over D-Bus, `kcminputrc`, `kxkbrc` | layouts, Caps Lock, Compose, key repeat; per device speed, natural scrolling, tap to click, left-handed |
| Date & Time, Language | `timedatectl`, `plasma-localerc` | time zone, network time, 24-hour clock; language and formats with a live sample |
| Users | AccountsService over D-Bus, `passwd` on a pseudo-terminal | picture (drawn initials or a photo), name, password, other people, administrators |
| Default Apps | `mimeapps.list`, `~/.config/autostart` | a tile per kind of file; apps that open at sign-in |
| Privacy & Security | ufw, Flatpak's permission store, `kscreenlockerrc`, `ktrashrc` | firewall, per-app camera/microphone/location, screen lock, recent files, emptying the Trash |
| Notifications | `~/.config/huginn-shell/notifications.json` | Do Not Disturb, quiet hours, previews, per-app allow/banner/sound (the shell reads it in Phase 3) |
| Software Update | `huginn_updates.py` | see below |

Anything the system guards (firewall, time zone, other people's accounts) goes through polkit, so the system's own
window asks for the password; Settings never sees it. PowerDevil now starts with the session, so the power settings act.

**Software Update** (`apps/huginn_updates.py`): system packages through PackageKit (or `pkexec apt-get`), Flathub apps
(user and system), firmware through fwupd, and the Huginn browser straight from its repository. A newer browser goes
into `~/.local/share/huginn-os/browser/<commit>`; `/usr/bin/huginn` starts whichever copy is newer, and Go Back
returns to the previous one. Downloads are unpacked only inside their folder and must compile before they're used.
Automatic updates (on by default) run from the session every six hours: apps and Huginn at once, system updates
downloaded and installed at the next restart (PackageKit offline updates). The App Store has an Updates page.

**Online Accounts** (`apps/huginn_accounts.py`): Google and Microsoft through their own sign-in pages (the same OAuth
registration as Mail, `/etc/huginn/mail-oauth.json`), iCloud with an app-specific password, Nextcloud through its
login flow. Sign-ins are kept in the Passwords vault. Mail gets the account (it notices without a restart);
calendars come in over CalDAV (Microsoft: Graph) and edits made in Calendar go back, touching only the name, day and
time in the server's copy so invitees and alarms survive; contacts come down over CardDAV; Nextcloud files are
mounted with gvfs. `huginn_accounts.py watch` keeps them in step every 15 minutes.

**Photos editing** (`apps/huginn_photoedit.py`): Adjust (light, colour, detail, Auto Enhance), eleven filters with
live previews and strength, crop with shapes, straighten (trimmed so no empty corners), turn, flip, undo and redo,
hold to compare, Save as Copy. Non-destructive: the original is put aside at the first edit, edits are kept as
numbers, re-editing starts from the original, Revert to Original restores it.

**Easel** (`apps/huginn_easel.py`, `huginn_easel_ui.py`, `qml/Easel.qml`), the new image editor: pixel and vector
layers in one picture, like Affinity's single app. Pixel bench: seven brushes (size, hardness, flow, opacity,
scatter), eraser, fill (tolerance, touching only), gradients, rectangle/ellipse/lasso/magic-wand selections that add
and subtract, feather, grow and shrink, move (what's selected, or the layer), crop. Vector bench: rectangles,
ellipses, lines, stars, a pen with curves, text; pick, move, resize, rotate, arrange, align, and combine (unite,
subtract, intersect, exclude). Layers with blend modes, opacity, masks you paint on, adjustment layers, merge,
flatten, rasterise. Filters, canvas and image size, rotate and flip, trim. Files: `.easel` (zip of a manifest and
PNG layers), OpenRaster `.ora` for Krita and GIMP, PNG/JPEG/WebP/TIFF/SVG in; PNG, JPEG, WebP, SVG and PDF out (SVG
and PDF keep shapes as vectors). Round 1 of several: next are layer groups, free transform for pixels, clone and
healing brushes, curves, smart objects, guides and rulers, node editing, gradients on shapes, and PSD import.

Tested here: `settings_test` (61: every parser on real output formats, the right command for each change, passwd on a
pseudo-terminal, Huginn's own updater end to end), `settings_ui_test` (26: all 17 pages load clean, search),
`accounts_dav_test` (26, against a real CalDAV/CardDAV server, Radicale), `mail_absorb_test` (5), `photoedit_test`
(40), `easel_test` (89), `easel_ui_test` (20, real mouse and keys); the earlier suites still pass. Not tried here,
because this machine has none of it: real Wi‑Fi, Bluetooth, screens, sound, batteries, KWin's input devices,
AccountsService, PackageKit and fwupd, and signing in to the real Google, Microsoft and iCloud.

## Easel, Code and Clips: round two

The second round on the professional apps. Each change was tested against the real tools (debugpy, GDB, pylsp,
melt, ffmpeg's vid.stab), not mocks.

**Easel** (`apps/huginn_easel.py`, `apps/huginn_easel_ui.py`)
- **Free transform** (Ctrl+T) of a layer or a selection: move, scale (Shift keeps the shape), rotate, flip.
- **Clone stamp** (S) and **healing brush** (J). Healing blends the patch's texture with what's around it. Alt-click a source, or let Easel pick a clean spot.
- **Curves** adjustment layers, per channel. The curve is a monotone cubic.
- **Gradient fills** on shapes: linear in any direction, or radial.
- **Point editing** (A) of vector outlines. Click a segment to add a point (a de Casteljau split), delete points, switch corner and smooth. Convert to Outlines turns type and simple shapes into paths.
- **PSD** in and out: layers, names, opacity, blend modes, hidden layers and the merged image (8-bit RGB and grey, raw and RLE).

**Code** (`apps/huginn_code.py`, new `apps/huginn_debug.py`)
- **A debugger** over the Debug Adapter Protocol, the protocol VS Code's debuggers speak:
  - Python uses debugpy. C, C++, Rust and Go use GDB 14+ (`gdb -i dap`). For compiled programs, Code asks for the program once and remembers it in `.huginn-debug`.
  - Click a line number or press F9 for a breakpoint. Breakpoints are kept per project and follow their code as lines are added or removed.
  - F5 starts or continues, F10/F11/Shift+F11 step, Shift+F5 stops. Run moves to Ctrl+F5.
  - The stopped line is marked. The Debug panel shows the call stack, variables a level at a time, and a console that works out expressions in the paused program. The controls dock in the panel, or float over the editor when the panel is closed.
- **Rename** (F2) across the project through the language server's `textDocument/rename`. It applies the WorkspaceEdit to open tabs (unsaved) and to closed files on disk. Without a server, whole words in the file are renamed.
- **Find all references** (Shift+F12) lists results in the Search panel. Without a server, they're found by name, in open tabs as typed and on disk for the rest.
- **Side by side** editing (Ctrl+\\).
- **A minimap** drawn by a Python image provider (`image://minimap`), with the visible part marked. Click or drag on it to scroll.

**Clips** (`apps/huginn_clips.py`)
- **Colour curves** per channel, through MLT's `avfilter.curves`. The curve pad draws the same natural cubic spline ffmpeg uses.
- **Steadying.** A quick `avfilter.deshake` plays at once. Meanwhile a careful two-pass vid.stab copy (detect, then transform with optimal zoom) is made in the background and swapped in for the viewer and the export.
  - Tested: on a shaky test clip, frame-to-frame difference falls by about half.
  - MLT's own `vidstab` filter wasn't used: its analysis only holds at the size it was made at, and Clips previews at a smaller size than it exports.
- **A mixer** with a strip per track: fader (track gain added to every clip's level), pan (MLT `panner`), mute, solo (the tracks' `hide` attributes) and meters from the sound outlines under the playhead. A fader drag is one undo step.
- **Captions** on their own track:
  - SRT and VTT in and out. Exports save an `.srt` alongside the video.
  - Speech to captions through whisper.cpp (`whisper-cli` and a ggml model) or faster-whisper when installed. The film's mix is rendered to 16 kHz mono first. Not shipped, because the models are large.

Packages added: `python3-debugpy`, `gdb`.

## Accessibility, three new apps, and the pro apps' round three

Tested against the real tools where this build machine has them: QEMU (a UEFI machine's screen drawn in the window),
SANE's test scanner, Tesseract, FluidSynth, git, pytest, `go test`, melt and ffmpeg.

**Settings → Accessibility** (`apps/qml/SetAccessibility.qml`)
- Seeing: the screen reader (Orca), Zoom (KWin's zoom effect: follow the pointer, keep it centred or push at the edges), bigger everything (the shell and apps scale by `QT_SCALE_FACTOR`), high contrast, solid surfaces instead of glass, reduce motion, colour filters (KWin's colour-blindness filters and greyscale) and pointer size.
- Hearing: a screen flash instead of the alert sound. Moving and typing: sticky, slow and bounce keys, mouse keys and the on-screen keyboard (Maliit).
- High contrast, solid surfaces and reduce motion are read by the shared theme, so every Huginn app follows them. KDE's own settings are written to `kaccessrc` and `kwinrc`, and KWin effects are switched over D-Bus so they take effect at once.

**Scan** (`apps/huginn_scan.py`, new): documents from scanners (SANE `scanimage`, glass or feeder, one side or both) or from photos of pages. A photo's paper is found (OpenCV, with a plain-numpy fallback) and straightened (`QTransform.quadToQuad`); drag the corners if the guess is off. Clean-up as Document (white paper, black ink, shadows gone), Grey, Colour or as it is; every page keeps its original. Tesseract reads the text; the PDF (A4, Letter or each page's size) gets a hidden layer of it, so it can be searched and copied.

**Machines** (`apps/huginn_machines.py`, new): other operating systems in a window on QEMU, with KVM when the computer allows. Machines recognises installers in Downloads (Ubuntu, Fedora, Debian, Mint, Windows…) and suggests memory, processors and disk. Windows machines get UEFI with Secure Boot (OVMF) and a TPM (swtpm). QEMU is controlled over QMP and drawn by Machines' own VNC (RFB 3.8) client over a private socket, so nothing listens on the network. Snapshots include the running state; closing Machines saves running machines to carry on later. A folder can be shared into Linux machines (9p).

**Tempo** (`apps/huginn_tempo.py`, `apps/huginn_tempo_engine.py`, new; first called Studio): a music studio in the GarageBand mould, with the depth of a DAW.
- Templates; instrument, drummer and audio tracks; regions to move, trim, split and copy; undo.
- Fifteen instruments: synthesised ones (FM, subtractive, organ, plucked) and General MIDI ones rendered from FluidSynth multisamples; three drum kits.
- A piano roll with velocity and quantize, a drum grid, a drummer (style, kit, a pad from simple to complex and soft to loud, fills) and 18 loops that follow the song's key.
- Smart controls; per-track EQ, compressor, drive, chorus, delay and filter; sends to a shared reverb (partitioned convolution) and echo; volume automation; a limiter on the output.
- Recording from the on-screen keyboard, the computer's keyboard, MIDI keyboards (`/dev/snd/midiC*D*`) and the microphone; cycle and metronome.
- Export to WAV, FLAC, MP3, AAC, Ogg, stems or MIDI; MIDI files and sounds come in by dropping them on the window.

**Easel**: *Fill with Surroundings* (content-aware fill: PatchMatch with expectation-maximisation over an image pyramid, on a crop round the selection, in the background), *text on a path* (type follows a pen path, with an offset along it), and *pen pressure* from tablets (size, strength, both or neither).

**Code**: *blame* by every line (`git blame --porcelain` on the unsaved text) and inline for the current line; *history* of the folder or the file with a lane graph of the branches, and each change's diff file by file; a *test explorer* for pytest (JUnit XML), Go (`go test -v`) and Rust (`cargo test`): run all, a file or one, with failures and their output.

**Clips**
- *Easing* between keyframes (even, ease in, ease out, both, hold). MLT animates in straight lines, so eased stretches are sampled every two frames.
- *Sound effects* per clip: clear voice (high-pass, presence, compressor), compressor, three-band EQ and echo. The EQ uses MLT's SoX filter: MLT's libavfilter biquads (`avfilter.bass`, `equalizer`, `highpass`) were found to pass sound through untouched.
- *Multicam*: two to four clips lined up by cross-correlating their sound; cut between angles with 1–4 or the angle tiles as it plays; pick whose sound to use; flatten back to clips.
- *Motion tracking*: draw a box round something and it's followed (OpenCV template matching, refreshed as it goes, searched for again when lost). Pixelate it (a run of MLT `obscure` filters), or make a title or picture follow it with position keyframes.

Packages added (`config/package-lists/51-huginn-settings.list`, `52-huginn-scan-machines-tempo.list`): `orca`, `speech-dispatcher`, `espeak-ng`, `maliit-keyboard`, `tesseract-ocr` and language packs, `python3-opencv`, `qemu-system-x86`, `qemu-utils`, `ovmf`, `swtpm`, `swtpm-tools`, `fluidsynth`, `fluid-soundfont-gm`.

Not tested here: KWin's effects and Orca (they need a KDE session), real scanners, KVM speed (this build machine has no KVM), sound output and the microphone (no sound card), drawing tablets, and whisper models.

## The pro suite

Four apps are being taken, round by round, to the level of the professional tools people already know:

| App | Measured against | Rounds so far |
|---|---|---|
| Easel | Photoshop, Illustrator | 3 |
| Code | Xcode, VS Code | 3 |
| Clips | Final Cut Pro, Premiere, DaVinci Resolve | 3 |
| Tempo (first called Studio) | Logic Pro, Ableton Live | 1 |

**Tempo, pro pass one** (`apps/huginn_tempo_engine.py`, `apps/huginn_tempo.py`, `apps/qml/Tempo.qml`)
- *Sections*: Intro, Verse, Chorus markers over the bars. Copy a section after itself, move it, or delete it with its music, and the song closes up; automation goes with it.
- *Track stacks*: buses with their own effects, fader and sends. Ctrl-click tracks to stack them, fold them away, or send any track into a stack. Solo and mute follow the stack.
- *Automation of any knob*: volume, pan, both sends and every effect's settings. Effects keep their state as knobs move, so sweeps don't click.
- *Sidechain*: any compressor can listen to another track (Duck Under… sets it up). The compressor now follows with real attack and release, a fast and a slow follower, whichever is higher.
- *Editing recordings*: gain, fades, reverse, transpose and follow-the-tempo. Stretching and transposing use our own phase vocoder, with phase locking so chords stay clear (a minute of stereo in about three seconds).
- *Takes and comping*: every pass round the cycle becomes a take, MIDI or sound (the count-in is no longer recorded). Comps are swiped across takes and crossfaded over 5 ms; flattening writes them as one recording.
- *Sampler*: any sound across the keys, its note heard by our own YIN pitch detector, held or one shot, with start, end, attack and release. Drum kits take sounds of your own on any drum.
- *MIDI effects*: an arpeggiator (up, down, up and down, as played, random; 1/8 to 1/32 and triplets; up to four octaves) and a chord trigger (fixed shapes, or the chords of the song's key, live too).
- Songs made in Studio move to Music/Tempo on first start.

## From power-on to the desktop

Every screen between pressing the power button and the desktop is now Huginn's own, and they flow into each other.

- **Live wallpapers** (`config/overlay/usr/share/huginn-os/live`): each realm has a scene of its own, painted on the
  graphics card and moving slowly. *Aurora*: northern lights folding over a range, stars, mist and a still lake.
  *Bifröst*: the bridge of light with sparks crossing it, over a sea of cloud. *Muspelheim*: a volcano and rivers of
  fire under smoke, embers rising. *Niflheim*: snowy ranges under a low winter sun, mist between them, snow falling.
  They are GLSL shaders (`shaders/live`, built by `scripts/make-live-wallpapers.py` with Qt's qsb into `.qsb` files),
  with a still of each for computers drawing without a graphics card, for Settings and for the boot screen. A scene
  never jumps: told to stop, it eases to rest. In the light appearance the same scenes are painted by day.
- **Boot screen** (Plymouth): the realm's scene, soft and dark, the mark, and a thin line of the realm's light that
  fills as the computer starts. An encrypted disk asks for its password in a glass pill where the line was. Shutting
  down shows the mark alone; updates say so, with how far along.
- **Sign-in screen** (SDDM theme `huginn`): the live wallpaper moves behind a quiet clock. One frosted glass island
  holds your picture in a ring of the realm's light, your name and your password, whose arrow wakes when there's
  something to send. Everyone else waits as small orbs below it ("Someone else" types a name). The keyboard layout and
  session are a capsule at the top right, with lists that drop down; sleep, restart and shut down a capsule at the
  bottom right; the computer's name at the bottom left. A wrong password shakes the island, and the third says to
  check Caps Lock and the layout. Left alone for 30 seconds, all but the clock fades and the wallpaper has the screen;
  any key or movement brings it back, and a key goes into the password. Signing in turns the password into a line
  of light and the scene slows toward rest.
- **Arrival**: the desktop starts with the same island where it was (your picture, the line of light, "Welcome
  back") over the same scene, still coming to rest. Then it fades and the bar, the dock and the widgets come in.
- **On the desktop** the wallpaper is the same scene at rest. Settings › Appearance shows each realm's scene, keeps
  it moving on the desktop too if you like ("Live wallpaper"; never with Reduce motion), and dresses the sign-in
  screen in your realm ("Use Bifröst"), through Huginn's password prompt (`/usr/libexec/huginn-login-look`, polkit
  action `org.huginn.login-look`, writes the theme's `theme.conf.user`).
- **Password prompts** (`apps/huginn_polkit.py`): Huginn's own polkit agent, a glass card.

Tested: the scenes and stills rendered with Mesa's OpenGL (llvmpipe) on a virtual display; the sign-in screen run
against stand-ins for everything SDDM gives a theme (38 checks: wallpaper moving and coming to rest, people, someone
else, sessions, layouts, Caps Lock, wrong passwords, idle and waking, power); the boot screen run by Plymouth itself
with its X11 renderer (starting, a disk password, shutting down); the shell's arrival and the Appearance page.
Not tested here: SDDM's own greeter on 26.04 showing the theme, and how smooth the scenes are on real graphics cards
(they are light: a few hundred operations a pixel).

## Install Huginn OS: our own installer

`apps/huginn_installer.py` + `apps/qml/Installer.qml` (the app, as the live user) and `apps/huginn_install_engine.py`
(the engine, as root). Started from the installation drive, the installer opens by itself; closing it leaves you
trying Huginn OS, and it waits in the launcher.

- **Steps**, in a rail at the left that can be gone back along: Welcome (language, then Try or Install), Keyboard
  (search, and a place to try it; picked from the language, applied to the live session at once), Network (Wi‑Fi
  through NetworkManager; optional), Disk, You (name → user name and computer name suggested, password with its
  strength, sign in by myself), Time zone (picked from the language), Ready (everything once more; the button says
  "Erase and Install" when it will). Continue stays put, saying why, until a step is complete.
- **Disks** are read without root (lsblk and /sys): the live drive itself is never offered; Windows, Linux, macOS,
  EFI and recovery partitions are recognised; free space is found from the partition table. A bar shows the disk as
  it will be. **Erase**: GPT, a 512 MB EFI partition and the rest (BIOS computers get a 1 MiB BIOS boot partition).
  **Beside**: new partitions in the free space, sharing the disk's EFI partition with Windows (Windows' files left
  alone, its fallback boot file too), and GRUB's menu offers both. **Your own partitions**: one for Huginn OS
  (formatted) and the EFI one (shared). **Encryption** (erase or beside): LUKS2 for the system with a plain /boot
  beside it, unlocked on the boot screen's glass pill.
- **The engine** (`/usr/libexec/huginn-install-engine`, polkit action `org.huginn.installer`; on the live system a rule
  lets the live user run it without a password) takes the plan as JSON on stdin, so passwords never touch a disk,
  and reports each step as JSON lines: partition (sfdisk), format, copy the system (unsquashfs from the live
  medium, with its percentage), the kernel (casper keeps it beside the squashfs), settings (fstab by UUID, crypttab,
  hostname, language, keyboard for the console, the sign-in screen and the desktop, time zone, the person in the
  groups that exist, password through chpasswd, signing in by yourself, a swap file sized to the memory and the
  free space), tidying away the live system's pieces (casper, the installer, its polkit rule), a new initramfs,
  GRUB with shim for Secure Boot (plus the firmware's fallback path when the disk is Huginn's alone) or BIOS GRUB,
  GRUB's own package from the ISO's pool/ so it keeps itself up to date, and its log kept without passwords. If a
  step fails it unmounts, closes what it opened and says why; the window offers the log and a way back.
- While it installs, the window becomes the installation: a line of the realm's light filling, what it's doing,
  and a slideshow of the apps waiting on the other side; Show Details for the log. Then Restart Now.

Tested: the engine for real against disk images (each partition through its own loop device), with a small Ubuntu
live system packed the way the ISO is: erase on UEFI, beside another system sharing its EFI partition, your own
partitions, and encryption as far as this machine allows (it can make a LUKS2 volume, not open one); then the
erased disk started in QEMU with UEFI firmware (shim, GRUB, the kernel, about 80 seconds without KVM), and signing
in on its console as the person the installer made, with her password, then checking from inside: Oslo time,
Norwegian, sudo, the EFI partition and the swap file. The window walked through every step in demo mode (21
checks). Two things in this test machine stand in for a real computer's: the EFI partition goes through FUSE (no
FAT in its kernel), and GRUB's which-disk questions are answered for it (no partition devices). Not tested here:
real disks and a real ISO, BIOS installs, an encrypted system starting, Secure Boot with Microsoft's keys, and Wi‑Fi.

## Not yet our own

The goal is a desktop that is Huginn's from the first screen to the last. Where it stands:
- **Ours:** the boot screen, sign-in, lock screen (`/usr/share/huginn-os/lock/Lock.qml`, in both sessions), the
  installer, the shell (top bar, dock, launcher, control centre, widgets), the session daemon that replaced Plasma's
  background services (notifications, power, the hardware keys, Wi‑Fi passwords, Bluetooth pairing), and every app.
- **The desktop portal is ours** for nearly everything apps ask the desktop (`huginn-portals.conf`):
  - Open and Save (`apps/huginn_portal.py`): remembers the view, the sort and each app's last folder.
  - Screenshots for apps: the screen holds still, drag the part to share or take it all; a quiet screenshot first
    asks "Allow …?" once. Colour picking: the screen holds still with a magnifier (`apps/huginn_portal_ask.py`).
  - "Allow <app> to …?" (camera, screenshots, running in the background…) and **Open With**.
  - Settings apps read: dark or light, the realm's accent, contrast, less motion, fonts (`apps/huginn_portal_settings.py`,
    a small resident process, so a change reaches every app at once). KDE's settings come after Huginn's.
  - Still KDE's: **screen sharing and recording** (PipeWire). KDE's backend only offers it, and KWin only allows it,
    when told it's in KDE and when KWin knows the installed apps: Huginn's session now starts it through
    `/usr/libexec/huginn-portal-kde` and sets `XDG_MENU_PREFIX=plasma-`. (Before, screen sharing was missing in
    Huginn's session.)
- **Everyone else's apps wear the realm** (`apps/huginn_look.py`, run by the shell at sign-in and on every change):
  Qt and KDE apps get a Kvantum style generated from the tokens (KvAdapta's shapes, Huginn's colours, all four realms
  dark and light) and the realm's KDE colours; GTK 3/4 apps get Breeze-GTK in Huginn's colours, and libadwaita apps
  its named colours. Inter is the font everywhere. Icons are still Papirus.
- **The compositor**: being replaced with Huginn's own, in Rust on Smithay (see "Huginn's own compositor" below): it
  is now the session **"Huginn OS (own compositor, preview)"**. The earlier preview in Python
  (`shell/huginn_compositor.py`, `shell/qml/Compositor.qml`, inside cage) is what the notes below describe; it stays
  for `huginn_shell.py --compositor` until the Rust one has caught up with it.
  - **X11 apps** open as windows of their own through xwayland-satellite (built with a small patch:
    `scripts/build-xwayland-satellite.sh`, `patches/xwayland-satellite/`; no longer put in the image, since the new
    compositor has XWayland built in).
  - **Frosted glass**: the bar, dock, launcher and control centre blur what's behind them, desktop cards the wallpaper
    only — when a GPU draws the scene (a VM without one gets plain glass).
  - **Several screens**: cage spans them; the bar, dock and panels stay on the main one, windows open on the screen
    of the window in front, and Maximise fills the screen a window is on.
  - **KWin stays the default** until the preview has been used on real computers. A few apps that need newer Wayland
    protocol versions than Qt's compositor offers (the foot terminal) still won't start in it.
- **In the KWin session** the top bar and control centre now show the real computer: the app in front and its menu
  (Help, Minimise, Close Window — told by a small KWin script, `huginnactive`), battery, Wi‑Fi or wired, Bluetooth,
  Do Not Disturb, night light, brightness and volume, and the notifications that came, with Clear. The dock brings a
  running app's window forward instead of starting another.

## Apps handing things to each other

- **Files → Mail**: right-click files → "Send by Mail" starts a message with them attached.
- **Anything → Mail**: an email link (`mailto:` with to, cc, subject, body, attach) opens a draft. Only one Mail runs:
  a second start hands its link to the open one and leaves. A link can only attach ordinary files in your home
  folder, never hidden files, keys, system files or folders, and nothing is ever sent without you pressing Send.
- **Mail → Contacts**: the person button beside a sender adds them; a contact card (.vcf) in a message says "Add to
  Contacts" instead of "Save".
- **Mail → Calendar**: an invitation (.ics) in a message says "Add to Calendar"; Calendar also opens .ics files from
  Files or the browser. Times are converted to this computer's time zone.
- **Invitations**: a message carrying one shows what, when, where and who from, with Accept, Maybe and Decline. The
  answer goes to the organiser in the form calendar programs understand (an iTIP reply); Accept and Maybe also put
  the event in Calendar. A newer version of an invitation updates the event in place; a cancellation offers
  "Remove from Calendar" (a whole event, or one day of a series); one moved day of a series moves just that day.
  Sending your own: the envelope button on an event in Calendar starts a message in Mail that goes out as a real
  invitation to everyone in To and Cc, and their answers read as "Ada accepted …". Not yet: Calendar keeping a
  list of who has answered, and sending an update or cancellation to guests when you change or delete the event.
- **Repeating events** in Calendar: daily, weekly, monthly, yearly, when adding one and from calendar files (with
  end date, count, weekdays and skipped days), plus every weekday, "the last Friday of the month", "the 15th and
  the last day", "the fourth Thursday of November". One day of a series can be skipped; the bin removes the series.
  Only patterns that pick the n-th of a set or go by week number still come in once, on their first day.
- **Photos, Notes, Documents → Mail**: a "Send by Mail" button. A photo or document goes as an attachment; a note
  goes as the words of the message, its first line as the subject.
- **Dock badge**: the Mail tile shows how many inbox messages are unread. Any app can show a number the same way (a
  small file in `$XDG_RUNTIME_DIR/huginn/badges/`). Closing Mail's window leaves it running without one, so it keeps
  checking, notifying and updating the badge; the session also starts it that way at login when there is an account
  (`huginn_app.py mail --background`). Ctrl+Q quits it; "Check when closed" in Accounts turns all of this off. After a
  login it can't check until the vault is unlocked once, in Mail, Passwords or the browser.
- **Mail, further**: conversations (replies gathered into one row, with the others a click away; a switch in
  Accounts turns it off), a signature per account, and an Outbox: a message written offline waits there and is sent
  when the server answers, while a refusal (wrong address, sign-in) is still told straight away. If the line drops
  after a message has started going out, Mail can't know whether it arrived, so it never resends by itself: it says
  so, and a queued message is held in the Outbox with "Send Anyway" and "Don't Send".
- Calendar and Contacts can be open in two windows (or get a hand-over while open) without one undoing the other.
- Tested with 22 + 33 checks here (`mailto` parsing and its attachment rules, the single-Mail hand-over, calendar files,
  repeats, sharing, badges, two windows at once) and about 40 more in Mail's own (invitations both ways, conversations, signatures, Outbox, dropped connections, staying on). Not tested on a real desktop: the windows actually coming to the front.

## Mail sign-in: registering Huginn with Google and Microsoft

Google and Microsoft no longer take an ordinary password from a mail app. They want the person to sign in on the
provider's own web page, which then hands the app a token good for mail and nothing else. For that the app has to be
registered with the provider, and the registration belongs to whoever ships the app: it can't be done by this kit.
Until it is, Gmail still works with an app password, and Outlook.com, Hotmail and Live can't be added at all.

1. **Google**: Google Cloud console → new project → enable the Gmail API → OAuth consent screen (External) with the
   scope `https://mail.google.com/` → Credentials → OAuth client ID, type "Desktop app". That scope is a "restricted"
   one: while the app is in testing only the test users you list can sign in (and Google expires their sign-in
   after seven days); opening it to everyone needs Google's verification and a security assessment.
2. **Microsoft**: Entra admin centre → App registrations → New, for "accounts in any organizational directory and
   personal Microsoft accounts" → Authentication → add "Mobile and desktop applications" with the redirect
   `http://localhost` → API permissions (delegated): `IMAP.AccessAsUser.All`, `SMTP.Send`, `offline_access`. No secret.
3. Put the ids in `/etc/huginn/mail-oauth.json` (everyone on the computer) or `~/.config/huginn/mail-oauth.json`:
   `{"google": {"client_id": "…", "client_secret": "…"}, "microsoft": {"client_id": "…"}}`. Google issues desktop
   apps a "secret" that it doesn't treat as secret; to ship the ids in the image, add the file under
   `config/includes.chroot/etc/huginn/`.

Mail then shows "Sign in with Google / Microsoft", opens the page in the browser, and waits on `127.0.0.1` for the
one-time code. Known wrinkle: some newly made personal Outlook.com mailboxes refuse sending over SMTP even with a
valid token; Mail keeps such an account for reading and says that sending was refused.

Tested against stand-ins on localhost (a token-only IMAP/SMTP server and a small sign-in service): the whole flow,
a refused sign-in, a forged answer, renewal, rotated tokens, a withdrawn sign-in and signing in again. Not tested
against Google or Microsoft themselves, which needs the registrations above.

## Tested in a VM (2026-11-11)

Run on a Windows host in VirtualBox 7.2, inside a Kubuntu 26.04.1 live session and then from the built ISO.

- `scripts/build.sh` builds a 2.1 GB ISO end to end (about 5 minutes on 6 cores, lz4).
- The ISO boots (BIOS) straight into the Huginn session; the shell, dock and Welcome tour appear.
- All 20 apps start on Qt 6.10.2 / KWin Wayland.

Known gaps: `snapshot.ubuntu.com` was unreachable from the test VM, so that ISO came from the live archive
(set `SNAPSHOT=""` to do the same); UEFI boot, installing to disk, Flatpak installs and media playback are untested.

## Tested in a VM (2026-11-15): the whole path, and every app

QEMU without KVM (2 CPUs, software drawing), from the ISO this kit builds, with an empty 32 GB disk:

- **Boot**: GRUB, then Plymouth's Huginn screen; the installation drive signs in to the Huginn session by itself and
  the installer opens over the desktop.
- **Installing** through the installer's own windows: language, keyboard, network, disk (erase), you, time zone,
  summary, Erase and Install; it copied, set up and finished with "Huginn OS is ready".
- **The installed system**: Huginn's sign-in screen (now on Wayland), signing in, the arrival, the desktop, the lock
  screen after idle and with Super+L in both sessions (wrong password, then the right one), Open and Save windows
  through the portal, and the preview session (cage + Huginn's compositor) with apps in it.
- **Every app** started on the image's own Python 3.14 and Qt 6.10 (inside the build chroot) and checked for QML and
  Python errors; idle CPU measured at 0–0.1%.

Fixed along the way:

- The browser's install step replaced `/usr/share/huginn`, deleting the live wallpapers and the lock screen with it:
  they now live in `/usr/share/huginn-os/`.
- The installation drive signed in to Plasma's session (casper picks it): `huginn-live-session.service` points it at
  Huginn's.
- The sign-in screen needed an X server that isn't installed: SDDM now runs its greeter on Wayland (KWin).
- Everything asking for the font "Inter" got Noto Sans (the image has "Inter Variable"): a fontconfig alias.
- KDE's screen locker (Plasma 6.6) takes its lock screen from a Plasma *shell* package, not the look-and-feel one,
  so Huginn's lock showed KDE's emergency fallback: it's now `/usr/share/plasma/shells/org.huginn.desktop`. It also
  quits straight after a right password, and recovers if a password arrives while an old question is pending.
- The preview session's cage aborted when the compositor asked for full screen before its first frame; it no longer
  asks (cage fills the screen anyway), and windows bigger than a small screen are asked to fit.
- The file chooser answers the portal at once (and opens its window once the compositor is listening): a slow start
  made the portal give up on it for the whole session.
- The live wallpaper settles on its still when drawing is slow (software drawing, most VMs), which kept the arrival,
  the sign-in and lock screens from responding.
- The desktop's cards showed made-up weather, trackers and events: they now read Weather, Privacy Report, Calendar
  and Reminders, with an empty state that says how to fill each.
- The preview session sorted first at the sign-in screen and became the default: renamed so "Huginn" stays first.
- Smaller: the installer looked for Wi‑Fi on its window's thread (it froze for up to 25 s) and said "Looking for
  Wi‑Fi networks…" for ever on computers without Wi‑Fi; "Use the free space" was offered on an empty disk; Tempo
  needed SciPy; Shortcuts had a QML warning; unused imports across the apps; Scan's "Look Again" wasn't a button;
  "Welcome back" greeted someone signing in for the first time.

## Tested (2026-11-15, second round): the real top bar, the portal, the compositor's extras, other apps' look

Every suite again on the new pieces, plus the ISO in QEMU (no KVM, software drawing):

- **The KWin session** (KWin on a virtual screen in the image, and the ISO): KWin's script tells the top bar which app
  is in front; Minimise from its menu and the dock bringing the window back; a restarted shell asks KWin itself. In
  the VM the top bar named the installer, Screenshot and Terminal as they came forward, and the control centre showed
  the wired connection, night light, sound and an empty notification list.
- **The portal** through the real xdg-desktop-portal (1.18 in a container, 1.21 in the image): settings (dark, accent,
  GTK theme, a change reaching apps at once), "Allow … to Take Screenshots?" then quiet screenshots, a dragged part,
  Escape, the colour picker with its magnifier, Access with choices, Open With with UpdateChoices and the app giving up
  (26 checks); Open and Save still pass (22). In the VM: the "Allow" card for the Screenshot app, a screenshot taken
  through KWin, nothing left in Pictures, and screen sharing offered (it wasn't before).
- **The compositor** (32 checks, and 13 more): two screens (bar and dock on the main one, Maximise on the second
  screen fills it and stays there), an X11 app with its island, frosted glass, the launcher's Enter and Escape.
- **Other apps' look**: a plain Qt app came up in Huginn's Kvantum style, the realm's colours and Inter with nothing
  set by hand; GTK 3 apps in Breeze with Huginn's colours (screenshots in two realms).
- **Headless**: `scripts/ci-smoke.py` opens all 54 apps and the shell with no screen: 54 of 54 fine.

Fixed along the way:

- **Screen sharing was missing in Huginn's session**: KDE's portal backend only offers it (and screenshots, global
  shortcuts) when `XDG_CURRENT_DESKTOP` is exactly `KDE`, and KWin only lets it in when KWin knows the installed apps
  (`XDG_MENU_PREFIX=plasma-`). Both are set now.
- **The home folders weren't made** in Huginn's session (other desktops run `xdg-user-dirs-update` from their autostart
  folder, which this session doesn't): no Pictures, Documents or Downloads on a first sign-in. The session makes them.
- **Five programs turned GLib's loop by hand** from a Qt timer although Ubuntu's Qt already runs it: Qt's events ran
  inside Qt's events, a window could be drawn in the middle of drawing another, and in the VM the desktop sometimes
  stayed at the arrival's first picture. Removed; the shell also has a safety net that ends the arrival after a few
  seconds and maps again any surface Qt has stopped drawing.
- **The apps and the shell are compiled at build time**: users can't write next to them, so every start compiled
  them again (seconds per sign-in on a slow computer).
- **The launcher** didn't close after opening an app, and Enter did nothing: Enter now opens the first app found, a
  click or Enter closes it, and so does Escape.
- The look for other apps is put in place a few seconds after sign-in (it makes KWin and KDE's apps reload), and the
  build leaves no stray folders under `/home`.
- Still slow in a VM without a graphics card: KWin draws with the CPU, so signing in takes a minute or two there and
  animations stutter. A real computer with a GPU doesn't have that.

## Tested on a real PC (2026-11-15): what changed

Booted from USB on a desktop (AMD Radeon RX 9070 XT, Ethernet and Wi‑Fi, two and three monitors). What it found,
and what changed:

- **The start menu, rebuilt** (Super). Islands over the dock: a greeting and the app search on top; in the middle the
  groups, Recent and every app, scrolling, lit in the colour of the app under the pointer; below, you and Lock, Sleep,
  Restart, Shut Down, Sign Out (the last three ask once more). It grows out of the dock's orb as the realm's light
  sweeps up through the glass and each app appears as it passes; closing pulls it back into the orb (Reduce Motion: a
  fade). Tab hands what you typed to Search everything.
- **Search everything** (Super+Space, or the magnifier in the top bar): a bar in the middle of the screen and results
  as islands: the top hit big (a picture shows itself), then apps, files, Settings pages and Huginn's open tabs in a
  fixed order, and the web always last. Before you type: pick up where you left off (recent files, paused music),
  suggested apps and quick actions. Sums, units and temperatures are worked out on the computer. Nothing typed
  leaves it unless you choose "Search the web".
- **Each app's own island** (right-click, a long press, or the Menu key / Shift+F10), the same in the start menu, the
  dock and Search: its recent files (the desktop's shared recent list, which Huginn's apps now write to), its own
  actions (New Window, New Private Window…), Keep in the dock (now remembered) and Uninstall for App Store apps.
- **Installing beside Windows.** The installer offered only "erase" or existing free space; now it can shrink
  Windows' partition (ntfsresize, after asking it first whether it can: Fast Startup, a pending disk check and
  BitLocker are explained in words), with a slider for how much room Huginn OS gets. A USB drive the live session had
  opened is closed first instead of refused, and an install on a USB drive puts its boot files only on that drive,
  leaving the computer's boot list and Windows alone.
- **Screenshots.** KWin hands pictures of the screen only to programs it knows by their executable, and Huginn's apps
  are Python; a small native helper (native/huginn-grab.c, built into /usr/libexec/huginn) is the one it knows now.
  The Screenshot app falls back to it and says why if a picture still fails (~/.cache/huginn/screenshot.log). Print
  saves the whole screen to Pictures › Screenshots at once; Shift+Print and Super+Shift+S open Screenshot.
- **The third monitor was black**: the wallpaper was drawn on one screen only. Every screen has its own now (and a
  screen plugged in later gets one).
- **Animations.** KWin's window effects are on explicitly (open/close, minimise, popups); the start menu, Search, the
  control centre and app islands move instead of popping.
- **The App Store queues** a second install (or removal) instead of refusing it, and store apps wear Huginn's look:
  a system-wide Flatpak override lets them read the GTK, Kvantum and KDE colour settings, Huginn's Kvantum theme is
  copied where they can see it, and the matching style extensions come along with an app.
- **Every window has rounded corners**, other apps' too: KDE-Rounded-Corners (a KWin effect, GPL-3.0) is built into
  the image against its KWin, at Huginn's window radius.
- **The control centre** shows the Wi‑Fi network you're on even while Ethernet carries the internet.
- **Huginn's welcome tour** counts as shown only once it has been on screen, so a first start that ends early (Huginn
  restarting itself to finish setting up) no longer skips it.

## The live island (2026-11-15)

Worked out with mockups (bubbles for more than one thing, it opens when you point at it, screen sharing treated like the
camera and microphone, and the two-players rule), then built:

- **What it hears about** (`shell/huginn_island.py`): anything with the standard media controls (MPRIS: Huginn's
  Music, Podcasts and Media Player now publish them; the Huginn browser and Spotify-like apps already do), apps that
  report over `org.huginn.Live` on the session bus (`apps/huginn_live.py`: Clock's timer, App Store installs,
  Screenshot's recording), the Privacy Report's watcher (screen, camera, microphone), files arriving in Downloads,
  Calendar events starting within 10 minutes, and calls through KDE Connect.
- **The rules**: one island for the most important thing (a call, a timer or alarm going off, something playing, a
  timer counting down, an event, downloads and installs); up to two more as round bubbles beside it, a "+N" when
  there's more; clicking a bubble or scrolling swaps it in. The screen, camera and microphone aren't in that order:
  each says so in the island for 4 seconds, then stays as a bubble (and a dot in the top bar) for as long as it's on,
  never bumped and not counted. Two things playing: the one whose window isn't in front wins, else the newest.
- **The island itself** (`LiveIsland.qml`): grows out of the dock's end and resizes as what it shows changes (the old
  content fades as the new one comes in); bubbles pop in and out and slide. Point at it for 0.3 s and it opens
  (`LivePanel.qml`): a full player with the cover, a scrubber you can drag and the transport; a timer's ring with
  +1 min / Pause / Cancel; a call with its replies; an event with Join; installs with their progress; who is using the
  screen, camera or microphone; and below, everything else going on. Calls and alarms open it by themselves. The
  play/pause key works on whatever it shows (the session daemon asks the island first). All of it follows Reduce
  Motion.
- **Calls through KDE Connect**: the computer can't answer or decline a phone call, so the island offers Silence,
  quick text replies and Phone. Apps that can answer (a calling app reporting `kind: "call"` with Answer/Decline) get
  those buttons.
- Tested: the rules on their own; a real session bus with two player processes and a reporting app (what wins, the
  buttons reaching the apps, two players and the window in front, the media key, the screen shared and stopped,
  apps quitting); Clock's timer driven from the island (start, pause, +1 min, resume, cancel); KWin nested on X11
  with a player and a ringing call (the island opens by itself); both compositor suites; every app in the smoke test.

## Huginn's own compositor, round 1 (2026-11-15)

KWin was holding the design back (glass, islands, the dock's animations, phone pairing), so Huginn gets a compositor of
its own: `compositor/`, in Rust, built on [Smithay](https://github.com/Smithay/smithay) (pinned to a commit of its main
branch; it started as a copy of Smithay's example compositor, Anvil, MIT: `LICENSE-Smithay.txt`). It's done in rounds:
1. **The core** (this round): drawing on the GPU, inputs, windows, X11 apps, locking, and everything the shell and
   the session daemon already asked of a compositor.
2. **Huginn's look**: glass and blur, rounded corners, islands, the dock's Ring and streak, snapping (done:
   see "The desktop, round 2" and "Huginn's compositor, round 2").
3. **What KWin did besides**: screen sharing and screenshots for apps, screen and input settings, night light,
   accessibility.
4. **The default**: it becomes the "Huginn" session and KWin goes.

What round 1 does:
- **Drawing**: on the GPU through DRM/KMS (with a nested window for development: `huginn-compositor --winit`).
  A game or video filling the screen goes straight to it (direct scanout), and FreeSync/adaptive sync turns on for it
  on screens that have it. X11 apps through XWayland, built in.
- **The session** (`/usr/bin/huginn-session-preview`): `huginn-compositor -- /usr/libexec/huginn-session-apps`: it
  starts the session services and the shell once it's listening (with `WAYLAND_DISPLAY` and `DISPLAY` set), and ends
  when the shell does. The keyboard layout is the system's (`/etc/default/keyboard`).
- **Windows**: a new window opens centred in the space the bar and dock leave, a little offset from one already there,
  and gets the keyboard; when one closes, the one under it does. Super+drag moves a window; Super+Up / Super+Down
  fill the screen / hide; Alt+F4 closes; Alt+Tab and Alt+Shift+Tab go through them.
- **The shell**: it hears which window is in front (`org.huginn.Shell.Active`), Super on its own (the launcher),
  Super+Space (search) and Print / Shift+Print / Super+Shift+S (the picture itself comes in round 3); the dock brings a running app forward and the top
  bar's app menu minimises and closes through the compositor (`org.huginn.Compositor`: `ActivateApp`,
  `WindowAction`, `Windows`), with KWin's scripts still used in the KWin session. The hardware keys (volume,
  brightness, media, power) go to the session daemon.
- **Locking** (`shell/huginn_locker.py`, `shell/qml/Locker.qml`): Super+L, the session daemon's timers, logind
  (`loginctl lock-session`, the lid) and going to sleep lock. The compositor starts the lock screen with a connection
  made only for it; while locked it draws nothing else and sends the keyboard and mouse nowhere else. The lock screen
  is the same `Lock.qml` as the KWin session's, the password checked through PAM; it unlocks by exiting with success,
  and if it crashes it's started again, so a broken lock screen never unlocks. `loginctl unlock-sessions` (from a text
  console) unlocks too.
- **Idle and the screen**: `IdleTime`, `Lock`, `Blank` and `Locked` as the session daemon already used them; a video
  that asks the screen to stay on (idle-inhibit) does; the screen-off timer switches the screens off (DPMS) and any
  key or movement brings them back.
- **Not yet** (rounds 2 and 3): the glass and corners, title bars for other apps (X11 apps get a plain bar for now),
  a visible Alt+Tab switcher, snapping, screenshots and screen sharing for apps, and per-screen settings.
- **Computers without a GPU driver** (a virtual machine without 3D, "safe graphics", a card Mesa doesn't know): it
  draws in software instead of refusing to start, as KWin does.
- **The installation drive's session**: its account has no password, so nothing locks it by itself any more (in
  either session), and the lock screen there takes an empty password.
- Tested nested on X11 (`--winit`, the software renderer) with the shell and apps: the bar, dock, widgets and
  launcher; launching from the launcher; the dock bringing an app forward; minimise and close from D-Bus and the keys;
  Alt+Tab; focus after closing; an X11 app; locking, a wrong password, the right one (a test password set in a
  throwaway copy of the image), and the lock screen being killed and coming back.
- Tested on DRM in a VM (QEMU without KVM or 3D, from the built ISO, started from a text console): the screen, the
  keyboard and mouse, the shell and the installer, Super and the launcher, locking with Super+L and unlocking with
  `loginctl unlock-sessions`, switching consoles and back. Found and fixed there: no GPU driver made it stop, and it
  kept trying to draw while on another console. Seen then in that VM (where the shell took minutes to start): the
  bar, dock and widgets stayed hidden until the mouse moved or a key was pressed. Checked again with the 2026-11-16
  ISO, touching nothing: they come by themselves in both sessions, just slowly under emulation (about five minutes).

## The desktop, round 2 (2026-11-15): the dock, Today, menus, the Overview, the tour

Everything chosen on the design canvas (the dock, Downloads, Today, app menus, the Overview, notifications, motion,
Settings and the welcome tour) is built, and Huginn's compositor got its second round (snapping, spaces, the
Overview, windows folding into the dock). The KWin session does what KWin allows (its scripts in
`config/overlay/usr/share/kwin-wayland/scripts/huginnactive`); the preview session does all of it.

- **The dock** (`shell/qml/Dock.qml`, `AppWindows.qml`): a bar under an app for each window (up to three), the Ring
  (a light in the app's colour round its tile while it starts), clicking the app in front hides it (a ring spreads
  round its tile) and again brings it back, an app's windows as an island (pointing or clicking), middle-click for a
  new window, scrolling through them, files dropped on an app. Size, hiding style and the rest: Settings.
- **Stacks** (`shell/huginn_stacks.py`, `StackIsland.qml`, `FileArt.qml`): Downloads as a pile at the end of the apps
  (a badge while something's arriving, a file flying in when it lands), opening as a list or grid; open, show in
  Files, copy, rename, move to the Bin, drag out. Any folder dropped on the end of the dock becomes a stack
  (`~/.config/huginn-shell/stacks.json`).
- **Today** (`shell/huginn_today.py`, `TodayIslands.qml`): the date in the bar or Super+T: the month, weather, what's
  coming and clocks as islands. Typing adds an event or reminder, read from plain words (`parse()`, with a preview);
  `~/.config/huginn-shell/today.json` keeps which islands and clocks.
- **App menus** (`apps/huginn_menu.py`, `AppMenuIsland.qml`): each Huginn app tells the shell its menus over D-Bus
  (`org.huginn.App.p<pid>`: `Menus`, `Trigger`), and the bar shows them as the One menu: search, About and Settings
  at the top, the groups opening to the side, Open Recent cascading. Only what the app can actually do is listed.
  Other apps get a basic menu (hide, close, quit). "A row of menus" puts the groups along the bar instead. Alt on its
  own opens it (KWin: a modifier-only shortcut in `kwinrc`; the compositor: Alt pressed and let go alone).
- **The Overview and spaces** (`compositor/src/wm.rs`, `OverviewOverlay.qml`): Super+Tab or three fingers up:
  the compositor glides the windows apart into a grid (and dims the rest), the shell draws the names and the spaces
  strip over them. Spaces: add, rename, remove, reorder, drag a window onto one; Super+Ctrl+←/→, Super+1–9,
  Super+Shift+←/→ (taking the window), three fingers left/right; the space's name shows for a moment.
- **Snapping** (`wm.rs`, `SnapGlass.qml`, the fill button in `apps/qml/GlassWindow.qml`): drag to an edge or corner
  (lit glass shows where it'll go), Super+arrows through halves, thirds and two-thirds, Snap Assist offering the other
  windows for the other half, the fill button's layouts island. Snapped pairs come forward together.
- **Hiding into the dock**: the window folds into its app's tile with light (drop and ring, line, or comet; the
  shell tells the compositor where the tiles are, `DockLayout`), and comes back out as a line.
- **Alt+Tab**: the compositor reports the order and the pick (`Switcher`), the shell draws the island.
- **Notifications** (`apps/huginn_sessiond.py`, `SessionUi.qml`): bloom from the top right with the app's colour once
  round the edge, piles per app (three at most on screen), inline replies (`inline-reply`), a ghost when one leaves;
  they wait while something fills the screen or it's being shared, except calls and alarms.
- **Motion in apps** (`apps/qml/GrowFrom.qml`, `MotionList.qml`, `Wash.qml`, `Shimmer.qml`, `Pressable.qml`,
  `Toggle.qml`): opening something grows out of what you clicked (or slides in, if picked in Settings); Photos uses it
  first. Reduce Motion turns them into short fades.
- **Settings › Desktop & Dock** (`apps/qml/SetDesktop.qml`, `apps/huginn_deskprefs.py`; was "Top Bar & Dock"): one
  page with a live preview that plays the choice you point at: dock size, hiding style, clicking hides, stacks, the
  top bar, Today's islands and clocks, snapping, the Overview's opening (glide, or glide with light), the hot corner,
  spaces on every screen, and how things open in apps. The shell follows changes as they're made.
- **The welcome tour** (`shell/huginn_tour.py`, `TourHost.qml`; the Welcome app now only asks the shell to play it):
  two full-screen pages (hello; light or dark and the realm), then an island walks the real desktop, led by a line of
  light: the dock, the date and Today, the app's One menu, snapping, the Overview, each with a "Try it" that moves on
  by itself when done. Once per account at first sign-in; again from Welcome or Help. After an update that brings
  something new (`/usr/share/huginn-os/version`), a short "What's new" tour shows just that.
- Tested nested (`--winit`) with the shell, Files, Writer, Photos and the session daemon: the dock (hiding, the
  windows island, the Ring, size), Downloads, Today (typing to add), the One menu (from Writer's bus, search, Alt
  alone), the tour (pages, realm changing live, the line of light, Try it moving on), the Overview, spaces, hiding
  into the dock, Super+arrows, Super+drag with the lit preview, Snap Assist (and it going away with Alt+Tab), the fill
  button's layouts, Alt+Tab, notifications piling, Photos growing a picture out of its tile, and the Settings page.
  Not testable here: the KWin paths (no KWin in the test root). Still open: dragging the line between two snapped
  windows to size both, live thumbnails in the windows island, and pausing a download from the stack.

## Huginn's compositor, round 2: the look (2026-11-15)

The second half of round 2 (the first half, snapping, spaces and the Overview, is in "The desktop, round 2"):
Huginn's compositor now draws the look itself (`compositor/src/look.rs`). Everything is GLES shaders, compiled
once per GPU; if a GPU can't compile them, windows are drawn plain as before.

- **Shadows**: a soft shadow under every window (the Gaussian of a rounded box, worked out in the shader, nothing
  drawn under the window itself), deeper under the window in front. None for maximised or full-screen windows.
- **Rounded corners**: every window is cut to a 14-pixel rounded outline (the same as Huginn's own windows draw),
  while its own texture is drawn. The outline is worked out where the window is actually drawn, so it holds while
  windows move and scale in the Overview or fold into the dock. Rounded windows can't go straight to the screen, so
  a full-screen game or video (not rounded) still does.
- **Frosted glass**: the shell's glass surfaces (the bar, the dock, Today, menus, the launcher, Search, the control
  centre, notifications, the switcher…, by their layer names) are drawn over a blur of what's behind them. Just
  before one is drawn, what's already on screen under it is copied at half size, blurred (dual Kawase, down to a
  sixteenth and back) and shows through the glass's translucent parts only, so shadows and soft edges stay clear.
  It's only redone when what's behind changes. Reduce Transparency and High Contrast turn it off (the shell says so
  with the dock's layout).
- **Title islands for other apps**: apps that don't draw their own title bar (X11 apps, and Wayland apps asking for
  one) get Huginn's: an island across the top with the three lights at the left (close, minimise, fill; grey
  when the window isn't in front, a mark on the one under the pointer) and the window's title in Inter, cut with an
  ellipsis. Drag it to move the window. X11 windows are now told where they really are after a move, so their
  menus open in the right place.
- Every layer, window and the dim are now drawn by Huginn's own scene code instead of Smithay's, so the frost can
  wrap the shell's surfaces.
- Tested nested (`--winit`, llvmpipe): shadows, corners (also while moving and in the Overview), the frost (Today
  over a document, against the same with the frost off), an X11 app's title island, its lights, moving it. And on
  DRM in a VM (QEMU without KVM, from the built ISO): the preview session draws the desktop with rounded windows and
  the shell's glass, and the bar and dock come up on their own (the KWin session too).

Also fixed: the start screens of Writer, Sheets, Slides, Notes, Documents and Archives sat right of centre (centred
beside the side island, which is short when there's nothing in it). They're centred in the window now, and only move
over when the side island would reach them (`GlassWindow.middleX`).

## Huginn's compositor, round 3: the computer's own settings (2026-11-15)

- **Pictures of the screen.** Print, Shift+Print, the Screenshot app and apps asking through the portal now work on
  Huginn's own compositor, not just under KWin: it answers `org.huginn.Compositor.Capture` with a picture of each
  screen and where it sits, and `huginn_capture.py` puts them together (`compositor/src/capture.rs`).
- **Screen sharing and recording for apps** (video calls, OBS, the browser): the compositor speaks
  ext-image-copy-capture, and xdg-desktop-portal-wlr turns that into a PipeWire stream. The own-compositor session
  says `XDG_CURRENT_DESKTOP=Huginn-Own:Huginn:KDE`, so the portal reads `huginn-own-portals.conf`, which sends
  screen sharing there. With more than one screen, Huginn asks which one to share (`apps/huginn_pick_screen.py`, the portal's chooser).
- **Settings › Displays on Huginn's own compositor**: resolution, refresh rate, size of things (scale), rotation and
  where each screen sits. The compositor lists its screens on the bus in kscreen-doctor's JSON and takes the same
  changes (`displays.rs`), so Settings speaks to it as it does to KWin. Each screen's settings are kept in
  `~/.config/huginn/displays.json` by make, model and serial number, and come back when it's plugged in again.
  Turning a screen off keeps it dark and out of the desktop until it's turned on again (or plugged in again); the
  main screen, where the top bar and dock go, is kept in the same file for the shell.
- **Settings › Keyboard & Mouse** there too: keyboard layouts and options and key repeat come from the files KWin
  reads (kxkbrc, kcminputrc), read again when Settings changes them; mice and touchpads (tap to click, natural
  scrolling, left-handed, speed, ignore while typing) are listed and changed over the bus and kept by device name in
  `~/.config/huginn/input.json` (`input.rs`).
- **Accessibility** there too (`access.rs`, from the settings KWin and KAccess read): colour filters for colour
  blindness through each screen's colour matrix (where the graphics card has one), inverted colours through its
  gamma, sticky, bounce and slow keys, mouse keys (the number pad moves the pointer, 5 clicks), zoom (Super+= and
  Super+-, Super+0 for the whole screen again; what's under the pointer stays put), the on-screen keyboard
  (Squeekboard), and Reduce Motion (no sliding windows or Overview, no fading in).
- **Night light** there too: the session daemon reads Settings' night light (kwinrc's [NightColor], as KWin does)
  and sets every screen's gamma through the compositor, easing in and out over half an hour.
- New windows fade in (160 ms), and windows closed from Huginn (the close light, Alt+F4, the dock) fade out and
  shrink a little once they're gone (a picture taken as they're asked to close); not with Reduce Motion.
- The line between two windows snapped side by side can be dragged: both windows follow it (each keeps at least a
  fifth of the screen).
- The dock's window cards show each window live (a small picture every second and a half while they're open,
  `WindowPicture` on the bus).
- Icons: the pictures inside the smoked glass are solid now, as macOS and iOS draw theirs (the app's colour with
  white details, a soft shadow, no glow; `STYLE` in make-icons.py). Huginn OS's and the browser's ravens are in the
  same glass, and Calendar's tile shows today's date.

## Huginn's compositor, rounds 4 and 5: staying up, and day-to-day polish (2026-11-16)

- **The shell comes back by itself** if it stops (a crash): `huginn-session-apps` starts it again, up to five times
  a minute, and the windows stay where they are.
- **Apps reopen when you sign in** (Settings › Desktop & Dock): the session daemon notes the open apps every minute
  and opens them again next time.
- **Windows open where they were**: each app's window comes back at its size and place (`places.rs`,
  `~/.config/huginn/places.json`), and **window rules** for particular apps can be written by hand in
  `~/.config/huginn/window-rules.json` (open on a space, filled, at a size or place).
- **Sharing one window** in calls and recordings: the compositor lists its windows for other programs
  (ext-foreign-toplevel-list) and draws one window alone for them (ext-image-copy-capture), so the portal's
  chooser offers windows as well as screens.
- **Touchpad**: three or four fingers up for the Overview, down to leave it, sideways between spaces; pinch in
  with three or more for the start menu, spread for the Overview.
- **Adaptive sync** (FreeSync, G-Sync compatible) can be turned off in Settings › Desktop & Dock; it's on while a
  game or video fills the screen. Screens are driven at 10 bits per colour where they can be.
- **Sharp older apps** (Settings › Displays): XWayland runs at the largest screen scale and X11 apps are told to
  draw bigger (Xft.dpi, through xrdb) instead of being stretched; apps that ignore Xft.dpi look small, so it can be
  turned off.
- **Screen sharing that doesn't drop**: xdg-desktop-portal-wlr 0.9.0 is built from `third_party/` (MIT) in place of
  Ubuntu's 0.8.1, whose frames could outlive their buffers when a viewer restarted the stream.
- **Tearing for games** (Settings › Desktop & Dock, "Let games tear"): a game that asks for it (wp-tearing-control,
  as with V-Sync off) gets page flips that don't wait for the refresh while it fills the screen. Smithay is vendored
  in `third_party/smithay` with that one patch (`AtomicDrmSurface::set_tearing`: an async atomic flip first, a
  normal one when the driver refuses).
- **HDR** (Settings › Displays, on screens whose connection offers it): the connection is set to BT.2020 and PQ
  with HDR metadata and 10 bits a colour, and everything drawn (sRGB, as every app draws) is turned into the HDR
  signal by a last pass (`look.rs`: HdrElement), with SDR white at a brightness of your choosing. Apps can't send
  HDR pictures of their own yet (that needs the colour-management protocol); `HUGINN_DEBUG_HDR=1` shows the pass in
  a window.

### HDR from apps, and KWin's gone

- **Apps' own HDR** (`color.rs`, wp-color-management-v1): games and video players can ask what each screen wants
  (BT.2020 and PQ with its SDR white while HDR is on, else sRGB), be told when that changes, and mark a surface as
  HDR. Parametric descriptions with named primaries (sRGB, BT.2020) and transfer functions (sRGB, gamma 2.2, PQ) and
  luminances; ICC profiles and scRGB are refused. On an HDR screen such a surface goes out as it is: the HDR pass
  skips it, except where something is over it (another window, the bar or dock, notifications, the pointer).
  Checked with a small client (`wayland-scanner` + libwayland): the descriptions and their information, the change
  events when HDR or SDR brightness changes, and a PQ window's pixels unchanged while the rest is converted.
  (wayland-backend fills in a new object's data after the request that made it, so the information object, which
  its own `done` ends, is answered from an idle callback: answering at once was a use-after-free.)
  On a screen not in HDR, an app's HDR (or BT.2020) picture is shown in sRGB instead of washed out (`look.rs`:
  the HDR element's other pass): PQ decoded, brightness above a knee rolled off so the picture's brightest (its
  content light level, else the mastering display's, else what its luminances say) just reaches white, colours
  brought into sRGB's. It's drawn under the pointer and under zoom, and goes into screen pictures. Checked: a PQ
  grey of 128 comes out at 181 as worked out by hand, and switching HDR on and off while it's open swaps between
  that and passing it through. Subsurfaces count (players often put the picture in one), and a window filling the
  screen is found where it's drawn.
- **KWin and Plasma's workspace are out of the image** (`config/not-wanted.list`): Huginn's compositor is the only
  session (`/usr/bin/huginn-session`, "Huginn OS" at sign-in) and draws the sign-in screen too (SDDM's
  `CompositorCommand`). Screen sharing goes through xdg-desktop-portal-wlr, everything else through KDE's portal.
  Gone with them: the KWin script, Plasma's lock-screen package, the rounded-corners effect and huginn-grab.
  What Plasma's workspace used to bring that's still used is listed now (plasma-integration, geoclue, hwdata), and
  every listed package is marked as installed on purpose, so `apt autoremove` keeps it.
- "Lock when waking" in Settings › Privacy & Security is honoured by the compositor (it was KDE's locker's).
- **Icons, polished**: every picture is brought to the same visual size and centred (`fit()` in make-icons.py:
  half how much it covers, half how far it reaches, at most a quarter bigger or smaller, never past 164 of 256),
  so a list or a bolt no longer looks small beside a wallet or a controller. The pictures that were only lines
  are solid objects with white details now, like the rest: Activity Monitor's screen, the Passwords key, the
  Screenshot frame, Podcasts and Backup as discs, Contacts as a card. Writer's page is solid (it was see-through,
  murky on the dark glass). Terminal and Reminders keep their own drawings (preferred as they were), only placed
  like the rest.
  Calendar keeps its exact drawing: the dock writes the date at fixed places on it.
- **Signing out** goes through the compositor (`org.huginn.Compositor.SignOut`): every window is asked to close, and
  once they've gone the compositor ends the session itself. Ending it through logind (as before) also ended SDDM's
  helper, which SDDM takes for a crash: no sign-in screen came back. A window still open after 20 seconds (an app
  asked whether to save, and was told Cancel) calls signing out off; signing out again within two minutes goes
  through even so.
- **The sign-in screen** on the compositor: with no session of anyone's it never locks, and the first key goes to the
  greeter (a layer that otherwise only takes keys once clicked). Checked in the VM: the greeter comes up on our
  compositor, takes the password, and signs in to the desktop.

## Huginn, the browser

Inside the Huginn repository (this kit is its `os/` folder) the image ships the repository's own browser. A kit used
on its own ships Huginn from `vendor/huginn` (the commit is in `vendor/huginn/SOURCE`); to move it to a newer Huginn:
`scripts/update-huginn.sh /path/to/Huginn`, then rebuild.

- Installed to `/usr/share/huginn`, started by `/usr/bin/huginn`, and set as the default browser.
- It uses the system's Python and Qt WebEngine (`config/package-lists/50-huginn-browser.list`), not a
  private copy fetched with pip, so engine security fixes come with system updates.
- The per-user installer (`Install Huginn (Linux).sh`) is left out of the image.
- Sandbox: Ubuntu blocks unprivileged user namespaces for programs without an AppArmor profile, and the
  browser engine needs them. `/etc/apparmor.d/huginn` grants that to `/usr/bin/huginn`, which is why the
  launcher is a Python script and not a shell wrapper. A live session loads no profiles, so
  `casper-bottom/98huginn_live_userns` lifts the block there (Ubuntu's own live images do the same).
- Huginn's own "make me the default browser" check only looks for a per-user install, so inside
  Huginn OS that setting is not shown; the system default already points at Huginn.
