//! Accessibility on Huginn's own compositor, from the settings KWin and KAccess read (Settings › Accessibility
//! writes them): colour filters (for colour blindness, through each screen's colour matrix) and inverted colours
//! (through its gamma), sticky, bounce and slow keys, mouse keys (the number pad moves the pointer), zoom
//! (Super+= and Super+-, following the pointer) and Reduce Motion (kdeglobals' AnimationDurationFactor: no sliding
//! windows or Overview). Read at start and again on `ReloadAccess`.

use std::{
    sync::atomic::{AtomicBool, Ordering},
    time::{Duration, Instant},
};

use smithay::input::keyboard::Keycode;

use crate::input::kconfig;

/// Reduce Motion: windows and the Overview appear without moving.
pub static STILL: AtomicBool = AtomicBool::new(false);

pub fn still() -> bool {
    STILL.load(Ordering::Relaxed)
}

#[derive(Default, Clone, PartialEq)]
pub struct Filter {
    /// a colour matrix (row by row, applied to R, G, B), for colour blindness
    pub matrix: Option<[f64; 9]>,
    pub invert: bool,
}

#[derive(Default)]
pub struct Keys {
    pub sticky: bool,
    pub bounce: Option<Duration>,
    /// slow keys: a key counts once it's been held this long
    pub slow: Option<Duration>,
    /// a key being held for slow keys, and keys it let through (their release goes too)
    slow_waiting: Option<Keycode>,
    slow_down: Vec<Keycode>,
    /// mouse keys: the number pad moves the pointer
    pub mouse: bool,
    /// the number pad's arrows held down, for mouse keys
    pub mouse_held: Vec<Keycode>,
    /// a modifier pressed on its own, so far
    alone: Option<Keycode>,
    /// modifiers held down for the next key (their release withheld)
    latched: Vec<Keycode>,
    /// the last key let go, and when (bounce keys)
    last_up: Option<(Keycode, Instant)>,
    /// a press bounce keys dropped: its release goes too
    dropped: Option<Keycode>,
}

/// What to do with a key, after sticky and bounce keys.
pub enum Key {
    /// as it is
    Pass,
    /// not at all
    Drop,
    /// as it is, then let go of these modifiers
    PassThenRelease(Vec<Keycode>),
    /// not yet: once it's been held this long (slow keys)
    Hold(Duration),
    /// the pointer's (mouse keys): pressed or let go
    Mouse(bool),
}

/// What the settings say, all together.
#[derive(Default)]
pub struct Settings {
    pub filter: Filter,
    pub sticky: bool,
    pub bounce: Option<Duration>,
    pub slow: Option<Duration>,
    pub mouse: bool,
    pub still: bool,
    /// zoom: whether Super+= zooms, and by how much each time
    pub zoom: bool,
    pub zoom_step: f64,
}

fn yes(file: &str, group: &str, key: &str) -> bool {
    kconfig(file, group, key).is_some_and(|v| v == "true")
}

/// The settings as they are now.
pub fn read() -> Settings {
    let invert = yes("kaccessrc", "Huginn", "Invert");
    let matrix = if yes("kwinrc", "Plugins", "colorblindnesscorrectionEnabled") && !invert {
        let mode = kconfig("kwinrc", "Effect-colorblindnesscorrection", "Mode").and_then(|m| m.parse().ok()).unwrap_or(0);
        let strength = kconfig("kwinrc", "Effect-colorblindnesscorrection", "Intensity")
            .and_then(|m| m.parse().ok())
            .unwrap_or(1.0);
        Some(correction(mode, strength))
    } else {
        None
    };
    let bounce = yes("kaccessrc", "Keyboard", "BounceKeys").then(|| {
        Duration::from_millis(kconfig("kaccessrc", "Keyboard", "BounceKeysDelay").and_then(|v| v.parse().ok()).unwrap_or(500))
    });
    let still = kconfig("kdeglobals", "KDE", "AnimationDurationFactor")
        .and_then(|v| v.parse::<f64>().ok())
        .is_some_and(|f| f <= 0.01);
    let ms = |key: &str, default: u64| Duration::from_millis(kconfig("kaccessrc", "Keyboard", key).and_then(|v| v.parse().ok()).unwrap_or(default));
    Settings {
        filter: Filter { matrix, invert },
        sticky: yes("kaccessrc", "Keyboard", "StickyKeys"),
        bounce,
        slow: yes("kaccessrc", "Keyboard", "SlowKeys").then(|| ms("SlowKeysDelay", 300)),
        mouse: yes("kaccessrc", "Mouse", "MouseKeys"),
        still,
        zoom: kconfig("kwinrc", "Plugins", "zoomEnabled").is_none_or(|v| v == "true"),
        zoom_step: kconfig("kwinrc", "Effect-zoom", "ZoomFactor").and_then(|v| v.parse().ok()).unwrap_or(1.2f64).clamp(1.05, 4.0),
    }
}

