use std::{convert::TryInto, sync::atomic::Ordering};

use crate::{HuginnState, focus::PointerFocusTarget, shell::FullscreenSurface};

#[cfg(feature = "udev")]
use crate::udev::UdevData;
#[cfg(feature = "udev")]
use smithay::input::tablet;

use smithay::{
    backend::input::{
        self, Axis, AxisSource, Device, DeviceCapability, Event, GestureBeginEvent, GestureEndEvent,
        GesturePinchUpdateEvent as _, GestureSwipeUpdateEvent as _, InputBackend, InputEvent, InputTime,
        KeyState, KeyboardKeyEvent, PointerAxisEvent, PointerButtonEvent, TouchEvent,
    },
    desktop::{WindowSurfaceType, layer_map_for_output},
    input::{
        keyboard::{FilterResult, Keysym, ModifiersState, keysyms as xkb},
        pointer::{AxisFrame, ButtonEvent, MotionEvent},
        pointer::{
            GestureHoldBeginEvent, GestureHoldEndEvent, GesturePinchBeginEvent, GesturePinchEndEvent,
            GesturePinchUpdateEvent, GestureSwipeBeginEvent, GestureSwipeEndEvent, GestureSwipeUpdateEvent,
        },
        tablet::{TabletDescriptor, TabletSeatTrait},
        touch::{DownEvent, UpEvent},
    },
    reexports::{
        wayland_server::protocol::wl_pointer,
    },
    utils::{Logical, Point, SERIAL_COUNTER as SCOUNTER, Serial},
    wayland::{
        input_method::InputMethodSeat,
        keyboard_shortcuts_inhibit::KeyboardShortcutsInhibitorSeat,
        shell::wlr_layer::{KeyboardInteractivity, Layer as WlrLayer},
        virtual_keyboard::{VirtualKeyboardBackend, VirtualKeyboardHandler, VirtualKeyboardSpecialEvent},
    },
};

use smithay::backend::input::AbsolutePositionEvent;

#[cfg(any(feature = "winit", feature = "x11"))]
use smithay::output::Output;
use tracing::{debug, error, info, warn};

use crate::state::Backend;
#[cfg(feature = "udev")]
use smithay::{
    backend::{
        input::{
            PointerMotionEvent, ProximityState, TabletToolButtonEvent, TabletToolEvent,
            TabletToolProximityEvent, TabletToolTipEvent, TabletToolTipState,
        },
        session::Session,
    },
    input::pointer::RelativeMotionEvent,
    reexports::wayland_server::DisplayHandle,
    wayland::{
        pointer_constraints::{PointerConstraint, with_pointer_constraint},
        seat::WaylandFocus,
    },
};

impl<BackendData: Backend> HuginnState<BackendData> {
    // Allow in this method because of existing usage
    #[allow(clippy::uninlined_format_args)]
    fn process_common_key_action(&mut self, action: KeyAction) {
        match action {
            KeyAction::None | KeyAction::VtSwitch(_) => (),
            KeyAction::Quit => {
                info!("Quitting.");
                self.running.store(false, Ordering::SeqCst);
            }
            KeyAction::Launcher => self.say(crate::dbus::Outgoing::Launcher),
            KeyAction::Search => self.say(crate::dbus::Outgoing::Search),
            KeyAction::Shell(what) => self.say(crate::dbus::Outgoing::ShellKey(what.into())),
            KeyAction::Overview => self.overview_toggle(),
            KeyAction::SpaceStep(delta, take) => self.space_step(delta, take),
            KeyAction::SpaceGo(n) => self.switch_space(n),
            KeyAction::Snap(dir) => self.snap_step(dir),
            KeyAction::Lock => self.lock_now(),
            KeyAction::CloseWindow => self.window_action("close"),
            KeyAction::Maximise => self.window_action("maximise"),
            KeyAction::Minimise => self.window_action("minimise"),
            KeyAction::Switch(forward) => self.switch_step(forward),
            KeyAction::Screenshot(what) => self.say(crate::dbus::Outgoing::Screenshot(what.into())),
            KeyAction::Hardware(name) => self.say(crate::dbus::Outgoing::Key(name.into())),
        }
    }

    fn keyboard_key_to_action<B: InputBackend>(&mut self, evt: B::KeyboardKeyEvent) -> KeyAction {
        let keycode = evt.key_code();
        let state = evt.state();
        debug!(?keycode, ?state, "key");
        let serial = SCOUNTER.next_serial();
        let time = Event::time(&evt);
        let mut suppressed_keys = self.suppressed_keys.clone();
        let keyboard = self.seat.get_keyboard().unwrap();

        // Locked: every key goes to the lock screen, except switching to a text console and the hardware keys.
        if self.is_locked() {
            let focus = self.lock_surface();
            keyboard.set_focus(self, focus, serial);
            let action = keyboard
                .input(self, keycode, state, serial, time, |_, modifiers, handle| {
                    let keysym = handle.modified_sym();
                    if let KeyState::Pressed = state {
                        match process_keyboard_shortcut(*modifiers, keysym) {
                            Some(action @ (KeyAction::VtSwitch(_) | KeyAction::Hardware(_))) => {
                                return FilterResult::Intercept(action);
                            }
                            _ => {}
                        }
                    }
                    FilterResult::Forward
                })
                .unwrap_or(KeyAction::None);
            self.huginn.super_alone = false;
            return action;
        }

        self.exclusive_layer_focus(serial);
        let inhibited = self
            .space
            .element_under(self.pointer.current_location())
            .and_then(|(window, _)| {
                let surface = window.wl_surface()?;
                self.seat.keyboard_shortcuts_inhibitor_for_surface(&surface)
            })
            .map(|inhibitor| inhibitor.is_active())
            .unwrap_or(false);

        let action = keyboard
            .input(self, keycode, state, serial, time, |state_, modifiers, handle| {
                let keysym = handle.modified_sym();
                let is_super = matches!(keysym, Keysym::Super_L | Keysym::Super_R);
                let is_alt = matches!(keysym, Keysym::Alt_L);
                // Super on its own (pressed and let go with nothing else): the start menu; Alt on its own: the app's menu
                if let KeyState::Pressed = state {
                    state_.huginn.super_alone = is_super;
                    state_.huginn.alt_alone = is_alt && !modifiers.ctrl && !modifiers.logo && !modifiers.shift;
                } else if is_super {
                    let alone = std::mem::take(&mut state_.huginn.super_alone);
                    if alone && !inhibited {
                        return FilterResult::Intercept(KeyAction::Launcher);
                    }
                } else if is_alt {
                    let alone = std::mem::take(&mut state_.huginn.alt_alone);
                    if alone && !inhibited && state_.huginn.switching.is_none() {
                        state_.switch_end();
                        return FilterResult::Intercept(KeyAction::Shell("menu"));
                    }
                }
                // Alt let go: Alt+Tab is over
                if let KeyState::Released = state
                    && matches!(keysym, Keysym::Alt_L | Keysym::Alt_R)
                {
                    state_.switch_end();
                }

                debug!(
                    ?state,
                    mods = ?modifiers,
                    keysym = ::xkbcommon::xkb::keysym_get_name(keysym),
                    "keysym"
                );

                // If the key is pressed and triggered a action
                // we will not forward the key to the client.
                // Additionally add the key to the suppressed keys
                // so that we can decide on a release if the key
                // should be forwarded to the client or not.
                if let KeyState::Pressed = state {
                    if !inhibited {
                        let action = process_keyboard_shortcut(*modifiers, keysym);

                        if action.is_some() {
                            suppressed_keys.push(keysym);
                        }

                        action
                            .map(FilterResult::Intercept)
                            .unwrap_or(FilterResult::Forward)
                    } else {
                        FilterResult::Forward
                    }
                } else {
                    let suppressed = suppressed_keys.contains(&keysym);
                    if suppressed {
                        suppressed_keys.retain(|k| *k != keysym);
                        FilterResult::Intercept(KeyAction::None)
                    } else {
                        FilterResult::Forward
                    }
                }
            })
            .unwrap_or(KeyAction::None);

        self.suppressed_keys = suppressed_keys;
        action
    }

