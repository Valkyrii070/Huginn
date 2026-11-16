use std::{borrow::Cow, time::Duration};

use smithay::{
    backend::{
        input::InputTime,
        renderer::{
            Renderer, Texture,
            element::{
                AsRenderElements, Kind,
                memory::MemoryRenderBufferRenderElement,
                solid::SolidColorRenderElement,
                surface::{WaylandSurfaceRenderElement, render_elements_from_surface_tree},
            },
        },
    },
    desktop::{
        PopupManager, Window, WindowSurface, WindowSurfaceType, space::SpaceElement, utils::OutputPresentationFeedback,
    },
    input::{
        Seat,
        pointer::{
            AxisFrame, ButtonEvent, GestureHoldBeginEvent, GestureHoldEndEvent, GesturePinchBeginEvent,
            GesturePinchEndEvent, GesturePinchUpdateEvent, GestureSwipeBeginEvent, GestureSwipeEndEvent,
            GestureSwipeUpdateEvent, MotionEvent, PointerTarget, RelativeMotionEvent,
        },
        tablet::tool::TabletToolTarget,
        touch::{FrameMarker, TouchTarget},
    },
    output::Output,
    reexports::{
        wayland_protocols::{wp::presentation_time::server::wp_presentation_feedback, xdg::shell::server::xdg_toplevel},
        wayland_server::protocol::wl_surface::WlSurface,
    },
    render_elements,
    utils::{IsAlive, Logical, Physical, Point, Rectangle, Scale, Serial, user_data::UserDataMap},
    wayland::{compositor::SurfaceData as WlSurfaceData, dmabuf::DmabufFeedback, seat::WaylandFocus},
};

use super::ssd::HEADER_BAR_HEIGHT;
use crate::{
    HuginnState,
    focus::PointerFocusTarget,
    look::{Look, Rounded, Shadow, ShaderElement, WindowLook},
    state::Backend,
};

#[derive(Debug, Clone, PartialEq)]
pub struct WindowElement(pub Window);

impl WindowElement {
    pub fn surface_under(
        &self,
        location: Point<f64, Logical>,
        window_type: WindowSurfaceType,
    ) -> Option<(PointerFocusTarget, Point<i32, Logical>)> {
        let state = self.decoration_state();
        if state.is_ssd && location.y < HEADER_BAR_HEIGHT as f64 {
            return Some((PointerFocusTarget::SSD(SSD(self.clone())), Point::default()));
        }
        let offset = if state.is_ssd {
            Point::from((0, HEADER_BAR_HEIGHT))
        } else {
            Point::default()
        };

        let surface_under = self.0.surface_under(location - offset.to_f64(), window_type);
        let (under, loc) = match self.0.underlying_surface() {
            WindowSurface::Wayland(_) => {
                surface_under.map(|(surface, loc)| (PointerFocusTarget::WlSurface(surface), loc))
            }
            #[cfg(feature = "xwayland")]
            WindowSurface::X11(s) => {
                surface_under.map(|(_, loc)| (PointerFocusTarget::X11Surface(s.clone()), loc))
            }
        }?;
        Some((under, loc + offset))
    }

    pub fn with_surfaces<F>(&self, processor: F)
    where
        F: FnMut(&WlSurface, &WlSurfaceData),
    {
        self.0.with_surfaces(processor);
    }

    pub fn send_frame<T, F>(
        &self,
        output: &Output,
        time: T,
        throttle: Option<Duration>,
        primary_scan_out_output: F,
    ) where
        T: Into<Duration>,
        F: FnMut(&WlSurface, &WlSurfaceData) -> Option<Output> + Copy,
    {
        self.0.send_frame(output, time, throttle, primary_scan_out_output)
    }

