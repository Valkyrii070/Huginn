//! Screens: what Settings › Displays shows and changes (resolution, refresh rate, size of things, rotation, where
//! each screen sits), kept per screen in ~/.config/huginn/displays.json and put back when the screen is plugged in
//! again; and night light, a warmer picture through each screen's gamma.
//!
//! On the bus the list is in kscreen-doctor's JSON (`-j`), and a change is one of its arguments without
//! "output.NAME." ("mode.ID", "scale.1.5", "rotation.left", "position.X,Y", "priority.1"), so Settings speaks to
//! KWin and to Huginn's compositor the same way.

use std::path::PathBuf;

use serde_json::{Value, json};
use smithay::{
    output::{Mode, Output, Scale},
    utils::Transform,
};

use crate::state::{Backend, HuginnState};

/// Settings › Displays, "Sharp older apps": X11 apps draw at the screens' scale (Xft.dpi) instead of being stretched.
pub static SHARP_X11: std::sync::atomic::AtomicBool = std::sync::atomic::AtomicBool::new(true);

const ROTATIONS: [(Transform, u32, &str); 4] = [
    (Transform::Normal, 1, "normal"),
    (Transform::_90, 2, "left"),
    (Transform::_180, 4, "inverted"),
    (Transform::_270, 8, "right"),
];

fn file() -> Option<PathBuf> {
    let base = std::env::var_os("XDG_CONFIG_HOME")
        .map(PathBuf::from)
        .or_else(|| std::env::var_os("HOME").map(|h| PathBuf::from(h).join(".config")))?;
    Some(base.join("huginn").join("displays.json"))
}

fn load() -> Value {
    file()
        .and_then(|f| std::fs::read_to_string(f).ok())
        .and_then(|t| serde_json::from_str(&t).ok())
        .unwrap_or_else(|| json!({}))
}

/// Which screen this is, wherever it's plugged in: its make, model and serial number (else its connector).
pub fn key(output: &Output) -> String {
    let p = output.physical_properties();
    if p.serial_number == "Unknown" && p.model == "Unknown" {
        output.name()
    } else {
        format!("{} {} {}", p.make, p.model, p.serial_number)
    }
}

/// HDR on a screen: SDR white's brightness in nits while it's on (look.rs: HdrElement), and the element's id.
pub struct Hdr {
    pub sdr: std::cell::Cell<Option<f64>>,
    pub id: smithay::backend::renderer::element::Id,
}

pub fn hdr_of(output: &Output) -> &Hdr {
    output.user_data().insert_if_missing(|| Hdr { sdr: std::cell::Cell::new(None), id: smithay::backend::renderer::element::Id::new() });
    output.user_data().get::<Hdr>().unwrap()
}

/// SDR white in nits while HDR is on, else None.
pub fn hdr_sdr(output: &Output) -> Option<f64> {
    hdr_of(output).sdr.get()
}

/// The main screen (the top bar and dock's), by its connector name, if one was chosen.
pub fn main_name() -> Option<String> {
    load().get("_main").and_then(|v| v.as_str()).map(String::from)
}

/// What was saved for this screen, if anything.
pub fn saved(output: &Output) -> Option<Value> {
    load().get(key(output)).cloned()
}

/// The saved resolution and refresh rate (mHz), for the backend to pick a mode with.
pub fn saved_mode(output: &Output) -> Option<(i32, i32, i32)> {
    let s = saved(output)?;
    let n = |k: &str| s.get(k).and_then(|v| v.as_i64()).map(|v| v as i32);
    Some((n("w")?, n("h")?, n("mhz").unwrap_or(0)))
}

/// The mode of `modes` closest to `(w, h, mhz)`: the same size, the nearest refresh rate.
pub fn pick(modes: &[Mode], (w, h, mhz): (i32, i32, i32)) -> Option<Mode> {
    modes
        .iter()
        .filter(|m| m.size.w == w && m.size.h == h)
        .min_by_key(|m| (m.refresh - mhz).abs())
        .copied()
}

