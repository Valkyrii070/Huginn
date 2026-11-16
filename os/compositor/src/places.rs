//! Where windows open: each app's window comes back where it was and at its size (Settings › Desktop & Dock,
//! "Windows open where they were"; ~/.config/huginn/places.json), and rules for particular apps
//! (~/.config/huginn/window-rules.json, written by hand):
//!
//! ```json
//! [{"app": "org.gimp.GIMP", "maximise": true},
//!  {"app": "huginn-terminal", "size": [900, 560], "position": [40, 60]},
//!  {"app": "discord", "title": "Discord", "space": 2}]
//! ```
//! "app" is the app's id (as the window list gives it), "title" a part of the title; "space" counts from 1.

use std::{
    path::PathBuf,
    sync::atomic::{AtomicBool, Ordering},
};

use serde_json::{Value, json};
use smithay::{
    desktop::space::SpaceElement,
    utils::{Logical, Point, Rectangle, Size},
};

use crate::{
    shell::WindowElement,
    state::{Backend, HuginnState},
};

/// "Windows open where they were" (the shell says, with the dock's layout).
pub static REMEMBER: AtomicBool = AtomicBool::new(true);

fn dir() -> Option<PathBuf> {
    let base = std::env::var_os("XDG_CONFIG_HOME")
        .map(PathBuf::from)
        .or_else(|| std::env::var_os("HOME").map(|h| PathBuf::from(h).join(".config")))?;
    Some(base.join("huginn"))
}

fn read(name: &str) -> Value {
    dir()
        .and_then(|d| std::fs::read_to_string(d.join(name)).ok())
        .and_then(|t| serde_json::from_str(&t).ok())
        .unwrap_or(Value::Null)
}

#[derive(Default)]
pub struct Places {
    /// app -> where its window last was (logical, desktop)
    pub seen: std::collections::HashMap<String, Rectangle<i32, Logical>>,
    pub dirty: bool,
    pub loaded: bool,
}

/// The first rule for this app and title, if any.
fn rule(app: &str, title: &str) -> Option<Value> {
    let rules = read("window-rules.json");
    rules.as_array()?.iter().find(|r| {
        r.get("app").and_then(|a| a.as_str()).is_some_and(|a| a.eq_ignore_ascii_case(app))
            && r.get("title").and_then(|t| t.as_str()).is_none_or(|t| title.contains(t))
    }).cloned()
}

impl<B: Backend + 'static> HuginnState<B> {
    /// A window being put on the screen for the first time: its rule, else where the app's window last was.
    /// Returns where it goes (its top-left), or None to leave it to the usual placing.
    pub fn place_from_memory(&mut self, window: &WindowElement) -> Option<Point<i32, Logical>> {
        let (title, app) = crate::shell::window_names(window);
        let id = crate::huginn::window_id(window);
        if let Some(r) = rule(&app, &title) {
            let n = |k: &str, i: usize| r.get(k).and_then(|v| v.get(i)).and_then(|v| v.as_i64()).map(|v| v as i32);
            if let Some(space) = r.get("space").and_then(|v| v.as_u64()).filter(|s| *s >= 1) {
                let to = space - 1;
                self.handle.insert_idle(move |state| state.space_do(&format!("move:{id}:{to}")));
            }
            if r.get("maximise").and_then(|v| v.as_bool()) == Some(true) {
                if let Some(t) = window.0.toplevel().cloned() {
                    let state: &mut Self = self;
                    smithay::wayland::shell::xdg::XdgShellHandler::maximize_request(state, t);
                    return None;
                }
            }
            if let (Some(w), Some(h)) = (n("size", 0), n("size", 1)) {
                self.configure_size(window, Size::from((w.max(200), h.max(120))), false);
            }
            if let (Some(x), Some(y)) = (n("position", 0), n("position", 1)) {
                return Some(self.on_a_screen(Point::from((x, y))));
            }
            return None;
        }
        if !REMEMBER.load(Ordering::Relaxed) {
            return None;
        }
        self.load_places();
        let was = *self.huginn.places.seen.get(&app)?;
        // a second window of the app goes beside the first, not on it
        let taken = self.space.elements().filter(|w| *w != window).any(|w| crate::shell::window_names(w).1 == app);
        self.configure_size(window, was.size, false);
        let at = if taken { was.loc + Point::from((32, 32)) } else { was.loc };
        Some(self.on_a_screen(at))
    }

    /// A point kept on one of the screens (a screen that's gone since).
    fn on_a_screen(&self, at: Point<i32, Logical>) -> Point<i32, Logical> {
        let inside = self.space.outputs().any(|o| self.space.output_geometry(o).is_some_and(|g| g.contains(at)));
        if inside {
            return at;
        }
        self.space.outputs().next().and_then(|o| self.space.output_geometry(o)).map_or(at, |g| g.loc + Point::from((60, 60)))
    }

    fn load_places(&mut self) {
        if self.huginn.places.loaded {
            return;
        }
        self.huginn.places.loaded = true;
        if let Some(all) = read("places.json").as_object() {
            for (app, r) in all {
                let n = |i: usize| r.get(i).and_then(|v| v.as_i64()).unwrap_or(0) as i32;
                if n(2) > 0 && n(3) > 0 {
                    self.huginn.places.seen.insert(app.clone(), Rectangle::new((n(0), n(1)).into(), (n(2), n(3)).into()));
                }
            }
        }
    }

    /// Now and then: where each app's free-standing window is (not snapped, filled or full screen), saved when it
    /// changed.
    pub fn note_places(&mut self) {
        if !REMEMBER.load(Ordering::Relaxed) {
            return;
        }
        self.load_places();
        let mut changed = false;
        let windows: Vec<WindowElement> = self.space.elements().cloned().collect();
        for w in windows {
            let id = crate::huginn::window_id(&w);
            if self.huginn.wm.snapped.contains_key(&id) {
                continue;
            }
            let maxed = w.0.toplevel().is_some_and(|t| {
                t.with_pending_state(|s| {
                    s.states.contains(smithay::reexports::wayland_protocols::xdg::shell::server::xdg_toplevel::State::Maximized)
                        || s.states.contains(smithay::reexports::wayland_protocols::xdg::shell::server::xdg_toplevel::State::Fullscreen)
                })
            });
            if maxed {
                continue;
            }
            let Some(loc) = self.space.element_location(&w) else { continue };
            let g = w.geometry();
            if g.size.w < 120 || g.size.h < 80 {
                continue;
            }
            let app = crate::shell::window_names(&w).1;
            if app.is_empty() {
                continue;
            }
            let rect = Rectangle::new(loc + g.loc, g.size);
            if self.huginn.places.seen.get(&app) != Some(&rect) {
                self.huginn.places.seen.insert(app, rect);
                changed = true;
            }
        }
        if changed {
            self.huginn.places.dirty = true;
        }
        if self.huginn.places.dirty {
            self.huginn.places.dirty = false;
            let all: serde_json::Map<String, Value> = self
                .huginn
                .places
                .seen
                .iter()
                .map(|(a, r)| (a.clone(), json!([r.loc.x, r.loc.y, r.size.w, r.size.h])))
                .collect();
            if let Some(d) = dir() {
                let _ = std::fs::create_dir_all(&d);
                let _ = std::fs::write(d.join("places.json"), serde_json::to_string(&Value::Object(all)).unwrap_or_default());
            }
        }
    }
}
