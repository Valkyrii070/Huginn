//! What Huginn's compositor does on top of the example it started from (Smithay's Anvil):
//!
//!  * windows: new ones open in the middle of the screen the pointer is on (cascading), minimised windows wait off
//!    the screen until the dock (or Alt+Tab) brings them back, Alt+Tab goes through the windows, Super+drag moves one;
//!  * the session: once the compositor is up it starts the session (the services and the shell) and ends with it;
//!  * the bus (dbus.rs): which window is in front goes to the shell, Super / Super+Space / Print / the hardware keys
//!    go to the shell and the session daemon, and they can ask for windows, the lock and the screens off;
//!  * the lock: a lock screen of its own (huginn_locker.py), started by the compositor on a connection only it
//!    knows. While locked, nothing but that lock screen is drawn or gets the keyboard and the mouse; if it crashes,
//!    the screens stay black and it is started again. It ends the lock only by exiting with success.

use std::{
    os::{
        fd::{AsRawFd, OwnedFd},
        unix::{net::UnixStream, process::CommandExt},
    },
    process::{Child, Command},
    sync::{Arc, atomic::Ordering, mpsc},
    time::{Duration, Instant},
};

use smithay::{
    desktop::{WindowSurfaceType, layer_map_for_output, space::SpaceElement},
    input::pointer::{Focus, GrabStartData as PointerGrabStartData},
    reexports::{
        calloop::{
            channel::{Event as ChannelEvent, channel},
            timer::{TimeoutAction, Timer},
        },
        wayland_protocols::xdg::shell::server::xdg_toplevel,
        wayland_server::{Resource, backend::ClientId},
    },
    utils::{IsAlive, Logical, Point, Rectangle, SERIAL_COUNTER, Serial},
    wayland::{
        compositor::with_states,
        shell::{wlr_layer::Layer as WlrLayer, xdg::XdgToplevelSurfaceData},
    },
};
use tracing::{info, warn};

use crate::{
    dbus::{self, Outgoing, Request, Shared},
    focus::KeyboardFocusTarget,
    shell::{FullscreenSurface, PointerMoveSurfaceGrab, WindowElement},
    state::{Backend, ClientState, HuginnState},
};

/// Where the lock screen lives (an installed system; HUGINN_LOCKER overrides it for tests).
const LOCKER: &str = "/usr/share/huginn-shell/huginn_locker.py";

/// The session to start once the compositor is listening (main.rs: what follows `--`).
pub static SESSION: std::sync::OnceLock<Vec<String>> = std::sync::OnceLock::new();

#[derive(Default)]
pub struct Huginn {
    pub shared: Shared,
    pub out: Option<mpsc::Sender<Outgoing>>,
    /// Minimised windows, with where they were.
    pub minimised: Vec<(WindowElement, Point<i32, Logical>)>,
    /// Super is down and nothing else has been pressed since (on its release: the start menu).
    pub super_alone: bool,
    /// Screens turned off in Settings › Displays (displays.rs): kept, dark, out of the desktop
    pub off_outputs: Vec<smithay::output::Output>,
    /// Sticky keys and bounce keys (access.rs)
    pub keys: crate::access::Keys,
    /// The colour filter in use (access.rs)
    pub filter: crate::access::Filter,
    /// Accessibility settings as last read, and how far the screen under the pointer is zoomed (1: not at all)
    pub access: crate::access::Settings,
    pub zoom: f64,
    /// Alt+Tab in progress: the windows in the order they were in when it began, and where we are.
    pub switching: Option<(Vec<WindowElement>, usize)>,
    /// The session to start once the compositor is listening, and whether it was.
    pub session: Vec<String>,
    pub session_started: bool,
    last_active: Option<(String, String, String, bool)>,
    /// The window list as the shell last heard it.
    last_windows: String,
    /// Alt is down and nothing else has been pressed since (on its release: the app's menu).
    pub alt_alone: bool,
    /// A three-finger swipe in progress: how far it has gone.
    pub swipe: Option<(f64, f64)>,
    /// Spaces, the Overview, snapping, hiding into the dock (wm.rs).
    pub wm: crate::wm::Wm,
    pub lock: Option<Lock>,
    pub blank: bool,
    /// Surfaces that asked the computer not to go idle (idle-inhibit), while they live.
    pub inhibitors: Vec<smithay::reexports::wayland_server::Weak<smithay::reexports::wayland_server::protocol::wl_surface::WlSurface>>,
}

