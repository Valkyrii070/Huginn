//! Huginn's window management on top of the compositor's basics (huginn.rs):
//!
//!  * spaces: windows live on one space each; switching hides the others (Super+Ctrl+←/→, Super+1…9, three fingers
//!    left/right), Super+Shift+←/→ takes the window in front along;
//!  * the Overview (Super+Tab, three fingers up): this space's windows glide apart so none overlap; the shell draws
//!    the spaces strip, each window's name and the search over them (its own surface) and says what was picked;
//!  * snapping: drag a window to an edge or a corner (the shell shows where it'll land: lit glass), Super+arrows step
//!    through halves, thirds and two-thirds; 8 px gaps; windows snapped side by side come forward together, and after
//!    snapping one, the shell offers the other windows for the other half;
//!  * hiding a window into its dock tile (and back out): "drop and ring" (it folds to a line, narrows to the tile and
//!    drops in), "line" or "comet", as Settings › Desktop & Dock says (the shell tells us, with where the tiles are);
//!  * Alt+Tab: the shell shows the windows while Alt is held.
//!
//! What's drawn differently (windows somewhere else, the desktop dimmed, light) is a `SceneView` the backends hand to
//! render.rs each frame.

use std::{
    cell::Cell,
    collections::HashMap,
    time::{Duration, Instant},
};

use smithay::{
    desktop::{layer_map_for_output, space::SpaceElement},
    output::Output,
    reexports::wayland_protocols::xdg::shell::server::xdg_toplevel,
    utils::{IsAlive, Logical, Point, Rectangle, Size},
};

use crate::{
    dbus::Outgoing,
    huginn::window_id,
    shell::WindowElement,
    state::{Backend, HuginnState},
};

const OVERVIEW_MS: f64 = 300.0;
const HIDE_MS: f64 = 420.0;
const GAP: i32 = 8;
const STRIP: i32 = 118; // the spaces strip over the Overview (the shell draws it)
const CHIP: i32 = 34; // a window's name under it in the Overview

/// Which space a window is on.
struct WindowSpace(Cell<usize>);
/// A window's size before it was snapped (it gets it back when dragged away).
struct Unsnapped(Cell<Option<Size<i32, Logical>>>);

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Snap {
    Left,
    Right,
    Max,
    TopLeft,
    TopRight,
    BottomLeft,
    BottomRight,
    LeftThird,
    RightThird,
    LeftTwoThirds,
    RightTwoThirds,
}

impl Snap {
    pub fn parse(s: &str) -> Option<Snap> {
        Some(match s {
            "left" => Snap::Left,
            "right" => Snap::Right,
            "max" | "top" => Snap::Max,
            "top-left" => Snap::TopLeft,
            "top-right" => Snap::TopRight,
            "bottom-left" => Snap::BottomLeft,
            "bottom-right" => Snap::BottomRight,
            "left-third" => Snap::LeftThird,
            "right-third" => Snap::RightThird,
            "left-two-thirds" => Snap::LeftTwoThirds,
            "right-two-thirds" => Snap::RightTwoThirds,
            _ => return None,
        })
    }
    fn name(self) -> &'static str {
        match self {
            Snap::Left => "left",
            Snap::Right => "right",
            Snap::Max => "max",
            Snap::TopLeft => "top-left",
            Snap::TopRight => "top-right",
            Snap::BottomLeft => "bottom-left",
            Snap::BottomRight => "bottom-right",
            Snap::LeftThird => "left-third",
            Snap::RightThird => "right-third",
            Snap::LeftTwoThirds => "left-two-thirds",
            Snap::RightTwoThirds => "right-two-thirds",
        }
    }
    /// The half or part across from this one (for "fill the other half").
    fn other(self) -> Option<Snap> {
        Some(match self {
            Snap::Left => Snap::Right,
            Snap::Right => Snap::Left,
            Snap::LeftThird => Snap::RightTwoThirds,
            Snap::RightThird => Snap::LeftTwoThirds,
            Snap::LeftTwoThirds => Snap::RightThird,
            Snap::RightTwoThirds => Snap::LeftThird,
            _ => return None,
        })
    }
}

pub struct Overview {
    start: Instant,
    pub opening: bool,
    pub slots: Vec<(WindowElement, Rectangle<i32, Logical>)>,
    pub output: Output,
    pub dimmed: Vec<u64>,
}

impl Overview {
    fn progress(&self) -> f64 {
        let t = (self.start.elapsed().as_secs_f64() * 1000.0 / OVERVIEW_MS).min(1.0);
        let e = 1.0 - (1.0 - t).powi(3);
        if self.opening { e } else { 1.0 - e }
    }
    fn settled(&self) -> bool {
        self.start.elapsed().as_secs_f64() * 1000.0 >= OVERVIEW_MS
    }
}

/// A window going into its dock tile (or coming back out).
pub struct Hiding {
    pub window: WindowElement,
    pub from: Rectangle<f64, Logical>,
    pub to: Rectangle<f64, Logical>,
    start: Instant,
    pub back: bool,
    pub style: String,
}

