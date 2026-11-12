Huginn - a Safari-style, privacy-first browser for Windows and Mac (and Linux)
==============================================================================
(Named after Huginn, the raven Odin sends out over the world each day. It was called
SafariQt at first; some files and folders still carry that name.)
Free for non-commercial use: PolyForm Noncommercial License 1.0.0 (LICENSE.md).

Install it (Windows): double-click "Install Huginn.bat" and press Install. That's all.
            It installs for you only (no admin rights), by default to
            %LOCALAPPDATA%\Programs\Huginn. Like Chrome and Firefox it always adds itself
            to the Start menu, puts a shortcut on the desktop (a switch) and an entry in
            Settings > Apps (Uninstall removes it cleanly). To keep it on the taskbar, right-
            click its icon there once it's open and choose Pin to taskbar (Windows only lets
            you do that, not apps). The other switch, "Build H.264 video support" (off), is
            explained under Video formats; when it's on, Huginn starts that build in the
            background the first time it opens. It takes a few minutes: it fetches a
            portable Python and the browser engine (about 250 MB) and shows its progress.
            Running it again updates or repairs the copy you installed.
Install it (Mac): double-click "Install Huginn (Mac).command". Huginn doesn't come from
            the App Store, so the first time macOS won't open it: click Done, then open
            System Settings > Privacy & Security, scroll down and click Open Anyway beside
            the installer's name (on macOS 14 or older, right-click the installer and choose
            Open instead). If Terminal asks to use your Downloads folder, allow it. It asks
            nothing else, takes a minute or two, and puts Huginn.app in Applications - so
            it's in Launchpad and Spotlight - and in the Dock, then opens it. Running it
            again updates the copy you have. To remove it, drag Huginn from Applications to
            the Bin (and out of the Dock). Prefer Terminal? bash ~/Downloads/Huginn/installer/
            install.sh does the same. If something goes wrong, ~/Library/Logs/Huginn has
            what the installer and Huginn said. (macOS 11 or later.)
            On a Mac Huginn has the usual menu bar (File, Edit, View, History, Bookmarks,
            Window, Help) and can be your default browser; every Ctrl shortcut here is
            Command (⌘) there and Alt is Option (⌥).
Install it (Linux): in a terminal, bash "Install Huginn (Linux).sh". It puts Huginn in
            your apps menu, and can add it to the desktop and (GNOME) pin it to the dock.
            To remove it: ~/.local/share/huginn/installer/install.sh --uninstall
            It asks a couple of questions in the terminal, takes a few minutes, and gets its
            own Python and engine; nothing is installed system-wide. If your desktop is
            missing a library Qt needs to open a window on X11 (usually libxcb-cursor0), it
            says so and offers the command that adds it (Wayland desktops don't need it).
            Read Aloud uses your desktop's voices (speech-dispatcher).
            For every user of the computer (a distribution's image, Huginn OS's for one), see
            "Huginn on Linux" below: sudo installer/install.sh --system, or a .deb package.
Or run it:  double-click run.bat in this folder (Windows; no installing, sets itself up)

The first time Huginn opens, a short welcome tour shows what makes it different and lets
you pick a theme (and whether its colours shift with the time of day), light or dark (or
light by day and dark at night), which side the window buttons go, the Start Page touches,
and import your bookmarks. Page menu > More Tools > Welcome Tour brings it back.

What's in this folder
  Install Huginn.bat  installs Huginn on Windows (installer\install.ps1 is the installer window)
  Install Huginn (Mac).command, Install Huginn (Linux).sh
                      install it on a Mac or Linux (installer/install.sh does the work)
  safari_browser.py   the browser (one file)
  readability.js      Reader's article finder (Mozilla Readability, Apache License 2.0)
  dictionaries\       the spell-check dictionary (en-US, from SCOWL / Kevin Atkinson; free licence)
  run.bat             starts the browser
  setup.bat           one-time setup: portable Python + PySide6 (+ cryptography for
                      Passwords), kept inside this folder
  python\             the portable Python and PySide6 (nothing was installed system-wide)
  test.bat            optional: runs a scripted visual test, screenshots go to test_out\
  bugcheck.bat        optional: edge-case stress test (stress_log.txt) + the visual test
  seccheck.bat        optional: privacy & security test (sec_test_log.txt) + screenshots
  adcheck.bat         optional: ad-blocking tests incl. a live YouTube check (runs minimized)
  build-engine.bat    optional: rebuilds the engine with H.264/AAC video (see Video formats)
  restore-engine.bat  puts the standard engine back
  engine\             the engine builder, its progress (status.txt) and logs

Installed with the installer? Remove it from Settings > Apps > Installed apps > Huginn
(it asks whether to keep your bookmarks, history, passwords and settings; kept by default).
Otherwise, to remove everything, delete this folder. Preferences live in the registry under
HKEY_CURRENT_USER\Software\SafariQt (its first name); bookmarks, history, site icons and the browser
profile (cookies, cache) live in %LOCALAPPDATA%\SafariQt.

Launching the browser while it's already open just opens a new tab in the running one.
Huginn reopens the tabs (and tab groups) you had open last time - also after a crash.
Only the tab you were on loads straight away; the others load when you click them.
(Page menu > Settings > Tabs > Reopen Tabs at Startup to switch it off.)

Ad blocking  (on by default; switch it in Privacy & Security, or per site in the page menu)
  Built into the browser itself, so Chrome's Manifest V3 limits on ad-blocking extensions
  don't apply: every rule of EasyList and EasyPrivacy is used (about 130,000), downloaded
  on first start and refreshed every 4 days (Update Now in the settings).
  YouTube: the ad data is removed from the player's responses before it can play, any ad
  that still slips through is fast-forwarded muted and skipped, and the "ad blockers are
  not allowed" pop-up is removed. Feed, banner and sidebar ads are hidden.
  "Block Ads on <site>" in the page menu turns it off for one site (the page reloads).
  YouTube changes its ad system often; the filter lists keep up by themselves, the
  YouTube part lives in safari_browser.py (YOUTUBE_SCRIPT) if it ever needs updating.

Video formats (H.264 / AAC)
  The standard engine plays YouTube (VP9, AV1, Opus) but not H.264/AAC, which many other
  sites use (Twitch, Reddit, X, Instagram, news-site players...). Huginn can rebuild its
  engine on this PC from Qt's open-source code with those formats switched on.
    - Start it from Privacy & Security > Video > Build..., or from the "This video needs
      H.264" bar that appears when a site's video can't play. (build-engine.bat does the
      same from a console window.)
    - Compiling takes a few hours at low priority, so games and other programs come first.
      Progress shows in Privacy & Security; Stop pauses it, Continue carries on where it
      left off. You can keep browsing meanwhile.
    - It installs Microsoft's free C++ Build Tools 2022 (Windows asks for permission once)
      and needs about 60 GB free while building; most of that is deleted at the end.
    - At the end Huginn asks you to restart: it closes, the new engine goes in, and it
      opens again with your tabs. The new engine is checked before it goes in and tested
      after; the standard one is kept in engine\standard-engine\ and restore-engine.bat
      puts it back (close the browser first).
  Updates: once a day Huginn checks whether Qt has published newer security fixes for the
  engine; Privacy & Security then shows Update... (it rebuilds in the background the same
  way). setup.bat leaves an H.264 engine alone.
  DRM services such as Netflix and Disney+ still won't play - use Edge or Chrome for those.

