use smithay::{
    backend::renderer::{
        Renderer,
        element::{
            AsRenderElements, Kind,
            solid::{SolidColorBuffer, SolidColorRenderElement},
        },
    },
    desktop::WindowSurface,
    input::Seat,
    utils::{Logical, Point, Serial},
    wayland::shell::xdg::XdgShellHandler,
};

use std::cell::{RefCell, RefMut};

use crate::{HuginnState, state::Backend};

use super::WindowElement;

pub struct WindowState {
    pub is_ssd: bool,
    pub header_bar: HeaderBar,
}

#[derive(Debug, Clone)]
pub struct HeaderBar {
    pub pointer_loc: Option<Point<f64, Logical>>,
    pub width: u32,
    pub close_button_hover: bool,
    pub maximize_button_hover: bool,
    pub background: SolidColorBuffer,
    pub close_button: SolidColorBuffer,
    pub maximize_button: SolidColorBuffer,
}

const BG_COLOR: [f32; 4] = [0.75f32, 0.9f32, 0.78f32, 1f32];
const MAX_COLOR: [f32; 4] = [1f32, 0.965f32, 0.71f32, 1f32];
const CLOSE_COLOR: [f32; 4] = [1f32, 0.66f32, 0.612f32, 1f32];
const MAX_COLOR_HOVER: [f32; 4] = [0.71f32, 0.624f32, 0f32, 1f32];
const CLOSE_COLOR_HOVER: [f32; 4] = [0.75f32, 0.11f32, 0.016f32, 1f32];

pub const HEADER_BAR_HEIGHT: i32 = 32;
const BUTTON_HEIGHT: u32 = HEADER_BAR_HEIGHT as u32;
const BUTTON_WIDTH: u32 = 32;

// Huginn's title island (drawn in look.rs): the three lights at the left, as on Huginn's own windows, then the title.
pub const LIGHT_X0: i32 = 20;
pub const LIGHT_GAP: i32 = 20;
pub const TITLE_X: i32 = 80;

/// Which light (0 close, 1 minimise, 2 fill) is under `x` (logical, from the island's left edge), if any.
pub fn light_at(x: f64) -> Option<i32> {
    (0..3).find(|i| (x - (LIGHT_X0 + LIGHT_GAP * i) as f64).abs() <= (LIGHT_GAP as f64) / 2.0)
}

/// What a click in the title island does: a light's job, or move the window.
enum Act {
    Close,
    Minimise,
    Fill,
    Move,
}

fn act_at(loc: Option<&Point<f64, Logical>>) -> Option<Act> {
    let loc = loc?;
    Some(match light_at(loc.x) {
        Some(0) => Act::Close,
        Some(1) => Act::Minimise,
        Some(2) => Act::Fill,
        _ => Act::Move,
    })
}

fn close(window: &WindowElement) {
    if !crate::access::still() {
        crate::capture::ask_window(crate::huginn::window_id(window), crate::capture::WindowAsk::Ghost);
    }
    match window.0.underlying_surface() {
        WindowSurface::Wayland(w) => w.send_close(),
        #[cfg(feature = "xwayland")]
        WindowSurface::X11(w) => {
            let _ = w.close();
        }
    };
}

fn fill<BackendData: Backend>(state: &mut HuginnState<BackendData>, window: &WindowElement) {
    match window.0.underlying_surface() {
        WindowSurface::Wayland(w) => state.maximize_request(w.clone()),
        #[cfg(feature = "xwayland")]
        WindowSurface::X11(w) => {
            let surface = w.clone();
            state.handle.insert_idle(move |data| data.maximize_request_x11(&surface));
        }
    };
}

fn minimise<BackendData: Backend>(state: &mut HuginnState<BackendData>, window: &WindowElement) {
    let window = window.clone();
    state.handle.insert_idle(move |data| data.minimise_window(&window));
}

impl HeaderBar {
    pub fn pointer_enter(&mut self, loc: Point<f64, Logical>) {
        self.pointer_loc = Some(loc);
    }

    pub fn pointer_leave(&mut self) {
        self.pointer_loc = None;
    }

    pub fn clicked<BackendData: Backend>(
        &mut self,
        seat: &Seat<HuginnState<BackendData>>,
        state: &mut HuginnState<BackendData>,
        window: &WindowElement,
        serial: Serial,
    ) {
        match act_at(self.pointer_loc.as_ref()) {
            Some(Act::Close) => close(window),
            Some(Act::Minimise) => minimise(state, window),
            Some(Act::Fill) => fill(state, window),
            Some(Act::Move) => {
                match window.0.underlying_surface() {
                    WindowSurface::Wayland(w) => {
                        let seat = seat.clone();
                        let toplevel = w.clone();
                        state
                            .handle
                            .insert_idle(move |data| data.move_request_xdg(&toplevel, &seat, serial));
                    }
                    #[cfg(feature = "xwayland")]
                    WindowSurface::X11(w) => {
                        let window = w.clone();
                        state
                            .handle
                            .insert_idle(move |data| data.move_request_x11(&window));
                    }
                };
            }
            None => {}
        };
    }

