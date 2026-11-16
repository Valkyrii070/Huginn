//! HDR pictures from apps (wp-color-management-v1): games and video players say their surfaces are HDR (PQ, BT.2020)
//! and ask what each screen wants. On an HDR screen such a surface's pixels go out as they are (the HDR pass in
//! look.rs leaves them alone, except where something is drawn over them); everything else is still turned into HDR
//! from sRGB. A screen that isn't in HDR asks for sRGB, so apps draw SDR there.
//!
//! What's offered: the parametric creator with named primaries (sRGB, BT.2020) and named transfer functions (sRGB,
//! gamma 2.2, PQ), luminances, and the perceptual intent. ICC profiles and scRGB aren't.

use std::sync::{
    Mutex,
    atomic::{AtomicU32, Ordering},
};

use smithay::{
    output::Output,
    reexports::{
        wayland_protocols::wp::color_management::v1::server::{
            wp_color_management_output_v1::{self, WpColorManagementOutputV1},
            wp_color_management_surface_feedback_v1::{self, WpColorManagementSurfaceFeedbackV1},
            wp_color_management_surface_v1::{self, WpColorManagementSurfaceV1},
            wp_color_manager_v1::{self, Feature, Primaries, RenderIntent, TransferFunction, WpColorManagerV1},
            wp_image_description_creator_icc_v1::{self, WpImageDescriptionCreatorIccV1},
            wp_image_description_creator_params_v1::{self, WpImageDescriptionCreatorParamsV1},
            wp_image_description_info_v1::WpImageDescriptionInfoV1,
            wp_image_description_v1::{self, Cause, WpImageDescriptionV1},
        },
        wayland_server::{
            Client, DataInit, DisplayHandle, New, Resource, Weak, WEnum,
            backend::ClientId,
            protocol::{wl_output::WlOutput, wl_surface::WlSurface},
        },
    },
    utils::{Physical, Rectangle},
    wayland::{Dispatch2, GlobalDispatch2, compositor::with_states},
};

use crate::state::{Backend, HuginnState};

/// What a picture is made of.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Desc {
    pub id: u32,
    pub pq: bool,
    pub bt2020: bool,
    /// min (0.0001 cd/m²), max, reference white (cd/m²)
    pub lum: (u32, u32, u32),
}

static NEXT: AtomicU32 = AtomicU32::new(10_000);

fn fresh(pq: bool, bt2020: bool, lum: (u32, u32, u32)) -> Desc {
    Desc { id: NEXT.fetch_add(1, Ordering::Relaxed), pq, bt2020, lum }
}

/// What a screen wants: HDR (PQ, BT.2020, its SDR white) while HDR is on, else sRGB.
pub fn screen_desc(output: &Output) -> Desc {
    match crate::displays::hdr_sdr(output) {
        Some(sdr) => Desc { id: 2000 + sdr.round() as u32, pq: true, bt2020: true, lum: (50, 1000, sdr.round() as u32) },
        None => Desc { id: 1, pq: false, bt2020: false, lum: (2000, 80, 80) },
    }
}

/// The surface's own description, if it set one.
struct SurfaceDesc(Mutex<Option<Desc>>);

/// Whether this surface's pixels are HDR (PQ).
pub fn is_hdr(surface: &WlSurface) -> bool {
    with_states(surface, |s| s.data_map.get::<SurfaceDesc>().and_then(|d| *d.0.lock().unwrap()).is_some_and(|d| d.pq))
}

/// Objects to tell when a screen's description changes.
static OUTPUTS: Mutex<Vec<(WpColorManagementOutputV1, WlOutput)>> = Mutex::new(Vec::new());
static FEEDBACK: Mutex<Vec<(WpColorManagementSurfaceFeedbackV1, Weak<WlSurface>)>> = Mutex::new(Vec::new());

fn preferred_for(surface: &WlSurface, fallback: Option<&Output>) -> Option<Desc> {
    let out = with_states(surface, |s| smithay::desktop::utils::surface_primary_scanout_output(surface, s));
    out.as_ref().or(fallback).map(screen_desc)
}