    pub fn send_dmabuf_feedback<'a, P, F>(
        &self,
        output: &Output,
        primary_scan_out_output: P,
        select_dmabuf_feedback: F,
    ) where
        P: FnMut(&WlSurface, &WlSurfaceData) -> Option<Output> + Copy,
        F: Fn(&WlSurface, &WlSurfaceData) -> &'a DmabufFeedback + Copy,
    {
        self.0
            .send_dmabuf_feedback(output, primary_scan_out_output, select_dmabuf_feedback)
    }

    pub fn take_presentation_feedback<F1, F2>(
        &self,
        output_feedback: &mut OutputPresentationFeedback,
        primary_scan_out_output: F1,
        presentation_feedback_flags: F2,
    ) where
        F1: FnMut(&WlSurface, &WlSurfaceData) -> Option<Output> + Copy,
        F2: FnMut(&WlSurface, &WlSurfaceData) -> wp_presentation_feedback::Kind + Copy,
    {
        self.0.take_presentation_feedback(
            output_feedback,
            primary_scan_out_output,
            presentation_feedback_flags,
        )
    }

    #[cfg(feature = "xwayland")]
    #[inline]
    pub fn is_x11(&self) -> bool {
        self.0.is_x11()
    }

    #[inline]
    pub fn is_wayland(&self) -> bool {
        self.0.is_wayland()
    }

    #[inline]
    pub fn wl_surface(&self) -> Option<Cow<'_, WlSurface>> {
        self.0.wl_surface()
    }

    #[inline]
    pub fn user_data(&self) -> &UserDataMap {
        self.0.user_data()
    }
}

impl IsAlive for WindowElement {
    #[inline]
    fn alive(&self) -> bool {
        self.0.alive()
    }
}

#[derive(Debug, Clone, PartialEq)]
pub struct SSD(WindowElement);

impl IsAlive for SSD {
    #[inline]
    fn alive(&self) -> bool {
        self.0.alive()
    }
}

impl WaylandFocus for SSD {
    #[inline]
    fn wl_surface(&self) -> Option<Cow<'_, WlSurface>> {
        self.0.wl_surface()
    }
}

impl<BackendData: Backend> PointerTarget<HuginnState<BackendData>> for SSD {
    fn enter(
        &self,
        _seat: &Seat<HuginnState<BackendData>>,
        _data: &mut HuginnState<BackendData>,
        event: &MotionEvent,
    ) {
        let mut state = self.0.decoration_state();
        if state.is_ssd {
            state.header_bar.pointer_enter(event.location);
        }
    }
    fn motion(
        &self,
        _seat: &Seat<HuginnState<BackendData>>,
        _data: &mut HuginnState<BackendData>,
        event: &MotionEvent,
    ) {
        let mut state = self.0.decoration_state();
        if state.is_ssd {
            state.header_bar.pointer_enter(event.location);
        }
    }
    fn relative_motion(
        &self,
        _seat: &Seat<HuginnState<BackendData>>,
        _data: &mut HuginnState<BackendData>,
        _event: &RelativeMotionEvent,
    ) {
    }
    fn button(
        &self,
        seat: &Seat<HuginnState<BackendData>>,
        data: &mut HuginnState<BackendData>,
        event: &ButtonEvent,
    ) {
        let mut state = self.0.decoration_state();
        if state.is_ssd {
            state.header_bar.clicked(seat, data, &self.0, event.serial);
        }
    }
    fn axis(
        &self,
        _seat: &Seat<HuginnState<BackendData>>,
        _data: &mut HuginnState<BackendData>,
        _frame: AxisFrame,
    ) {
    }
    fn frame(&self, _seat: &Seat<HuginnState<BackendData>>, _data: &mut HuginnState<BackendData>) {}
    fn leave(
        &self,
        _seat: &Seat<HuginnState<BackendData>>,
        _data: &mut HuginnState<BackendData>,
        _serial: Serial,
        _time: InputTime,
    ) {
        let mut state = self.0.decoration_state();
        if state.is_ssd {
            state.header_bar.pointer_leave();
        }
    }
    fn gesture_swipe_begin(
        &self,
        _seat: &Seat<HuginnState<BackendData>>,
        _data: &mut HuginnState<BackendData>,
        _event: &GestureSwipeBeginEvent,
    ) {
    }
    fn gesture_swipe_update(
        &self,
        _seat: &Seat<HuginnState<BackendData>>,
        _data: &mut HuginnState<BackendData>,
        _event: &GestureSwipeUpdateEvent,
    ) {
    }
    fn gesture_swipe_end(
        &self,
        _seat: &Seat<HuginnState<BackendData>>,
        _data: &mut HuginnState<BackendData>,
        _event: &GestureSwipeEndEvent,
    ) {
    }
    fn gesture_pinch_begin(
        &self,
        _seat: &Seat<HuginnState<BackendData>>,
        _data: &mut HuginnState<BackendData>,
        _event: &GesturePinchBeginEvent,
    ) {
    }
    fn gesture_pinch_update(
        &self,
        _seat: &Seat<HuginnState<BackendData>>,
        _data: &mut HuginnState<BackendData>,
        _event: &GesturePinchUpdateEvent,
    ) {
    }
    fn gesture_pinch_end(
        &self,
        _seat: &Seat<HuginnState<BackendData>>,
        _data: &mut HuginnState<BackendData>,
        _event: &GesturePinchEndEvent,
    ) {
    }
    fn gesture_hold_begin(
        &self,
        _seat: &Seat<HuginnState<BackendData>>,
        _data: &mut HuginnState<BackendData>,
        _event: &GestureHoldBeginEvent,
    ) {
    }
    fn gesture_hold_end(
        &self,
        _seat: &Seat<HuginnState<BackendData>>,
        _data: &mut HuginnState<BackendData>,
        _event: &GestureHoldEndEvent,
    ) {
    }
}