#[derive(Default)]
pub struct Wm {
    pub spaces: Vec<String>,
    pub current: usize,
    /// Windows on the other spaces, with where they were.
    pub away: Vec<(WindowElement, Point<i32, Logical>)>,
    pub overview: Option<Overview>,
    pub snap: Option<Snap>,
    pub snapped: HashMap<u64, Snap>,
    pub hiding: Vec<Hiding>,
    /// The dock's tiles (app id -> where, on the screen) and how windows hide into them, from the shell.
    pub tiles: HashMap<String, Rectangle<i32, Logical>>,
    pub hide_style: String,
    pub glow: [f32; 4],
    pub gaps: bool,
    pub switcher_shown: bool,
}

/// What render.rs draws differently this frame.
#[derive(Default)]
pub struct SceneView {
    /// Black over the desktop behind the windows (0: none).
    pub dim: f32,
    /// Windows drawn somewhere else (or not at all, at alpha 0): the window, its new rect, how it's stretched.
    pub moved: Vec<(WindowElement, Rectangle<f64, Logical>, f64, f64, f32)>,
    /// Light over a rect (the hiding window turning to light).
    pub light: Vec<(Rectangle<f64, Logical>, [f32; 4])>,
}

impl SceneView {
    pub fn active(&self) -> bool {
        self.dim > 0.0 || !self.moved.is_empty() || !self.light.is_empty()
    }
}

fn lerp(a: f64, b: f64, t: f64) -> f64 {
    a + (b - a) * t
}

fn lerp_rect(a: Rectangle<f64, Logical>, b: Rectangle<f64, Logical>, t: f64) -> Rectangle<f64, Logical> {
    Rectangle::new(
        (lerp(a.loc.x, b.loc.x, t), lerp(a.loc.y, b.loc.y, t)).into(),
        (lerp(a.size.w, b.size.w, t), lerp(a.size.h, b.size.h, t)).into(),
    )
}