    pub fn touch_down<BackendData: Backend>(
        &mut self,
        seat: &Seat<HuginnState<BackendData>>,
        state: &mut HuginnState<BackendData>,
        window: &WindowElement,
        serial: Serial,
    ) {
        if let Some(Act::Move) = act_at(self.pointer_loc.as_ref()) {
            match window.0.underlying_surface() {
                WindowSurface::Wayland(w) => {
                    let seat = seat.clone();
                    let toplevel = w.clone();
                    state
                        .handle
                        .insert_idle(move |data| data.move_request_xdg(&toplevel, &seat, serial));
                }
                #[cfg(feature = "xwayland")]
                WindowSurface::X11(w) => {
                    let window = w.clone();
                    state
                        .handle
                        .insert_idle(move |data| data.move_request_x11(&window));
                }
            };
        }
    }

    pub fn touch_up<BackendData: Backend>(
        &mut self,
        _seat: &Seat<HuginnState<BackendData>>,
        state: &mut HuginnState<BackendData>,
        window: &WindowElement,
    ) {
        match act_at(self.pointer_loc.as_ref()) {
            Some(Act::Close) => close(window),
            Some(Act::Minimise) => minimise(state, window),
            Some(Act::Fill) => fill(state, window),
            _ => {}
        }
    }

    pub fn redraw(&mut self, width: u32) {
        if width == 0 {
            self.width = 0;
            return;
        }

        self.background
            .update((width as i32, HEADER_BAR_HEIGHT), BG_COLOR);

        let mut needs_redraw_buttons = false;
        if width != self.width {
            needs_redraw_buttons = true;
            self.width = width;
        }

        if self
            .pointer_loc
            .as_ref()
            .map(|l| l.x >= (width - BUTTON_WIDTH) as f64)
            .unwrap_or(false)
            && (needs_redraw_buttons || !self.close_button_hover)
        {
            self.close_button
                .update((BUTTON_WIDTH as i32, BUTTON_HEIGHT as i32), CLOSE_COLOR_HOVER);
            self.close_button_hover = true;
        } else if !self
            .pointer_loc
            .as_ref()
            .map(|l| l.x >= (width - BUTTON_WIDTH) as f64)
            .unwrap_or(false)
            && (needs_redraw_buttons || self.close_button_hover)
        {
            self.close_button
                .update((BUTTON_WIDTH as i32, BUTTON_HEIGHT as i32), CLOSE_COLOR);
            self.close_button_hover = false;
        }

        if self
            .pointer_loc
            .as_ref()
            .map(|l| l.x >= (width - BUTTON_WIDTH * 2) as f64 && l.x <= (width - BUTTON_WIDTH) as f64)
            .unwrap_or(false)
            && (needs_redraw_buttons || !self.maximize_button_hover)
        {
            self.maximize_button
                .update((BUTTON_WIDTH as i32, BUTTON_HEIGHT as i32), MAX_COLOR_HOVER);
            self.maximize_button_hover = true;
        } else if !self
            .pointer_loc
            .as_ref()
            .map(|l| l.x >= (width - BUTTON_WIDTH * 2) as f64 && l.x <= (width - BUTTON_WIDTH) as f64)
            .unwrap_or(false)
            && (needs_redraw_buttons || self.maximize_button_hover)
        {
            self.maximize_button
                .update((BUTTON_WIDTH as i32, BUTTON_HEIGHT as i32), MAX_COLOR);
            self.maximize_button_hover = false;
        }
    }
}

impl<R: Renderer> AsRenderElements<R> for HeaderBar {
    type RenderElement = SolidColorRenderElement;

    fn render_elements<C: From<Self::RenderElement>>(
        &self,
        _renderer: &mut R,
        location: Point<i32, smithay::utils::Physical>,
        scale: smithay::utils::Scale<f64>,
        alpha: f32,
    ) -> Vec<C> {
        let header_end_offset: Point<i32, Logical> = Point::from((self.width as i32, 0));
        let button_offset: Point<i32, Logical> = Point::from((BUTTON_WIDTH as i32, 0));

        vec![
            SolidColorRenderElement::from_buffer(
                &self.close_button,
                location + (header_end_offset - button_offset).to_physical_precise_round(scale),
                scale,
                alpha,
                Kind::Unspecified,
            )
            .into(),
            SolidColorRenderElement::from_buffer(
                &self.maximize_button,
                location + (header_end_offset - button_offset.upscale(2)).to_physical_precise_round(scale),
                scale,
                alpha,
                Kind::Unspecified,
            )
            .into(),
            SolidColorRenderElement::from_buffer(&self.background, location, scale, alpha, Kind::Unspecified)
                .into(),
        ]
    }
}

impl WindowElement {
    pub fn decoration_state(&self) -> RefMut<'_, WindowState> {
        self.user_data().insert_if_missing(|| {
            RefCell::new(WindowState {
                is_ssd: false,
                header_bar: HeaderBar {
                    pointer_loc: None,
                    width: 0,
                    close_button_hover: false,
                    maximize_button_hover: false,
                    background: SolidColorBuffer::default(),
                    close_button: SolidColorBuffer::default(),
                    maximize_button: SolidColorBuffer::default(),
                },
            })
        });

        self.user_data()
            .get::<RefCell<WindowState>>()
            .unwrap()
            .borrow_mut()
    }

    pub fn set_ssd(&self, ssd: bool) {
        self.decoration_state().is_ssd = ssd;
    }
}