/// HDR was turned on or off on a screen (or its SDR white changed): apps that asked are told.
pub fn screen_changed(output: &Output) {
    for (obj, wl) in OUTPUTS.lock().unwrap().iter() {
        if obj.is_alive() && Output::from_resource(wl).as_ref() == Some(output) {
            obj.image_description_changed();
        }
    }
    for (obj, surface) in FEEDBACK.lock().unwrap().iter() {
        if let (true, Ok(surface)) = (obj.is_alive(), surface.upgrade()) {
            if let Some(d) = preferred_for(&surface, Some(output)) {
                obj.preferred_changed(d.id);
            }
        }
    }
}

/// On an HDR screen: the parts of HDR surfaces with nothing over them (physical, the screen's own coordinates),
/// which the HDR pass leaves as they are.
pub fn hdr_parts(space: &smithay::desktop::Space<crate::shell::WindowElement>, output: &Output, pointer: smithay::utils::Point<f64, smithay::utils::Logical>) -> Vec<Rectangle<i32, Physical>> {
    use smithay::{
        desktop::{layer_map_for_output, space::SpaceElement},
        wayland::shell::wlr_layer::Layer,
    };
    let Some(geo) = space.output_geometry(output) else { return Vec::new() };
    let scale = output.current_scale().fractional_scale();
    let local = |r: Rectangle<i32, smithay::utils::Logical>| Rectangle::new(r.loc - geo.loc, r.size).to_physical_precise_round(scale);
    // over everything: the pointer, the bar, the dock, notifications
    let mut over: Vec<Rectangle<i32, Physical>> =
        vec![local(Rectangle::new(pointer.to_i32_round() - smithay::utils::Point::from((8, 8)), (72, 72).into()))];
    let map = layer_map_for_output(output);
    for layer in map.layers().filter(|l| matches!(l.layer(), Layer::Top | Layer::Overlay)) {
        if let Some(g) = map.layer_geometry(layer) {
            over.push(Rectangle::new(g.loc, g.size).to_physical_precise_round(scale));
        }
    }
    let mut parts = Vec::new();
    let windows: Vec<_> = space.elements_for_output(output).collect();
    for w in windows.iter().rev() {
        let Some(loc) = space.element_location(w) else { continue };
        let hdr = w.wl_surface().is_some_and(|s| is_hdr(&s));
        if hdr {
            let g = w.geometry();
            let mine = local(Rectangle::new(loc + g.loc, g.size));
            parts.extend(Rectangle::subtract_rects_many([mine], over.iter().copied()));
        }
        over.push(local(Rectangle::new(loc + w.bbox().loc, w.bbox().size)));
    }
    parts
}

// ------------------------------------------------------------------------------------------------- the protocol
pub struct ManagerGlobal;
pub struct ManagerData;
pub struct OutputData;
pub struct SurfaceData(Weak<WlSurface>);
pub struct FeedbackData(Weak<WlSurface>);
#[derive(Default)]
pub struct ParamsData(Mutex<(Option<bool>, Option<bool>, Option<(u32, u32, u32)>)>);
pub struct IccData;
/// An image description; `info`: whether the app may ask what's in it (those from screens and preferences).
pub struct DescData(pub Desc, pub bool);
pub struct InfoData;

pub fn init<B: Backend + 'static>(dh: &DisplayHandle) {
    dh.create_global::<HuginnState<B>, WpColorManagerV1, _>(1, ManagerGlobal);
}

fn ready<B: Backend + 'static>(data_init: &mut DataInit<'_, HuginnState<B>>, id: New<WpImageDescriptionV1>, d: Desc, info: bool) {
    let obj = data_init.init(id, DescData(d, info));
    obj.ready(d.id);
}

impl<B: Backend + 'static> GlobalDispatch2<WpColorManagerV1, HuginnState<B>> for ManagerGlobal {
    fn bind(
        &self,
        _state: &mut HuginnState<B>,
        _handle: &DisplayHandle,
        _client: &Client,
        resource: New<WpColorManagerV1>,
        data_init: &mut DataInit<'_, HuginnState<B>>,
    ) {
        let m = data_init.init(resource, ManagerData);
        m.supported_intent(RenderIntent::Perceptual);
        m.supported_feature(Feature::Parametric);
        m.supported_feature(Feature::SetLuminances);
        for tf in [TransferFunction::Srgb, TransferFunction::Gamma22, TransferFunction::St2084Pq] {
            m.supported_tf_named(tf);
        }
        for p in [Primaries::Srgb, Primaries::Bt2020] {
            m.supported_primaries_named(p);
        }
        m.done();
    }
}

