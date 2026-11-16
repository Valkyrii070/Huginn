//! The compositor on the session bus.
//!
//! It answers as `org.huginn.Compositor` at /org/huginn/Compositor, the same interface Huginn's earlier preview
//! compositor had, so the session daemon (huginn_sessiond.py: idle time, dimming, locking, the screen off) works
//! with it unchanged; and it adds what the shell needs from a compositor (bring an app's window forward, minimise or
//! close the window in front, the list of windows).
//!
//! It tells the shell (`org.huginn.Shell`) which window is in front and when Super, Super+Space and Print were
//! pressed, and the session daemon (`org.huginn.Session.Key`) about the volume, brightness, media and power keys.
//!
//! The bus lives on a thread of its own. Calls that need the compositor's state go to the event loop over a calloop
//! channel; the answer comes back over a std channel (waited for at most a second).

use std::{
    sync::{
        Arc,
        atomic::{AtomicBool, AtomicU64, Ordering},
        mpsc,
    },
    time::{Duration, Instant},
};

use smithay::reexports::calloop::channel::Sender as LoopSender;
use tracing::{info, warn};

use erased::Body as _;

/// What the bus asks of the compositor's event loop.
pub enum Request {
    Lock,
    /// logind's "unlock the session" (`loginctl unlock-session`, from a text console if the lock screen ever can't).
    Unlock,
    Blank(bool),
    Windows(mpsc::Sender<String>),
    ActivateApp(Vec<String>, mpsc::Sender<bool>),
    WindowAction(String),
    /// Something done to one window, by the id the window list gives it: "activate", "minimise", "close",
    /// "toggle" (hide it if it's in front, else bring it forward), "maximise".
    WindowDo(u64, String),
    /// The shell's Overview: "close", "toggle", "activate:ID", "dim:ID,ID…"
    OverviewDo(String),
    /// Spaces: "switch:N", "add", "remove:N", "rename:N:name", "move:ID:N", "reorder:A:B"
    SpaceDo(String),
    /// Where the dock's tiles are, and how windows hide into them (JSON)
    DockLayout(String),
    /// Pictures of every screen (capture.rs): JSON, [{"path", "w", "h", "x", "y", "lw", "lh"}]
    Capture(mpsc::Sender<String>),
    /// The screens, as kscreen-doctor -j lists them (displays.rs)
    Displays(mpsc::Sender<String>),
    /// One change to one screen ("mode.1920x1080@60000", "scale.1.25"…): "" when done, else why not
    ConfigureDisplay(String, String, mpsc::Sender<String>),
    /// Night light: the colour temperature, in kelvin (6500: off)
    NightLight(u32),
    /// A small picture of one window, for the dock's window cards: JSON {"path", "w", "h"}, or ""
    WindowPicture(u64, mpsc::Sender<String>),
    /// Mice and touchpads (input.rs): JSON
    Pointers(mpsc::Sender<String>),
    /// One setting on one of them: device, setting, value (JSON): "" when done, else why not
    SetPointer(String, String, String, mpsc::Sender<String>),
    /// Settings changed the keyboard's layouts or key repeat
    ReloadInput,
    /// Settings changed accessibility (colour filters, sticky and bounce keys, Reduce Motion)
    ReloadAccess,
}

/// What the compositor tells others over the bus.
#[derive(Debug, Clone)]
pub enum Outgoing {
    /// The window in front changed (caption, app, desktop file id, maximised): org.huginn.Shell.Active.
    Active(String, String, String, bool),
    /// Super on its own.
    Launcher,
    /// Super+Space (with nothing typed).
    Search,
    /// A key for the shell (org.huginn.Shell.Key): "today" (Super+T)…
    ShellKey(String),
    /// Print ("screen") and Shift+Print / Super+Shift+S ("choose").
    Screenshot(String),
    /// A hardware key, by the session daemon's name for it ("volumeUp", "playPause"…).
    Key(String),
    /// logind's LockedHint for this session.
    LockedHint(bool),
    /// The windows changed (JSON, as `Windows` gives them): org.huginn.Shell.Windows.
    Windows(String),
    /// The Overview opened (where each window is in it) or closed: org.huginn.Shell.Overview.
    Overview(String),
    /// A dragged window would snap there ("" none): org.huginn.Shell.SnapPreview.
    SnapPreview(String),
    /// After snapping one: the other half, and the windows that could fill it: org.huginn.Shell.SnapAssist.
    SnapAssist(String),
    /// Alt+Tab: the windows and the one picked ("" when it's over): org.huginn.Shell.Switcher.
    Switcher(String),
}