impl<BackendData: Backend> TouchTarget<HuginnState<BackendData>> for SSD {
    fn down(
        &self,
        seat: &Seat<HuginnState<BackendData>>,
        data: &mut HuginnState<BackendData>,
        event: &smithay::input::touch::DownEvent,
    ) {
        let mut state = self.0.decoration_state();
        if state.is_ssd {
            state.header_bar.pointer_enter(event.location);
            state.header_bar.touch_down(seat, data, &self.0, event.serial);
        }
    }

    fn up(
        &self,
        seat: &Seat<HuginnState<BackendData>>,
        data: &mut HuginnState<BackendData>,
        _event: &smithay::input::touch::UpEvent,
    ) {
        let mut state = self.0.decoration_state();
        if state.is_ssd {
            state.header_bar.touch_up(seat, data, &self.0);
        }
    }

    fn motion(
        &self,
        _seat: &Seat<HuginnState<BackendData>>,
        _data: &mut HuginnState<BackendData>,
        event: &smithay::input::touch::MotionEvent,
    ) {
        let mut state = self.0.decoration_state();
        if state.is_ssd {
            state.header_bar.pointer_enter(event.location);
        }
    }

    fn frame(
        &self,
        _seat: &Seat<HuginnState<BackendData>>,
        _data: &mut HuginnState<BackendData>,
        _marker: FrameMarker,
    ) {
    }

    fn cancel(
        &self,
        _seat: &Seat<HuginnState<BackendData>>,
        _data: &mut HuginnState<BackendData>,
        _marker: FrameMarker,
    ) {
    }

    fn shape(
        &self,
        _seat: &Seat<HuginnState<BackendData>>,
        _data: &mut HuginnState<BackendData>,
        _event: &smithay::input::touch::ShapeEvent,
    ) {
    }

    fn orientation(
        &self,
        _seat: &Seat<HuginnState<BackendData>>,
        _data: &mut HuginnState<BackendData>,
        _event: &smithay::input::touch::OrientationEvent,
    ) {
    }

    fn last_frame(
        &self,
        _seat: &Seat<HuginnState<BackendData>>,
        _data: &mut HuginnState<BackendData>,
    ) -> Option<FrameMarker> {
        // It would be more correct to store the marker on frame and cancel,
        // but since we're ignoring those anyway, no need for the added complexity.
        None
    }
}