    /// The shell's start menu and Search take every key while they're open (keys our shortcuts didn't take).
    fn exclusive_layer_focus(&mut self, serial: Serial) {
        let keyboard = self.seat.get_keyboard().unwrap();
        for layer in self.layer_shell_state.layer_surfaces().rev() {
            let exclusive = layer.with_cached_state(|data| {
                data.keyboard_interactivity == KeyboardInteractivity::Exclusive
                    && (data.layer == WlrLayer::Top || data.layer == WlrLayer::Overlay)
            });
            if exclusive {
                let surface = self.space.outputs().find_map(|o| {
                    let map = layer_map_for_output(o);
                    map.layers().find(|l| l.layer_surface() == &layer).cloned()
                });
                if let Some(surface) = surface {
                    keyboard.set_focus(self, Some(surface.into()), serial);
                    return;
                };
            }
        }

    }

    fn on_pointer_button<B: InputBackend>(&mut self, evt: B::PointerButtonEvent) {
        let serial = SCOUNTER.next_serial();
        let button = evt.button_code();

        let state = wl_pointer::ButtonState::from(evt.state());

        if wl_pointer::ButtonState::Pressed == state {
            self.huginn.super_alone = false;
            self.huginn.alt_alone = false;
            if self.is_locked() {
                let focus = self.lock_surface();
                self.seat.get_keyboard().unwrap().set_focus(self, focus, serial);
            } else {
                let logo = self.seat.get_keyboard().map(|k| k.modifier_state().logo).unwrap_or(false);
                if logo && button == 0x110 && self.super_drag(button, serial) {
                    return;
                }
                self.update_keyboard_focus(self.pointer.current_location(), serial);
            }
        };
        let pointer = self.pointer.clone();
        pointer.button(
            self,
            &ButtonEvent {
                button,
                state: state.try_into().unwrap(),
                serial,
                time: evt.time(),
            },
        );
        pointer.frame(self);
    }

    fn on_gesture_swipe_begin<B: InputBackend>(&mut self, evt: B::GestureSwipeBeginEvent) {
        if evt.fingers() == 3 {
            self.huginn.swipe = Some((0.0, 0.0));
            return;
        }
        let serial = SCOUNTER.next_serial();
        let pointer = self.pointer.clone();
        pointer.gesture_swipe_begin(
            self,
            &GestureSwipeBeginEvent {
                serial,
                time: evt.time(),
                fingers: evt.fingers(),
            },
        );
    }

    fn on_gesture_swipe_update<B: InputBackend>(&mut self, evt: B::GestureSwipeUpdateEvent) {
        if let Some((x, y)) = self.huginn.swipe.as_mut() {
            *x += evt.delta().x;
            *y += evt.delta().y;
            return;
        }
        let pointer = self.pointer.clone();
        pointer.gesture_swipe_update(
            self,
            &GestureSwipeUpdateEvent {
                time: evt.time(),
                delta: evt.delta(),
            },
        );
    }

    fn on_gesture_swipe_end<B: InputBackend>(&mut self, evt: B::GestureSwipeEndEvent) {
        if let Some((x, y)) = self.huginn.swipe.take() {
            if !evt.cancelled() {
                if y < -60.0 && y.abs() > x.abs() {
                    self.overview_open();
                } else if y > 60.0 && y.abs() > x.abs() {
                    self.overview_close(None);
                } else if x.abs() > 80.0 {
                    self.space_step(if x < 0.0 { 1 } else { -1 }, false);
                }
            }
            return;
        }
        let serial = SCOUNTER.next_serial();
        let pointer = self.pointer.clone();
        pointer.gesture_swipe_end(
            self,
            &GestureSwipeEndEvent {
                serial,
                time: evt.time(),
                cancelled: evt.cancelled(),
            },
        );
    }

    fn on_gesture_pinch_begin<B: InputBackend>(&mut self, evt: B::GesturePinchBeginEvent) {
        let serial = SCOUNTER.next_serial();
        let pointer = self.pointer.clone();
        pointer.gesture_pinch_begin(
            self,
            &GesturePinchBeginEvent {
                serial,
                time: evt.time(),
                fingers: evt.fingers(),
            },
        );
    }