fn remember(output: &Output) {
    let mut all = load();
    let mode = output.current_mode();
    let loc = output.current_location();
    let rot = ROTATIONS.iter().find(|r| r.0 == output.current_transform()).map_or("normal", |r| r.2);
    all[key(output)] = json!({
        "w": mode.map(|m| m.size.w), "h": mode.map(|m| m.size.h), "mhz": mode.map(|m| m.refresh),
        "scale": output.current_scale().fractional_scale(), "rotation": rot, "x": loc.x, "y": loc.y,
        "hdr": hdr_sdr(output).is_some(), "sdr": hdr_sdr(output).unwrap_or(203.0),
    });
    save(&all);
}

fn save(all: &Value) {
    let Some(path) = file() else { return };
    if let Some(dir) = path.parent() {
        let _ = std::fs::create_dir_all(dir);
    }
    let _ = std::fs::write(path, serde_json::to_string_pretty(all).unwrap_or_default());
}

/// Night light: how much of red, green and blue a colour temperature leaves (6500 K: all of them).
pub fn warmth(kelvin: u32) -> [f64; 3] {
    let at = |t: f64| -> [f64; 3] {
        let t = t / 100.0;
        let g = (0.390_081_578_769 * t.ln() - 0.631_841_443_788).clamp(0.0, 1.0);
        let b = if t <= 19.0 { 0.0 } else { (0.543_206_789_110 * (t - 10.0).ln() - 1.196_254_089_14).clamp(0.0, 1.0) };
        [1.0, g, b]
    };
    let (w, white) = (at(kelvin.clamp(1000, 6500) as f64), at(6500.0));
    [1.0, (w[1] / white[1]).min(1.0), (w[2] / white[2]).min(1.0)]
}