impl<BackendData: Backend> TabletToolTarget<HuginnState<BackendData>> for SSD {
    fn proximity_in(
        &self,
        _seat: &Seat<HuginnState<BackendData>>,
        _data: &mut HuginnState<BackendData>,
        _tool_descriptor: &smithay::backend::input::TabletToolDescriptor,
        _tablet: &smithay::input::tablet::Tablet,
        _serial: Serial,
    ) {
    }

    fn proximity_out(
        &self,
        _seat: &Seat<HuginnState<BackendData>>,
        _data: &mut HuginnState<BackendData>,
        _tool_descriptor: &smithay::backend::input::TabletToolDescriptor,
    ) {
        let mut state = self.0.decoration_state();
        if state.is_ssd {
            state.header_bar.pointer_leave();
        }
    }

    fn down(
        &self,
        seat: &Seat<HuginnState<BackendData>>,
        data: &mut HuginnState<BackendData>,
        _tool_descriptor: &smithay::backend::input::TabletToolDescriptor,
        event: &smithay::input::tablet::tool::DownEvent,
    ) {
        let mut state = self.0.decoration_state();
        if state.is_ssd {
            state.header_bar.touch_down(seat, data, &self.0, event.serial);
        }
    }

    fn up(
        &self,
        seat: &Seat<HuginnState<BackendData>>,
        data: &mut HuginnState<BackendData>,
        _tool_descriptor: &smithay::backend::input::TabletToolDescriptor,
        _event: &smithay::input::tablet::tool::UpEvent,
    ) {
        let mut state = self.0.decoration_state();
        if state.is_ssd {
            state.header_bar.touch_up(seat, data, &self.0);
        }
    }

    fn motion(
        &self,
        _seat: &Seat<HuginnState<BackendData>>,
        _data: &mut HuginnState<BackendData>,
        _tool_descriptor: &smithay::backend::input::TabletToolDescriptor,
        event: &smithay::input::tablet::tool::MotionEvent,
    ) {
        let mut state = self.0.decoration_state();
        if state.is_ssd {
            state.header_bar.pointer_enter(event.location);
        }
    }

    fn button(
        &self,
        seat: &Seat<HuginnState<BackendData>>,
        data: &mut HuginnState<BackendData>,
        _tool_descriptor: &smithay::backend::input::TabletToolDescriptor,
        event: &smithay::input::tablet::tool::ButtonEvent,
    ) {
        let mut state = self.0.decoration_state();
        if state.is_ssd {
            state.header_bar.clicked(seat, data, &self.0, event.serial);
        }
    }

    fn axis(
        &self,
        _seat: &Seat<HuginnState<BackendData>>,
        _data: &mut HuginnState<BackendData>,
        _tool_descriptor: &smithay::backend::input::TabletToolDescriptor,
        _frame: smithay::input::tablet::tool::AxisFrame,
    ) {
    }

    fn frame(
        &self,
        _seat: &Seat<HuginnState<BackendData>>,
        _data: &mut HuginnState<BackendData>,
        _tool_descriptor: &smithay::backend::input::TabletToolDescriptor,
        _time: InputTime,
    ) {
    }
}

impl SpaceElement for WindowElement {
    fn geometry(&self) -> Rectangle<i32, Logical> {
        let mut geo = SpaceElement::geometry(&self.0);
        if self.decoration_state().is_ssd {
            geo.size.h += HEADER_BAR_HEIGHT;
        }
        geo
    }
    fn bbox(&self) -> Rectangle<i32, Logical> {
        let mut bbox = SpaceElement::bbox(&self.0);
        if self.decoration_state().is_ssd {
            bbox.size.h += HEADER_BAR_HEIGHT;
        }
        bbox
    }
    fn is_in_input_region(&self, point: &Point<f64, Logical>) -> bool {
        if self.decoration_state().is_ssd {
            point.y < HEADER_BAR_HEIGHT as f64
                || SpaceElement::is_in_input_region(
                    &self.0,
                    &(*point - Point::from((0.0, HEADER_BAR_HEIGHT as f64))),
                )
        } else {
            SpaceElement::is_in_input_region(&self.0, point)
        }
    }
    fn z_index(&self) -> u8 {
        SpaceElement::z_index(&self.0)
    }