    fn on_gesture_pinch_update<B: InputBackend>(&mut self, evt: B::GesturePinchUpdateEvent) {
        let pointer = self.pointer.clone();
        pointer.gesture_pinch_update(
            self,
            &GesturePinchUpdateEvent {
                time: evt.time(),
                delta: evt.delta(),
                scale: evt.scale(),
                rotation: evt.rotation(),
            },
        );
    }

    fn on_gesture_pinch_end<B: InputBackend>(&mut self, evt: B::GesturePinchEndEvent) {
        let serial = SCOUNTER.next_serial();
        let pointer = self.pointer.clone();
        pointer.gesture_pinch_end(
            self,
            &GesturePinchEndEvent {
                serial,
                time: evt.time(),
                cancelled: evt.cancelled(),
            },
        );
    }

    fn on_gesture_hold_begin<B: InputBackend>(&mut self, evt: B::GestureHoldBeginEvent) {
        let serial = SCOUNTER.next_serial();
        let pointer = self.pointer.clone();
        pointer.gesture_hold_begin(
            self,
            &GestureHoldBeginEvent {
                serial,
                time: evt.time(),
                fingers: evt.fingers(),
            },
        );
    }

    fn on_gesture_hold_end<B: InputBackend>(&mut self, evt: B::GestureHoldEndEvent) {
        let serial = SCOUNTER.next_serial();
        let pointer = self.pointer.clone();
        pointer.gesture_hold_end(
            self,
            &GestureHoldEndEvent {
                serial,
                time: evt.time(),
                cancelled: evt.cancelled(),
            },
        );
    }

    fn update_keyboard_focus(&mut self, location: Point<f64, Logical>, serial: Serial) {
        let keyboard = self.seat.get_keyboard().unwrap();
        let touch = self.seat.get_touch();
        let input_method = self.seat.input_method();
        // change the keyboard focus unless the pointer or keyboard is grabbed
        // We test for any matching surface type here but always use the root
        // (in case of a window the toplevel) surface for the focus.
        // So for example if a user clicks on a subsurface or popup the toplevel
        // will receive the keyboard focus. Directly assigning the focus to the
        // matching surface leads to issues with clients dismissing popups and
        // subsurface menus (for example firefox-wayland).
        // see here for a discussion about that issue:
        // https://gitlab.freedesktop.org/wayland/wayland/-/issues/294
        if !self.pointer.is_grabbed()
            && (!keyboard.is_grabbed() || input_method.keyboard_grabbed())
            && !touch.map(|touch| touch.is_grabbed()).unwrap_or(false)
        {
            let output = self.space.output_under(location).next().cloned();
            if let Some(output) = output.as_ref() {
                let output_geo = self.space.output_geometry(output).unwrap();
                if let Some(window) = output
                    .user_data()
                    .get::<FullscreenSurface>()
                    .and_then(|f| f.get())
                    && let Some((_, _)) =
                        window.surface_under(location - output_geo.loc.to_f64(), WindowSurfaceType::ALL)
                {
                    #[cfg(feature = "xwayland")]
                    if let Some(surface) = window.0.x11_surface() {
                        self.xwm.as_mut().unwrap().raise_window(surface).unwrap();
                    }
                    keyboard.set_focus(self, Some(window.into()), serial);
                    return;
                }

                let layers = layer_map_for_output(output);
                if let Some(layer) = layers
                    .layer_under(WlrLayer::Overlay, location - output_geo.loc.to_f64())
                    .or_else(|| layers.layer_under(WlrLayer::Top, location - output_geo.loc.to_f64()))
                    && layer.can_receive_keyboard_focus()
                    && let Some((_, _)) = layer.surface_under(
                        location
                            - output_geo.loc.to_f64()
                            - layers.layer_geometry(layer).unwrap().loc.to_f64(),
                        WindowSurfaceType::ALL,
                    )
                {
                    keyboard.set_focus(self, Some(layer.clone().into()), serial);
                    return;
                }
            }

            if let Some((window, _)) = self.space.element_under(location).map(|(w, p)| (w.clone(), p)) {
                self.space.raise_element(&window, true);
                #[cfg(feature = "xwayland")]
                if let Some(surface) = window.0.x11_surface() {
                    self.xwm.as_mut().unwrap().raise_window(surface).unwrap();
                }
                keyboard.set_focus(self, Some(window.into()), serial);
                return;
            }

            if let Some(output) = output.as_ref() {
                let output_geo = self.space.output_geometry(output).unwrap();
                let layers = layer_map_for_output(output);
                if let Some(layer) = layers
                    .layer_under(WlrLayer::Bottom, location - output_geo.loc.to_f64())
                    .or_else(|| layers.layer_under(WlrLayer::Background, location - output_geo.loc.to_f64()))
                    && layer.can_receive_keyboard_focus()
                    && let Some((_, _)) = layer.surface_under(
                        location
                            - output_geo.loc.to_f64()
                            - layers.layer_geometry(layer).unwrap().loc.to_f64(),
                        WindowSurfaceType::ALL,
                    )
                {
                    keyboard.set_focus(self, Some(layer.clone().into()), serial);
                }
            };
        }
    }

    pub fn surface_under(
        &self,
        pos: Point<f64, Logical>,
    ) -> Option<(PointerFocusTarget, Point<f64, Logical>)> {
        if self.is_locked() {
            return self.lock_surface_under(pos);
        }
        let output = self.space.outputs().find(|o| {
            let geometry = self.space.output_geometry(o).unwrap();
            geometry.contains(pos.to_i32_round())
        })?;
        let output_geo = self.space.output_geometry(output).unwrap();
        let layers = layer_map_for_output(output);

        let mut under = None;
        // The top-most layer surface on a level that takes input there (its input region counts: the shell's
        // full-screen surfaces, like the Welcome tour's, take clicks only where they say).
        let in_layers = |levels: &[WlrLayer]| {
            levels.iter().find_map(|level| {
                layers.layers_on(*level).rev().find_map(|layer| {
                    let layer_loc = layers.layer_geometry(layer)?.loc;
                    layer
                        .surface_under(pos - output_geo.loc.to_f64() - layer_loc.to_f64(), WindowSurfaceType::ALL)
                        .map(|(surface, loc)| (PointerFocusTarget::from(surface), loc + layer_loc + output_geo.loc))
                })
            })
        };
        if let Some((surface, loc)) = output
            .user_data()
            .get::<FullscreenSurface>()
            .and_then(|f| f.get())
            .and_then(|w| w.surface_under(pos - output_geo.loc.to_f64(), WindowSurfaceType::ALL))
        {
            under = Some((surface, loc + output_geo.loc));
        } else if let Some(focus) = in_layers(&[WlrLayer::Overlay, WlrLayer::Top]) {
            under = Some(focus)
        } else if let Some(focus) = self.space.element_under(pos).and_then(|(window, loc)| {
            window
                .surface_under(pos - loc.to_f64(), WindowSurfaceType::ALL)
                .map(|(surface, surf_loc)| (surface, surf_loc + loc))
        }) {
            under = Some(focus);
        } else if let Some(focus) = in_layers(&[WlrLayer::Bottom, WlrLayer::Background]) {
            under = Some(focus)
        };
        under.map(|(s, l)| (s, l.to_f64()))
    }