/// The number pad, for mouse keys: which way each key moves the pointer (5 clicks).
pub fn pad(code: Keycode) -> Option<(i32, i32)> {
    Some(match code.raw() {
        79 => (-1, -1),
        80 => (0, -1),
        81 => (1, -1),
        83 => (-1, 0),
        84 => (0, 0),
        85 => (1, 0),
        87 => (-1, 1),
        88 => (0, 1),
        89 => (1, 1),
        _ => return None,
    })
}

fn mul(a: &[f64; 9], b: &[f64; 9]) -> [f64; 9] {
    let mut m = [0.0; 9];
    for r in 0..3 {
        for c in 0..3 {
            m[r * 3 + c] = (0..3).map(|k| a[r * 3 + k] * b[k * 3 + c]).sum();
        }
    }
    m
}

/// Daltonisation (as KWin's colour blindness correction): what someone with protanopia (0), deuteranopia (1) or
/// tritanopia (2) can't tell apart is moved to colours they can, by `strength` (0 to 1). One matrix, all linear.
pub fn correction(mode: u32, strength: f64) -> [f64; 9] {
    const RGB_LMS: [f64; 9] = [17.8824, 43.5161, 4.11935, 3.45565, 27.1554, 3.86714, 0.0299566, 0.184309, 1.46709];
    const LMS_RGB: [f64; 9] = [
        0.0809444479, -0.130504409, 0.116721066, -0.0102485335, 0.0540193266, -0.113614708, -0.000365296938,
        -0.00412161469, 0.693511405,
    ];
    let blind: [f64; 9] = match mode {
        0 => [0.0, 2.02344, -2.52581, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0],
        1 => [1.0, 0.0, 0.0, 0.494207, 0.0, 1.24827, 0.0, 0.0, 1.0],
        _ => [1.0, 0.0, 0.0, 0.0, 1.0, 0.0, -0.395913, 0.801109, 0.0],
    };
    let seen = mul(&LMS_RGB, &mul(&blind, &RGB_LMS));
    const ID: [f64; 9] = [1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0];
    let missed: [f64; 9] = std::array::from_fn(|i| ID[i] - seen[i]);
    const SHIFT: [f64; 9] = [0.0, 0.0, 0.0, 0.7, 1.0, 0.0, 0.7, 0.0, 1.0];
    let shift = mul(&SHIFT, &missed);
    std::array::from_fn(|i| ID[i] + strength.clamp(0.0, 1.0) * shift[i])
}

const MODIFIERS: [u32; 8] = [50, 62, 37, 105, 64, 108, 133, 134]; // Shift, Control, Alt, Super, left and right (xkb)

impl Keys {
    pub fn set(&mut self, sticky: bool, bounce: Option<Duration>, slow: Option<Duration>, mouse: bool) {
        self.sticky = sticky;
        self.bounce = bounce;
        self.slow = slow;
        self.mouse = mouse;
        if !mouse {
            self.mouse_held.clear();
        }
        if !sticky {
            self.latched.clear();
        }
    }

    /// Modifiers still held for sticky keys, to let go of when sticky keys are turned off.
    pub fn take_latched(&mut self) -> Vec<Keycode> {
        std::mem::take(&mut self.latched)
    }

    /// A key slow keys held long enough: let it through (false: it was let go first).
    pub fn slow_ready(&mut self, code: Keycode) -> bool {
        if self.slow_waiting == Some(code) {
            self.slow_waiting = None;
            self.slow_down.push(code);
            true
        } else {
            false
        }
    }

    pub fn key(&mut self, code: Keycode, pressed: bool) -> Key {
        if self.mouse && pad(code).is_some() {
            if pressed {
                if !self.mouse_held.contains(&code) {
                    self.mouse_held.push(code);
                }
            } else {
                self.mouse_held.retain(|c| *c != code);
            }
            return Key::Mouse(pressed);
        }
        if let Some(wait) = self.slow {
            if pressed {
                self.slow_waiting = Some(code);
                return Key::Hold(wait);
            }
            if self.slow_waiting == Some(code) {
                self.slow_waiting = None;
                return Key::Drop;
            }
            self.slow_down.retain(|c| *c != code);
        }
        if let Some(gap) = self.bounce {
            if pressed {
                if let Some((last, at)) = self.last_up
                    && last == code
                    && at.elapsed() < gap
                {
                    self.dropped = Some(code);
                    return Key::Drop;
                }
            } else {
                if self.dropped == Some(code) {
                    self.dropped = None;
                    return Key::Drop;
                }
                self.last_up = Some((code, Instant::now()));
            }
        }
        if !self.sticky {
            return Key::Pass;
        }
        let modifier = MODIFIERS.contains(&code.raw());
        match (modifier, pressed) {
            (true, true) => {
                // pressed again while latched: it stays down until let go (a second press is an ordinary hold)
                self.latched.retain(|c| *c != code);
                self.alone = Some(code);
                Key::Pass
            }
            (true, false) if self.alone == Some(code) => {
                self.alone = None;
                self.latched.push(code);
                Key::Drop
            }
            (true, false) => Key::Pass,
            (false, true) => {
                self.alone = None;
                if self.latched.is_empty() { Key::Pass } else { Key::PassThenRelease(std::mem::take(&mut self.latched)) }
            }
            (false, false) => Key::Pass,
        }
    }
}

