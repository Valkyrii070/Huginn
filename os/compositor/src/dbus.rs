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
    /// Print ("screen") and Shift+Print / Super+Shift+S ("choose").
    Screenshot(String),
    /// A hardware key, by the session daemon's name for it ("volumeUp", "playPause"…).
    Key(String),
    /// logind's LockedHint for this session.
    LockedHint(bool),
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

    /// A picture of the screen for the desktop portal: its path ("" when it can't be done yet).
    fn capture(&self) -> String {
        String::new()
    }

    /// The windows, as JSON: [{"app", "title", "minimised", "focused"}].
    fn windows(&self) -> String {
        let (tx, rx) = mpsc::channel();
        if self.to_loop.send(Request::Windows(tx)).is_err() {
            return "[]".into();
        }
        rx.recv_timeout(Duration::from_secs(1)).unwrap_or_else(|_| "[]".into())
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
                    Outgoing::Screenshot(what) => shell("Screenshot", &(what.as_str(),)),
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