    fn on_pointer_axis<B: InputBackend>(&mut self, evt: B::PointerAxisEvent) {
        let horizontal_amount = evt
            .amount(input::Axis::Horizontal)
            .unwrap_or_else(|| evt.amount_v120(input::Axis::Horizontal).unwrap_or(0.0) * 15.0 / 120.);
        let vertical_amount = evt
            .amount(input::Axis::Vertical)
            .unwrap_or_else(|| evt.amount_v120(input::Axis::Vertical).unwrap_or(0.0) * 15.0 / 120.);
        let horizontal_amount_discrete = evt.amount_v120(input::Axis::Horizontal);
        let vertical_amount_discrete = evt.amount_v120(input::Axis::Vertical);

        {
            let mut frame = AxisFrame::new(evt.time()).source(evt.source());
            if horizontal_amount != 0.0 {
                frame = frame.relative_direction(Axis::Horizontal, evt.relative_direction(Axis::Horizontal));
                frame = frame.value(Axis::Horizontal, horizontal_amount);
                if let Some(discrete) = horizontal_amount_discrete {
                    frame = frame.v120(Axis::Horizontal, discrete as i32);
                }
            }
            if vertical_amount != 0.0 {
                frame = frame.relative_direction(Axis::Vertical, evt.relative_direction(Axis::Vertical));
                frame = frame.value(Axis::Vertical, vertical_amount);
                if let Some(discrete) = vertical_amount_discrete {
                    frame = frame.v120(Axis::Vertical, discrete as i32);
                }
            }
            if evt.source() == AxisSource::Finger {
                if evt.amount(Axis::Horizontal) == Some(0.0) {
                    frame = frame.stop(Axis::Horizontal);
                }
                if evt.amount(Axis::Vertical) == Some(0.0) {
                    frame = frame.stop(Axis::Vertical);
                }
            }
            let pointer = self.pointer.clone();
            pointer.axis(self, frame);
            pointer.frame(self);
        }
    }

    fn touch_location_transformed<B: InputBackend, E: AbsolutePositionEvent<B>>(
        &self,
        evt: &E,
    ) -> Option<Point<f64, Logical>> {
        let output = self
            .space
            .outputs()
            .find(|output| output.name().starts_with("eDP"))
            .or_else(|| self.space.outputs().next());

        let output = output?;
        let output_geometry = self.space.output_geometry(output)?;

        let transform = output.current_transform();
        let size = transform.invert().transform_size(output_geometry.size);
        Some(
            transform.transform_point_in(evt.position_transformed(size), &size.to_f64())
                + output_geometry.loc.to_f64(),
        )
    }

    fn on_touch_down<B: InputBackend>(&mut self, evt: B::TouchDownEvent) {
        let Some(handle) = self.seat.get_touch() else {
            return;
        };

        let Some(touch_location) = self.touch_location_transformed(&evt) else {
            return;
        };

        let serial = SCOUNTER.next_serial();
        self.update_keyboard_focus(touch_location, serial);

        let under = self.surface_under(touch_location);
        handle.down(
            self,
            under,
            &DownEvent {
                slot: evt.slot(),
                location: touch_location,
                serial,
                time: evt.time(),
            },
        );
    }

    fn on_touch_up<B: InputBackend>(&mut self, evt: B::TouchUpEvent) {
        let Some(handle) = self.seat.get_touch() else {
            return;
        };
        let serial = SCOUNTER.next_serial();
        handle.up(
            self,
            &UpEvent {
                slot: evt.slot(),
                serial,
                time: evt.time(),
            },
        )
    }

    fn on_touch_motion<B: InputBackend>(&mut self, evt: B::TouchMotionEvent) {
        let Some(handle) = self.seat.get_touch() else {
            return;
        };
        let Some(touch_location) = self.touch_location_transformed(&evt) else {
            return;
        };

        let under = self.surface_under(touch_location);
        handle.motion(
            self,
            under,
            &smithay::input::touch::MotionEvent {
                slot: evt.slot(),
                location: touch_location,
                time: evt.time(),
            },
        );
    }

    fn on_touch_frame<B: InputBackend>(&mut self, _evt: B::TouchFrameEvent) {
        let Some(handle) = self.seat.get_touch() else {
            return;
        };
        handle.frame(self);
    }

    fn on_touch_cancel<B: InputBackend>(&mut self, _evt: B::TouchCancelEvent) {
        let Some(handle) = self.seat.get_touch() else {
            return;
        };
        handle.cancel(self);
    }

    fn on_device_added<B: InputBackend>(&mut self, device: B::Device) {
        let dh = &self.display_handle;
        if device.has_capability(DeviceCapability::TabletTool) {
            self.seat
                .tablet_seat()
                .add_wp_tablet(dh, &TabletDescriptor::from(&device));
        }
        if device.has_capability(DeviceCapability::Touch) && self.seat.get_touch().is_none() {
            self.seat.add_touch();
        }
    }

    fn on_device_removed<B: InputBackend>(&mut self, device: B::Device) {
        if device.has_capability(DeviceCapability::TabletTool) {
            let tablet_seat = self.seat.tablet_seat();

            tablet_seat.remove_tablet(&TabletDescriptor::from(&device));

            // If there are no tablets in seat we can remove all tools
            if tablet_seat.count_tablets() == 0 {
                tablet_seat.clear_tools();
            }
        }
    }
}