/// What the bus thread can read without asking the event loop.
#[derive(Clone)]
pub struct Shared {
    pub start: Instant,
    /// Milliseconds since `start` at the last touch of a key, the mouse or the screen.
    pub last_input_ms: Arc<AtomicU64>,
    /// Something asked not to be left idle (a video playing full screen: idle-inhibit).
    pub inhibited: Arc<AtomicBool>,
    pub locked: Arc<AtomicBool>,
}

impl Shared {
    pub fn new() -> Self {
        Shared {
            start: Instant::now(),
            last_input_ms: Arc::new(AtomicU64::new(0)),
            inhibited: Arc::new(AtomicBool::new(false)),
            locked: Arc::new(AtomicBool::new(false)),
        }
    }

    pub fn touched(&self) {
        self.last_input_ms
            .store(self.start.elapsed().as_millis() as u64, Ordering::Relaxed);
    }

    fn idle_ms(&self) -> u64 {
        if self.inhibited.load(Ordering::Relaxed) && !self.locked.load(Ordering::Relaxed) {
            return 0;
        }
        (self.start.elapsed().as_millis() as u64).saturating_sub(self.last_input_ms.load(Ordering::Relaxed))
    }
}

impl Default for Shared {
    fn default() -> Self {
        Self::new()
    }
}

struct Compositor {
    to_loop: LoopSender<Request>,
    shared: Shared,
}

#[zbus::interface(name = "org.huginn.Compositor")]
impl Compositor {
    /// How long since anyone touched the computer, in milliseconds (0 while something keeps it awake).
    fn idle_time(&self) -> u64 {
        self.shared.idle_ms()
    }

    fn lock(&self) {
        let _ = self.to_loop.send(Request::Lock);
    }

    fn locked(&self) -> bool {
        self.shared.locked.load(Ordering::Relaxed)
    }

    /// Screens off (true) or on again (false).
    fn blank(&self, off: bool) {
        let _ = self.to_loop.send(Request::Blank(off));
    }

    /// A picture of the screen, saved: its path ("" when it can't be done yet).
    fn screenshot(&self) -> String {
        String::new()
    }

    /// Pictures of the screens, for Print, the Screenshot app and the desktop portal: JSON, one entry per screen,
    /// [{"path": a raw picture in $XDG_RUNTIME_DIR (huginn_capture.py reads it), "w", "h" in pixels, "x", "y", "lw",
    /// "lh": where the screen is on the desktop}], or "" when it can't be done.
    fn capture(&self) -> String {
        let (tx, rx) = mpsc::channel();
        if self.to_loop.send(Request::Capture(tx)).is_err() {
            return String::new();
        }
        // a slow computer (or a virtual one) can take a while to draw the screen again
        rx.recv_timeout(Duration::from_secs(15)).unwrap_or_default()
    }

    /// The screens, in kscreen-doctor's JSON (`kscreen-doctor -j`), for Settings › Displays.
    fn displays(&self) -> String {
        let (tx, rx) = mpsc::channel();
        if self.to_loop.send(Request::Displays(tx)).is_err() {
            return String::new();
        }
        rx.recv_timeout(Duration::from_secs(1)).unwrap_or_default()
    }

    /// One change to one screen, as kscreen-doctor's "output.NAME.CHANGE" without "output.NAME.": "" when done,
    /// else why not, in words for the person.
    fn configure_display(&self, name: &str, change: &str) -> String {
        let (tx, rx) = mpsc::channel();
        if self.to_loop.send(Request::ConfigureDisplay(name.into(), change.into(), tx)).is_err() {
            return "The compositor didn't answer.".into();
        }
        rx.recv_timeout(Duration::from_secs(5)).unwrap_or_else(|_| "The compositor didn't answer.".into())
    }

    /// Night light: every screen's colour temperature, in kelvin (6500 or more: off). The session daemon sets it
    /// from Settings' schedule.
    fn night_light(&self, kelvin: u32) {
        let _ = self.to_loop.send(Request::NightLight(kelvin));
    }

    /// Mice and touchpads, as JSON: [{"sys", "name", "touchpad", "tap", "natural", "left", "speed", "dwt", "canDwt",
    /// "canTap"}] (Settings › Keyboard & Mouse).
    fn pointers(&self) -> String {
        let (tx, rx) = mpsc::channel();
        if self.to_loop.send(Request::Pointers(tx)).is_err() {
            return String::new();
        }
        rx.recv_timeout(Duration::from_secs(1)).unwrap_or_default()
    }