    fn set_activate(&self, activated: bool) {
        SpaceElement::set_activate(&self.0, activated);
    }
    fn output_enter(&self, output: &Output, overlap: Rectangle<i32, Logical>) {
        SpaceElement::output_enter(&self.0, output, overlap);
    }
    fn output_leave(&self, output: &Output) {
        SpaceElement::output_leave(&self.0, output);
    }
    #[profiling::function]
    fn refresh(&self) {
        SpaceElement::refresh(&self.0);
    }
}

render_elements!(
    pub WindowRenderElement<R> where R: Look;
    Window=WaylandSurfaceRenderElement<R>,
    Decoration=SolidColorRenderElement,
    Rounded=Rounded<WaylandSurfaceRenderElement<R>>,
    Shader=ShaderElement,
    Text=MemoryRenderBufferRenderElement<R>,
);

impl<R: Renderer> std::fmt::Debug for WindowRenderElement<R> {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Window(arg0) => f.debug_tuple("Window").field(arg0).finish(),
            Self::Decoration(arg0) => f.debug_tuple("Decoration").field(arg0).finish(),
            Self::Rounded(arg0) => f.debug_tuple("Rounded").field(arg0).finish(),
            Self::Shader(arg0) => f.debug_tuple("Shader").field(arg0).finish(),
            Self::Text(arg0) => f.debug_tuple("Text").field(arg0).finish(),
            Self::_GenericCatcher(arg0) => f.debug_tuple("_GenericCatcher").field(arg0).finish(),
        }
    }
}

impl WindowElement {
    /// (in front, plain): plain is maximised or full screen — no corners, no shadow.
    fn look_flags(&self) -> (bool, bool) {
        match self.0.underlying_surface() {
            WindowSurface::Wayland(t) => t.with_committed_state(|s| {
                s.map(|s| {
                    (
                        s.states.contains(xdg_toplevel::State::Activated),
                        s.states.contains(xdg_toplevel::State::Maximized) || s.states.contains(xdg_toplevel::State::Fullscreen),
                    )
                })
                .unwrap_or((false, false))
            }),
            #[cfg(feature = "xwayland")]
            WindowSurface::X11(x) => (x.is_activated(), x.is_maximized() || x.is_fullscreen()),
        }
    }

    fn look(&self) -> std::cell::RefMut<'_, WindowLook> {
        self.0.user_data().insert_if_missing(|| std::cell::RefCell::new(WindowLook::default()));
        self.0.user_data().get::<std::cell::RefCell<WindowLook>>().unwrap().borrow_mut()
    }
}