impl<B: Backend + 'static> Dispatch2<WpColorManagerV1, HuginnState<B>> for ManagerData {
    fn request(
        &self,
        state: &mut HuginnState<B>,
        _client: &Client,
        resource: &WpColorManagerV1,
        request: wp_color_manager_v1::Request,
        _dhandle: &DisplayHandle,
        data_init: &mut DataInit<'_, HuginnState<B>>,
    ) {
        use wp_color_manager_v1::Request;
        match request {
            Request::GetOutput { id, output } => {
                let obj = data_init.init(id, OutputData);
                OUTPUTS.lock().unwrap().push((obj, output));
            }
            Request::GetSurface { id, surface } => {
                let taken = with_states(&surface, |s| s.data_map.get::<SurfaceDesc>().is_some_and(|d| d.0.lock().unwrap().is_some()));
                if taken {
                    resource.post_error(wp_color_manager_v1::Error::SurfaceExists, "the surface has a color management surface already");
                    return;
                }
                with_states(&surface, |s| {
                    s.data_map.insert_if_missing_threadsafe(|| SurfaceDesc(Mutex::new(None)));
                });
                data_init.init(id, SurfaceData(surface.downgrade()));
            }
            Request::GetSurfaceFeedback { id, surface } => {
                let obj = data_init.init(id, FeedbackData(surface.downgrade()));
                FEEDBACK.lock().unwrap().push((obj, surface.downgrade()));
            }
            Request::CreateIccCreator { obj } => {
                data_init.init(obj, IccData);
                resource.post_error(wp_color_manager_v1::Error::UnsupportedFeature, "ICC profiles aren't supported");
            }
            Request::CreateParametricCreator { obj } => {
                data_init.init(obj, ParamsData::default());
            }
            Request::CreateWindowsScrgb { image_description } => {
                let obj = data_init.init(image_description, DescData(fresh(false, false, (0, 0, 0)), false));
                obj.failed(Cause::Unsupported, "scRGB isn't supported".into());
            }
            Request::Destroy => {}
            _ => {}
        }
        let _ = state;
    }
}

impl<B: Backend + 'static> Dispatch2<WpColorManagementOutputV1, HuginnState<B>> for OutputData {
    fn request(
        &self,
        _state: &mut HuginnState<B>,
        _client: &Client,
        resource: &WpColorManagementOutputV1,
        request: wp_color_management_output_v1::Request,
        _dhandle: &DisplayHandle,
        data_init: &mut DataInit<'_, HuginnState<B>>,
    ) {
        if let wp_color_management_output_v1::Request::GetImageDescription { image_description } = request {
            let wl = OUTPUTS.lock().unwrap().iter().find(|(o, _)| o == resource).map(|(_, w)| w.clone());
            match wl.and_then(|w| Output::from_resource(&w)) {
                Some(output) => ready(data_init, image_description, screen_desc(&output), true),
                None => {
                    let obj = data_init.init(image_description, DescData(fresh(false, false, (0, 0, 0)), false));
                    obj.failed(Cause::NoOutput, "the screen is gone".into());
                }
            }
        }
    }

    fn destroyed(&self, _state: &mut HuginnState<B>, _client: ClientId, resource: &WpColorManagementOutputV1) {
        OUTPUTS.lock().unwrap().retain(|(o, _)| o != resource);
    }
}