#[cfg(any(feature = "winit", feature = "x11"))]
impl<BackendData: Backend> HuginnState<BackendData> {
    pub fn process_input_event_windowed<B: InputBackend>(&mut self, event: InputEvent<B>, output_name: &str) {
        self.touched();
        match event {
            InputEvent::Keyboard { event } => {
                self.touched();
                let action = self.keyboard_key_to_action::<B>(event);
                let _ = output_name;
                self.process_common_key_action(action)
            }

            InputEvent::PointerMotionAbsolute { event } => {
                let output = self
                    .space
                    .outputs()
                    .find(|o| o.name() == output_name)
                    .unwrap()
                    .clone();
                self.on_pointer_move_absolute_windowed::<B>(event, &output)
            }
            InputEvent::PointerButton { event } => self.on_pointer_button::<B>(event),
            InputEvent::PointerAxis { event } => self.on_pointer_axis::<B>(event),

            InputEvent::GestureSwipeBegin { event, .. } => self.on_gesture_swipe_begin::<B>(event),
            InputEvent::GestureSwipeUpdate { event, .. } => self.on_gesture_swipe_update::<B>(event),
            InputEvent::GestureSwipeEnd { event, .. } => self.on_gesture_swipe_end::<B>(event),
            InputEvent::GesturePinchBegin { event, .. } => self.on_gesture_pinch_begin::<B>(event),
            InputEvent::GesturePinchUpdate { event, .. } => self.on_gesture_pinch_update::<B>(event),
            InputEvent::GesturePinchEnd { event, .. } => self.on_gesture_pinch_end::<B>(event),
            InputEvent::GestureHoldBegin { event, .. } => self.on_gesture_hold_begin::<B>(event),
            InputEvent::GestureHoldEnd { event, .. } => self.on_gesture_hold_end::<B>(event),

            InputEvent::TouchDown { event } => self.on_touch_down::<B>(event),
            InputEvent::TouchUp { event } => self.on_touch_up::<B>(event),
            InputEvent::TouchMotion { event } => self.on_touch_motion::<B>(event),
            InputEvent::TouchFrame { event } => self.on_touch_frame::<B>(event),
            InputEvent::TouchCancel { event } => self.on_touch_cancel::<B>(event),
            InputEvent::DeviceAdded { device } => self.on_device_added::<B>(device),
            InputEvent::DeviceRemoved { device } => self.on_device_removed::<B>(device),
            _ => (), // other events are not handled in anvil (yet)
        }
    }

    fn on_pointer_move_absolute_windowed<B: InputBackend>(
        &mut self,
        evt: B::PointerMotionAbsoluteEvent,
        output: &Output,
    ) {
        let output_geo = self.space.output_geometry(output).unwrap();

        let pos = evt.position_transformed(output_geo.size) + output_geo.loc.to_f64();
        let serial = SCOUNTER.next_serial();

        let pointer = self.pointer.clone();
        let under = self.surface_under(pos);
        pointer.motion(
            self,
            under,
            &MotionEvent {
                location: pos,
                serial,
                time: evt.time(),
            },
        );
        pointer.frame(self);
    }

    pub fn release_all_keys(&mut self) {
        let keyboard = self.seat.get_keyboard().unwrap();
        for keycode in keyboard.pressed_keys() {
            keyboard.input(
                self,
                keycode,
                KeyState::Released,
                SCOUNTER.next_serial(),
                InputTime::now(),
                |_, _, _| FilterResult::Forward::<bool>,
            );
        }
    }
}

#[cfg(feature = "udev")]
impl HuginnState<UdevData> {
    pub fn process_input_event<B: InputBackend>(&mut self, dh: &DisplayHandle, event: InputEvent<B>) {
        self.touched();
        match event {
            InputEvent::Keyboard { event, .. } => {
                self.touched();
                match self.keyboard_key_to_action::<B>(event) {
                    KeyAction::VtSwitch(vt) => {
                        info!(to = vt, "Trying to switch vt");
                        if let Err(err) = self.backend_data.session.change_vt(vt) {
                            error!(vt, "Error switching vt: {}", err);
                        }
                    }
                    action => self.process_common_key_action(action),
                }
            }
            InputEvent::PointerMotion { event, .. } => self.on_pointer_move::<B>(dh, event),
            InputEvent::PointerMotionAbsolute { event, .. } => self.on_pointer_move_absolute::<B>(dh, event),
            InputEvent::PointerButton { event, .. } => self.on_pointer_button::<B>(event),
            InputEvent::PointerAxis { event, .. } => self.on_pointer_axis::<B>(event),
            InputEvent::TabletToolAxis { event, .. } => self.on_tablet_tool_axis::<B>(event),
            InputEvent::TabletToolProximity { event, .. } => self.on_tablet_tool_proximity::<B>(dh, event),
            InputEvent::TabletToolTip { event, .. } => self.on_tablet_tool_tip::<B>(event),
            InputEvent::TabletToolButton { event, .. } => self.on_tablet_button::<B>(event),
            InputEvent::GestureSwipeBegin { event, .. } => self.on_gesture_swipe_begin::<B>(event),
            InputEvent::GestureSwipeUpdate { event, .. } => self.on_gesture_swipe_update::<B>(event),
            InputEvent::GestureSwipeEnd { event, .. } => self.on_gesture_swipe_end::<B>(event),
            InputEvent::GesturePinchBegin { event, .. } => self.on_gesture_pinch_begin::<B>(event),
            InputEvent::GesturePinchUpdate { event, .. } => self.on_gesture_pinch_update::<B>(event),
            InputEvent::GesturePinchEnd { event, .. } => self.on_gesture_pinch_end::<B>(event),
            InputEvent::GestureHoldBegin { event, .. } => self.on_gesture_hold_begin::<B>(event),
            InputEvent::GestureHoldEnd { event, .. } => self.on_gesture_hold_end::<B>(event),

            InputEvent::TouchDown { event } => self.on_touch_down::<B>(event),
            InputEvent::TouchUp { event } => self.on_touch_up::<B>(event),
            InputEvent::TouchMotion { event } => self.on_touch_motion::<B>(event),
            InputEvent::TouchFrame { event } => self.on_touch_frame::<B>(event),
            InputEvent::TouchCancel { event } => self.on_touch_cancel::<B>(event),

            InputEvent::DeviceAdded { device } => self.on_device_added::<B>(device),
            InputEvent::DeviceRemoved { device } => self.on_device_removed::<B>(device),
            _ => {
                // other events are not handled in anvil (yet)
            }
        }
    }