impl<R> AsRenderElements<R> for WindowElement
where
    R: Look,
    R::TextureId: Clone + Texture + Send + 'static,
{
    type RenderElement = WindowRenderElement<R>;

    /// A window, front to back: its popups, its title island (if Huginn draws it), the window itself cut to its
    /// rounded outline, and its shadow. Maximised and full-screen windows are drawn plain.
    fn render_elements<C: From<Self::RenderElement>>(
        &self,
        renderer: &mut R,
        location: Point<i32, Physical>,
        scale: Scale<f64>,
        alpha: f32,
    ) -> Vec<C> {
        let window_bbox = SpaceElement::bbox(&self.0);
        let ssd = self.decoration_state().is_ssd && !window_bbox.is_empty();
        let inner = SpaceElement::geometry(&self.0);
        let header = if ssd { (scale.y * HEADER_BAR_HEIGHT as f64).round() as i32 } else { 0 };
        let at = location + Point::from((0, header));
        let (active, plain) = self.look_flags();
        let programs = crate::look::programs(renderer.gles());
        let mut out: Vec<WindowRenderElement<R>> = Vec::new();

        // the popups (menus and the like reach outside the window, so they're not cut)
        let surfaces: Vec<WaylandSurfaceRenderElement<R>> = match self.0.underlying_surface() {
            WindowSurface::Wayland(t) => {
                let surface = t.wl_surface();
                for (popup, offset) in PopupManager::popups_for_surface(surface) {
                    let offset = (self.0.geometry().loc + offset - popup.geometry().loc).to_physical_precise_round(scale);
                    out.extend(
                        render_elements_from_surface_tree::<R, WaylandSurfaceRenderElement<R>>(
                            renderer,
                            popup.wl_surface(),
                            at + offset,
                            scale,
                            alpha,
                            Kind::Unspecified,
                        )
                        .into_iter()
                        .map(WindowRenderElement::Window),
                    );
                }
                render_elements_from_surface_tree(renderer, surface, at, scale, alpha, Kind::Unspecified)
            }
            #[cfg(feature = "xwayland")]
            WindowSurface::X11(x) => AsRenderElements::<R>::render_elements(x, renderer, at, scale, alpha),
        };

        let window = Rectangle::new(at + inner.loc.to_physical_precise_round(scale), inner.size.to_physical_precise_round(scale));
        let Some(programs) = programs.filter(|_| !plain && !inner.is_empty()) else {
            // plain: the old header (if any) and the window as it is
            if ssd {
                let mut state = self.decoration_state();
                state.header_bar.redraw(inner.size.w as u32);
                out.extend(AsRenderElements::<R>::render_elements::<WindowRenderElement<R>>(
                    &state.header_bar,
                    renderer,
                    location,
                    scale,
                    alpha,
                ));
            }
            out.extend(surfaces.into_iter().map(WindowRenderElement::Window));
            return out.into_iter().map(C::from).collect();
        };

        let radius = crate::look::RADIUS * scale.x;
        let full = Rectangle::new((window.loc.x, window.loc.y - header).into(), (window.size.w, window.size.h + header).into());
        let mut look = self.look();
        if ssd {
            // the title island: the lights, then the title beside them
            let hover = {
                let state = self.decoration_state();
                state.header_bar.pointer_loc.and_then(|p| super::ssd::light_at(p.x)).unwrap_or(-1)
            };
            let bar = Rectangle::new(full.loc, (full.size.w, header).into());
            let (title, app) = window_names(self);
            let text = if title.is_empty() { app } else { title };
            let max_w = inner.size.w - super::ssd::TITLE_X - 14;
            if max_w > 24
                && let Some((buf, size, bs)) = look.title(&text, scale.x, max_w)
            {
                let h = (size.1 as f64 / bs as f64 * scale.y).round() as i32;
                let x = bar.loc.x as f64 + super::ssd::TITLE_X as f64 * scale.x;
                let y = bar.loc.y as f64 + ((header - h) as f64 / 2.0).round();
                if let Ok(e) = MemoryRenderBufferRenderElement::from_buffer(
                    renderer,
                    (x.round(), y),
                    &buf,
                    Some(if active { alpha } else { alpha * 0.6 }),
                    None,
                    None,
                    Kind::Unspecified,
                ) {
                    out.push(WindowRenderElement::Text(e));
                }
            }
            out.push(WindowRenderElement::Shader(look.deco(&programs, bar, scale.x, active, hover, alpha)));
        }
        // the window, cut to the outline (with a title island, only its bottom corners: the island has the top ones)
        let r = radius.ceil() as i32;
        let clip = if ssd {
            Rectangle::new((window.loc.x, window.loc.y - r).into(), (window.size.w, window.size.h + r).into())
        } else {
            window
        };
        out.extend(surfaces.into_iter().map(|e| WindowRenderElement::Rounded(Rounded::new(e, clip, radius, scale))));
        out.push(WindowRenderElement::Shader(look.shadow(&programs, Shadow { rect: full, radius, active, scale: scale.x }, alpha)));
        out.into_iter().map(C::from).collect()
    }
}

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
            smithay::wayland::compositor::with_states(t.wl_surface(), |states| {
                states
                    .data_map
                    .get::<smithay::wayland::shell::xdg::XdgToplevelSurfaceData>()
                    .and_then(|d| d.lock().ok())
                    .map(|d| (d.title.clone().unwrap_or_default(), d.app_id.clone().unwrap_or_default()))
            })
        })
        .unwrap_or_default()
}
