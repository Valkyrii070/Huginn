#![warn(rust_2018_idioms)]
#![allow(clippy::collapsible_match)]
// If no backend is enabled, a large portion of the codebase is unused.
// So silence this useless warning for the CI.
#![cfg_attr(
    not(any(feature = "winit", feature = "udev")),
    allow(dead_code, unused_imports)
)]

#[cfg(any(feature = "udev", feature = "xwayland"))]
pub mod access;
pub mod capture;
pub mod cursor;
pub mod dbus;
pub mod displays;
pub mod input;
pub mod places;
pub mod tearing;
pub mod drawing;
pub mod focus;
pub mod huginn;
pub mod input_handler;
pub mod look;
pub mod render;
pub mod shell;
pub mod state;
#[cfg(feature = "udev")]
pub mod udev;
#[cfg(feature = "winit")]
pub mod winit;
pub mod wm;

pub use state::{ClientState, HuginnState};