    fn on_pointer_move<B: InputBackend>(&mut self, _dh: &DisplayHandle, evt: B::PointerMotionEvent) {
        let mut pointer_location = self.pointer.current_location();
        let serial = SCOUNTER.next_serial();

        let pointer = self.pointer.clone();
        let under = self.surface_under(pointer_location);

        let mut pointer_locked = false;
        let mut pointer_confined = false;
        let mut confine_region = None;
        if let Some((surface, surface_loc)) = under
            .as_ref()
            .and_then(|(target, l)| Some((target.wl_surface()?, l)))
        {
            with_pointer_constraint(&surface, &pointer, |constraint| match constraint {
                Some(constraint) if constraint.is_active() => {
                    // Constraint does not apply if not within region
                    if !constraint
                        .region()
                        .is_none_or(|x| x.contains((pointer_location - *surface_loc).to_i32_round()))
                    {
                        return;
                    }
                    match &*constraint {
                        PointerConstraint::Locked(_locked) => {
                            pointer_locked = true;
                        }
                        PointerConstraint::Confined(confine) => {
                            pointer_confined = true;
                            confine_region = confine.region().cloned();
                        }
                    }
                }
                _ => {}
            });
        }

        pointer.relative_motion(
            self,
            under.clone(),
            &RelativeMotionEvent {
                delta: evt.delta(),
                delta_unaccel: evt.delta_unaccel(),
                time: evt.time(),
            },
        );

        // If pointer is locked, only emit relative motion
        if pointer_locked {
            pointer.frame(self);
            return;
        }

        // Clamp delta, such that the pointer never moves out of bounds
        let mut delta = self.clamp_coords(pointer_location + evt.delta()) - pointer_location;

        // Clamp the individual x and y components of delta to respect confinement regions
        if pointer_confined
            && let Some((_, surface_loc)) = &under
            && let Some(region) = &confine_region
        {
            // Clamp delta.x
            if !region.contains((pointer_location + Point::new(delta.x, 0f64) - *surface_loc).to_i32_round())
            {
                delta.x = 0f64;
            }

            // Clamp delta.y
            if !region.contains((pointer_location + Point::new(0f64, delta.y) - *surface_loc).to_i32_round())
            {
                delta.y = 0f64;
            }
        }

        pointer_location += delta;

        let new_under = self.surface_under(pointer_location);

        // If confined, don't move pointer if it would go outside surface
        if pointer_confined
            && let Some((surface, _)) = &under
            && new_under.as_ref().and_then(|(under, _)| under.wl_surface()) != surface.wl_surface()
        {
            pointer.frame(self);
            return;
        }

        pointer.motion(
            self,
            under,
            &MotionEvent {
                location: pointer_location,
                serial,
                time: evt.time(),
            },
        );
        pointer.frame(self);

        // If pointer is now in a constraint region, activate it
        // TODO Anywhere else pointer is moved needs to do this
        if let Some((under, surface_location)) =
            new_under.and_then(|(target, loc)| Some((target.wl_surface()?.into_owned(), loc)))
        {
            with_pointer_constraint(&under, &pointer, |constraint| match constraint {
                Some(constraint) if !constraint.is_active() => {
                    let point = (pointer_location - surface_location).to_i32_round();
                    if constraint.region().is_none_or(|region| region.contains(point)) {
                        constraint.activate();
                    }
                }
                _ => {}
            });
        }
    }

    fn on_pointer_move_absolute<B: InputBackend>(
        &mut self,
        _dh: &DisplayHandle,
        evt: B::PointerMotionAbsoluteEvent,
    ) {
        let serial = SCOUNTER.next_serial();

        let max_x = self
            .space
            .outputs()
            .fold(0, |acc, o| acc + self.space.output_geometry(o).unwrap().size.w);

        let max_h_output = self
            .space
            .outputs()
            .max_by_key(|o| self.space.output_geometry(o).unwrap().size.h)
            .unwrap();

        let max_y = self.space.output_geometry(max_h_output).unwrap().size.h;

        let mut pointer_location = (evt.x_transformed(max_x), evt.y_transformed(max_y)).into();

        // clamp to screen limits
        pointer_location = self.clamp_coords(pointer_location);

        let pointer = self.pointer.clone();
        let under = self.surface_under(pointer_location);

        pointer.motion(
            self,
            under,
            &MotionEvent {
                location: pointer_location,
                serial,
                time: evt.time(),
            },
        );
        pointer.frame(self);
    }

    fn on_tablet_tool_axis<B: InputBackend>(&mut self, evt: B::TabletToolAxisEvent) {
        let tablet_seat = self.seat.tablet_seat();

        if let Some(pointer_location) = self.touch_location_transformed(&evt) {
            let pointer = self.pointer.clone();
            let under = self.surface_under(pointer_location);
            let tool = tablet_seat.get_tool(&evt.tool());
            let time = InputTime::now();

            pointer.motion(
                self,
                under.clone(),
                &MotionEvent {
                    location: pointer_location,
                    serial: SCOUNTER.next_serial(),
                    time,
                },
            );

            if let Some(tool) = tool {
                let frame = tablet::tool::AxisFrame {
                    pressure: evt.pressure_has_changed().then(|| evt.pressure()),
                    distance: evt.distance_has_changed().then(|| evt.distance()),
                    tilt: evt.tilt_has_changed().then(|| evt.tilt()),
                    rotation: evt.rotation_has_changed().then(|| evt.rotation()),
                    slider: evt.slider_has_changed().then(|| evt.slider_position()),
                    wheel: evt
                        .wheel_has_changed()
                        .then(|| (evt.wheel_delta(), evt.wheel_delta_discrete())),
                };

                tool.axis(self, frame);

                tool.motion(
                    self,
                    under,
                    &tablet::tool::MotionEvent {
                        location: pointer_location,
                        serial: SCOUNTER.next_serial(),
                        time,
                    },
                );

                tool.frame(self, time);
            }

            pointer.frame(self);
        }
    }