    /// One setting on one mouse or touchpad ("tap", "natural", "left", "speed", "dwt"; the value as JSON): "" when
    /// done, else why not.
    fn set_pointer(&self, sys: &str, setting: &str, value: &str) -> String {
        let (tx, rx) = mpsc::channel();
        if self.to_loop.send(Request::SetPointer(sys.into(), setting.into(), value.into(), tx)).is_err() {
            return "The compositor didn't answer.".into();
        }
        rx.recv_timeout(Duration::from_secs(2)).unwrap_or_else(|_| "The compositor didn't answer.".into())
    }

    /// Settings changed accessibility (kaccessrc, kwinrc, kdeglobals): read it again.
    fn reload_access(&self) {
        let _ = self.to_loop.send(Request::ReloadAccess);
    }

    /// Settings changed the keyboard (kxkbrc, kcminputrc): read it again.
    fn reload_input(&self) {
        let _ = self.to_loop.send(Request::ReloadInput);
    }

    /// A small picture of one window (by the id the window list gives it), for the dock's window cards: JSON
    /// {"path": a raw picture in $XDG_RUNTIME_DIR, "w", "h"}, or "" (no such window, or it couldn't be drawn).
    fn window_picture(&self, id: &str) -> String {
        let Ok(id) = id.parse::<u64>() else { return String::new() };
        let (tx, rx) = mpsc::channel();
        if self.to_loop.send(Request::WindowPicture(id, tx)).is_err() {
            return String::new();
        }
        rx.recv_timeout(Duration::from_secs(5)).unwrap_or_default()
    }

    /// The windows, as JSON: {"current": space, "spaces": [names], "windows": [{"id", "app", "title", "minimised",
    /// "active", "space", "x", "y", "w", "h"}]}. The shell is also told whenever this changes (Shell.Windows).
    fn windows(&self) -> String {
        let (tx, rx) = mpsc::channel();
        if self.to_loop.send(Request::Windows(tx)).is_err() {
            return "[]".into();
        }
        rx.recv_timeout(Duration::from_secs(1)).unwrap_or_else(|_| "{}".into())
    }

    /// The Overview: "toggle", "close", "activate:ID", "dim:ID,ID…".
    fn overview_do(&self, action: &str) {
        let _ = self.to_loop.send(Request::OverviewDo(action.to_string()));
    }

    /// Spaces: "switch:N", "add", "remove:N", "rename:N:name", "move:ID:N", "reorder:A:B".
    fn space_do(&self, action: &str) {
        let _ = self.to_loop.send(Request::SpaceDo(action.to_string()));
    }

    /// The dock: where its tiles are and how windows hide into them (JSON).
    fn dock_layout(&self, json: &str) {
        let _ = self.to_loop.send(Request::DockLayout(json.to_string()));
    }

    /// Something done to one window, by its id in the window list (see `Request::WindowDo`).
    fn window_do(&self, id: &str, action: &str) {
        if let Ok(id) = id.parse::<u64>() {
            let _ = self.to_loop.send(Request::WindowDo(id, action.to_string()));
        }
    }

    /// Bring forward (and un-minimise) the most recent window of an app, by any of its ids (desktop file id, app id,
    /// window class), separated by spaces. False when it has no window.
    fn activate_app(&self, ids: &str) -> bool {
        let ids: Vec<String> = ids.split_whitespace().map(|s| s.to_lowercase()).collect();
        let (tx, rx) = mpsc::channel();
        if ids.is_empty() || self.to_loop.send(Request::ActivateApp(ids, tx)).is_err() {
            return false;
        }
        rx.recv_timeout(Duration::from_secs(1)).unwrap_or(false)
    }

    /// The window in front: "minimise", "close", "maximise".
    fn window_action(&self, action: &str) {
        let _ = self.to_loop.send(Request::WindowAction(action.to_string()));
    }
}