Huginn on Linux
  For every user   sudo installer/install.sh --system puts Huginn in /opt/huginn, huginn in
                   /usr/bin, its apps-menu entry and icons under /usr/share, and registers it
                   as a web browser (x-www-browser, gnome-www-browser). Add --default to make
                   it everyone's default browser (/etc/xdg/mimeapps.list). Remove it with
                   sudo /opt/huginn/installer/install.sh --system --uninstall.
  Packages         installer/build-deb.sh makes a .deb of the same (run it on the release it's
                   for). installer/build-deb.sh --system-engine makes a small one (under 1 MB,
                   every architecture) that runs on the distribution's own python3 and PySide6
                   (Ubuntu 25.04+ / Debian 13+, PySide6 6.10 or later): that engine plays H.264
                   and AAC video, and its security fixes arrive with the system's updates.
                   install.sh --system-engine does the same without a package. Set the
                   package's version with HUGINN_VERSION=2026.11.12.1.
  Video            Huginn's own engine plays YouTube (VP9, AV1, Opus) but not H.264/AAC, and
                   the H.264 build is Windows-only; installed with --system-engine, the
                   distribution's engine plays both.
  Page sandbox     Ubuntu 23.10 and later let a browser's page sandbox run only with an
                   AppArmor profile for it. The installer and the package add Huginn's
                   (/etc/apparmor.d/huginn), for the huginn command itself: a profile for
                   the engine's page process (Ubuntu's, or an older Huginn's) is not enough.
                   Without it, Huginn runs pages with the sandbox off and says so in
                   Privacy & Security (run the installer again to add it).
  Global menu      On a desktop with a menu bar along the top of the screen (KDE Plasma,
                   Unity, Huginn OS: anything offering com.canonical.AppMenu.Registrar) Huginn's
                   File, Edit, View, History, Bookmarks, Window and Help menus appear there,
                   with Linux keys (Alt+Left, F11, F12...). Elsewhere nothing changes.
  Sheets           Settings, Clear History, Valhalla and the like open inside the window over
                   a dimmed backdrop (Wayland doesn't let an app place a window of its own);
                   while one is open the window's keys and menus wait for it.
  From a terminal  huginn [link], huginn --new-tab, huginn --private-window [link] (the
                   last two are also the apps menu entry's right-click actions). A second
                   launch hands its links to the running Huginn.
  Desktop hooks    Huginn's open tabs are shared with the desktop over D-Bus
                   (org.huginn.Browser at /org/huginn/Browser: ListTabs, ActivateTab,
                   CloseTab, OpenUrl, Search, ListApps, OpenApp, and a TabsChanged signal),
                   so a launcher or dock can list, switch and search them. On by default on
                   Huginn OS, off elsewhere: Privacy & Security > Share tabs with the desktop.
                   Private windows and burner tabs are never shared.
  Media keys       A tab playing sound appears in the desktop's media controls (MPRIS:
                   title, artist, artwork, play/pause, next/previous, seek), as in GNOME's
                   and KDE's panels, and the keyboard's media keys work.
  Notifications    Web apps' notifications and Heimdall's go through the desktop's own
                   (notify-send, from libnotify-bin); clicking one opens the page.
  Fonts            Huginn uses Inter where it's installed (fonts-inter), else your desktop's.
  Default browser  Huginn reads which browser opens links from the desktop's mimeapps.list
                   files (yours first, then the system's), as every desktop keeps it.
  Not on Linux     Game Mode (Windows), sharing or publishing updates from a system install
                   (the package manager updates it).

Privacy & Security  (Ctrl+, or "Privacy & Security..." in the page menu)
  Private Browsing      Ctrl+Shift+N opens a private window (dark address field): no
                        history, and its cookies and website data vanish when it closes
  Tracking              known trackers and third-party cookies are blocked; tracking codes
                        (utm_, fbclid, gclid...) are removed from links; sites are told
                        not to sell your data (Global Privacy Control)
  Connections           sites are tried over HTTPS first; certificate problems show a
                        warning page; DNS lookups are encrypted (Quad9 by default - switch
                        to Off if you rely on company/intranet names)
  Permissions           sites must ask before using camera, microphone, location,
                        clipboard or fonts; notifications only from web apps you
                        installed and allowed
  Look-alike addresses  a fake domain like "apple.com" written in Cyrillic shows as xn--...
  Downloads             apps and scripts (.exe, .msi, .ps1...) ask first, and every download
                        is marked as coming from the internet so Windows SmartScreen checks it
  Dialogs               pop-up dialogs show which site sent them, and a page that keeps
                        showing them can be silenced
  Clear History         Ctrl+Shift+Delete: last hour / today / today and yesterday / all;
                        also removes those sites' cookies and website data
  Cookie pop-ups        "Reject all" is clicked for you on cookie consent banners (the
                        common consent platforms and any banner whose button plainly says
                        reject / decline / only necessary) - never Accept. Banners that
                        only say OK are hidden after a few seconds.
  Fingerprinting        sites that try to recognise your PC without cookies (by drawing an
                        invisible picture or sound and reading it back, or asking for your
                        graphics card and core count) get slightly different answers on
                        every site and in every session, and common values for the rest.
                        If a site's drawing tool misbehaves, switch it off here.
  Delete cookies when Huginn closes (off by default): you're signed out of sites when
                        you close Huginn, except those you pick "Keep Me Signed In to ..."
                        for in the page menu. (Done again before the next start, so a crash
                        or shutdown doesn't skip it.)

Passwords  (Ctrl+Shift+P, "Passwords..." in the page menu, or Privacy & Security)
  Saved logins are kept in one encrypted file, passwords.vault in %LOCALAPPDATA%\SafariQt\
  SafariQt: AES-256-GCM, with a key protected by your master password (scrypt). The master
  password is never stored. If you forget it the passwords can't be recovered - there's no reset.
    - Sign in somewhere and Huginn asks "Save Password?" (or "Update" when it changed).
    - Click a login field and your saved logins for that site appear under it - pick one
      with the mouse or the arrow keys + Enter. Nothing is filled in until you choose,
      only the page's own frame is filled (not ads or embedded frames), and a site's logins
      are only offered to that site (a secure site's never to an http:// copy of it).
    - Sign-up forms get "Use Strong Password" (like kH7qzT-m4Rdwx-9cBnLa); it is saved
      the moment you pick it.
    - The Passwords window flags passwords that are weak, used on more than one site,
      or (once you've checked) found in a data breach.
      Showing, copying or exporting a password asks for the master password again;
      copied passwords stay out of Windows clipboard history and clear after 30 seconds.
    - Import: More > Import Passwords..., or drop the file on the window. Reads the CSV
      export of Chrome, Edge, Firefox, Safari, Brave, Opera, Bitwarden, 1Password,
      LastPass, KeePass and Proton Pass. Afterwards it offers to delete the CSV, since
      that file holds your passwords unencrypted.
    - Export: an encrypted backup (.sqpw, protected by a password you choose - import it
      to restore) or a CSV for another password manager (not encrypted).
    - Locked after an hour unused and whenever Huginn closes. "Unlock with my Windows
      sign-in" (off by default) skips the master password on this PC; anyone signed in
      to your Windows account could then use them.
  Private windows can fill and save passwords too (only when you choose Save).
  iCloud Passwords: switch on "Use iCloud Passwords" in the Passwords window. It needs
  iCloud for Windows with Passwords turned on, and its "Install extension" for Chrome or
  Edge done once - Huginn talks to the same iCloud helper those extensions use. Your
  iCloud Keychain logins then show up under login fields on secure (https) sites. iCloud
  shows a 6-digit code the first time you use it after Huginn starts; type it in and it
  stays connected until Huginn closes. New passwords are saved in Huginn's own vault
  (saving into iCloud Keychain isn't supported). The pairing and lookup code follows the
  open-source "iCloud Passwords for Firefox" by au2001 (Apache License 2.0).

  Passkeys and security keys: sites that sign you in with a passkey or a USB/NFC security
  key (YubiKey and the like) work. Huginn shows a sheet that says what to do: touch your
  key, pick an account, enter or set the key's PIN (with how many tries are left). The
  key itself does the cryptography; nothing about it is stored by Huginn. On Linux the
  libu2f-udev package lets your account use the key (the .deb recommends it).
  Breach check: Passwords > More > Check for Breaches... asks Have I Been Pwned whether
  each password has turned up in a data breach. Only the first 5 characters of a hash of
  each password leave your computer (the service sends back every leaked hash starting
  with them, padded so the reply's size gives nothing away, and Huginn compares here).
  Passwords found are marked "In a breach" - change those first.

Web apps  (page menu > Install <site> as App...; Settings > Web Apps...)
  Any site can become an app: its own window with no address field or tabs, its own icon
  in the Start menu / Applications / your apps menu, and it remembers its size and place.
  It shares Huginn's sign-ins and protections; links to other sites open in Huginn.
  Installed apps may show notifications if you allow them when they first ask (no other
  site can). From a terminal: huginn --app=ID opens one, huginn --list-apps lists them as
  JSON and huginn --remove-app=ID removes one (Huginn OS's app store uses these).

Forget on Close  (page menu > the site card > Forget <site> When Its Tabs Close)
  For sites you don't want remembering you: when a site's last tab closes (or moves on
  to another site), its cookies, local storage, IndexedDB databases, caches and service
  workers are wiped (its own pages and frames, like login.<site> inside <site>). If
  Huginn closes or crashes first, they're wiped at the next start. Its files in the
  browser cache stay until you clear history (the cache can only be cleared as a whole;
  sites can't read each other's entries in it). On hosting sites such as github.io each
  name is its own site. The list is in Privacy & Security > Forget on close > Manage...

Heimdall  (page menu > Watch Page for Changes...; History > Heimdall)
  Heimdall keeps an eye on pages for you while Huginn is open - a price, a timetable, a
  "back in stock" notice - and tells you when they change (a notification, and the
  changes in his list: what's new in green, what went struck through). Select part of
  a page first to watch only that part. Choose every hour, every 6 hours or every day.
  He visits on his own from a fresh private profile each time, with Huginn's blocking and
  no cookies, so sites can't tell it's you (and pages that need you signed in can't be
  watched). "5 minutes ago"-style text and reordering don't count as changes. While a
  game is running (Game Mode) he waits.

Trails  (History > Trails...; page menu > How You Got Here...; Valhalla links to it)
  Every page you visit is a step under the page you came from - a link in the same tab,
  or the page a new tab was opened from - so Trails shows your browsing as trees, newest
  first, for each day of the past week. "How You Got Here" picks out the page you're on
  and the trail that led to it. Search shows matches with the trails that led to them.
  Back and Forward don't make new steps; typing an address starts a new trail. Private
  windows and burner tabs leave none, and Clear History clears them.

Translation  (the translate button in the address field; page menu > Translate)
  Pages in another language are translated on this computer, by Mozilla's translation
  engine (the one in Firefox) - nothing you read is sent anywhere. The first time you
  translate a language, Huginn downloads its files from Mozilla once (about 20-40 MB per
  language; the engine is 5 MB more), each checked against the hash Mozilla published.
  It translates what's on screen first, keeps links and buttons working, translates what
  the page adds later, and keeps translating as you follow links in that tab. "Show
  Original" puts the page back exactly as it was. Languages without a direct model go
  through English. In the translate menu: Translate From / To, Always Translate <language>,
  Never Offer for a language or a site; Translation Languages... lists what's downloaded
  and removes it. Code, form fields and anything marked "translate=no" are left alone.

Bifröst Sync  (page menu > Settings > Bifröst Sync...; More Tools)
  Keeps your Favorites, Reading List, passwords and open tabs the same on your own
  computers, with no account and no server. Your devices share one random key, given to a
  new device when you pair it, and everything is encrypted with it (AES-256-GCM).
    - Pair: on one device choose Add a Device..., on the other Join Another Device... Both
      show a 6-digit number; check they're the same and click They Match on both. Nothing is
      sent until both of you have. (It's what stops someone else on the network from
      slipping in, either way round.) Or copy the pairing key across, or scan its QR code
      with a phone and send yourself the text. Anyone with the key can join, so keep it to
      yourself. Add a Device asks for your master password first when passwords sync.
    - Passwords are sealed a second time, with a key kept inside your password vault (so
      only your master password unlocks it). It goes to a new device only when you pair
      it; the key your computer's keyring keeps can't read them on its own.
    - Devices meet directly on your local network (their announcements change every
      minute, so they can't be followed) and/or in a sync folder you choose - Syncthing,
      Nextcloud, Dropbox, a USB stick. Each device writes only its own file there, so the
      sync tool never sees a conflict, and nothing in the files is readable without the key.
    - When the same thing changed on two devices, the newest change wins; deletions sync
      too. Passwords sync while the vault is unlocked; changes wait until it is. Only web
      addresses (http and https) come in from other devices.
    - Tabs on Your Other Devices (History menu) opens what's open elsewhere.
    - The key is kept in Windows' protected storage, the macOS Keychain, or your Linux
      desktop's keyring (secret-tool). Without a keyring it's in a file only your account
      can read, and passwords don't sync unless you turn them on.
    - Leave... stops syncing this device; what's on it stays.
  Windows may ask once whether Huginn can use the network (for syncing on your network).

Mímir  (page menu > Summarize with Mímir; More Tools > Mímir; History > Ask Mímir...)
  An AI assistant that runs entirely on this computer: it summarizes the page you're on,
  answers questions about it, and answers questions about pages you've visited (from
  Muninn, with the pages it used as numbered sources). Nothing you ask leaves your computer.
  It's off until you download it: Quick (Qwen3 0.6B, about 0.65 GB) or Better answers
  (Qwen3 1.7B, about 1.8 GB) - open models (Apache 2.0) from Hugging Face plus Hugging
  Face's Transformers.js engine from npm, each file checked before it's used. It runs in
  a page of its own that can't reach the network, uses several processor cores, and
  closes after 5 minutes unused. Small models make mistakes: check what matters. Remove
  Mímir... deletes it.

Search engine  (page menu > Settings > Search Engine, or Privacy & Security > Search)
  Google (default), DuckDuckGo, Bing, Brave Search, Startpage, Ecosia, Qwant, Kagi, or a
  custom one: give the address of its results page with %s where the words go.

Page colour in the tab bar  (page menu > Settings > Theme > Tint With Page Colour; off by default)
  Like Safari's coloured tab bar (and the Firefox add-on Adaptive Tab Bar Colour): the
  window frame and tab bar take on the colour of the site you're looking at - its own
  theme colour, or else the colour at the top of the page - and follow it as you scroll
  or the page changes. Each tab keeps its colour; the change fades smoothly. Colours are
  lightened (or darkened in dark mode) just enough to keep the window's text readable.
  Also in that menu: "Use Websites' Theme Colours" (off = always use the page's actual
  colour) and "Tint on <site>" to switch it off for one site.

Typing sounds  (page menu > Settings > Typing Sounds; off by default)
  A key sound for every key you type - in the address field and in web pages - like
  Opera GX: each one is the key going down and, a moment later, coming back up, with
  their own sounds for Space, Enter and Backspace. Tactile and Clicky are tuned to match
  GX's packs of those names; also Thocky (deep and muted), Typewriter (with a bell on
  Enter) and Bubble, at three volumes. All are levelled the same and leave headroom, so
  fast typing doesn't clip. The sounds are generated by Huginn itself (no recordings);
  nothing you type is recorded. On Linux, Huginn first checks (once) that your desktop has
  a working sound output; without one, typing sounds stay off and say why.

Find on Page  (Ctrl+F, or "Find on Page..." in the page menu)
  A small search card at the top right of the page: every match is highlighted and it
  counts them ("3 of 12"). Enter / F3 next, Shift+Enter / Shift+F3 previous, Esc closes.

Import From Another Browser  (page menu > More Tools)
  Brings over bookmarks and history from Chrome, Edge, Brave, Vivaldi, Opera, Opera GX,
  Firefox, LibreWolf, Waterfox or Zen (each profile is listed separately), or from an
  exported bookmarks .html file. It reads copies of their files, so the other browser
  can stay open; nothing is sent anywhere. Bookmarks go to Favorites, history to History;
  running it again only adds what's new.

Address field suggestions
  As you type, Huginn suggests the search, then open tabs (Switch to Tab), favorites,
  Reading List and history that match - all from this PC. Addresses you've been to are
  completed as you type (Backspace removes the completion). Up/Down + Enter to pick.
  Search-engine suggestions can be switched on in Privacy & Security (off by default,
  because what you type is then sent to the search engine as you type).

Command bar  (Ctrl+K or Ctrl+E)
  One box for everything: type a few letters to jump to an open tab, favorite, history
  or Reading List page, or run a command ("dark", "screenshot", "split", "theme"...).

Bookmark folders and search  (the sidebar, Ctrl+Shift+L)
  Right-click a favorite > Move to Folder... to file it; right-click a folder to rename
  it, delete it or open everything in it. The sidebar's search box searches favorites,
  history or the Reading List (all 5,000 history entries).

Reading List  (Ctrl+Shift+D, or the sidebar's Reading tab)
  Save a page to read later. A copy is saved with it, so it can be read offline (right-
  click > Open Saved Copy). Unread pages are in bold.

Pinned tabs  (right-click a tab > Pin Tab, or the page menu)
  Small tabs that stay on the left, for sites you always keep open; they come back with
  your session. Right-clicking a tab also has Duplicate, Mute, Move to Group, Open in
  Split View and Close Other Tabs.

Split View  (page menu > Open Split View; right-click a link > Open Link in Split View)
  A second page beside your tabs, with its own address field. Drag the gap to resize;
  the tab button turns it into a normal tab.

Auto-play  (page menu > the site card > Auto-Play Videos on <site>)
  Like Chrome, Huginn lets a site start videos with sound by itself once you've played sound
  there yourself for a few seconds - so a YouTube link just plays, while a site you've never
  watched anything on can't blare at you (muted previews still play). The switch in the
  site card turns it on or off for that site; off stays off.

Video  (page menu > Video)
  Pop Out Video plays the page's video in a small window that stays on top of your other
  windows (drag it by its top bar, resize it from the corner; the button at the top
  brings it back to the tab at the same moment). Playback speed from 0.5x to 3x, for any
  site's videos.

Tab Manager  (Shift+Esc, or page menu > More Tools)
  Like GX Control: how much memory and processor each tab uses, with Sleep and Close
  buttons. RAM limit: when Huginn uses more than you set (1-8 GB), the background tabs
  using the most memory go to sleep (never the one you're on or one playing sound).

Zoom and dark websites
  Zoom is remembered per site. Settings > Appearance > Websites: Their Own Colours, Dark When Huginn
  Is Dark, or Always Dark (turns light-only sites dark), with "Dark on <site>" to leave
  out a site that looks wrong.

Tab groups  (the small arrow next to the sidebar button)
  Keep sets of tabs apart - Work, a trip, a game - and switch between them; only the
  group you're in shows in the tab bar. That menu also makes (New Tab Group...), renames
  and deletes groups; "Move Tab to Group" in the page menu moves the current tab.
  Separate Logins for a group (same menu) gives it its own cookies and site data, so you
  can be signed in to two accounts of the same site at once - one in the group, one
  outside it.
  The window title shows which group you're in.

Downloads  (Ctrl+J, the arrow button that appears at the top right, or More Tools)
  Everything you've downloaded, with progress, speed and time left while it runs.
  Double-click a file to open it; the folder button shows it in File Explorer; a failed
  or cancelled one can be downloaded again. Clear empties the list (not your files).

Reader  (F9, or the page button in the address field when a page is an article)
  Shows just the article - no ads, menus or pop-ups - in clean type over the page. Larger
  or smaller text, serif or sans, white / sepia / night; Esc or Done closes it.

Screenshots  (page menu > Take Screenshot; Ctrl+Shift+S for the whole page)
  Whole Page captures the full length of the page (headers that stay on screen appear
  once), Visible Part just what you see. Saved as PNG in Downloads and listed there.

Sound  (Ctrl+M)
  A tab playing sound shows a speaker (on the tab, and in the address field); click it to
  mute or unmute that tab.

Spell-check  (page menu > Settings > Check Spelling; on by default)
  Misspelt words in text boxes get a red underline; right-click one for suggestions.

Sleep Inactive Tabs  (page menu > Settings > Tabs; on by default)
  Tabs you haven't looked at for 5 minutes are paused, and after an hour unloaded, to
  save memory and battery. Never the tab you're on, one playing sound, one using the
  camera or microphone, or (unloading) one where you've typed something. A sleeping
  tab's name is faded; click it and it wakes up (an unloaded one reloads its page).

Muninn - search what pages said  (on by default; Privacy & Security to switch off)
  Huginn keeps the words of pages you read (on this PC only, for 90 days), so you can
  find one by what was on it, not just its title: type a few words you remember in the
  address field, Ctrl+K or the sidebar's search. Never from private windows, burner tabs
  or pages with a password or card field. Clear History clears it too.

Valhalla - closed tabs  (page menu > More Tools, or the sidebar's menu)
  Every tab you closed this past week, by day, searchable. Click one to bring it back.
  (Ctrl+Shift+T still reopens the last one.)

What the ravens saw  (page menu > Settings > Start Page > Weekly Recap; on by default)
  A card on the Start Page, under the Privacy Report: this week's pages visited, ads
  blocked, cookie pop-ups refused and roughly how much time that saved you.

Rippling Aurora  (page menu > Settings > Start Page; off by default)
  Soft curtains of light drift very slowly across the top of the Start Page, behind the
  greeting, in your theme's colours (green to violet in Aurora, violet to pink in Bifröst,
  ember in Muspelheim, ice blue in Niflheim). Off, the Start Page keeps its plain soft glow
  and nothing extra is drawn. The glow, the curtains and the weather icon move only while
  you're using the page: a few seconds after the mouse stops they hold still, so a Start
  Page left open costs no battery or CPU, and they carry on when the mouse moves. If your
  system's animation effects are off (Windows: Settings > Accessibility > Visual effects;
  Mac: Reduce motion), it holds still.

Weather on the Start Page  (page menu > Settings > Start Page > Weather)
  A card beside the greeting: the temperature, the sky (drawn and gently animated - sun,
  moon and stars at night, drifting clouds, rain, snow, lightning), today's high and low,
  sunset or sunrise, and the next three days. The sky's Old Norse word (Sól, Ský, Regn,
  Snjór, Þruma...) is written in runes above it; with Greet in Old Norse on, the card says
  it in Old Norse too. Click the city to change it or switch between °F and °C.
  Don't want it? Hover the card and click its × (or turn off page menu > Settings >
  Start Page > Weather); the same switch brings it back.
  Privacy: nothing is fetched until you pick a city, and then only that city's position
  (rounded to about 1 km) goes to Open-Meteo.com - free, no account, no key. It refreshes
  every half hour while Huginn is open. Weather data by Open-Meteo.com (CC BY 4.0).

Window Buttons  (page menu > Settings > Window Buttons; Mac style by default)
  Left - Mac Style: the red, yellow and green buttons on the left of the toolbar.
  Right - Windows Style: minimize, maximize and close on the right, drawn to match Huginn
  (close turns red on hover). The address field stays centred either way. Also in the
  welcome tour, and in the command bar (Ctrl+K > "Window Buttons").

Shift Colours With Time of Day  (page menu > Settings; off by default; in the welcome
tour it's the switch under the themes)
  The frame and Start Page aurora warm up at dawn and dusk and turn deep blue at night;
  the season tints the glow (icy in winter, green in spring, amber in autumn). Works with
  any theme; turn it off and your theme stays exactly as you chose. It changes colours
  only: light or dark is the Appearance setting.

Appearance  (page menu > Settings > Appearance)
  Match Windows follows Windows' own light or dark setting (Match Mac on a Mac, Match
  System on Linux), or pick Light or Dark.
  Sunrise to Sunset is light from sunrise until sunset and dark at night: it uses your
  weather city's sunrise and sunset (see Weather), or 7 am to 7 pm until you add a city,
  and switches within a minute. Websites' own light or dark follows your system; to have
  them follow Huginn, pick Settings > Appearance > Websites > Dark When Huginn Is Dark.

Game Mode  (page menu > Settings; on by default)
  When a game is running full screen, Huginn puts background tabs to sleep, drops to a
  lower priority so the game gets the processor, and goes quiet (no typing sounds).
  Everything goes back to normal when you leave the game. Ctrl+K > "Game Mode" switches
  it on or off by hand.

Web Panels  (page menu > Settings > Web Panels in Sidebar; off by default)
  Keep sites like Discord, Spotify or WhatsApp open in the sidebar while you browse: a
  row of their icons appears at the top of the sidebar, + adds the page you're on, and
  right-click an icon to reload or remove it. They keep running in the background. With
  the switch off the sidebar looks just as before.

Site Style  (page menu > Site Style...)
  Change how a site looks, every time you visit: ready-made styles (YouTube: Hide Shorts,
  comments, recommended videos, end-screen cards; X: hide trends; any site: Reduce
  Motion) and your own CSS. Applies straight away; switch a style off to undo it.

Focus Hours  (page menu > Settings > Focus Hours...)
  Pick sites that should rest during set hours and days (e.g. reddit.com 09:00-17:00 on
  weekdays). They show a calm "Not now" page instead, with a button to open the site for
  5 minutes if you really need it.

Privacy Grade  (the card at the top of the page menu)
  Every site gets a grade from A to F: secure connection, trackers it tried to load,
  how many other companies' servers it contacted, and whether it pushed a cookie banner.
  Hover the card for the reasons and the site's switches (Block Ads, tracking, etc.).

Burner tabs  (Ctrl+Alt+N, or page menu > More Tools)
  A tab with its own empty cookies and storage, marked with a flame. Nothing from it is
  kept - not history, not cookies, not the session, not Valhalla - and it can't see your
  logins in other tabs. Close it and it's gone.

Read Aloud  (page menu > Read Aloud, or Listen in the Reader)
  Reads the article to you with Windows' voices; the same menu item stops it.

Default browser
  "Make Huginn Your Default Browser..." in the page menu (Huginn also asks, once a month
  at most, until you say yes or Don't Ask Again):
  it registers itself with Windows for your account only and opens Settings > Default
  apps, where you click Set default. It also adds Huginn to the Start menu. Windows
  only lets you make that choice yourself, so Huginn never changes it behind your back.

Sharing Huginn with friends  (page menu > More Tools > Share Huginn With Friends...)
  Makes a zip on your Desktop: a friend unpacks it and double-clicks "Install Huginn.bat"
  (see Install it, at the top; run.bat works too). Nothing personal goes in it - no
  bookmarks, history, passwords, cookies or settings.
  Updates (optional): give the web address where you'll put updates, ending in
  huginn-update.json - for example a GitHub release:
    https://github.com/<you>/huginn/releases/latest/download/huginn-update.json
  When you've changed something, "Publish Update for Friends..." (More Tools) puts two
  files in a folder on your Desktop; upload both there, replacing the old ones. Your
  friends' copies check once a day, install it and offer to restart.
  Every update is signed with a key that only your PC has (release-key.pem in
  %LOCALAPPDATA%\SafariQt - keep a copy somewhere safe; without it you can't publish
  updates their copies will accept). Their copies refuse anything else.

Handy shortcuts
  Ctrl+T new tab        Ctrl+W close tab          Ctrl+Shift+T reopen closed tab
  Ctrl+F find on page   F3 / Shift+F3 next / previous match
  F9 Reader             Ctrl+J downloads          Ctrl+M mute tab
  Ctrl+K command bar    Ctrl+Shift+D add to Reading List
  Shift+Esc Tab Manager
  Ctrl+Shift+S screenshot of the whole page
  Ctrl+Shift+N private window                     Ctrl+, Privacy & Security
  Ctrl+Alt+N burner tab
  Ctrl+Shift+P Passwords
  Ctrl+L address field  Ctrl+R reload             Alt+Left / Alt+Right back / forward
  Ctrl+Shift+\ all tabs Ctrl+Shift+L sidebar      Ctrl+D add to Favorites
  Ctrl+Shift+H Start Page                         Ctrl+= / Ctrl+- / Ctrl+0 zoom
  F12 Web Inspector     Ctrl+Q quit               F11 full screen
  Ctrl+Tab / Ctrl+Shift+Tab next / previous tab
  On a Mac: ⌘ for Ctrl and ⌥ for Alt throughout, plus ⇧⌘R Reader, ⌘M minimize,
  ⌃M mute tab, ⌃Tab / ⌃⇧Tab next / previous tab, ⌃⌘F full screen, ⌥⌘I Web Inspector.

The page menu (the small icon at the left end of the address field):
  Site card    The site's Privacy Grade, whether the connection is secure, trackers and
               ads stopped. Hover it for the details and the site's switches: Block Ads
               on <site>, Prevent Cross-Site Tracking, Keep Me Signed In, Reset Permissions
  Quick row    Find, Reader, Listen (read aloud), Screenshot (whole page), Split View
  This page    Zoom (- 100% +; click the percentage for actual size), Site Style, Video
               (pop out, speed)
  This tab     Pin, Mute (when the tab plays sound), Move Tab to Group
  Keep it      Add to Favorites, Add to Reading List, Copy Link
  Privacy      Privacy & Security..., Passwords...
  Settings     Check Spelling, Start Page (Greet in Old Norse, Rippling Aurora, Weekly
               Recap, Weather, Weather Location...), Shift Colours With Time
               of Day, Web Panels, Game Mode, Focus Hours, Window Buttons (Mac or
               Windows side), Tabs (tab bar, sleeping,
               reopening), Theme (Aurora, Bifröst, Muspelheim, Niflheim - tints the
               frame, accent and Start Page aurora), Appearance (Light, Dark, Sunrise to
               Sunset, Match Windows; and dark websites), Search Engine, Typing Sounds
  More Tools   Downloads, Tab Manager, Command Bar, New Burner Tab, Valhalla, Add Page
               as Web Panel (when web panels are on), Screenshot of Visible Part, Import
               From Another Browser, Share Huginn With Friends..., Welcome Tour,
               Web Inspector
  In every menu, on/off settings are switches and choices (theme, search engine...) are
  ticked on the right.

The Start Page greets you by time of day, with the Old Norse words written in runes above
it - hover the greeting or the runes for the Old Norse, and the date for the day's Old
Norse name. Page menu > Settings > Start Page > Greet in Old Norse turns it around: the
greeting is in Old Norse, and hovering shows the English.
