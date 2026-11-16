//! Accessibility on Huginn's own compositor, from the settings KWin and KAccess read (Settings › Accessibility
//! writes them): colour filters (for colour blindness, through each screen's colour matrix) and inverted colours
//! (through its gamma), sticky keys and bounce keys, and Reduce Motion (kdeglobals' AnimationDurationFactor: no
//! sliding windows or Overview). Read at start and again on `ReloadAccess`.

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
}

fn yes(file: &str, group: &str, key: &str) -> bool {
    kconfig(file, group, key).is_some_and(|v| v == "true")
}

/// The settings as they are now: (filter, sticky keys, bounce keys, still).
pub fn read() -> (Filter, bool, Option<Duration>, bool) {
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
    (Filter { matrix, invert }, yes("kaccessrc", "Keyboard", "StickyKeys"), bounce, still)
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
    pub fn set(&mut self, sticky: bool, bounce: Option<Duration>) {
        self.sticky = sticky;
        self.bounce = bounce;
        if !sticky {
            self.latched.clear();
        }
    }

    /// Modifiers still held for sticky keys, to let go of when sticky keys are turned off.
    pub fn take_latched(&mut self) -> Vec<Keycode> {
        std::mem::take(&mut self.latched)
    }

    pub fn key(&mut self, code: Keycode, pressed: bool) -> Key {
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
        let (filter, sticky, bounce, still) = read();
        STILL.store(still, Ordering::Relaxed);
        if !sticky {
            let held = self.huginn.keys.take_latched();
            self.release_keys(held);
        }
        self.huginn.keys.set(sticky, bounce);
        if filter != self.huginn.filter {
            self.backend_data.set_filter(&filter);
            self.huginn.filter = filter;
        }
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
