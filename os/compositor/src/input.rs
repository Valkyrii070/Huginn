//! Keyboard, mouse and touchpad settings: what Settings › Keyboard & Mouse asks for.
//!
//! The keyboard comes from the same files KWin reads (kxkbrc: layouts and options; kcminputrc: key repeat), read
//! again when Settings says so (`ReloadInput` on the bus). Mice and touchpads are listed on the bus as Settings lists
//! KWin's (`Pointers`), changed one setting at a time (`SetPointer`), and kept by device name in
//! ~/.config/huginn/input.json, put back whenever the device appears.

use std::path::PathBuf;

use serde_json::{Value, json};
use smithay::{
    input::keyboard::XkbConfig,
    reexports::input::{Device, DeviceCapability},
};
use tracing::warn;

use crate::state::{Backend, HuginnState};

fn config_dir() -> Option<PathBuf> {
    std::env::var_os("XDG_CONFIG_HOME")
        .map(PathBuf::from)
        .or_else(|| std::env::var_os("HOME").map(|h| PathBuf::from(h).join(".config")))
}

/// One value from a KDE-style config file ([Group] key=value).
pub fn kconfig(file: &str, group: &str, key: &str) -> Option<String> {
    let text = std::fs::read_to_string(config_dir()?.join(file)).ok()?;
    let mut inside = false;
    for line in text.lines() {
        let line = line.trim();
        if line.starts_with('[') {
            inside = line == format!("[{group}]");
        } else if inside {
            if let Some((k, v)) = line.split_once('=') {
                if k.trim() == key {
                    return Some(v.trim().to_string());
                }
            }
        }
    }
    None
}

/// The keyboard as Settings set it: (layouts, variants, options), or None to keep the system's.
pub fn layouts() -> Option<(String, String, Option<String>)> {
    let layouts = kconfig("kxkbrc", "Layout", "LayoutList").filter(|l| !l.is_empty())?;
    let variants = kconfig("kxkbrc", "Layout", "VariantList").unwrap_or_default();
    let options = kconfig("kxkbrc", "Layout", "Options").filter(|o| !o.is_empty());
    Some((layouts, variants, options))
}

/// Key repeat: (characters a second, milliseconds before it starts); 0 a second is off.
pub fn repeat() -> (i32, i32) {
    let on = kconfig("kcminputrc", "Keyboard", "KeyRepeat").is_none_or(|v| v != "nothing");
    let delay = kconfig("kcminputrc", "Keyboard", "RepeatDelay").and_then(|v| v.parse().ok()).unwrap_or(600);
    let rate = kconfig("kcminputrc", "Keyboard", "RepeatRate").and_then(|v| v.parse::<f64>().ok()).unwrap_or(25.0);
    (if on { rate.round().clamp(1.0, 100.0) as i32 } else { 0 }, delay.clamp(100, 2000))
}

fn saved_file() -> Option<PathBuf> {
    Some(config_dir()?.join("huginn").join("input.json"))
}

fn saved() -> Value {
    saved_file()
        .and_then(|f| std::fs::read_to_string(f).ok())
        .and_then(|t| serde_json::from_str(&t).ok())
        .unwrap_or_else(|| json!({}))
}

fn is_touchpad(d: &Device) -> bool {
    d.config_tap_finger_count() > 0
}

/// A mouse or touchpad as Settings lists them.
pub fn describe(d: &mut Device) -> Value {
    json!({
        "sys": d.sysname(), "name": d.name(), "touchpad": is_touchpad(d),
        "tap": d.config_tap_enabled(), "natural": d.config_scroll_natural_scroll_enabled(),
        "left": d.config_left_handed(), "speed": d.config_accel_speed(),
        "dwt": d.config_dwt_enabled(), "canDwt": d.config_dwt_is_available(), "canTap": is_touchpad(d),
    })
}

/// One setting on one device: true when it took.
fn set(d: &mut Device, prop: &str, value: &Value) -> bool {
    let b = value.as_bool().unwrap_or(false);
    match prop {
        "tap" => d.config_tap_set_enabled(b).is_ok(),
        "natural" => d.config_scroll_set_natural_scroll_enabled(b).is_ok(),
        "left" => d.config_left_handed_set(b).is_ok(),
        "speed" => d.config_accel_set_speed(value.as_f64().unwrap_or(0.0).clamp(-1.0, 1.0)).is_ok(),
        "dwt" => d.config_dwt_set_enabled(b).is_ok(),
        _ => false,
    }
}

/// A mouse or touchpad just appeared: its saved settings.
pub fn restore(d: &mut Device) {
    if !d.has_capability(DeviceCapability::Pointer) {
        return;
    }
    if let Some(mine) = saved().get(d.name().as_ref()).and_then(|v| v.as_object()).cloned() {
        for (prop, value) in mine {
            set(d, &prop, &value);
        }
    }
}

/// Settings changed one setting on a device: "" when done, else why not.
pub fn change(devices: &mut [Device], sys: &str, prop: &str, value: &str) -> String {
    let value: Value = serde_json::from_str(value).unwrap_or(Value::Null);
    let Some(d) = devices.iter_mut().find(|d| d.sysname() == sys) else {
        return "That device isn't plugged in any more.".into();
    };
    if !set(d, prop, &value) {
        return "That device can't do that.".into();
    }
    let mut all = saved();
    all[d.name().as_ref()][prop] = value;
    if let Some(path) = saved_file() {
        let _ = path.parent().map(std::fs::create_dir_all);
        if let Err(err) = std::fs::write(path, serde_json::to_string_pretty(&all).unwrap_or_default()) {
            warn!("The pointer settings couldn't be saved: {err}");
        }
    }
    String::new()
}

impl<B: Backend + 'static> HuginnState<B> {
    /// Settings changed the keyboard (kxkbrc, kcminputrc): use it now.
    pub fn reload_input(&mut self) {
        let Some(keyboard) = self.seat.get_keyboard() else { return };
        if let Some((layout, variant, options)) = layouts() {
            let xkb = XkbConfig { layout: &layout, variant: &variant, options, ..XkbConfig::default() };
            if let Err(err) = keyboard.set_xkb_config(self, xkb) {
                warn!("The keyboard layouts couldn't be used: {err:?}");
            }
        }
        let (rate, delay) = repeat();
        keyboard.change_repeat_info(rate, delay);
    }
}