impl<B: Backend + 'static> Dispatch2<WpColorManagementSurfaceV1, HuginnState<B>> for SurfaceData {
    fn request(
        &self,
        _state: &mut HuginnState<B>,
        _client: &Client,
        resource: &WpColorManagementSurfaceV1,
        request: wp_color_management_surface_v1::Request,
        _dhandle: &DisplayHandle,
        _data_init: &mut DataInit<'_, HuginnState<B>>,
    ) {
        use wp_color_management_surface_v1::Request;
        let Ok(surface) = self.0.upgrade() else { return };
        let set = |d: Option<Desc>| {
            with_states(&surface, |s| {
                if let Some(sd) = s.data_map.get::<SurfaceDesc>() {
                    *sd.0.lock().unwrap() = d;
                }
            })
        };
        match request {
            Request::SetImageDescription { image_description, render_intent } => {
                if !matches!(render_intent, WEnum::Value(RenderIntent::Perceptual)) {
                    resource.post_error(wp_color_management_surface_v1::Error::RenderIntent, "only the perceptual intent is supported");
                    return;
                }
                match image_description.data::<DescData>() {
                    Some(d) => set(Some(d.0)),
                    None => resource.post_error(wp_color_management_surface_v1::Error::ImageDescription, "not a ready image description"),
                }
            }
            Request::UnsetImageDescription => set(None),
            Request::Destroy => set(None),
            _ => {}
        }
    }

    fn destroyed(&self, _state: &mut HuginnState<B>, _client: ClientId, _resource: &WpColorManagementSurfaceV1) {
        if let Ok(surface) = self.0.upgrade() {
            with_states(&surface, |s| {
                if let Some(sd) = s.data_map.get::<SurfaceDesc>() {
                    *sd.0.lock().unwrap() = None;
                }
            });
        }
    }
}

impl<B: Backend + 'static> Dispatch2<WpColorManagementSurfaceFeedbackV1, HuginnState<B>> for FeedbackData {
    fn request(
        &self,
        state: &mut HuginnState<B>,
        _client: &Client,
        _resource: &WpColorManagementSurfaceFeedbackV1,
        request: wp_color_management_surface_feedback_v1::Request,
        _dhandle: &DisplayHandle,
        data_init: &mut DataInit<'_, HuginnState<B>>,
    ) {
        use wp_color_management_surface_feedback_v1::Request;
        let first = state.space.outputs().next().cloned();
        let pick = |id| -> (New<WpImageDescriptionV1>, Desc) {
            let d = self.0.upgrade().ok().and_then(|s| preferred_for(&s, first.as_ref())).unwrap_or(Desc {
                id: 1,
                pq: false,
                bt2020: false,
                lum: (2000, 80, 80),
            });
            (id, d)
        };
        match request {
            Request::GetPreferred { image_description } | Request::GetPreferredParametric { image_description } => {
                let (id, d) = pick(image_description);
                ready(data_init, id, d, true);
            }
            Request::Destroy => {}
            _ => {}
        }
    }

    fn destroyed(&self, _state: &mut HuginnState<B>, _client: ClientId, resource: &WpColorManagementSurfaceFeedbackV1) {
        FEEDBACK.lock().unwrap().retain(|(o, _)| o != resource);
    }
}

impl<B: Backend + 'static> Dispatch2<WpImageDescriptionCreatorParamsV1, HuginnState<B>> for ParamsData {
    fn request(
        &self,
        _state: &mut HuginnState<B>,
        _client: &Client,
        resource: &WpImageDescriptionCreatorParamsV1,
        request: wp_image_description_creator_params_v1::Request,
        _dhandle: &DisplayHandle,
        data_init: &mut DataInit<'_, HuginnState<B>>,
    ) {
        use wp_image_description_creator_params_v1::{Error, Request};
        let mut p = self.0.lock().unwrap();
        match request {
            Request::SetTfNamed { tf } => {
                let pq = match tf {
                    WEnum::Value(TransferFunction::St2084Pq) => true,
                    WEnum::Value(TransferFunction::Srgb | TransferFunction::Gamma22) => false,
                    _ => {
                        resource.post_error(Error::InvalidTf, "that transfer function isn't supported");
                        return;
                    }
                };
                p.0 = Some(pq);
            }
            Request::SetPrimariesNamed { primaries } => {
                let bt2020 = match primaries {
                    WEnum::Value(Primaries::Bt2020) => true,
                    WEnum::Value(Primaries::Srgb) => false,
                    _ => {
                        resource.post_error(Error::InvalidPrimariesNamed, "those primaries aren't supported");
                        return;
                    }
                };
                p.1 = Some(bt2020);
            }
            Request::SetLuminances { min_lum, max_lum, reference_lum } => p.2 = Some((min_lum, max_lum, reference_lum)),
            Request::SetTfPower { .. } | Request::SetPrimaries { .. } => {
                resource.post_error(Error::UnsupportedFeature, "only named transfer functions and primaries are supported");
            }
            // mastering display, content light levels: taken, not needed (the screen's own metadata is used)
            Request::SetMasteringDisplayPrimaries { .. } | Request::SetMasteringLuminance { .. } | Request::SetMaxCll { .. } | Request::SetMaxFall { .. } => {}
            Request::Create { image_description } => {
                let (Some(pq), Some(bt2020)) = (p.0, p.1) else {
                    resource.post_error(Error::IncompleteSet, "a transfer function and primaries are needed");
                    return;
                };
                let lum = p.2.unwrap_or(if pq { (50, 10000, 203) } else { (2000, 80, 80) });
                ready(data_init, image_description, fresh(pq, bt2020, lum), false);
            }
            _ => {}
        }
    }
}