impl<B: Backend + 'static> HuginnState<B> {
    /// XWayland's scale: the largest of the screens' (HUGINN_XWAYLAND_SCALE overrides; 1 with sharp X11 apps off).
    /// X11 apps then draw at the screens' real resolution, told to make things bigger through Xft.dpi, and Smithay
    /// turns their sizes and places into the desktop's. Apps read Xft.dpi when they open.
    pub fn xwayland_rescale(&mut self) {
        #[cfg(feature = "xwayland")]
        {
            use smithay::wayland::compositor::CompositorHandler;
            let Some(client) = self.xwayland_client.clone() else { return };
            let scale = std::env::var("HUGINN_XWAYLAND_SCALE").ok().and_then(|s| s.parse::<f64>().ok()).unwrap_or_else(|| {
                if SHARP_X11.load(std::sync::atomic::Ordering::Relaxed) {
                    self.space.outputs().map(|o| o.current_scale().fractional_scale()).fold(1.0, f64::max)
                } else {
                    1.0
                }
            });
            let state = self.client_compositor_state(&client);
            if (state.client_scale() - scale).abs() < 0.001 {
                return;
            }
            state.set_client_scale(scale);
            // the screens again, at the new scale, for XWayland
            for o in self.space.outputs() {
                o.change_current_state(o.current_mode(), None, None, None);
            }
            if let Some(n) = self.xdisplay {
                let resources = format!("Xft.dpi: {}\nXcursor.size: {}\n", (96.0 * scale).round(), (24.0 * scale).round());
                if let Ok(mut child) = std::process::Command::new("xrdb")
                    .args(["-merge", "-"])
                    .env("DISPLAY", format!(":{n}"))
                    .stdin(std::process::Stdio::piped())
                    .stdout(std::process::Stdio::null())
                    .stderr(std::process::Stdio::null())
                    .spawn()
                {
                    use std::io::Write;
                    if let Some(mut stdin) = child.stdin.take() {
                        let _ = stdin.write_all(resources.as_bytes());
                    }
                    std::thread::spawn(move || {
                        let _ = child.wait();
                    });
                }
            }
        }
    }

    /// A screen just plugged in: put back its saved rotation, size of things and place.
    pub fn restore_display(&mut self, output: &Output) {
        let Some(s) = saved(output) else { return };
        let transform = s
            .get("rotation")
            .and_then(|r| r.as_str())
            .and_then(|r| ROTATIONS.iter().find(|x| x.2 == r))
            .map(|x| x.0);
        let scale = s.get("scale").and_then(|v| v.as_f64()).filter(|v| (0.5..=4.0).contains(v));
        let loc = match (s.get("x").and_then(|v| v.as_i64()), s.get("y").and_then(|v| v.as_i64())) {
            (Some(x), Some(y)) => Some((x as i32, y as i32).into()),
            _ => None,
        };
        output.change_current_state(None, transform, scale.map(Scale::Fractional), loc);
        if let Some(loc) = loc {
            self.space.map_output(output, loc);
        }
        self.xwayland_rescale();
        if s.get("hdr").and_then(|v| v.as_bool()) == Some(true) && self.backend_data.hdr_capable(output) {
            let sdr = s.get("sdr").and_then(|v| v.as_f64()).unwrap_or(203.0).clamp(80.0, 500.0);
            if self.backend_data.set_hdr(output, true).is_ok() {
                hdr_of(output).sdr.set(Some(sdr));
            }
        }
    }

    /// The screens, as `kscreen-doctor -j` lists them (those turned off too).
    pub fn displays_json(&self) -> String {
        let main = main_name().filter(|m| self.space.outputs().any(|o| &o.name() == m));
        let outputs: Vec<Value> = self
            .space
            .outputs()
            .map(|o| (o, true))
            .chain(self.huginn.off_outputs.iter().map(|o| (o, false)))
            .enumerate()
            .map(|(i, (o, on))| {
                let current = o.current_mode();
                let mut modes = o.modes();
                if let Some(c) = current {
                    if !modes.contains(&c) {
                        modes.push(c);
                    }
                }
                let id = |m: &Mode| format!("{}x{}@{}", m.size.w, m.size.h, m.refresh);
                let loc = o.current_location();
                json!({
                    "id": i + 1, "name": o.name(), "connected": true, "enabled": on,
                    "priority": if main.as_ref().map_or(i == 0, |m| *m == o.name()) { 1 } else { 2 },
                    "modes": modes.iter().map(|m| json!({"id": id(m), "size": {"width": m.size.w, "height": m.size.h},
                                                          "refreshRate": m.refresh as f64 / 1000.0})).collect::<Vec<_>>(),
                    "currentModeId": current.map(|m| id(&m)).unwrap_or_default(),
                    "scale": o.current_scale().fractional_scale(),
                    "rotation": ROTATIONS.iter().find(|r| r.0 == o.current_transform()).map_or(1, |r| r.1),
                    "pos": {"x": loc.x, "y": loc.y},
                    "hdr": hdr_sdr(o).is_some(), "sdr-brightness": hdr_sdr(o).unwrap_or(203.0).round() as i64,
                    "hdrCapable": self.backend_data.hdr_capable(o),
                })
            })
            .collect();
        json!({ "outputs": outputs }).to_string()
    }

    /// One change to one screen: "" when done, else why not.
    pub fn configure_display(&mut self, name: &str, change: &str) -> String {
        let (what, value) = change.split_once('.').unwrap_or((change, ""));
        if what == "enable" {
            let Some(i) = self.huginn.off_outputs.iter().position(|o| o.name() == name) else { return String::new() };
            let output = self.huginn.off_outputs.remove(i);
            self.space.map_output(&output, output.current_location());
            self.backend_data.reset_buffers(&output);
            crate::shell::fixup_positions(&mut self.space, self.pointer.current_location());
            return String::new();
        }
        let Some(output) = self.space.outputs().find(|o| o.name() == name).cloned() else {
            return format!("There's no screen called {name}, or it's off.");
        };
        match what {
            "mode" => {
                let mut bits = value.split(['x', '@']).map(|b| b.parse::<i32>().unwrap_or(0));
                let want = (bits.next().unwrap_or(0), bits.next().unwrap_or(0), bits.next().unwrap_or(0));
                let Some(mode) = pick(&output.modes(), want) else {
                    return "That screen can't show that resolution.".into();
                };
                if let Err(why) = self.backend_data.set_mode(&output, mode) {
                    return why;
                }
                output.change_current_state(Some(mode), None, None, None);
            }
            "scale" => match value.parse::<f64>() {
                Ok(scale) if (0.5..=4.0).contains(&scale) => {
                    output.change_current_state(None, None, Some(Scale::Fractional(scale)), None)
                }
                _ => return "That size isn't one a screen can have.".into(),
            },
            // in a window (winit) the picture is already turned over for OpenGL; turning it is for real screens
            "rotation" if output.current_transform() == Transform::Flipped180 => {
                return "Turning the picture needs a real screen.".into();
            }
            "rotation" => match ROTATIONS.iter().find(|r| r.2 == value) {
                Some(r) => output.change_current_state(None, Some(r.0), None, None),
                None => return "That isn't a way a screen can turn.".into(),
            },
            "position" => {
                let mut bits = value.split(',').map(|b| b.parse::<i32>().unwrap_or(0));
                let loc = (bits.next().unwrap_or(0).max(0), bits.next().unwrap_or(0).max(0)).into();
                output.change_current_state(None, None, None, Some(loc));
                self.space.map_output(&output, loc);
            }
            // the main screen: where the top bar and dock are (the shell reads it from displays.json)
            "priority" => {
                let mut all = load();
                all["_main"] = json!(name);
                save(&all);
                return String::new();
            }
            // HDR (kscreen-doctor's "hdr.enable", "hdr.disable", "sdr-brightness.N")
            "hdr" => {
                let on = value == "enable";
                if on && !self.backend_data.hdr_capable(&output) {
                    return "This screen (or its connection) can't show HDR.".into();
                }
                if let Err(why) = self.backend_data.set_hdr(&output, on) {
                    return why;
                }
                let sdr = saved(&output).and_then(|s| s.get("sdr").and_then(|v| v.as_f64())).unwrap_or(203.0);
                hdr_of(&output).sdr.set(on.then_some(sdr));
                self.backend_data.reset_buffers(&output);
                crate::color::screen_changed(&output);
            }
            "sdr-brightness" => match value.parse::<f64>() {
                Ok(nits) if (80.0..=500.0).contains(&nits) => {
                    if hdr_sdr(&output).is_some() {
                        hdr_of(&output).sdr.set(Some(nits));
                        crate::color::screen_changed(&output);
                    }
                    let mut all = load();
                    all[key(&output)]["sdr"] = json!(nits);
                    save(&all);
                    self.backend_data.reset_buffers(&output);
                    return String::new();
                }
                _ => return "That isn't a brightness for SDR white.".into(),
            },
            "disable" => {
                if self.space.outputs().count() <= 1 {
                    return "That's the only screen that's on, so it stays on.".into();
                }
                self.space.unmap_output(&output);
                self.huginn.off_outputs.push(output);
                crate::shell::fixup_positions(&mut self.space, self.pointer.current_location());
                self.refit_windows();
                return String::new();
            }
            _ => return format!("Not something a screen can do: {change}."),
        }
        remember(&output);
        self.xwayland_rescale();
        self.backend_data.reset_buffers(&output);
        crate::shell::fixup_positions(&mut self.space, self.pointer.current_location());
        self.refit_windows();
        String::new()
    }
}

impl<B: Backend + 'static> HuginnState<B> {
    /// After a screen changed size: maximised windows fill it again.
    pub fn refit_windows(&mut self) {
        use smithay::{reexports::wayland_protocols::xdg::shell::server::xdg_toplevel, wayland::shell::xdg::XdgShellHandler};
        let windows: Vec<_> = self.space.elements().cloned().collect();
        for w in windows {
            if let Some(t) = w.0.toplevel() {
                let maxed = t.with_pending_state(|s| s.states.contains(xdg_toplevel::State::Maximized));
                if maxed {
                    self.maximize_request(t.clone());
                }
            } else if let Some(x) = w.0.x11_surface() {
                if x.is_maximized() {
                    let x = x.clone();
                    self.maximize_request_x11(&x);
                }
            }
        }
    }
}