impl std::fmt::Debug for Huginn {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("Huginn")
            .field("minimised", &self.minimised.len())
            .field("locked", &self.lock.is_some())
            .field("session_started", &self.session_started)
            .finish()
    }
}

pub struct Lock {
    pub client: Option<ClientId>,
    child: Option<Child>,
    restart_at: Option<Instant>,
}

/// Something that marks a new window that still has to be put in its place (once it has a size).
pub struct NeedsPlacing(pub std::cell::Cell<bool>);

/// Every window's number for the shell (the dock, the Overview): given once, never reused.
struct WindowId(u64);
static NEXT_WINDOW_ID: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(1);

pub fn window_id(window: &WindowElement) -> u64 {
    window
        .0
        .user_data()
        .get_or_insert(|| WindowId(NEXT_WINDOW_ID.fetch_add(1, Ordering::Relaxed)))
        .0
}

impl<B: Backend + 'static> HuginnState<B> {
    /// After the compositor's own set-up: the bus, and a timer for what is checked now and then.
    pub fn huginn_start(&mut self) {
        self.huginn.session = SESSION.get().cloned().unwrap_or_default();
        let (to_loop, from_bus) = channel::<Request>();
        self.handle
            .insert_source(from_bus, |event, _, state| {
                if let ChannelEvent::Msg(request) = event {
                    state.bus_request(request);
                }
            })
            .expect("can't listen to the bus thread");
        self.huginn.out = Some(dbus::start(to_loop, self.huginn.shared.clone()));
        self.wm_start();
        self.reload_access();
        self.huginn.shared.touched();
        self.handle
            .insert_source(Timer::from_duration(Duration::from_millis(400)), |_, _, state| {
                state.tick();
                TimeoutAction::ToDuration(Duration::from_millis(400))
            })
            .expect("can't start the timer");
    }

    pub fn say(&self, msg: Outgoing) {
        if let Some(out) = &self.huginn.out {
            let _ = out.send(msg);
        }
    }

    /// Any key, movement or touch.
    /// A key, the mouse or the screen was touched: not idle any more, and a screen switched off comes back on.
    pub fn touched(&mut self) {
        self.huginn.shared.touched();
        if self.huginn.blank {
            self.huginn.blank = false;
            self.backend_data.set_blank(false);
        }
    }

    pub fn is_locked(&self) -> bool {
        self.huginn.lock.is_some()
    }

    fn tick(&mut self) {
        self.report_active();
        self.report_windows();
        self.watch_lock();
        self.huginn.inhibitors.retain(|s| s.upgrade().is_ok());
        self.huginn
            .shared
            .inhibited
            .store(!self.huginn.inhibitors.is_empty(), Ordering::Relaxed);
    }

    fn bus_request(&mut self, request: Request) {
        match request {
            Request::Lock => self.lock_now(),
            Request::Unlock => self.unlock_now(),
            Request::Blank(off) => {
                self.huginn.blank = off;
                self.backend_data.set_blank(off);
            }
            Request::Windows(reply) => {
                let _ = reply.send(self.windows_json());
            }
            Request::ActivateApp(ids, reply) => {
                let _ = reply.send(self.activate_app(&ids));
            }
            Request::WindowAction(action) => self.window_action(&action),
            Request::WindowDo(id, action) => self.window_do(id, &action),
            Request::OverviewDo(action) => self.overview_do(&action),
            Request::SpaceDo(action) => self.space_do(&action),
            Request::DockLayout(json) => self.dock_layout(&json),
            Request::Pointers(tx) => {
                let _ = tx.send(serde_json::Value::Array(self.backend_data.pointers()).to_string());
            }
            Request::SetPointer(sys, prop, value, tx) => {
                let _ = tx.send(self.backend_data.set_pointer(&sys, &prop, &value));
            }
            Request::ReloadInput => self.reload_input(),
            Request::ReloadAccess => self.reload_access(),
            Request::Displays(tx) => {
                let _ = tx.send(self.displays_json());
            }
            Request::ConfigureDisplay(name, change, tx) => {
                let _ = tx.send(self.configure_display(&name, &change));
            }
            Request::NightLight(kelvin) => self.backend_data.set_warmth(crate::displays::warmth(kelvin)),
            Request::Capture(tx) => {
                let outputs: Vec<_> = self.space.outputs().cloned().collect();
                if outputs.is_empty() {
                    let _ = tx.send(String::new());
                }
                let collect = std::rc::Rc::new(std::cell::RefCell::new(crate::capture::Collect {
                    left: outputs.len(),
                    parts: Vec::new(),
                    tx,
                    files: Vec::new(),
                }));
                for output in outputs {
                    let geo = self.space.output_geometry(&output).unwrap_or_default();
                    let name = format!("\"x\":{},\"y\":{},\"lw\":{},\"lh\":{}", geo.loc.x, geo.loc.y, geo.size.w, geo.size.h);
                    crate::capture::ask_shot(&output, collect.clone(), name);
                }
            }
        }
    }

    // ------------------------------------------------------------------------------------------- windows
    /// (title, app id) of a window.
    pub fn window_names(window: &WindowElement) -> (String, String) {
        #[cfg(feature = "xwayland")]
        if let Some(x) = window.0.x11_surface() {
            return (x.title(), x.class());
        }
        window
            .0
            .toplevel()
            .and_then(|t| {
                with_states(t.wl_surface(), |states| {
                    states
                        .data_map
                        .get::<XdgToplevelSurfaceData>()
                        .and_then(|d| d.lock().ok())
                        .map(|d| (d.title.clone().unwrap_or_default(), d.app_id.clone().unwrap_or_default()))
                })
            })
            .unwrap_or_default()
    }

    fn is_maximised(window: &WindowElement) -> bool {
        #[cfg(feature = "xwayland")]
        if let Some(x) = window.0.x11_surface() {
            return x.is_maximized();
        }
        window
            .0
            .toplevel()
            .map(|t| t.with_committed_state(|s| s.is_some_and(|s| s.states.contains(xdg_toplevel::State::Maximized))))
            .unwrap_or(false)
    }

    pub fn focused_window(&self) -> Option<WindowElement> {
        match self.seat.get_keyboard()?.current_focus()? {
            KeyboardFocusTarget::Window(w) => self.space.elements().find(|e| e.0 == w).cloned(),
            _ => None,
        }
    }

    /// A window went away: if it had the keyboard, the window now on top gets it (as it would on any desktop).
    pub fn focus_after_close(&mut self) {
        if self.is_locked() {
            return;
        }
        let Some(keyboard) = self.seat.get_keyboard() else {
            return;
        };
        let lost = match keyboard.current_focus() {
            None => true,
            Some(KeyboardFocusTarget::Window(w)) => !w.alive() || !self.space.elements().any(|e| e.0 == w),
            Some(_) => false, // a layer surface (the launcher…) or a popup keeps it
        };
        if lost {
            let top = self.space.elements().last().cloned();
            keyboard.set_focus(self, top.map(KeyboardFocusTarget::from), SERIAL_COUNTER.next_serial());
        }
    }

    /// The shell's top bar shows the app in front; tell it when that changes (or the window's name does).
    fn report_active(&mut self) {
        // The shell's own panels (the launcher, search…) take the keyboard without changing the app in front.
        if let Some(keyboard) = self.seat.get_keyboard()
            && matches!(keyboard.current_focus(), Some(KeyboardFocusTarget::LayerSurface(_) | KeyboardFocusTarget::Popup(_)))
        {
            return;
        }
        let now = match self.focused_window() {
            Some(w) => {
                let (title, app) = Self::window_names(&w);
                let desktop = app.trim_end_matches(".desktop").to_string();
                (title, app, desktop, Self::is_maximised(&w))
            }
            None => Default::default(),
        };
        if self.huginn.last_active.as_ref() != Some(&now) {
            self.huginn.last_active = Some(now.clone());
            self.say(Outgoing::Active(now.0, now.1, now.2, now.3));
        }
    }

    /// Bring a window forward (out of hiding too) and give it the keyboard.
    pub fn activate_window(&mut self, window: &WindowElement) {
        self.bring_space_of(window);
        if let Some(i) = self.huginn.minimised.iter().position(|(w, _)| w == window) {
            let (w, loc) = self.huginn.minimised.remove(i);
            let rect = Rectangle::new(loc + w.geometry().loc, w.geometry().size);
            self.space.map_element(w.clone(), loc, true);
            self.animate_hide(&w, rect, true);
        }
        // a window snapped beside it comes forward too
        if let Some(partner) = self.partner_of(window) {
            self.space.raise_element(&partner, false);
        }
        self.space.raise_element(window, true);
        #[cfg(feature = "xwayland")]
        if let Some(surface) = window.0.x11_surface()
            && let Some(xwm) = self.xwm.as_mut()
        {
            let _ = xwm.raise_window(surface);
        }
        if let Some(keyboard) = self.seat.get_keyboard() {
            keyboard.set_focus(self, Some(window.clone().into()), SERIAL_COUNTER.next_serial());
        }
    }

    fn matches(window: &WindowElement, ids: &[String]) -> bool {
        let (_, app) = Self::window_names(window);
        let app = app.to_lowercase();
        let app = app.trim_end_matches(".desktop");
        !app.is_empty() && ids.iter().any(|i| i.trim_end_matches(".desktop") == app)
    }

    /// The dock: the app's window in front of the others (the top-most one, or a minimised one), if it has one.
    pub fn activate_app(&mut self, ids: &[String]) -> bool {
        let found = self
            .space
            .elements()
            .rev()
            .find(|w| Self::matches(w, ids))
            .cloned()
            .or_else(|| {
                self.huginn
                    .minimised
                    .iter()
                    .rev()
                    .map(|(w, _)| w)
                    .find(|w| Self::matches(w, ids))
                    .cloned()
            });
        match found {
            Some(w) => {
                self.activate_window(&w);
                true
            }
            None => false,
        }
    }

    pub fn minimise_window(&mut self, window: &WindowElement) {
        let Some(loc) = self.space.element_location(window) else {
            return;
        };
        self.animate_hide(window, Rectangle::new(loc + window.geometry().loc, window.geometry().size), false);
        self.space.unmap_elem(window);
        self.huginn.minimised.push((window.clone(), loc));
        // the keyboard goes to the window that's now in front, if any
        let next = self.space.elements().last().cloned();
        if let Some(keyboard) = self.seat.get_keyboard() {
            keyboard.set_focus(self, next.map(KeyboardFocusTarget::from), SERIAL_COUNTER.next_serial());
        }
    }

    pub fn close_window(window: &WindowElement) {
        #[cfg(feature = "xwayland")]
        if let Some(x) = window.0.x11_surface() {
            let _ = x.close();
            return;
        }
        if let Some(t) = window.0.toplevel() {
            t.send_close();
        }
    }

    pub fn window_action(&mut self, action: &str) {
        let Some(window) = self.focused_window() else {
            return;
        };
        match action {
            "minimise" | "minimize" => self.minimise_window(&window),
            "close" => Self::close_window(&window),
            "maximise" | "maximize" => {
                if let Some(t) = window.0.toplevel().cloned() {
                    if Self::is_maximised(&window) {
                        smithay::wayland::shell::xdg::XdgShellHandler::unmaximize_request(self, t);
                    } else {
                        smithay::wayland::shell::xdg::XdgShellHandler::maximize_request(self, t);
                    }
                }
            }
            _ => {}
        }
    }

    /// The process a window belongs to (the shell asks it for its menus).
    fn window_pid(&self, w: &WindowElement) -> i32 {
        #[cfg(feature = "xwayland")]
        if let Some(x) = w.0.x11_surface() {
            return x.pid().map(|p| p as i32).unwrap_or(0);
        }
        w.0.toplevel()
            .and_then(|t| t.wl_surface().client())
            .and_then(|c| c.get_credentials(&self.display_handle).ok())
            .map(|c| c.pid)
            .unwrap_or(0)
    }

    fn window_row(&self, w: &WindowElement, minimised: bool, focused: Option<&WindowElement>, at: Option<Point<i32, Logical>>) -> serde_json::Value {
        let (title, app) = Self::window_names(w);
        let pid = self.window_pid(w);
        let full = w.0.toplevel().is_some_and(|t| t.with_committed_state(|s| s.is_some_and(|s| s.states.contains(xdg_toplevel::State::Fullscreen))));
        let size = w.geometry().size;
        let at = at.unwrap_or_default();
        serde_json::json!({"id": window_id(w).to_string(), "app": app, "title": title, "minimised": minimised,
                           "active": !minimised && Some(w) == focused, "space": Self::window_space(w).unwrap_or(0), "pid": pid, "full": full, "x": at.x, "y": at.y, "w": size.w, "h": size.h})
    }

    /// Every window (bottom to top, then the hidden ones) and the spaces, for the shell.
    fn windows_json(&self) -> String {
        let focused = self.focused_window();
        let mut rows: Vec<serde_json::Value> = self
            .space
            .elements()
            .map(|w| self.window_row(w, false, focused.as_ref(), self.space.element_location(w)))
            .collect();
        rows.extend(self.huginn.minimised.iter().map(|(w, loc)| self.window_row(w, true, None, Some(*loc))));
        rows.extend(self.huginn.wm.away.iter().map(|(w, loc)| self.window_row(w, false, None, Some(*loc))));
        serde_json::json!({"current": self.huginn.wm.current, "spaces": self.huginn.wm.spaces, "windows": rows}).to_string()
    }

    /// The shell's dock and Overview keep their own list of windows; tell them when it changes.
    fn report_windows(&mut self) {
        let now = self.windows_json();
        if now != self.huginn.last_windows {
            self.huginn.last_windows = now.clone();
            self.say(Outgoing::Windows(now));
        }
    }

    fn window_by_id(&self, id: u64) -> Option<WindowElement> {
        self.space
            .elements()
            .find(|w| window_id(w) == id)
            .cloned()
            .or_else(|| self.huginn.minimised.iter().map(|(w, _)| w).find(|w| window_id(w) == id).cloned())
    }

    /// The shell asks for something done to one window (the dock, the Overview).
    pub fn window_do(&mut self, id: u64, action: &str) {
        let Some(window) = self.window_by_id(id) else {
            return;
        };
        let hidden = self.huginn.minimised.iter().any(|(w, _)| *w == window);
        let in_front = !hidden && self.focused_window().as_ref() == Some(&window);
        match action {
            "activate" => self.activate_window(&window),
            "minimise" | "minimize" if !hidden => self.minimise_window(&window),
            "toggle" if in_front => self.minimise_window(&window),
            "toggle" => self.activate_window(&window),
            "close" => Self::close_window(&window),
            "maximise" | "maximize" => {
                self.activate_window(&window);
                self.window_action("maximise");
            }
            other => {
                if let Some(snap) = other.strip_prefix("snap:").and_then(crate::wm::Snap::parse) {
                    if hidden {
                        self.activate_window(&window);
                    }
                    self.snap_window(&window, snap, false);
                } else if let Some(n) = other.strip_prefix("space:").and_then(|n| n.parse::<usize>().ok()) {
                    self.space_do(&format!("move:{id}:{n}"));
                }
            }
        }
        self.report_windows();
    }

    pub fn report_windows_now(&mut self) {
        self.report_windows();
    }

    /// Alt+Tab (forward) and Alt+Shift+Tab: the windows as they were stacked when Alt+Tab began, minimised ones last.
    pub fn switch_step(&mut self, forward: bool) {
        if self.huginn.switching.is_none() {
            let mut order: Vec<WindowElement> = self.space.elements().rev().cloned().collect();
            order.extend(self.huginn.minimised.iter().rev().map(|(w, _)| w.clone()));
            if order.len() < 2 {
                return;
            }
            self.huginn.switching = Some((order, 0));
        }
        let Some((order, at)) = self.huginn.switching.as_mut() else {
            return;
        };
        let n = order.len();
        *at = if forward { (*at + 1) % n } else { (*at + n - 1) % n };
        let window = order[*at].clone();
        if window.0.alive() {
            self.activate_window(&window);
        }
        self.switcher_report();
    }

    pub fn switch_end(&mut self) {
        self.huginn.switching = None;
        self.switcher_report();
    }

    /// Super + the left button on a window: move it.
    pub fn super_drag(&mut self, button: u32, serial: Serial) -> bool {
        let location = self.pointer.current_location();
        let Some((window, loc)) = self.space.element_under(location).map(|(w, l)| (w.clone(), l)) else {
            return false;
        };
        let start_data = PointerGrabStartData { focus: None, button, location };
        self.unsnap_for_drag(&window);
        let grab = PointerMoveSurfaceGrab { start_data, window: window.clone(), initial_window_location: loc };
        self.activate_window(&window);
        let pointer = self.pointer.clone();
        pointer.set_grab(self, grab, serial, Focus::Clear);
        true
    }

    /// A new window, once it has a size: in the middle of the screen the pointer is on (between the top bar and the
    /// dock), a little lower and to the right if another window is already exactly there.
    pub fn place_window(&mut self, window: &WindowElement) {
        self.claim_window(window);
        let size = window.geometry().size;
        if size.w <= 0 || size.h <= 0 {
            return;
        }
        let pointer = self.pointer.current_location();
        let Some(output) = self
            .space
            .output_under(pointer)
            .next()
            .or_else(|| self.space.outputs().next())
            .cloned()
        else {
            return;
        };
        let area = {
            let geo = self.space.output_geometry(&output).unwrap_or_default();
            let zone = layer_map_for_output(&output).non_exclusive_zone();
            Rectangle::new(geo.loc + zone.loc, zone.size)
        };
        let mut loc = Point::<i32, Logical>::from((
            area.loc.x + (area.size.w - size.w).max(0) / 2,
            area.loc.y + (area.size.h - size.h).max(0) / 2,
        ));
        let taken: Vec<Point<i32, Logical>> = self
            .space
            .elements()
            .filter(|w| *w != window)
            .filter_map(|w| self.space.element_location(w).map(|l| l + w.geometry().loc))
            .collect();
        let mut tries = 0;
        while taken.contains(&loc) && tries < 12 {
            loc += Point::from((32, 32));
            tries += 1;
        }
        // its own top-left corner, not its shadow's
        let offset = window.geometry().loc;
        self.space.map_element(window.clone(), loc - offset, true);
        self.tell_x11_where(window);
        // a new window comes to the front with the keyboard (not over the lock screen)
        if !self.is_locked() {
            self.activate_window(window);
        }
    }

    // ------------------------------------------------------------------------------------------- the session
    /// Once listening (and with X11 apps' server up): start the session; the compositor ends when it does.
    pub fn start_session(&mut self) {
        if self.huginn.session_started || self.huginn.session.is_empty() {
            return;
        }
        self.huginn.session_started = true;
        let mut cmd = Command::new(&self.huginn.session[0]);
        cmd.args(&self.huginn.session[1..]).env("XDG_SESSION_TYPE", "wayland");
        if let Some(socket) = &self.socket_name {
            cmd.env("WAYLAND_DISPLAY", socket);
        }
        #[cfg(feature = "xwayland")]
        if let Some(n) = self.xdisplay {
            cmd.env("DISPLAY", format!(":{n}"));
        }
        info!(session = ?self.huginn.session, "Starting the session");
        match cmd.spawn() {
            Ok(mut child) => {
                let (tx, rx) = channel::<()>();
                std::thread::spawn(move || {
                    let _ = child.wait();
                    let _ = tx.send(());
                });
                self.handle
                    .insert_source(rx, |event, _, state| {
                        if let ChannelEvent::Msg(()) = event {
                            info!("The session ended");
                            state.running.store(false, Ordering::SeqCst);
                        }
                    })
                    .expect("can't watch the session");
            }
            Err(err) => {
                warn!(%err, "Couldn't start the session");
                self.running.store(false, Ordering::SeqCst);
            }
        }
    }

    // ------------------------------------------------------------------------------------------- the lock
    pub fn lock_now(&mut self) {
        if self.huginn.lock.is_some() {
            return;
        }
        info!("Locking");
        self.huginn.lock = Some(Lock { client: None, child: None, restart_at: None });
        self.huginn.shared.locked.store(true, Ordering::Relaxed);
        self.huginn.switching = None;
        self.say(Outgoing::LockedHint(true));
        if let Some(pointer) = self.seat.get_pointer() {
            pointer.unset_grab(self, SERIAL_COUNTER.next_serial(), smithay::backend::input::InputTime::now());
        }
        // nothing behind the lock keeps the keyboard (it goes to the lock screen once that's up)
        if let Some(keyboard) = self.seat.get_keyboard() {
            keyboard.set_focus(self, None, SERIAL_COUNTER.next_serial());
        }
        self.start_locker();
    }

    fn start_locker(&mut self) {
        let Some(lock) = self.huginn.lock.as_mut() else {
            return;
        };
        let (ours, theirs) = match UnixStream::pair() {
            Ok(p) => p,
            Err(err) => {
                warn!(%err, "can't make a connection for the lock screen");
                lock.restart_at = Some(Instant::now() + Duration::from_secs(2));
                return;
            }
        };
        let client = match self.display_handle.insert_client(ours, Arc::new(ClientState::default())) {
            Ok(c) => c,
            Err(err) => {
                warn!(%err, "can't add the lock screen's connection");
                lock.restart_at = Some(Instant::now() + Duration::from_secs(2));
                return;
            }
        };
        let theirs: OwnedFd = theirs.into();
        let fd = theirs.as_raw_fd();
        let locker = std::env::var("HUGINN_LOCKER").unwrap_or_else(|_| LOCKER.into());
        let mut cmd = Command::new("python3");
        cmd.arg(&locker).env("WAYLAND_SOCKET", "3").env_remove("WAYLAND_DISPLAY");
        // the connection becomes the lock screen's fd 3 (and only it: everything else is closed on exec)
        unsafe {
            cmd.pre_exec(move || {
                if fd == 3 {
                    // already there: dup2 would leave it marked close-on-exec
                    if libc::fcntl(3, libc::F_SETFD, 0) < 0 {
                        return Err(std::io::Error::last_os_error());
                    }
                } else if libc::dup2(fd, 3) < 0 {
                    return Err(std::io::Error::last_os_error());
                }
                Ok(())
            });
        }
        match cmd.spawn() {
            Ok(child) => {
                lock.client = Some(client.id());
                lock.child = Some(child);
                lock.restart_at = None;
            }
            Err(err) => {
                warn!(%err, "can't start the lock screen");
                lock.restart_at = Some(Instant::now() + Duration::from_secs(2));
            }
        }
        drop(theirs);
    }

    /// The lock screen ends the lock by exiting with success; anything else (a crash) starts it again.
    fn watch_lock(&mut self) {
        let Some(lock) = self.huginn.lock.as_mut() else {
            return;
        };
        if let Some(child) = lock.child.as_mut()
            && let Ok(Some(status)) = child.try_wait()
        {
            lock.child = None;
            if status.success() {
                self.unlocked();
                return;
            }
            warn!(?status, "The lock screen stopped; starting it again");
            lock.restart_at = Some(Instant::now() + Duration::from_millis(800));
        }
        if lock.restart_at.is_some_and(|t| Instant::now() >= t) {
            lock.restart_at = None;
            self.start_locker();
            return;
        }
        // the lock screen has the keyboard as soon as it's on screen (so its password field does)
        if let Some(keyboard) = self.seat.get_keyboard() {
            let want = self.lock_surface();
            if want.is_some() && keyboard.current_focus() != want {
                keyboard.set_focus(self, want, SERIAL_COUNTER.next_serial());
            }
        }
    }

    /// logind said to unlock: the lock screen goes away whatever it was doing.
    pub fn unlock_now(&mut self) {
        let Some(mut lock) = self.huginn.lock.take() else {
            return;
        };
        if let Some(mut child) = lock.child.take() {
            let _ = child.kill();
            let _ = child.wait();
        }
        if let Some(client) = lock.client.take() {
            self.display_handle.backend_handle().kill_client(client, smithay::reexports::wayland_server::backend::DisconnectReason::ConnectionClosed);
        }
        self.huginn.lock = Some(lock);
        self.unlocked();
    }

    fn unlocked(&mut self) {
        info!("Unlocked");
        self.huginn.lock = None;
        self.huginn.shared.locked.store(false, Ordering::Relaxed);
        self.huginn.shared.touched();
        self.say(Outgoing::LockedHint(false));
        let focus = self.space.elements().last().cloned();
        if let Some(keyboard) = self.seat.get_keyboard() {
            keyboard.set_focus(self, focus.map(KeyboardFocusTarget::from), SERIAL_COUNTER.next_serial());
        }
    }

    /// While locked: is this the lock screen's?
    pub fn is_lock_client(&self, client: Option<ClientId>) -> bool {
        match (&self.huginn.lock, client) {
            (Some(lock), Some(c)) => lock.client.as_ref() == Some(&c),
            _ => false,
        }
    }

    /// While locked: the lock screen's surface on the output under the pointer (or any), for the keyboard.
    pub fn lock_surface(&self) -> Option<KeyboardFocusTarget> {
        let pointer = self.pointer.current_location();
        let mut outputs: Vec<_> = self.space.output_under(pointer).cloned().collect();
        outputs.extend(self.space.outputs().cloned());
        for output in outputs {
            let map = layer_map_for_output(&output);
            if let Some(layer) = map.layers_on(WlrLayer::Overlay).find(|l| {
                self.is_lock_client(l.wl_surface().client().map(|c| c.id()))
            }) {
                return Some(layer.clone().into());
            }
        }
        None
    }

    /// While locked: what the pointer is over, among the lock screen's surfaces only.
    pub fn lock_surface_under(
        &self,
        pos: Point<f64, Logical>,
    ) -> Option<(crate::focus::PointerFocusTarget, Point<f64, Logical>)> {
        let output = self.space.output_under(pos).next()?;
        let geo = self.space.output_geometry(output)?;
        let map = layer_map_for_output(output);
        let layer = map.layer_under(WlrLayer::Overlay, pos - geo.loc.to_f64())?;
        if !self.is_lock_client(layer.wl_surface().client().map(|c| c.id())) {
            return None;
        }
        let layer_loc = map.layer_geometry(layer)?.loc;
        layer
            .surface_under(pos - geo.loc.to_f64() - layer_loc.to_f64(), WindowSurfaceType::ALL)
            .map(|(surface, loc)| (crate::focus::PointerFocusTarget::from(surface), (loc + layer_loc + geo.loc).to_f64()))
    }

    /// Fullscreen on an output (for FreeSync: on while a game or a video fills the screen).
    pub fn output_has_fullscreen(output: &smithay::output::Output) -> bool {
        output.user_data().get::<FullscreenSurface>().and_then(|f| f.get()).is_some()
    }
}