impl<B: Backend + 'static> Dispatch2<WpImageDescriptionCreatorIccV1, HuginnState<B>> for IccData {
    fn request(
        &self,
        _state: &mut HuginnState<B>,
        _client: &Client,
        _resource: &WpImageDescriptionCreatorIccV1,
        request: wp_image_description_creator_icc_v1::Request,
        _dhandle: &DisplayHandle,
        data_init: &mut DataInit<'_, HuginnState<B>>,
    ) {
        if let wp_image_description_creator_icc_v1::Request::Create { image_description } = request {
            let obj = data_init.init(image_description, DescData(fresh(false, false, (0, 0, 0)), false));
            obj.failed(Cause::Unsupported, "ICC profiles aren't supported".into());
        }
    }
}

impl<B: Backend + 'static> Dispatch2<WpImageDescriptionV1, HuginnState<B>> for DescData {
    fn request(
        &self,
        state: &mut HuginnState<B>,
        _client: &Client,
        resource: &WpImageDescriptionV1,
        request: wp_image_description_v1::Request,
        _dhandle: &DisplayHandle,
        data_init: &mut DataInit<'_, HuginnState<B>>,
    ) {
        if let wp_image_description_v1::Request::GetInformation { information } = request {
            if !self.1 {
                resource.post_error(wp_image_description_v1::Error::NoInformation, "no information for this image description");
                return;
            }
            let info: WpImageDescriptionInfoV1 = data_init.init(information, InfoData);
            let d = self.0;
            // `done` ends the object, which mustn't happen before this request has finished (wayland-backend fills
            // in the new object's data afterwards): sent once it has
            state.handle.insert_idle(move |_| send_info(&info, d));
        }
    }
}

fn send_info(info: &WpImageDescriptionInfoV1, d: Desc) {
    if !info.is_alive() {
        return;
    }
    {
        {
            let prim = if d.bt2020 { Primaries::Bt2020 } else { Primaries::Srgb };
            info.primaries_named(prim);
            info.tf_named(if d.pq { TransferFunction::St2084Pq } else { TransferFunction::Srgb });
            info.luminances(d.lum.0, d.lum.1, d.lum.2);
            // the screen's own primaries (x, y × 1 000 000): red, green, blue, white
            let c = if d.bt2020 {
                [708_000, 292_000, 170_000, 797_000, 131_000, 46_000, 312_700, 329_000]
            } else {
                [640_000, 330_000, 300_000, 600_000, 150_000, 60_000, 312_700, 329_000]
            };
            info.target_primaries(c[0], c[1], c[2], c[3], c[4], c[5], c[6], c[7]);
            info.target_luminance(d.lum.0, d.lum.1);
            info.done();
        }
    }
}

impl<B: Backend + 'static> Dispatch2<WpImageDescriptionInfoV1, HuginnState<B>> for InfoData {
    fn request(
        &self,
        _state: &mut HuginnState<B>,
        _client: &Client,
        _resource: &WpImageDescriptionInfoV1,
        _request: smithay::reexports::wayland_protocols::wp::color_management::v1::server::wp_image_description_info_v1::Request,
        _dhandle: &DisplayHandle,
        _data_init: &mut DataInit<'_, HuginnState<B>>,
    ) {
    }
}