/// Starts the bus thread. Returns where to send what the compositor wants to tell others.
pub fn start(to_loop: LoopSender<Request>, shared: Shared) -> mpsc::Sender<Outgoing> {
    let (tx, rx) = mpsc::channel::<Outgoing>();
    let logind_loop = to_loop.clone();
    std::thread::Builder::new()
        .name("logind".into())
        .spawn(move || watch_logind(logind_loop))
        .expect("can't start the logind thread");
    std::thread::Builder::new()
        .name("dbus".into())
        .spawn(move || {
            let iface = Compositor { to_loop, shared };
            let conn = match zbus::blocking::connection::Builder::session()
                .and_then(|b| b.name("org.huginn.Compositor"))
                .and_then(|b| b.serve_at("/org/huginn/Compositor", iface))
                .and_then(|b| b.build())
            {
                Ok(conn) => {
                    info!("On the session bus as org.huginn.Compositor");
                    conn
                }
                Err(err) => {
                    warn!(?err, "No session bus: the shell and the session daemon won't hear from the compositor");
                    for _ in rx {}
                    return;
                }
            };
            let system = zbus::blocking::Connection::system().ok();
            for msg in rx {
                let shell = |member: &str, body: &dyn erased::Body| body.send_to(&conn, "org.huginn.Shell", "/org/huginn/Shell", "org.huginn.Shell", member);
                let result = match &msg {
                    Outgoing::Active(caption, app, desktop, max) => {
                        shell("Active", &(caption.as_str(), app.as_str(), desktop.as_str(), *max))
                    }
                    Outgoing::Launcher => shell("ToggleLauncher", &()),
                    Outgoing::Search => shell("Search", &("",)),
                    Outgoing::ShellKey(what) => shell("Key", &(what.as_str(),)),
                    Outgoing::Screenshot(what) => shell("Screenshot", &(what.as_str(),)),
                    Outgoing::Windows(json) => shell("Windows", &(json.as_str(),)),
                    Outgoing::Overview(json) => shell("Overview", &(json.as_str(),)),
                    Outgoing::SnapPreview(json) => shell("SnapPreview", &(json.as_str(),)),
                    Outgoing::SnapAssist(json) => shell("SnapAssist", &(json.as_str(),)),
                    Outgoing::Switcher(json) => shell("Switcher", &(json.as_str(),)),
                    Outgoing::Key(name) => (name.as_str(),).send_to(
                        &conn,
                        "org.huginn.Session",
                        "/org/huginn/Session",
                        "org.huginn.Session",
                        "Key",
                    ),
                    Outgoing::LockedHint(on) => match &system {
                        Some(system) => (*on,).send_to(
                            system,
                            "org.freedesktop.login1",
                            "/org/freedesktop/login1/session/auto",
                            "org.freedesktop.login1.Session",
                            "SetLockedHint",
                        ),
                        None => Ok(()),
                    },
                };
                if let Err(err) = result {
                    // the shell may not be there yet (or restarting): nothing to do but say so quietly
                    tracing::debug!(?msg, %err, "bus call");
                }
            }
        })
        .expect("can't start the bus thread");
    tx
}

/// logind: "lock the session" (`loginctl lock-session`, and anything else that asks logind) and going to sleep lock;
/// "unlock the session" unlocks.
fn watch_logind(to_loop: LoopSender<Request>) {
    let Ok(system) = zbus::blocking::Connection::system() else {
        warn!("No system bus: logind can't lock the session");
        return;
    };
    let session: Option<zbus::zvariant::OwnedObjectPath> = system
        .call_method(
            Some("org.freedesktop.login1"),
            "/org/freedesktop/login1",
            Some("org.freedesktop.login1.Manager"),
            "GetSession",
            &("auto",),
        )
        .ok()
        .and_then(|reply| reply.body().deserialize().ok());
    let Some(session) = session else {
        info!("Not in a logind session: only Super+L and the session daemon lock");
        return;
    };
    let rule = match zbus::MatchRule::builder()
        .msg_type(zbus::message::Type::Signal)
        .sender("org.freedesktop.login1")
        .map(|b| b.build())
    {
        Ok(rule) => rule,
        Err(err) => {
            warn!(%err, "can't listen to logind");
            return;
        }
    };
    let messages = match zbus::blocking::MessageIterator::for_match_rule(rule, &system, Some(16)) {
        Ok(m) => m,
        Err(err) => {
            warn!(%err, "can't listen to logind");
            return;
        }
    };
    for msg in messages.flatten() {
        let header = msg.header();
        let (Some(member), Some(path)) = (header.member(), header.path()) else {
            continue;
        };
        let ours = path.as_str() == session.as_str();
        let request = match member.as_str() {
            "Lock" if ours => Some(Request::Lock),
            "Unlock" if ours => Some(Request::Unlock),
            "PrepareForSleep" if msg.body().deserialize::<bool>().unwrap_or(false) => Some(Request::Lock),
            _ => None,
        };
        if let Some(request) = request {
            let _ = to_loop.send(request);
        }
    }
}

/// A small helper so calls with differently typed bodies can share one closure.
mod erased {
    pub trait Body {
        fn send_to(&self, conn: &zbus::blocking::Connection, dest: &str, path: &str, iface: &str, member: &str) -> zbus::Result<()>;
    }
    impl<T: serde::Serialize + zbus::zvariant::DynamicType> Body for T {
        fn send_to(&self, conn: &zbus::blocking::Connection, dest: &str, path: &str, iface: &str, member: &str) -> zbus::Result<()> {
            conn.call_method(Some(dest), path, Some(iface), member, self).map(|_| ())
        }
    }
}