    fn on_tablet_tool_proximity<B: InputBackend>(
        &mut self,
        dh: &DisplayHandle,
        evt: B::TabletToolProximityEvent,
    ) {
        let tablet_seat = self.seat.tablet_seat();

        if let Some(pointer_location) = self.touch_location_transformed(&evt) {
            let tool = evt.tool();

            let pointer = self.pointer.clone();
            let under = self.surface_under(pointer_location);
            let tablet = tablet_seat.get_tablet(&TabletDescriptor::from(&evt.device()));
            let tool = tablet_seat
                .get_tool(&tool)
                .unwrap_or_else(|| tablet_seat.add_wp_tool(self, dh, &tool));

            pointer.motion(
                self,
                under.clone(),
                &MotionEvent {
                    location: pointer_location,
                    serial: SCOUNTER.next_serial(),
                    time: evt.time(),
                },
            );
            pointer.frame(self);

            if let Some(tablet) = tablet {
                let frame = tablet::tool::AxisFrame {
                    pressure: evt.pressure_has_changed().then(|| evt.pressure()),
                    distance: evt.distance_has_changed().then(|| evt.distance()),
                    tilt: evt.tilt_has_changed().then(|| evt.tilt()),
                    rotation: evt.rotation_has_changed().then(|| evt.rotation()),
                    slider: evt.slider_has_changed().then(|| evt.slider_position()),
                    wheel: evt
                        .wheel_has_changed()
                        .then(|| (evt.wheel_delta(), evt.wheel_delta_discrete())),
                };

                match evt.state() {
                    ProximityState::In => {
                        tool.proximity_in(
                            self,
                            under,
                            tablet,
                            &tablet::tool::ProximityInEvent {
                                location: pointer_location,
                                axis: Some(frame),
                                serial: SCOUNTER.next_serial(),
                                time: evt.time(),
                            },
                        );
                    }
                    ProximityState::Out => {
                        tool.proximity_out(
                            self,
                            &tablet::tool::ProximityOutEvent {
                                serial: SCOUNTER.next_serial(),
                                time: evt.time(),
                            },
                        );
                    }
                }

                // Doing this in an idle handler would allow other events (e.g. buttons) to be
                // sent as part of the same frame, which is closer to what the protocol
                // expect, and let well behaved clients accumulate events.
                tool.frame(self, evt.time());
            }
        }
    }

    fn on_tablet_tool_tip<B: InputBackend>(&mut self, evt: B::TabletToolTipEvent) {
        let tool = self.seat.tablet_seat().get_tool(&evt.tool());

        if let Some(tool) = tool {
            let serial = SCOUNTER.next_serial();

            match evt.tip_state() {
                TabletToolTipState::Down => {
                    tool.down(
                        self,
                        &tablet::tool::DownEvent {
                            serial,
                            time: evt.time(),
                        },
                    );

                    // change the keyboard focus
                    self.update_keyboard_focus(self.pointer.current_location(), serial);
                }
                TabletToolTipState::Up => {
                    tool.up(
                        self,
                        &tablet::tool::UpEvent {
                            serial,
                            time: evt.time(),
                        },
                    );
                }
            }

            tool.frame(self, evt.time());
        }
    }

    fn on_tablet_button<B: InputBackend>(&mut self, evt: B::TabletToolButtonEvent) {
        let tool = self.seat.tablet_seat().get_tool(&evt.tool());

        if let Some(tool) = tool {
            tool.button(
                self,
                &tablet::tool::ButtonEvent {
                    serial: SCOUNTER.next_serial(),
                    button: evt.button(),
                    state: evt.button_state(),
                    time: evt.time(),
                },
            );

            tool.frame(self, evt.time());
        }
    }

    fn clamp_coords(&self, pos: Point<f64, Logical>) -> Point<f64, Logical> {
        if self.space.outputs().next().is_none() {
            return pos;
        }

        let (pos_x, pos_y) = pos.into();
        let max_x = self
            .space
            .outputs()
            .fold(0, |acc, o| acc + self.space.output_geometry(o).unwrap().size.w);
        let clamped_x = pos_x.clamp(0.0, max_x as f64);
        let max_y = self
            .space
            .outputs()
            .find(|o| {
                let geo = self.space.output_geometry(o).unwrap();
                geo.contains((clamped_x as i32, 0))
            })
            .map(|o| self.space.output_geometry(o).unwrap().size.h);

        if let Some(max_y) = max_y {
            let clamped_y = pos_y.clamp(0.0, max_y as f64);
            (clamped_x, clamped_y).into()
        } else {
            (clamped_x, pos_y).into()
        }
    }
}