impl<B: crate::state::Backend + 'static> crate::state::HuginnState<B> {
    /// Read the accessibility settings again and use them.
    pub fn reload_access(&mut self) {
        let now = read();
        STILL.store(now.still, Ordering::Relaxed);
        if !now.sticky {
            let held = self.huginn.keys.take_latched();
            self.release_keys(held);
        }
        self.huginn.keys.set(now.sticky, now.bounce, now.slow, now.mouse);
        if now.filter != self.huginn.filter {
            self.backend_data.set_filter(&now.filter);
            self.huginn.filter = now.filter.clone();
        }
        if !now.zoom {
            self.huginn.zoom = 1.0;
        }
        self.huginn.access = now;
    }

    /// Super+= (1), Super+- (-1), Super+0 (0): zoom in, out, or back to the whole screen.
    pub fn zoom_by(&mut self, step: i32) {
        if !self.huginn.access.zoom {
            return;
        }
        let k = self.huginn.access.zoom_step;
        let z = self.huginn.zoom.max(1.0);
        self.huginn.zoom = match step {
            0 => 1.0,
            s if s > 0 => (z * k).min(16.0),
            _ => (z / k).max(1.0),
        };
        if self.huginn.zoom < 1.01 {
            self.huginn.zoom = 1.0;
        }
    }

    /// Slow keys: after `wait`, the key counts if it's still held.
    pub fn slow_key_later(&mut self, code: Keycode, wait: Duration) {
        use smithay::reexports::calloop::timer::{TimeoutAction, Timer};
        let _ = self.handle.insert_source(Timer::from_duration(wait), move |_, _, state| {
            if state.huginn.keys.slow_ready(code)
                && let Some(keyboard) = state.seat.get_keyboard()
            {
                let serial = smithay::utils::SERIAL_COUNTER.next_serial();
                let time = smithay::backend::input::InputTime::now();
                keyboard.input::<(), _>(state, code, smithay::backend::input::KeyState::Pressed, serial, time, |_, _, _| {
                    smithay::input::keyboard::FilterResult::Forward
                });
            }
            TimeoutAction::Drop
        });
    }

    /// Mouse keys: 5 clicks; the others move the pointer while they're held, faster the longer.
    pub fn mouse_key(&mut self, code: Keycode, pressed: bool) {
        use smithay::{
            input::pointer::{ButtonEvent, MotionEvent},
            reexports::calloop::timer::{TimeoutAction, Timer},
        };
        if pad(code) == Some((0, 0)) {
            let pointer = self.pointer.clone();
            let serial = smithay::utils::SERIAL_COUNTER.next_serial();
            if pressed {
                let at = pointer.current_location();
                self.update_keyboard_focus(at, serial);
            }
            let state = if pressed { smithay::backend::input::ButtonState::Pressed } else { smithay::backend::input::ButtonState::Released };
            pointer.button(self, &ButtonEvent { button: 0x110, state, serial, time: smithay::backend::input::InputTime::now() });
            pointer.frame(self);
            return;
        }
        if !pressed || self.huginn.keys.mouse_held.len() != 1 {
            return; // already moving
        }
        let start = Instant::now();
        let _ = self.handle.insert_source(Timer::immediate(), move |_, _, state| {
            let (mut dx, mut dy) = (0, 0);
            for c in &state.huginn.keys.mouse_held {
                if let Some((x, y)) = pad(*c) {
                    dx += x;
                    dy += y;
                }
            }
            if state.huginn.keys.mouse_held.is_empty() {
                return TimeoutAction::Drop;
            }
            let speed = 2.0 + 14.0 * (start.elapsed().as_secs_f64() / 1.2).min(1.0);
            let to = state.pointer.current_location()
                + smithay::utils::Point::<f64, smithay::utils::Logical>::from((dx.signum() as f64 * speed, dy.signum() as f64 * speed));
            // kept on the screens
            let here = state.pointer.current_location();
            let to = if state.space.outputs().any(|o| state.space.output_geometry(o).is_some_and(|g| g.to_f64().contains(to))) {
                to
            } else {
                here
            };
            let under = state.surface_under(to);
            let pointer = state.pointer.clone();
            let serial = smithay::utils::SERIAL_COUNTER.next_serial();
            pointer.motion(state, under, &MotionEvent { location: to, serial, time: smithay::backend::input::InputTime::now() });
            pointer.frame(state);
            TimeoutAction::ToDuration(Duration::from_millis(16))
        });
    }

    /// Let go of keys the client still thinks are down (sticky keys' modifiers).
    pub fn release_keys(&mut self, keys: Vec<Keycode>) {
        let Some(keyboard) = self.seat.get_keyboard() else { return };
        let time = smithay::backend::input::InputTime::now();
        for code in keys {
            let serial = smithay::utils::SERIAL_COUNTER.next_serial();
            keyboard.input::<(), _>(self, code, smithay::backend::input::KeyState::Released, serial, time, |_, _, _| {
                smithay::input::keyboard::FilterResult::Forward
            });
        }
    }
}