impl<B: Backend + 'static> HuginnState<B> {
    // ------------------------------------------------------------------------------------------- spaces
    pub fn wm_start(&mut self) {
        if self.huginn.wm.spaces.is_empty() {
            self.huginn.wm.spaces = vec!["Main".into()];
            self.huginn.wm.hide_style = "drop".into();
            self.huginn.wm.glow = [0.24, 0.84, 0.71, 1.0];
            self.huginn.wm.gaps = true;
        }
    }

    pub fn window_space(window: &WindowElement) -> Option<usize> {
        window.0.user_data().get::<WindowSpace>().map(|s| s.0.get())
    }

    /// A new window: on the space in front.
    pub fn claim_window(&mut self, window: &WindowElement) {
        let current = self.huginn.wm.current;
        window.0.user_data().get_or_insert(|| WindowSpace(Cell::new(current)));
    }

    fn set_window_space(window: &WindowElement, n: usize) {
        window.0.user_data().get_or_insert(|| WindowSpace(Cell::new(n))).0.set(n);
    }

    pub fn switch_space(&mut self, n: usize) {
        let wm = &mut self.huginn.wm;
        if n >= wm.spaces.len() || n == wm.current {
            return;
        }
        wm.current = n;
        let leaving: Vec<WindowElement> = self
            .space
            .elements()
            .filter(|w| Self::window_space(w).unwrap_or(0) != n)
            .cloned()
            .collect();
        for w in leaving {
            if let Some(loc) = self.space.element_location(&w) {
                self.space.unmap_elem(&w);
                self.huginn.wm.away.push((w, loc));
            }
        }
        let (coming, staying): (Vec<_>, Vec<_>) =
            std::mem::take(&mut self.huginn.wm.away).into_iter().partition(|(w, _)| Self::window_space(w).unwrap_or(0) == n);
        self.huginn.wm.away = staying;
        for (w, loc) in coming {
            if w.alive() {
                self.space.map_element(w, loc, false);
            }
        }
        let top = self.space.elements().last().cloned();
        if let Some(top) = top {
            self.activate_window(&top);
        } else if let Some(keyboard) = self.seat.get_keyboard() {
            keyboard.set_focus(self, None, smithay::utils::SERIAL_COUNTER.next_serial());
        }
        if self.huginn.wm.overview.is_some() {
            self.overview_relayout();
        }
        self.report_windows_now();
    }

    /// Super+Ctrl+←/→ (and three fingers): the space beside; with `take`, the window in front comes along.
    pub fn space_step(&mut self, delta: i32, take: bool) {
        let n = self.huginn.wm.spaces.len() as i32;
        let next = self.huginn.wm.current as i32 + delta;
        if next < 0 || next >= n {
            if take && next == n {
                self.huginn.wm.spaces.push(format!("Space {}", n + 1));
            } else {
                return;
            }
        }
        let next = next as usize;
        if take && let Some(w) = self.focused_window() {
            Self::set_window_space(&w, next);
        }
        self.switch_space(next);
    }

    /// From the shell (the Overview's strip, the dock's menus): "switch:N", "add", "remove:N", "rename:N:name",
    /// "move:ID:N", "reorder:A:B".
    pub fn space_do(&mut self, action: &str) {
        let mut parts = action.splitn(3, ':');
        let what = parts.next().unwrap_or("");
        let a = parts.next().unwrap_or("");
        let b = parts.next().unwrap_or("");
        match what {
            "switch" => {
                if let Ok(n) = a.parse() {
                    self.switch_space(n)
                }
            }
            "add" => {
                let n = self.huginn.wm.spaces.len();
                self.huginn.wm.spaces.push(format!("Space {}", n + 1));
            }
            "rename" => {
                if let Ok(n) = a.parse::<usize>()
                    && n < self.huginn.wm.spaces.len()
                    && !b.trim().is_empty()
                {
                    self.huginn.wm.spaces[n] = b.trim().chars().take(40).collect();
                }
            }
            "remove" => {
                if let Ok(n) = a.parse::<usize>() {
                    self.remove_space(n);
                }
            }
            "move" => {
                if let (Ok(id), Ok(n)) = (a.parse::<u64>(), b.parse::<usize>())
                    && n < self.huginn.wm.spaces.len()
                    && let Some(w) = self.any_window_by_id(id)
                {
                    Self::set_window_space(&w, n);
                    if n != self.huginn.wm.current
                        && let Some(loc) = self.space.element_location(&w)
                    {
                        self.space.unmap_elem(&w);
                        self.huginn.wm.away.push((w, loc));
                        self.focus_after_close();
                    }
                    if self.huginn.wm.overview.is_some() {
                        self.overview_relayout();
                    }
                }
            }
            "reorder" => {
                if let (Ok(from), Ok(to)) = (a.parse::<usize>(), b.parse::<usize>()) {
                    self.reorder_space(from, to);
                }
            }
            _ => {}
        }
        self.report_windows_now();
    }

    fn remove_space(&mut self, n: usize) {
        let len = self.huginn.wm.spaces.len();
        if len <= 1 || n >= len {
            return;
        }
        let next_door = if n == 0 { 1 } else { n - 1 };
        // its windows move next door; everything after it moves down one
        let shift = |s: usize| if s == n { if next_door > n { next_door - 1 } else { next_door } } else if s > n { s - 1 } else { s };
        for w in self.all_windows() {
            let s = Self::window_space(&w).unwrap_or(0);
            Self::set_window_space(&w, shift(s));
        }
        self.huginn.wm.spaces.remove(n);
        let cur = self.huginn.wm.current;
        self.huginn.wm.current = usize::MAX; // make switch_space redo the mapping
        self.switch_space(shift(cur).min(self.huginn.wm.spaces.len() - 1));
    }

    fn reorder_space(&mut self, from: usize, to: usize) {
        let len = self.huginn.wm.spaces.len();
        if from >= len || to >= len || from == to {
            return;
        }
        let name = self.huginn.wm.spaces.remove(from);
        self.huginn.wm.spaces.insert(to, name);
        let map = |s: usize| {
            if s == from {
                to
            } else if from < to && s > from && s <= to {
                s - 1
            } else if to < from && s >= to && s < from {
                s + 1
            } else {
                s
            }
        };
        for w in self.all_windows() {
            let s = Self::window_space(&w).unwrap_or(0);
            Self::set_window_space(&w, map(s));
        }
        self.huginn.wm.current = map(self.huginn.wm.current);
    }

    pub fn all_windows(&self) -> Vec<WindowElement> {
        let mut all: Vec<WindowElement> = self.space.elements().cloned().collect();
        all.extend(self.huginn.minimised.iter().map(|(w, _)| w.clone()));
        all.extend(self.huginn.wm.away.iter().map(|(w, _)| w.clone()));
        all
    }

    pub fn any_window_by_id(&self, id: u64) -> Option<WindowElement> {
        self.all_windows().into_iter().find(|w| window_id(w) == id)
    }

    /// A window on another space, brought forward (the dock, Alt+Tab): its space comes first.
    pub fn bring_space_of(&mut self, window: &WindowElement) {
        if let Some(n) = Self::window_space(window)
            && n != self.huginn.wm.current
            && self.huginn.wm.away.iter().any(|(w, _)| w == window)
        {
            self.switch_space(n);
        }
    }

    // ------------------------------------------------------------------------------------------- the Overview
    pub fn overview_toggle(&mut self) {
        match &self.huginn.wm.overview {
            Some(o) if o.opening => self.overview_close(None),
            _ => self.overview_open(),
        }
    }

    fn overview_output(&self) -> Option<Output> {
        let pointer = self.pointer.current_location();
        self.space.output_under(pointer).next().or_else(|| self.space.outputs().next()).cloned()
    }

    fn overview_layout(&self, output: &Output) -> Vec<(WindowElement, Rectangle<i32, Logical>)> {
        let Some(geo) = self.space.output_geometry(output) else {
            return vec![];
        };
        let mut wins: Vec<(WindowElement, Rectangle<i32, Logical>)> = self
            .space
            .elements_for_output(output)
            .filter_map(|w| {
                let loc = self.space.element_location(w)?;
                let g = w.geometry();
                Some((w.clone(), Rectangle::new(loc + g.loc - geo.loc, g.size)))
            })
            .collect();
        if wins.is_empty() {
            return vec![];
        }
        // keep a sense of where they were: top to bottom, then left to right
        wins.sort_by_key(|(_, r)| (r.loc.y + r.size.h / 2, r.loc.x));
        let area = Rectangle::<i32, Logical>::new((48, STRIP + 12).into(), (geo.size.w - 96, geo.size.h - STRIP - 12 - 110).into());
        let n = wins.len();
        let mut best = (0.0, 1usize);
        for rows in 1..=n {
            let cols = n.div_ceil(rows);
            let cw = area.size.w as f64 / cols as f64;
            let ch = area.size.h as f64 / rows as f64;
            let total: f64 = wins
                .iter()
                .map(|(_, r)| {
                    let s = ((cw - 32.0) / r.size.w as f64).min((ch - CHIP as f64 - 24.0) / r.size.h as f64).min(1.0);
                    s * s * (r.size.w * r.size.h) as f64
                })
                .sum();
            if total > best.0 {
                best = (total, rows);
            }
        }
        let rows = best.1;
        let cols = n.div_ceil(rows);
        let cw = area.size.w as f64 / cols as f64;
        let ch = area.size.h as f64 / rows as f64;
        let mut out = Vec::new();
        for (i, (w, r)) in wins.into_iter().enumerate() {
            let row = i / cols;
            let in_row = if row == rows - 1 { n - row * cols } else { cols };
            let col = i % cols;
            let s = ((cw - 32.0) / r.size.w as f64).min((ch - CHIP as f64 - 24.0) / r.size.h as f64).min(1.0);
            let (ww, hh) = ((r.size.w as f64 * s) as i32, (r.size.h as f64 * s) as i32);
            let row_left = area.loc.x as f64 + (area.size.w as f64 - in_row as f64 * cw) / 2.0;
            let x = row_left + col as f64 * cw + (cw - ww as f64) / 2.0;
            let y = area.loc.y as f64 + row as f64 * ch + (ch - CHIP as f64 - hh as f64) / 2.0;
            out.push((w, Rectangle::new((x as i32, y as i32).into(), (ww, hh).into())));
        }
        out
    }

    pub fn overview_open(&mut self) {
        let Some(output) = self.overview_output() else {
            return;
        };
        let slots = self.overview_layout(&output);
        let start = match &self.huginn.wm.overview {
            // coming back while it was closing: carry on from where it is
            Some(o) if !o.opening => Instant::now() - Duration::from_secs_f64((1.0 - o.progress()) * OVERVIEW_MS / 1000.0 * 0.6),
            _ => Instant::now(),
        };
        self.huginn.wm.overview = Some(Overview { start, opening: true, slots, output, dimmed: vec![] });
        self.overview_report();
    }

    fn overview_relayout(&mut self) {
        let Some(output) = self.huginn.wm.overview.as_ref().map(|o| o.output.clone()) else {
            return;
        };
        let slots = self.overview_layout(&output);
        if let Some(o) = self.huginn.wm.overview.as_mut() {
            o.slots = slots;
        }
        self.overview_report();
    }

    /// Back to the desktop: everything glides home (the picked window comes to the front first).
    pub fn overview_close(&mut self, pick: Option<WindowElement>) {
        if let Some(w) = pick {
            self.activate_window(&w);
        }
        if let Some(o) = self.huginn.wm.overview.as_mut() {
            if o.opening {
                let p = o.progress();
                o.opening = false;
                o.start = Instant::now() - Duration::from_secs_f64((1.0 - p) * OVERVIEW_MS / 1000.0);
            }
        }
        self.say(Outgoing::Overview(r#"{"open":false}"#.into()));
    }

    fn overview_report(&self) {
        let Some(o) = &self.huginn.wm.overview else {
            return;
        };
        let rows: Vec<serde_json::Value> = o
            .slots
            .iter()
            .map(|(w, r)| {
                let (title, app) = Self::window_names(w);
                serde_json::json!({"id": window_id(w).to_string(), "app": app, "title": title, "x": r.loc.x, "y": r.loc.y, "w": r.size.w, "h": r.size.h})
            })
            .collect();
        self.say(Outgoing::Overview(
            serde_json::json!({"open": true, "windows": rows, "current": self.huginn.wm.current, "spaces": self.huginn.wm.spaces}).to_string(),
        ));
    }

    /// From the shell's Overview: "close", "toggle", "open", "activate:ID", "dim:ID,ID…".
    pub fn overview_do(&mut self, action: &str) {
        let (what, arg) = action.split_once(':').unwrap_or((action, ""));
        match what {
            "close" => self.overview_close(None),
            "open" => self.overview_open(),
            "toggle" => self.overview_toggle(),
            "activate" => {
                let w = arg.parse::<u64>().ok().and_then(|id| self.any_window_by_id(id));
                if let Some(w) = &w {
                    self.bring_space_of(w);
                }
                self.overview_close(w);
            }
            "dim" => {
                if let Some(o) = self.huginn.wm.overview.as_mut() {
                    o.dimmed = arg.split(',').filter_map(|s| s.parse().ok()).collect();
                }
            }
            _ => {}
        }
    }

    // ------------------------------------------------------------------------------------------- snapping
    fn work_area(&self, output: &Output) -> Rectangle<i32, Logical> {
        let geo = self.space.output_geometry(output).unwrap_or_default();
        let zone = layer_map_for_output(output).non_exclusive_zone();
        Rectangle::new(geo.loc + zone.loc, zone.size)
    }

    fn output_of(&self, window: &WindowElement) -> Option<Output> {
        self.space.outputs_for_element(window).first().cloned().or_else(|| self.overview_output())
    }

    pub fn snap_rect(&self, output: &Output, snap: Snap) -> Rectangle<i32, Logical> {
        let a = self.work_area(output);
        let g = if self.huginn.wm.gaps { GAP } else { 0 };
        let (x0, y0, w, h) = (a.loc.x + g, a.loc.y + g, a.size.w - 2 * g, a.size.h - 2 * g);
        let half = (w - g) / 2;
        let third = (w - 2 * g) / 3;
        let (x, y, ww, hh) = match snap {
            Snap::Max => (x0, y0, w, h),
            Snap::Left => (x0, y0, half, h),
            Snap::Right => (x0 + w - half, y0, half, h),
            Snap::TopLeft => (x0, y0, half, (h - g) / 2),
            Snap::TopRight => (x0 + w - half, y0, half, (h - g) / 2),
            Snap::BottomLeft => (x0, y0 + h - (h - g) / 2, half, (h - g) / 2),
            Snap::BottomRight => (x0 + w - half, y0 + h - (h - g) / 2, half, (h - g) / 2),
            Snap::LeftThird => (x0, y0, third, h),
            Snap::RightThird => (x0 + w - third, y0, third, h),
            Snap::LeftTwoThirds => (x0, y0, w - third - g, h),
            Snap::RightTwoThirds => (x0 + third + g, y0, w - third - g, h),
        };
        Rectangle::new((x, y).into(), (ww, hh).into())
    }

    /// While a window is dragged: is the pointer at an edge or a corner? The shell shows where it'll land.
    pub fn snap_hover(&mut self, pos: Point<f64, Logical>) {
        let Some(output) = self.space.output_under(pos).next().cloned() else {
            return;
        };
        let geo = self.space.output_geometry(&output).unwrap_or_default();
        let a = self.work_area(&output);
        let (x, y) = (pos.x as i32, pos.y as i32);
        let left = x <= geo.loc.x + 4;
        let right = x >= geo.loc.x + geo.size.w - 5;
        let top = y <= a.loc.y + 4;
        let bottom = y >= a.loc.y + a.size.h - 5;
        let near_top = y <= a.loc.y + 90;
        let near_bottom = y >= a.loc.y + a.size.h - 90;
        let snap = if left && near_top {
            Some(Snap::TopLeft)
        } else if left && near_bottom {
            Some(Snap::BottomLeft)
        } else if right && near_top {
            Some(Snap::TopRight)
        } else if right && near_bottom {
            Some(Snap::BottomRight)
        } else if left {
            Some(Snap::Left)
        } else if right {
            Some(Snap::Right)
        } else if top {
            Some(Snap::Max)
        } else {
            let _ = bottom;
            None
        };
        if snap != self.huginn.wm.snap {
            self.huginn.wm.snap = snap;
            let msg = match snap {
                Some(s) => {
                    let r = self.snap_rect(&output, s);
                    let edge = if left { "left" } else if right { "right" } else { "top" };
                    serde_json::json!({"x": r.loc.x - geo.loc.x, "y": r.loc.y - geo.loc.y, "w": r.size.w, "h": r.size.h, "edge": edge, "snap": s.name()}).to_string()
                }
                None => String::new(),
            };
            self.say(Outgoing::SnapPreview(msg));
        }
    }

    /// The drag ended: snap it where it was shown.
    pub fn snap_drop(&mut self, window: &WindowElement) {
        let snap = self.huginn.wm.snap.take();
        self.say(Outgoing::SnapPreview(String::new()));
        if let Some(snap) = snap {
            self.snap_window(window, snap, true);
        }
    }

    /// A window starts being dragged: if it was snapped, it gets its own size back.
    pub fn unsnap_for_drag(&mut self, window: &WindowElement) {
        let id = window_id(window);
        if self.huginn.wm.snapped.remove(&id).is_some()
            && let Some(size) = window.0.user_data().get::<Unsnapped>().and_then(|u| u.0.take())
        {
            self.configure_size(window, size, false);
        }
    }

    fn configure_size(&mut self, window: &WindowElement, size: Size<i32, Logical>, tiled: bool) {
        if let Some(t) = window.0.toplevel() {
            t.with_pending_state(|s| {
                s.size = Some(size);
                s.states.unset(xdg_toplevel::State::Maximized);
                for st in [xdg_toplevel::State::TiledLeft, xdg_toplevel::State::TiledRight, xdg_toplevel::State::TiledTop, xdg_toplevel::State::TiledBottom] {
                    if tiled {
                        s.states.set(st);
                    } else {
                        s.states.unset(st);
                    }
                }
            });
            if t.is_initial_configure_sent() {
                t.send_configure();
            }
        }
        #[cfg(feature = "xwayland")]
        if let Some(x) = window.0.x11_surface() {
            let loc = x.geometry().loc;
            let _ = x.configure(Rectangle::new(loc, size));
        }
    }

    pub fn snap_window(&mut self, window: &WindowElement, snap: Snap, offer_other_half: bool) {
        let Some(output) = self.output_of(window) else {
            return;
        };
        let rect = self.snap_rect(&output, snap);
        let id = window_id(window);
        if !self.huginn.wm.snapped.contains_key(&id) {
            let size = window.geometry().size;
            window.0.user_data().get_or_insert(|| Unsnapped(Cell::new(None))).0.set(Some(size));
        }
        self.huginn.wm.snapped.insert(id, snap);
        if snap == Snap::Max {
            if let Some(t) = window.0.toplevel().cloned() {
                smithay::wayland::shell::xdg::XdgShellHandler::maximize_request(self, t);
                self.activate_window(window);
                return;
            }
        }
        self.configure_size(window, rect.size, true);
        let offset = window.geometry().loc;
        self.space.map_element(window.clone(), rect.loc - offset, true);
        #[cfg(feature = "xwayland")]
        if let Some(x) = window.0.x11_surface() {
            let _ = x.configure(rect);
        }
        self.activate_window(window);
        // the other half: if other windows are about, the shell offers them for it
        if offer_other_half
            && let Some(other) = snap.other()
            && !self.huginn.wm.snapped.iter().any(|(oid, s)| *oid != id && *s == other && self.space.elements().any(|w| window_id(w) == *oid))
        {
            let geo = self.space.output_geometry(&output).unwrap_or_default();
            let r = self.snap_rect(&output, other);
            let candidates: Vec<String> = self
                .space
                .elements()
                .rev()
                .chain(self.huginn.minimised.iter().map(|(w, _)| w))
                .filter(|w| window_id(w) != id && Self::window_space(w).unwrap_or(0) == self.huginn.wm.current)
                .map(|w| window_id(w).to_string())
                .collect();
            if !candidates.is_empty() {
                self.say(Outgoing::SnapAssist(
                    serde_json::json!({"x": r.loc.x - geo.loc.x, "y": r.loc.y - geo.loc.y, "w": r.size.w, "h": r.size.h, "snap": other.name(), "windows": candidates}).to_string(),
                ));
            }
        }
        self.report_windows_now();
    }

    /// Super+←/→/↑/↓: through the sizes (half, a third, two-thirds), full, and back (then hidden).
    pub fn snap_step(&mut self, dir: &str) {
        let Some(window) = self.focused_window() else {
            return;
        };
        let now = self.huginn.wm.snapped.get(&window_id(&window)).copied();
        let next = match (dir, now) {
            ("left", Some(Snap::Left)) => Some(Snap::LeftThird),
            ("left", Some(Snap::LeftThird)) => Some(Snap::LeftTwoThirds),
            ("left", Some(Snap::Right | Snap::RightThird | Snap::RightTwoThirds)) => None,
            ("left", _) => Some(Snap::Left),
            ("right", Some(Snap::Right)) => Some(Snap::RightThird),
            ("right", Some(Snap::RightThird)) => Some(Snap::RightTwoThirds),
            ("right", Some(Snap::Left | Snap::LeftThird | Snap::LeftTwoThirds)) => None,
            ("right", _) => Some(Snap::Right),
            ("up", _) => Some(Snap::Max),
            ("down", Some(_)) => None,
            ("down", None) => {
                self.minimise_window(&window);
                return;
            }
            _ => return,
        };
        match next {
            Some(s) => self.snap_window(&window, s, matches!(s, Snap::Left | Snap::Right)),   // a half: offer the other half (Snap Assist)
            None => {
                // back to its own size, in the middle
                let id = window_id(&window);
                self.huginn.wm.snapped.remove(&id);
                if let Some(t) = window.0.toplevel().cloned()
                    && t.with_committed_state(|s| s.is_some_and(|s| s.states.contains(xdg_toplevel::State::Maximized)))
                {
                    smithay::wayland::shell::xdg::XdgShellHandler::unmaximize_request(self, t);
                }
                if let Some(size) = window.0.user_data().get::<Unsnapped>().and_then(|u| u.0.take()) {
                    self.configure_size(&window, size, false);
                    if let Some(output) = self.output_of(&window) {
                        let a = self.work_area(&output);
                        let loc = Point::from((a.loc.x + (a.size.w - size.w).max(0) / 2, a.loc.y + (a.size.h - size.h).max(0) / 2));
                        self.space.map_element(window.clone(), loc - window.geometry().loc, true);
                    }
                }
                self.report_windows_now();
            }
        }
    }

    /// Windows snapped side by side come forward together.
    pub fn partner_of(&self, window: &WindowElement) -> Option<WindowElement> {
        let id = window_id(window);
        let mine = *self.huginn.wm.snapped.get(&id)?;
        let other = mine.other()?;
        let (oid, _) = self.huginn.wm.snapped.iter().find(|(oid, s)| **oid != id && **s == other)?;
        self.space.elements().find(|w| window_id(w) == *oid).cloned()
    }

    // ------------------------------------------------------------------------------------------- hiding into the dock
    /// The shell's dock: where each app's tile is, how windows hide, the realm's light, the gaps.
    /// {"tiles": {"huginn-writer": [x, y, w, h], …}, "style": "drop", "glow": "#3DD6B5", "gaps": true}
    pub fn dock_layout(&mut self, json: &str) {
        let Ok(v) = serde_json::from_str::<serde_json::Value>(json) else {
            return;
        };
        if let Some(tiles) = v.get("tiles").and_then(|t| t.as_object()) {
            self.huginn.wm.tiles = tiles
                .iter()
                .filter_map(|(k, r)| {
                    let a = r.as_array()?;
                    let n = |i: usize| a.get(i).and_then(|x| x.as_f64()).unwrap_or(0.0) as i32;
                    Some((k.to_lowercase(), Rectangle::new((n(0), n(1)).into(), (n(2), n(3)).into())))
                })
                .collect();
        }
        if let Some(s) = v.get("style").and_then(|s| s.as_str()) {
            self.huginn.wm.hide_style = s.to_string();
        }
        if let Some(g) = v.get("glow").and_then(|s| s.as_str()) {
            let h = g.trim_start_matches('#');
            if h.len() == 6
                && let Ok(n) = u32::from_str_radix(h, 16)
            {
                self.huginn.wm.glow = [((n >> 16) & 255) as f32 / 255.0, ((n >> 8) & 255) as f32 / 255.0, (n & 255) as f32 / 255.0, 1.0];
            }
        }
        if let Some(g) = v.get("gaps").and_then(|s| s.as_bool()) {
            self.huginn.wm.gaps = g;
        }
    }

    fn tile_for(&self, window: &WindowElement, output: &Output) -> Rectangle<f64, Logical> {
        let (_, app) = Self::window_names(window);
        let app = app.to_lowercase();
        let app = app.trim_end_matches(".desktop");
        let geo = self.space.output_geometry(output).unwrap_or_default();
        let r = self
            .huginn
            .wm
            .tiles
            .get(app)
            .copied()
            .unwrap_or_else(|| Rectangle::new((geo.size.w / 2 - 22, geo.size.h - 56).into(), (44, 44).into()));
        Rectangle::new((r.loc.x as f64, r.loc.y as f64).into(), (r.size.w as f64, r.size.h as f64).into())
    }

    /// A window hides into its tile (`back`: it comes back out of it). `from` is its rect on the screen.
    pub fn animate_hide(&mut self, window: &WindowElement, rect: Rectangle<i32, Logical>, back: bool) {
        let Some(output) = self.space.output_under(rect.loc.to_f64()).next().cloned().or_else(|| self.overview_output()) else {
            return;
        };
        if self.huginn.wm.hide_style == "none" {
            return;
        }
        let geo = self.space.output_geometry(&output).unwrap_or_default();
        let from = Rectangle::new(((rect.loc.x - geo.loc.x) as f64, (rect.loc.y - geo.loc.y) as f64).into(), (rect.size.w as f64, rect.size.h as f64).into());
        let to = self.tile_for(window, &output);
        self.huginn.wm.hiding.retain(|h| h.window != *window);
        self.huginn.wm.hiding.push(Hiding { window: window.clone(), from, to, start: Instant::now(), back, style: self.huginn.wm.hide_style.clone() });
    }

    // ------------------------------------------------------------------------------------------- what to draw
    pub fn scene_view(&mut self, output: &Output) -> SceneView {
        let mut view = SceneView::default();
        // the Overview
        let done = match &self.huginn.wm.overview {
            Some(o) if &o.output == output => {
                let p = o.progress();
                view.dim = (0.42 * p) as f32;
                let geo = self.space.output_geometry(output).unwrap_or_default();
                for (w, to) in &o.slots {
                    let Some(loc) = self.space.element_location(w) else {
                        continue;
                    };
                    let g = w.geometry();
                    let from = Rectangle::<f64, Logical>::new(((loc.x + g.loc.x - geo.loc.x) as f64, (loc.y + g.loc.y - geo.loc.y) as f64).into(), g.size.to_f64());
                    let to = Rectangle::<f64, Logical>::new((to.loc.x as f64, to.loc.y as f64).into(), to.size.to_f64());
                    let r = lerp_rect(from, to, p);
                    let s = r.size.w / from.size.w.max(1.0);
                    let alpha = if o.dimmed.contains(&window_id(w)) { 1.0 - 0.65 * p as f32 } else { 1.0 };
                    view.moved.push((w.clone(), r, s, s, alpha));
                }
                !o.opening && o.settled()
            }
            _ => false,
        };
        if done {
            self.huginn.wm.overview = None;
        }
        // windows hiding into the dock, or coming back out
        let glow = self.huginn.wm.glow;
        self.huginn.wm.hiding.retain(|h| h.start.elapsed().as_secs_f64() * 1000.0 < HIDE_MS && h.window.alive());
        for h in &self.huginn.wm.hiding {
            if !self.space.outputs_for_element(&h.window).is_empty() && !h.back {
                continue; // it came back before it was all the way in
            }
            let t = (h.start.elapsed().as_secs_f64() * 1000.0 / HIDE_MS).min(1.0);
            let t = if h.back { 1.0 - t } else { t };
            let (f, to) = (h.from, h.to);
            let cx = to.loc.x + to.size.w / 2.0;
            let line = 6.0;
            let (rect, light) = match h.style.as_str() {
                // a spark that arcs down into the tile
                "comet" => {
                    let e = t * t;
                    let size = lerp(f.size.w.min(f.size.h), 10.0, e.sqrt().min(1.0));
                    let x = lerp(f.loc.x + f.size.w / 2.0, cx, e);
                    let y = lerp(f.loc.y + f.size.h / 2.0, to.loc.y + to.size.h / 2.0, e) - (1.0 - (2.0 * t - 1.0).powi(2)) * 80.0;
                    (Rectangle::new((x - size / 2.0, y - size / 2.0).into(), (size, size * f.size.h / f.size.w.max(1.0)).into()), (t * 1.6).min(1.0))
                }
                // fills with light, folds to a line and streaks down into the tile
                "line" => {
                    let fold = (t / 0.35).min(1.0);
                    let go = ((t - 0.35) / 0.65).clamp(0.0, 1.0);
                    let h_ = lerp(f.size.h, line, fold);
                    let w_ = lerp(f.size.w, to.size.w * 0.8, go);
                    let x = lerp(f.loc.x, cx - w_ / 2.0, go);
                    let y = lerp(f.loc.y + (f.size.h - h_) / 2.0, to.loc.y + to.size.h / 2.0, go * go);
                    (Rectangle::new((x, y).into(), (w_, h_).into()), fold)
                }
                // drop and ring: folds to a line, narrows to the tile's width and drops straight in
                _ => {
                    let fold = (t / 0.38).min(1.0);
                    let narrow = ((t - 0.38) / 0.27).clamp(0.0, 1.0);
                    let drop = ((t - 0.65) / 0.35).clamp(0.0, 1.0);
                    let h_ = lerp(f.size.h, line, fold * (2.0 - fold));
                    let w_ = lerp(f.size.w, to.size.w * 0.8, narrow * (2.0 - narrow));
                    let x = lerp(f.loc.x + f.size.w / 2.0, cx, narrow) - w_ / 2.0;
                    let y = lerp(f.loc.y + (f.size.h - h_) / 2.0, to.loc.y + to.size.h / 2.0, drop * drop);
                    (Rectangle::new((x, y).into(), (w_, h_).into()), fold)
                }
            };
            let sx = rect.size.w / f.size.w.max(1.0);
            let sy = rect.size.h / f.size.h.max(1.0);
            let alpha = (1.0 - ((t - 0.85) / 0.15).clamp(0.0, 1.0)) as f32;
            view.moved.push((h.window.clone(), rect, sx, sy, alpha * (1.0 - light as f32 * 0.6)));
            view.light.push((rect, [glow[0], glow[1], glow[2], (light as f32 * 0.85) * alpha]));
        }
        view
    }

    /// Something is moving (the Overview, a window hiding): keep drawing every frame.
    pub fn animating(&self) -> bool {
        self.huginn.wm.overview.as_ref().is_some_and(|o| !o.settled() || !o.opening) || !self.huginn.wm.hiding.is_empty()
    }

    // ------------------------------------------------------------------------------------------- Alt+Tab, shown
    pub fn switcher_report(&mut self) {
        let msg = match &self.huginn.switching {
            Some((order, at)) => {
                let rows: Vec<serde_json::Value> = order
                    .iter()
                    .map(|w| {
                        let (title, app) = Self::window_names(w);
                        serde_json::json!({"id": window_id(w).to_string(), "app": app, "title": title})
                    })
                    .collect();
                self.huginn.wm.switcher_shown = true;
                serde_json::json!({"windows": rows, "at": at}).to_string()
            }
            None => {
                if !self.huginn.wm.switcher_shown {
                    return;
                }
                self.huginn.wm.switcher_shown = false;
                String::new()
            }
        };
        self.say(Outgoing::Switcher(msg));
    }
}