/// Possible results of a keyboard action
#[allow(dead_code)] // some of these are only read if udev is enabled
#[derive(Debug)]
enum KeyAction {
    /// Quit the compositor (Ctrl+Alt+Backspace, only with HUGINN_DEV=1)
    Quit,
    /// Switch to a text console (Ctrl+Alt+F1…)
    VtSwitch(i32),
    /// Super on its own: the start menu
    Launcher,
    /// Super+Space: Search everything
    Search,
    /// Super+L
    Lock,
    /// Something the shell does: "today" (Super+T), "menu" (Alt on its own)…
    Shell(&'static str),
    /// Super+Tab: the Overview
    Overview,
    /// Super+Ctrl+←/→ (the space beside), Super+Shift+←/→ (taking the window in front along)
    SpaceStep(i32, bool),
    /// Super+1…9
    SpaceGo(usize),
    /// Super+←/→/↑/↓: through the sizes
    Snap(&'static str),
    /// Alt+F4
    CloseWindow,
    /// Super+Up, Super+Down
    Maximise,
    Minimise,
    /// Alt+Tab (forward), Alt+Shift+Tab
    Switch(bool),
    /// Print ("screen"), Shift+Print and Super+Shift+S ("choose")
    Screenshot(&'static str),
    /// Volume, brightness, media and power keys, for the session daemon
    Hardware(&'static str),
    /// Do nothing more
    None,
}

fn hardware_key(keysym: Keysym) -> Option<&'static str> {
    Some(match keysym {
        Keysym::XF86_AudioRaiseVolume => "volumeUp",
        Keysym::XF86_AudioLowerVolume => "volumeDown",
        Keysym::XF86_AudioMute => "volumeMute",
        Keysym::XF86_AudioMicMute => "micMute",
        Keysym::XF86_MonBrightnessUp => "brightnessUp",
        Keysym::XF86_MonBrightnessDown => "brightnessDown",
        Keysym::XF86_KbdBrightnessUp => "keyboardLightUp",
        Keysym::XF86_KbdBrightnessDown => "keyboardLightDown",
        Keysym::XF86_KbdLightOnOff => "keyboardLight",
        Keysym::XF86_PowerOff => "power",
        Keysym::XF86_Sleep => "sleep",
        Keysym::XF86_Suspend => "suspend",
        Keysym::XF86_AudioPlay => "playPause",
        Keysym::XF86_AudioPause => "pause",
        Keysym::XF86_AudioNext => "next",
        Keysym::XF86_AudioPrev => "previous",
        Keysym::XF86_AudioStop => "stop",
        _ => return None,
    })
}

fn process_keyboard_shortcut(modifiers: ModifiersState, keysym: Keysym) -> Option<KeyAction> {
    let dev = std::env::var("HUGINN_DEV").is_ok_and(|v| v == "1");
    if dev && modifiers.ctrl && modifiers.alt && keysym == Keysym::BackSpace {
        Some(KeyAction::Quit)
    } else if (xkb::KEY_XF86Switch_VT_1..=xkb::KEY_XF86Switch_VT_12).contains(&keysym.raw()) {
        Some(KeyAction::VtSwitch((keysym.raw() - xkb::KEY_XF86Switch_VT_1 + 1) as i32))
    } else if let Some(name) = hardware_key(keysym) {
        Some(KeyAction::Hardware(name))
    } else if modifiers.logo && keysym == Keysym::space {
        Some(KeyAction::Search)
    } else if modifiers.logo && (keysym == Keysym::l || keysym == Keysym::L) {
        Some(KeyAction::Lock)
    } else if modifiers.logo && !modifiers.shift && (keysym == Keysym::t || keysym == Keysym::T) {
        Some(KeyAction::Shell("today"))
    } else if modifiers.logo && keysym == Keysym::Tab {
        Some(KeyAction::Overview)
    } else if modifiers.logo && modifiers.ctrl && (keysym == Keysym::Left || keysym == Keysym::Right) {
        Some(KeyAction::SpaceStep(if keysym == Keysym::Left { -1 } else { 1 }, false))
    } else if modifiers.logo && modifiers.shift && (keysym == Keysym::Left || keysym == Keysym::Right) {
        Some(KeyAction::SpaceStep(if keysym == Keysym::Left { -1 } else { 1 }, true))
    } else if modifiers.logo && !modifiers.shift && (Keysym::_1.raw()..=Keysym::_9.raw()).contains(&keysym.raw()) {
        Some(KeyAction::SpaceGo((keysym.raw() - Keysym::_1.raw()) as usize))
    } else if modifiers.logo && keysym == Keysym::Left {
        Some(KeyAction::Snap("left"))
    } else if modifiers.logo && keysym == Keysym::Right {
        Some(KeyAction::Snap("right"))
    } else if modifiers.alt && keysym == Keysym::F4 {
        Some(KeyAction::CloseWindow)
    } else if modifiers.logo && keysym == Keysym::Up {
        Some(KeyAction::Snap("up"))
    } else if modifiers.logo && keysym == Keysym::Down {
        Some(KeyAction::Snap("down"))
    } else if modifiers.alt && (keysym == Keysym::Tab || keysym == Keysym::ISO_Left_Tab) {
        Some(KeyAction::Switch(!(modifiers.shift || keysym == Keysym::ISO_Left_Tab)))
    } else if keysym == Keysym::Print {
        Some(KeyAction::Screenshot(if modifiers.shift { "choose" } else { "screen" }))
    } else if modifiers.logo && modifiers.shift && (keysym == Keysym::s || keysym == Keysym::S) {
        Some(KeyAction::Screenshot("choose"))
    } else {
        None
    }
}

impl<BackendData: Backend> VirtualKeyboardHandler for HuginnState<BackendData> {
    fn process_virtual_keyboard_event(&mut self, event: InputEvent<VirtualKeyboardBackend>) {
        let keyboard = self.seat.get_keyboard().unwrap();

        match event {
            // The device's keycodes only mean anything under its own keymap, so
            // activate it before processing events. Anvil never switches back;
            // a real compositor should track which device the seat keymap came
            // from and restore its configured one when a physical key arrives.
            InputEvent::DeviceAdded { device }
            | InputEvent::Special(VirtualKeyboardSpecialEvent::KeymapChanged { device }) => {
                let Some(keymap) = device.keymap() else {
                    return;
                };
                if let Err(err) = keyboard.set_keymap_from_keymap_file(self, keymap) {
                    warn!(?err, "Failed to apply virtual keyboard keymap");
                }
            }
            InputEvent::Keyboard { event } => {
                match self.keyboard_key_to_action::<VirtualKeyboardBackend>(event) {
                    // VT switching is out of scope for virtual keyboards.
                    KeyAction::VtSwitch(_) => {}
                    action @ (KeyAction::None
                    | KeyAction::Launcher
                    | KeyAction::Search
                    | KeyAction::Shell(_)
                    | KeyAction::Hardware(_)) => self.process_common_key_action(action),
                    action => debug!(?action, "ignoring key action from a virtual keyboard"),
                }
            }
            InputEvent::Special(VirtualKeyboardSpecialEvent::Modifiers {
                mods_depressed,
                mods_latched,
                mods_locked,
                group,
                ..
            }) => {
                keyboard.with_xkb_state(self, |mut context| {
                    context.set_modifier_mask(mods_depressed, mods_latched, mods_locked, group)
                });
            }
            _ => (),
        }
    }
}
