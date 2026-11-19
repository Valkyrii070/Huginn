//! Tearing for games (wp-tearing-control-v1): a game that asks for its frames to go out at once (the "async"
//! hint, as with V-Sync off) gets page flips that don't wait for the screen's refresh while it fills the screen,
//! unless Settings › Desktop & Dock turns that off. The flips themselves are in Huginn's patched Smithay
//! (third_party/smithay: AtomicDrmSurface::set_tearing); drivers that can't, flip normally.

use std::sync::atomic::{AtomicBool, Ordering};

use smithay::{
    reexports::{
        wayland_protocols::wp::tearing_control::v1::server::{
            wp_tearing_control_manager_v1::{self, WpTearingControlManagerV1},
            wp_tearing_control_v1::{self, PresentationHint, WpTearingControlV1},
        },
        wayland_server::{
            Client, DataInit, DisplayHandle, New, Resource, Weak,
            protocol::wl_surface::WlSurface,
        },
    },
    wayland::{
        Dispatch2, GlobalDispatch2,
        compositor::with_states,
    },
};

use crate::state::{Backend, HuginnState};

/// Settings: "Let games tear" (on unless turned off).
pub static ALLOWED: AtomicBool = AtomicBool::new(true);

/// A surface's hint, kept in its data map.
#[derive(Default)]
struct Hint(AtomicBool);

/// Whether this surface asked for tearing.
pub fn wants(surface: &WlSurface) -> bool {
    ALLOWED.load(Ordering::Relaxed) && with_states(surface, |s| s.data_map.get::<Hint>().is_some_and(|h| h.0.load(Ordering::Relaxed)))
}

fn set(surface: &WlSurface, on: bool) {
    with_states(surface, |s| {
        s.data_map.insert_if_missing_threadsafe(Hint::default);
        s.data_map.get::<Hint>().unwrap().0.store(on, Ordering::Relaxed);
    });
}

pub struct ManagerGlobal;
pub struct ManagerData;
pub struct ControlData(Weak<WlSurface>);

pub fn init<B: Backend + 'static>(dh: &DisplayHandle) {
    dh.create_global::<HuginnState<B>, WpTearingControlManagerV1, _>(1, ManagerGlobal);
}

impl<B: Backend + 'static> GlobalDispatch2<WpTearingControlManagerV1, HuginnState<B>> for ManagerGlobal {
    fn bind(
        &self,
        _state: &mut HuginnState<B>,
        _handle: &DisplayHandle,
        _client: &Client,
        resource: New<WpTearingControlManagerV1>,
        data_init: &mut DataInit<'_, HuginnState<B>>,
    ) {
        data_init.init(resource, ManagerData);
    }
}

impl<B: Backend + 'static> Dispatch2<WpTearingControlManagerV1, HuginnState<B>> for ManagerData {
    fn request(
        &self,
        _state: &mut HuginnState<B>,
        _client: &Client,
        _resource: &WpTearingControlManagerV1,
        request: wp_tearing_control_manager_v1::Request,
        _dhandle: &DisplayHandle,
        data_init: &mut DataInit<'_, HuginnState<B>>,
    ) {
        match request {
            wp_tearing_control_manager_v1::Request::GetTearingControl { id, surface } => {
                data_init.init(id, ControlData(surface.downgrade()));
            }
            wp_tearing_control_manager_v1::Request::Destroy => {}
            _ => {}
        }
    }
}

impl<B: Backend + 'static> Dispatch2<WpTearingControlV1, HuginnState<B>> for ControlData {
    fn request(
        &self,
        _state: &mut HuginnState<B>,
        _client: &Client,
        _resource: &WpTearingControlV1,
        request: wp_tearing_control_v1::Request,
        _dhandle: &DisplayHandle,
        _data_init: &mut DataInit<'_, HuginnState<B>>,
    ) {
        match request {
            wp_tearing_control_v1::Request::SetPresentationHint { hint } => {
                if let Ok(surface) = self.0.upgrade() {
                    set(&surface, matches!(hint.into_result(), Ok(PresentationHint::Async)));
                }
            }
            wp_tearing_control_v1::Request::Destroy => {
                if let Ok(surface) = self.0.upgrade() {
                    set(&surface, false);
                }
            }
            _ => {}
        }
    }

    fn destroyed(&self, _state: &mut HuginnState<B>, _client: smithay::reexports::wayland_server::backend::ClientId, _resource: &WpTearingControlV1) {
        if let Ok(surface) = self.0.upgrade() {
            set(&surface, false);
        }
    }
}
