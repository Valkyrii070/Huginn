//! Huginn's look, drawn by the compositor (round 2): a soft shadow under each window, rounded corners, the title
//! island for apps that don't draw their own, and frosted glass behind the shell's islands.
//!
//! Every backend here draws with GLES (llvmpipe included when there's no GPU driver), so all of it is shaders. They
//! are compiled once per GPU and kept with its EGL context; if that fails, windows are simply drawn plain.
//!
//! - Rounded corners and the frost are drawn while the window's (or layer's) own texture is drawn, by swapping in a
//!   texture program (`override_default_tex_program`) that knows the shape. Shapes are worked out in framebuffer
//!   pixels at draw time, from where the element is actually drawn, so a window being moved and scaled (the Overview,
//!   hiding into the dock) keeps its corners.
//! - The frost is a "framebuffer effect": just before the shell's surface is drawn, what's already in the framebuffer
//!   under it is copied (halved), blurred (dual Kawase, three levels down and up), and the surface is then drawn over
//!   it with the blur showing through its translucent parts. Only where the surface is glass (alpha above a quarter),
//!   so shadows and anti-aliased edges keep what's behind as it is.

use std::{
    cell::RefCell,
    rc::Rc,
    sync::{
        Mutex, OnceLock,
        atomic::{AtomicBool, Ordering},
    },
};

use smithay::{
    backend::{
        allocator::Fourcc,
        renderer::{
            Frame, ImportAll, ImportMem, Renderer,
            element::{Element, Id, Kind, RenderElement, UnderlyingStorage, memory::MemoryRenderBuffer},
            gles::{
                Capability, GlesError, GlesFrame, GlesPixelProgram, GlesRenderer, GlesTexProgram, Uniform, UniformName,
                UniformType, ffi,
            },
            utils::{CommitCounter, DamageSet, OpaqueRegions},
        },
    },
    utils::{Buffer as BufferCoords, Physical, Point, Rectangle, Scale, Size, Transform, user_data::UserDataMap},
};
use tracing::warn;

/// The renderers Huginn draws with, and how to get at the GLES underneath each.
pub trait Look: Renderer + ImportAll + ImportMem {
    fn gles(&mut self) -> &mut GlesRenderer;
    fn gles_frame<'a, 'f, 'b>(frame: &'a mut Self::Frame<'f, 'b>) -> &'a mut GlesFrame<'f, 'b>
    where
        'b: 'f,
        Self: 'f;
    fn gles_error(err: GlesError) -> Self::Error;
}

impl Look for GlesRenderer {
    fn gles(&mut self) -> &mut GlesRenderer {
        self
    }
    fn gles_frame<'a, 'f, 'b>(frame: &'a mut Self::Frame<'f, 'b>) -> &'a mut GlesFrame<'f, 'b>
    where
        'b: 'f,
        Self: 'f,
    {
        frame
    }
    fn gles_error(err: GlesError) -> GlesError {
        err
    }
}

/// Dark or light: the shell says (with the dock's layout); the title islands follow.
pub static DARK: AtomicBool = AtomicBool::new(true);
/// Frost behind the shell's glass (off with Reduce Transparency; the shell says).
pub static FROST: AtomicBool = AtomicBool::new(true);

/// Window corners, in logical pixels: the same as Huginn's own windows draw (tokens: radius.window).
pub const RADIUS: f64 = 14.0;

/// The shell's surfaces that are glass (layer-shell namespaces). Full-screen ones (the Overview, the tour) aren't.
pub fn frosted(namespace: &str) -> bool {
    matches!(
        namespace,
        "huginn-topbar"
            | "huginn-dock"
            | "huginn-live"
            | "huginn-app-windows"
            | "huginn-stack"
            | "huginn-today"
            | "huginn-app-menu"
            | "huginn-app-island"
            | "huginn-control-centre"
            | "huginn-launcher"
            | "huginn-search"
            | "huginn-switcher"
            | "huginn-tabs"
            | "huginn-space-name"
            | "huginn-dock-tip"
            | "huginn-banners"
            | "huginn-level"
    )
}

// ---------------------------------------------------------------------------------------------------- the shaders

const TEX_HEAD: &str = r#"
//_DEFINES_
#if defined(EXTERNAL)
#extension GL_OES_EGL_image_external : require
#endif
precision highp float;
#if defined(EXTERNAL)
uniform samplerExternalOES tex;
#else
uniform sampler2D tex;
#endif
uniform float alpha;
varying vec2 v_coords;
#if defined(DEBUG_FLAGS)
uniform float tint;
#endif
float rsdf(vec2 p, vec4 r, float k) {
    vec2 c = r.xy + r.zw * 0.5;
    vec2 q = abs(p - c) - r.zw * 0.5 + k;
    return min(max(q.x, q.y), 0.0) + length(max(q, 0.0)) - k;
}
vec4 texel() {
    vec4 c = texture2D(tex, v_coords);
#if defined(NO_ALPHA)
    c = vec4(c.rgb, 1.0);
#endif
    return c;
}
vec4 finish(vec4 c) {
    c *= alpha;
#if defined(DEBUG_FLAGS)
    if (tint == 1.0)
        c = vec4(0.0, 0.2, 0.0, 0.2) + c * 0.8;
#endif
    return c;
}
"#;

/// A window's texture, cut to its rounded outline (`clip`: framebuffer pixels, GL's way up).
const CLIP: &str = r#"
uniform vec4 clip;
uniform float radius;
void main() {
    vec4 c = texel();
    c *= clamp(0.5 - rsdf(gl_FragCoord.xy, clip, radius), 0.0, 1.0);
    gl_FragColor = finish(c);
}
"#;

/// The shell's surface with the blurred backdrop showing through its glass.
const FROST_SHADER: &str = r#"
uniform sampler2D bg;
uniform vec4 bg_rect;
uniform float frost;
void main() {
    vec4 c = texel();
    vec3 b = texture2D(bg, (gl_FragCoord.xy - bg_rect.xy) / bg_rect.zw).rgb;
    float m = smoothstep(0.22, 0.38, c.a) * frost;
    gl_FragColor = finish(vec4(c.rgb + m * (1.0 - c.a) * b, c.a + m * (1.0 - c.a)));
}
"#;

/// A soft shadow under a rounded box (the analytic Gaussian of a rounded rectangle), none under the window itself.
const SHADOW: &str = r#"
precision highp float;
varying vec2 v_coords;
uniform vec2 size;
uniform float alpha;
uniform vec4 box;
uniform vec4 hole;
uniform float radius;
uniform float sigma;
uniform float strength;
vec2 erf2(vec2 x) {
    vec2 s = sign(x), a = abs(x);
    x = 1.0 + (0.278393 + (0.230389 + 0.078108 * (a * a)) * a) * a;
    x *= x;
    return s - s / (x * x);
}
float gaussian(float x, float s) {
    return exp(-(x * x) / (2.0 * s * s)) / (2.5066282746 * s);
}
float shadow_x(float x, float y, float s, float corner, vec2 half_size) {
    float delta = min(half_size.y - corner - abs(y), 0.0);
    float curved = half_size.x - corner + sqrt(max(0.0, corner * corner - delta * delta));
    vec2 integral = 0.5 + 0.5 * erf2((x + vec2(-curved, curved)) * (0.7071067811 / s));
    return integral.y - integral.x;
}
float box_shadow(vec2 lower, vec2 upper, vec2 p, float s, float corner) {
    vec2 center = (lower + upper) * 0.5;
    vec2 half_size = (upper - lower) * 0.5;
    p -= center;
    float low = p.y - half_size.y;
    float high = p.y + half_size.y;
    float start = clamp(-3.0 * s, low, high);
    float end = clamp(3.0 * s, low, high);
    float step = (end - start) / 4.0;
    float y = start + step * 0.5;
    float value = 0.0;
    for (int i = 0; i < 4; i++) {
        value += shadow_x(p.x, p.y - y, s, corner, half_size) * gaussian(y, s) * step;
        y += step;
    }
    return value;
}
float rsdf(vec2 p, vec4 r, float k) {
    vec2 c = r.xy + r.zw * 0.5;
    vec2 q = abs(p - c) - r.zw * 0.5 + k;
    return min(max(q.x, q.y), 0.0) + length(max(q, 0.0)) - k;
}
void main() {
    vec2 p = v_coords * size;
    float a = box_shadow(box.xy, box.xy + box.zw, p, sigma, radius);
    a *= clamp(rsdf(p, hole, radius) + 0.5, 0.0, 1.0);
    gl_FragColor = vec4(0.0, 0.0, 0.0, 1.0) * clamp(a, 0.0, 1.0) * strength * alpha;
}
"#;

/// The title island of an app that doesn't draw its own: glass with rounded top corners, a hairline under it, and
/// the three lights (close, minimise, fill) — grey when the window isn't in front.
const DECO: &str = r#"
precision highp float;
varying vec2 v_coords;
uniform vec2 size;
uniform float alpha;
uniform vec4 bg;
uniform vec4 line;
uniform float radius;
uniform vec3 dots;
uniform float dot_y;
uniform float dot_r;
uniform float active;
uniform float hover;
uniform float px;
float rsdf(vec2 p, vec4 r, float k) {
    vec2 c = r.xy + r.zw * 0.5;
    vec2 q = abs(p - c) - r.zw * 0.5 + k;
    return min(max(q.x, q.y), 0.0) + length(max(q, 0.0)) - k;
}
vec4 over(vec4 top, vec4 under) { return top + under * (1.0 - top.a); }
vec4 light(vec2 p, float x, vec3 on, float i) {
    float d = length(p - vec2(x, dot_y)) - dot_r;
    float m = clamp(0.5 - d, 0.0, 1.0);
    vec3 off = mix(vec3(0.36, 0.38, 0.41), vec3(0.78, 0.80, 0.82), step(0.5, 1.0 - bg.r));
    vec3 c = mix(off, on, active);
    if (abs(hover - i) < 0.5) {
        c = on;
        float inner = clamp(0.5 - (length(p - vec2(x, dot_y)) - dot_r * 0.34), 0.0, 1.0);
        c = mix(c, c * 0.45, inner);
    }
    return vec4(c, 1.0) * m;
}
void main() {
    vec2 p = v_coords * size;
    float inside = clamp(0.5 - rsdf(p, vec4(0.0, 0.0, size.x, size.y + radius), radius), 0.0, 1.0);
    vec4 c = vec4(bg.rgb * bg.a, bg.a) * inside;
    if (p.y > size.y - px)
        c = over(vec4(line.rgb * line.a, line.a) * inside, c);
    c = over(light(p, dots.x, vec3(1.0, 0.373, 0.341), 0.0), c);
    c = over(light(p, dots.y, vec3(0.996, 0.737, 0.180), 1.0), c);
    c = over(light(p, dots.z, vec3(0.157, 0.784, 0.251), 2.0), c);
    gl_FragColor = c * alpha;
}
"#;

const KAWASE_VERT: &str = r#"#version 100
attribute vec2 pos;
varying vec2 uv;
void main() {
    uv = pos * 0.5 + 0.5;
    gl_Position = vec4(pos, 0.0, 1.0);
}
"#;

const KAWASE_DOWN: &str = r#"#version 100
precision mediump float;
uniform sampler2D tex;
uniform vec2 half_px;
uniform float offset;
varying vec2 uv;
void main() {
    vec4 sum = texture2D(tex, uv) * 4.0;
    sum += texture2D(tex, uv - half_px * offset);
    sum += texture2D(tex, uv + half_px * offset);
    sum += texture2D(tex, uv + vec2(half_px.x, -half_px.y) * offset);
    sum += texture2D(tex, uv - vec2(half_px.x, -half_px.y) * offset);
    gl_FragColor = sum / 8.0;
}
"#;

const KAWASE_UP: &str = r#"#version 100
precision mediump float;
uniform sampler2D tex;
uniform vec2 half_px;
uniform float offset;
varying vec2 uv;
void main() {
    vec2 h = half_px * offset;
    vec4 sum = texture2D(tex, uv + vec2(-h.x * 2.0, 0.0));
    sum += texture2D(tex, uv + vec2(-h.x, h.y)) * 2.0;
    sum += texture2D(tex, uv + vec2(0.0, h.y * 2.0));
    sum += texture2D(tex, uv + vec2(h.x, h.y)) * 2.0;
    sum += texture2D(tex, uv + vec2(h.x * 2.0, 0.0));
    sum += texture2D(tex, uv + vec2(h.x, -h.y)) * 2.0;
    sum += texture2D(tex, uv + vec2(0.0, -h.y * 2.0));
    sum += texture2D(tex, uv + vec2(-h.x, -h.y)) * 2.0;
    gl_FragColor = sum / 12.0;
}
"#;

#[derive(Debug)]
pub struct Programs {
    pub shadow: GlesPixelProgram,
    pub deco: GlesPixelProgram,
    pub clip: GlesTexProgram,
    pub frost: GlesTexProgram,
}

type Shared = RefCell<Option<Option<Rc<Programs>>>>;

/// The shaders for this GPU, compiled the first time they're asked for.
pub fn programs(renderer: &mut GlesRenderer) -> Option<Rc<Programs>> {
    renderer.egl_context().user_data().insert_if_missing(|| Shared::new(None));
    if let Some(done) = renderer.egl_context().user_data().get::<Shared>().unwrap().borrow().clone() {
        return done;
    }
    let made = compile(renderer)
        .map_err(|err| warn!(?err, "the look's shaders didn't compile: windows are drawn plain"))
        .ok()
        .map(Rc::new);
    *renderer.egl_context().user_data().get::<Shared>().unwrap().borrow_mut() = Some(made.clone());
    made
}

fn programs_in(frame: &GlesFrame<'_, '_>) -> Option<Rc<Programs>> {
    frame.egl_context().user_data().get::<Shared>().and_then(|s| s.borrow().clone().flatten())
}

fn compile(r: &mut GlesRenderer) -> Result<Programs, GlesError> {
    let f = |n: &'static str| UniformName::new(n, UniformType::_1f);
    let f3 = |n: &'static str| UniformName::new(n, UniformType::_3f);
    let f4 = |n: &'static str| UniformName::new(n, UniformType::_4f);
    let i1 = |n: &'static str| UniformName::new(n, UniformType::_1i);
    Ok(Programs {
        shadow: r.compile_custom_pixel_shader(
            SHADOW,
            &[f4("box"), f4("hole"), f("radius"), f("sigma"), f("strength")],
        )?,
        deco: r.compile_custom_pixel_shader(
            DECO,
            &[f4("bg"), f4("line"), f("radius"), f3("dots"), f("dot_y"), f("dot_r"), f("active"), f("hover"), f("px")],
        )?,
        clip: r.compile_custom_texture_shader(format!("{TEX_HEAD}{CLIP}"), &[f4("clip"), f("radius")])?,
        frost: r.compile_custom_texture_shader(
            format!("{TEX_HEAD}{FROST_SHADER}"),
            &[i1("bg"), f4("bg_rect"), f("frost")],
        )?,
    })
}

/// A rectangle in the framebuffer's own pixels (GL's), from one in the output's pixels. Smithay draws an output
/// with transform Normal top row first (row 0 of a buffer for the screen is its top), so there the two agree; the
/// nested window (winit) is drawn Flipped180 into a y-up default framebuffer, so there y turns over.
/// None for rotated outputs (no rounding or frost there yet).
fn to_gl(frame: &GlesFrame<'_, '_>, r: Rectangle<f64, Physical>) -> Option<[f32; 4]> {
    let h = frame.output_size().h as f64;
    match frame.transformation() {
        Transform::Normal => Some([r.loc.x as f32, r.loc.y as f32, r.size.w as f32, r.size.h as f32]),
        Transform::Flipped180 => Some([r.loc.x as f32, (h - r.loc.y - r.size.h) as f32, r.size.w as f32, r.size.h as f32]),
        _ => None,
    }
}

// ------------------------------------------------------------------------------------------- a pixel-shader element

/// Something drawn entirely by a pixel shader: a shadow, a title island.
#[derive(Debug, Clone)]
pub struct ShaderElement {
    id: Id,
    commit: CommitCounter,
    program: GlesPixelProgram,
    geo: Rectangle<i32, Physical>,
    alpha: f32,
    uniforms: Vec<Uniform<'static>>,
}

impl Element for ShaderElement {
    fn id(&self) -> &Id {
        &self.id
    }
    fn current_commit(&self) -> CommitCounter {
        self.commit
    }
    fn src(&self) -> Rectangle<f64, BufferCoords> {
        Rectangle::from_size((self.geo.size.w as f64, self.geo.size.h as f64).into())
    }
    fn geometry(&self, _scale: Scale<f64>) -> Rectangle<i32, Physical> {
        self.geo
    }
    fn alpha(&self) -> f32 {
        self.alpha
    }
    fn kind(&self) -> Kind {
        Kind::Unspecified
    }
}

impl<R: Look> RenderElement<R> for ShaderElement {
    fn draw(
        &self,
        frame: &mut R::Frame<'_, '_>,
        src: Rectangle<f64, BufferCoords>,
        dst: Rectangle<i32, Physical>,
        damage: &[Rectangle<i32, Physical>],
        _opaque_regions: &[Rectangle<i32, Physical>],
        _cache: Option<&UserDataMap>,
    ) -> Result<(), R::Error> {
        R::gles_frame(frame)
            .render_pixel_shader_to(
                &self.program,
                src,
                dst,
                (self.geo.size.w, self.geo.size.h).into(),
                Some(damage),
                self.alpha,
                &self.uniforms,
            )
            .map_err(R::gles_error)
    }
    fn underlying_storage(&self, _renderer: &mut R) -> Option<UnderlyingStorage<'_>> {
        None
    }
}

/// Keeps a shader element's identity from frame to frame, so it's only redrawn when what it shows changes.
#[derive(Debug)]
pub struct Kept {
    id: Id,
    commit: CommitCounter,
    key: Vec<f32>,
}

impl Default for Kept {
    fn default() -> Self {
        Self { id: Id::new(), commit: CommitCounter::default(), key: Vec::new() }
    }
}

impl Kept {
    fn element(
        &mut self,
        program: &GlesPixelProgram,
        geo: Rectangle<i32, Physical>,
        alpha: f32,
        uniforms: Vec<(&'static str, Vec<f32>)>,
    ) -> ShaderElement {
        let mut key = vec![geo.loc.x as f32, geo.loc.y as f32, geo.size.w as f32, geo.size.h as f32];
        for (_, v) in &uniforms {
            key.extend_from_slice(v);
        }
        if key != self.key {
            self.key = key;
            self.commit.increment();
        }
        let uniforms = uniforms
            .into_iter()
            .map(|(name, v)| match v.len() {
                1 => Uniform::new(name, v[0]),
                2 => Uniform::new(name, (v[0], v[1])),
                3 => Uniform::new(name, (v[0], v[1], v[2])),
                _ => Uniform::new(name, (v[0], v[1], v[2], v[3])),
            })
            .collect();
        ShaderElement { id: self.id.clone(), commit: self.commit, program: program.clone(), geo, alpha, uniforms }
    }
}

/// What a window keeps for its look: its shadow's and title island's identities, and its title, drawn.
#[derive(Debug, Default)]
pub struct WindowLook {
    pub shadow: Kept,
    pub deco: Kept,
    pub title: Option<(String, i32, bool, MemoryRenderBuffer, (i32, i32))>,
}

pub struct Shadow {
    pub rect: Rectangle<i32, Physical>,
    pub radius: f64,
    pub active: bool,
    pub scale: f64,
}

impl WindowLook {
    /// The shadow under a window whose outline is `s.rect` (output pixels).
    pub fn shadow(&mut self, p: &Programs, s: Shadow, alpha: f32) -> ShaderElement {
        let (sigma, off, strength) = if s.active { (18.0, 10.0, 0.50) } else { (12.0, 6.0, 0.30) };
        let (sigma, off) = (sigma * s.scale, off * s.scale);
        let spread = (sigma * 3.0 + off).ceil() as i32;
        let r = s.rect;
        let geo = Rectangle::new(
            (r.loc.x - spread, r.loc.y - spread + off as i32).into(),
            (r.size.w + spread * 2, r.size.h + spread * 2).into(),
        );
        let (w, h) = (r.size.w as f32, r.size.h as f32);
        self.shadow.element(
            &p.shadow,
            geo,
            alpha,
            vec![
                ("box", vec![spread as f32, spread as f32, w, h]),
                ("hole", vec![spread as f32, spread as f32 - off as f32, w, h]),
                ("radius", vec![s.radius as f32]),
                ("sigma", vec![sigma as f32]),
                ("strength", vec![strength]),
            ],
        )
    }

    /// The title island across the top of a window (`rect`: output pixels), lights at the left.
    pub fn deco(&mut self, p: &Programs, rect: Rectangle<i32, Physical>, scale: f64, active: bool, hover: i32, alpha: f32) -> ShaderElement {
        let dark = DARK.load(Ordering::Relaxed);
        let (bg, line) = if dark {
            (vec![0.102, 0.118, 0.137, 1.0], vec![1.0, 1.0, 1.0, 0.08])
        } else {
            (vec![0.957, 0.961, 0.969, 1.0], vec![0.08, 0.12, 0.16, 0.12])
        };
        let s = scale as f32;
        let (x0, gap) = (crate::shell::ssd::LIGHT_X0 as f32 * s, crate::shell::ssd::LIGHT_GAP as f32 * s);
        self.deco.element(
            &p.deco,
            rect,
            alpha,
            vec![
                ("bg", bg),
                ("line", line),
                ("radius", vec![RADIUS as f32 * s]),
                ("dots", vec![x0, x0 + gap, x0 + gap * 2.0]),
                ("dot_y", vec![rect.size.h as f32 / 2.0]),
                ("dot_r", vec![6.0 * s]),
                ("active", vec![if active { 1.0 } else { 0.0 }]),
                ("hover", vec![hover as f32]),
                ("px", vec![s.max(1.0)]),
            ],
        )
    }

    /// The title as a picture: (picture, its size in pixels, its scale). Redrawn when the title, the scale or dark
    /// and light change.
    pub fn title(&mut self, text: &str, scale: f64, max_w: i32) -> Option<(MemoryRenderBuffer, (i32, i32), i32)> {
        let s = scale.ceil().max(1.0) as i32;
        let dark = DARK.load(Ordering::Relaxed);
        if let Some((t, ts, td, buf, size)) = &self.title
            && t == text
            && *ts == s
            && *td == dark
        {
            return Some((buf.clone(), *size, s));
        }
        let colour = if dark { [236, 239, 243] } else { [24, 28, 33] };
        let (buf, size) = text_picture(text, 13.0 * s as f32, max_w * s, colour, s)?;
        self.title = Some((text.to_string(), s, dark, buf.clone(), size));
        Some((buf, size, s))
    }
}

// --------------------------------------------------------------------------------------------------- the title text

static FONT: OnceLock<Option<ab_glyph::FontVec>> = OnceLock::new();

fn font() -> Option<&'static ab_glyph::FontVec> {
    FONT.get_or_init(|| {
        use ab_glyph::VariableFont;
        for path in [
            "/usr/share/fonts/truetype/inter-vf/InterVariable.ttf",
            "/usr/share/fonts/truetype/ubuntu/Ubuntu-M.ttf",
            "/usr/share/fonts/truetype/noto/NotoSans-Medium.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        ] {
            if let Ok(bytes) = std::fs::read(path)
                && let Ok(mut f) = ab_glyph::FontVec::try_from_vec(bytes)
            {
                let _ = f.set_variation(b"wght", 600.0);
                return Some(f);
            }
        }
        warn!("no font for the title islands");
        None
    })
    .as_ref()
}

/// Text drawn into a premultiplied ARGB buffer, cut with an ellipsis to `max_w` pixels.
fn text_picture(text: &str, px: f32, max_w: i32, rgb: [u32; 3], buffer_scale: i32) -> Option<(MemoryRenderBuffer, (i32, i32))> {
    use ab_glyph::{Font, ScaleFont, point};
    let font = font()?;
    let scale = ab_glyph::PxScale::from(px);
    let sf = font.as_scaled(scale);
    let ellipsis = sf.glyph_id('…');
    let ell_w = sf.h_advance(ellipsis);
    let chars: Vec<char> = text.chars().filter(|c| !c.is_control()).collect();
    let mut glyphs = Vec::new();
    let mut x = 0.0f32;
    let mut last = None;
    for (i, ch) in chars.iter().enumerate() {
        let id = sf.glyph_id(*ch);
        if let Some(prev) = last {
            x += sf.kern(prev, id);
        }
        let adv = sf.h_advance(id);
        let room = if i + 1 < chars.len() { ell_w } else { 0.0 };
        if x + adv + room > max_w as f32 {
            glyphs.push(ellipsis.with_scale_and_position(scale, point(x, sf.ascent())));
            x += ell_w;
            break;
        }
        glyphs.push(id.with_scale_and_position(scale, point(x, sf.ascent())));
        x += adv;
        last = Some(id);
    }
    if glyphs.is_empty() {
        return None;
    }
    let w = (x.ceil() as i32 + 2).max(1);
    let h = ((sf.ascent() - sf.descent()).ceil() as i32 + 2).max(1);
    let mut pixels = vec![0u8; (w * h * 4) as usize];
    for g in glyphs {
        if let Some(outline) = font.outline_glyph(g) {
            let b = outline.px_bounds();
            outline.draw(|gx, gy, c| {
                let (px_x, px_y) = (gx as i32 + b.min.x as i32, gy as i32 + b.min.y as i32);
                if px_x < 0 || px_y < 0 || px_x >= w || px_y >= h {
                    return;
                }
                let i = ((px_y * w + px_x) * 4) as usize;
                let a = (c.clamp(0.0, 1.0) * 255.0).round() as u32;
                if a as u8 <= pixels[i + 3] {
                    return;
                }
                // ARGB8888, little-endian: B, G, R, A — premultiplied
                pixels[i] = (rgb[2] * a / 255) as u8;
                pixels[i + 1] = (rgb[1] * a / 255) as u8;
                pixels[i + 2] = (rgb[0] * a / 255) as u8;
                pixels[i + 3] = a as u8;
            });
        }
    }
    Some((MemoryRenderBuffer::from_slice(&pixels, Fourcc::Argb8888, (w, h), buffer_scale, Transform::Normal, None), (w, h)))
}

// -------------------------------------------------------------------------------------------------- rounded corners

/// A window's surface, drawn cut to the window's rounded outline.
#[derive(Debug)]
pub struct Rounded<E> {
    inner: E,
    /// where the element is (output pixels) when it was made, and the outline within that
    at: Rectangle<i32, Physical>,
    clip: Rectangle<i32, Physical>,
    radius: f64,
}

impl<E: Element> Rounded<E> {
    pub fn new(inner: E, clip: Rectangle<i32, Physical>, radius: f64, scale: Scale<f64>) -> Self {
        let at = inner.geometry(scale);
        Self { inner, at, clip, radius }
    }

    /// The outline where the element is actually being drawn (`dst`: it may have been moved and scaled since).
    fn outline(&self, dst: Rectangle<i32, Physical>) -> (Rectangle<f64, Physical>, f64) {
        let sx = dst.size.w as f64 / self.at.size.w.max(1) as f64;
        let sy = dst.size.h as f64 / self.at.size.h.max(1) as f64;
        let r = Rectangle::new(
            (
                dst.loc.x as f64 + (self.clip.loc.x - self.at.loc.x) as f64 * sx,
                dst.loc.y as f64 + (self.clip.loc.y - self.at.loc.y) as f64 * sy,
            )
                .into(),
            (self.clip.size.w as f64 * sx, self.clip.size.h as f64 * sy).into(),
        );
        (r, self.radius * sx.min(sy))
    }
}

impl<E: Element> Element for Rounded<E> {
    fn id(&self) -> &Id {
        self.inner.id()
    }
    fn current_commit(&self) -> CommitCounter {
        self.inner.current_commit()
    }
    fn location(&self, scale: Scale<f64>) -> Point<i32, Physical> {
        self.inner.location(scale)
    }
    fn src(&self) -> Rectangle<f64, BufferCoords> {
        self.inner.src()
    }
    fn transform(&self) -> Transform {
        self.inner.transform()
    }
    fn geometry(&self, scale: Scale<f64>) -> Rectangle<i32, Physical> {
        self.inner.geometry(scale)
    }
    fn damage_since(&self, scale: Scale<f64>, commit: Option<CommitCounter>) -> DamageSet<i32, Physical> {
        self.inner.damage_since(scale, commit)
    }
    fn opaque_regions(&self, scale: Scale<f64>) -> OpaqueRegions<i32, Physical> {
        // the corners aren't opaque any more
        let geo = self.inner.geometry(scale);
        let r = self.radius.ceil() as i32;
        let c = self.clip;
        let corners = [
            Rectangle::new((c.loc.x, c.loc.y).into(), (r, r).into()),
            Rectangle::new((c.loc.x + c.size.w - r, c.loc.y).into(), (r, r).into()),
            Rectangle::new((c.loc.x, c.loc.y + c.size.h - r).into(), (r, r).into()),
            Rectangle::new((c.loc.x + c.size.w - r, c.loc.y + c.size.h - r).into(), (r, r).into()),
        ]
        .map(|mut k: Rectangle<i32, Physical>| {
            k.loc -= geo.loc;
            k
        });
        let inside = Rectangle::new(c.loc - geo.loc, c.size);
        self.inner
            .opaque_regions(scale)
            .into_iter()
            .filter_map(|o| o.intersection(inside))
            .flat_map(|o| o.subtract_rects(corners))
            .collect()
    }
    fn alpha(&self) -> f32 {
        self.inner.alpha()
    }
    fn kind(&self) -> Kind {
        self.inner.kind()
    }
}

impl<R: Look, E: RenderElement<R>> RenderElement<R> for Rounded<E> {
    fn draw(
        &self,
        frame: &mut R::Frame<'_, '_>,
        src: Rectangle<f64, BufferCoords>,
        dst: Rectangle<i32, Physical>,
        damage: &[Rectangle<i32, Physical>],
        opaque_regions: &[Rectangle<i32, Physical>],
        cache: Option<&UserDataMap>,
    ) -> Result<(), R::Error> {
        let gles = R::gles_frame(frame);
        let (outline, radius) = self.outline(dst);
        let set = match (programs_in(gles), to_gl(gles, outline)) {
            (Some(p), Some(clip)) => {
                gles.override_default_tex_program(
                    p.clip.clone(),
                    vec![Uniform::new("clip", (clip[0], clip[1], clip[2], clip[3])), Uniform::new("radius", radius as f32)],
                );
                true
            }
            _ => false,
        };
        let res = self.inner.draw(frame, src, dst, damage, opaque_regions, cache);
        if set {
            R::gles_frame(frame).clear_tex_program_override();
        }
        res
    }
    fn underlying_storage(&self, _renderer: &mut R) -> Option<UnderlyingStorage<'_>> {
        None // rounded: it can't go straight to the screen
    }
}

// ------------------------------------------------------------------------------------------------------- the frost

/// HUGINN_DEBUG_LOOK=1: say what the frost is doing (each thing once).
fn note(what: &'static str) {
    static SEEN: Mutex<Vec<&'static str>> = Mutex::new(Vec::new());
    static ON: OnceLock<bool> = OnceLock::new();
    if !*ON.get_or_init(|| std::env::var_os("HUGINN_DEBUG_LOOK").is_some()) {
        return;
    }
    if let Ok(mut seen) = SEEN.lock()
        && !seen.contains(&what)
    {
        seen.push(what);
        warn!("look: {what}");
    }
}

/// GL names to delete, from blur textures whose surfaces have gone (deleted the next time GL is at hand).
static GARBAGE: Mutex<Vec<(u32, u32)>> = Mutex::new(Vec::new());
const PAD: i32 = 48;
const LEVELS: usize = 4;

#[derive(Debug, Default)]
struct Level {
    tex: u32,
    fbo: u32,
    w: i32,
    h: i32,
}

#[derive(Debug, Default)]
struct FrostState {
    levels: Vec<Level>,
    /// the capture, in framebuffer pixels (GL)
    rect: [f32; 4],
    ok: bool,
}

impl Drop for FrostState {
    fn drop(&mut self) {
        if let Ok(mut g) = GARBAGE.lock() {
            g.extend(self.levels.iter().map(|l| (l.tex, l.fbo)));
        }
    }
}

struct Kawase {
    down: (u32, i32, i32, i32, i32),
    up: (u32, i32, i32, i32, i32),
}

unsafe fn shader(gl: &ffi::Gles2, kind: u32, src: &str) -> u32 {
    unsafe {
        let s = gl.CreateShader(kind);
        let ptr = src.as_ptr() as *const ffi::types::GLchar;
        let len = src.len() as i32;
        gl.ShaderSource(s, 1, &ptr, &len);
        gl.CompileShader(s);
        let mut ok = 0;
        gl.GetShaderiv(s, ffi::COMPILE_STATUS, &mut ok);
        if ok == 0 {
            warn!("a blur shader didn't compile");
            gl.DeleteShader(s);
            return 0;
        }
        s
    }
}

/// (program, tex, half_px, offset, pos)
unsafe fn link(gl: &ffi::Gles2, frag: &str) -> Option<(u32, i32, i32, i32, i32)> {
    unsafe {
        let v = shader(gl, ffi::VERTEX_SHADER, KAWASE_VERT);
        let f = shader(gl, ffi::FRAGMENT_SHADER, frag);
        if v == 0 || f == 0 {
            return None;
        }
        let p = gl.CreateProgram();
        gl.AttachShader(p, v);
        gl.AttachShader(p, f);
        gl.LinkProgram(p);
        gl.DetachShader(p, v);
        gl.DetachShader(p, f);
        gl.DeleteShader(v);
        gl.DeleteShader(f);
        let mut ok = 0;
        gl.GetProgramiv(p, ffi::LINK_STATUS, &mut ok);
        if ok == 0 {
            gl.DeleteProgram(p);
            return None;
        }
        let loc = |n: &std::ffi::CStr| gl.GetUniformLocation(p, n.as_ptr());
        Some((p, loc(c"tex"), loc(c"half_px"), loc(c"offset"), gl.GetAttribLocation(p, c"pos".as_ptr())))
    }
}

type KawaseShared = RefCell<Option<Option<Rc<Kawase>>>>;

fn kawase(frame: &mut GlesFrame<'_, '_>) -> Option<Rc<Kawase>> {
    let ud = frame.egl_context().user_data();
    ud.insert_if_missing(|| KawaseShared::new(None));
    if let Some(done) = ud.get::<KawaseShared>().unwrap().borrow().clone() {
        return done;
    }
    let made = frame
        .with_context(|gl| unsafe {
            match (link(gl, KAWASE_DOWN), link(gl, KAWASE_UP)) {
                (Some(down), Some(up)) => Some(Rc::new(Kawase { down, up })),
                _ => None,
            }
        })
        .ok()
        .flatten();
    if made.is_none() {
        warn!("no blur on this GPU: the shell's glass stays clear");
    }
    *frame.egl_context().user_data().get::<KawaseShared>().unwrap().borrow_mut() = Some(made.clone());
    made
}

const QUAD: [f32; 8] = [-1.0, -1.0, 1.0, -1.0, -1.0, 1.0, 1.0, 1.0];

unsafe fn level(gl: &ffi::Gles2, w: i32, h: i32) -> Level {
    unsafe {
        let mut tex = 0;
        gl.GenTextures(1, &mut tex);
        gl.BindTexture(ffi::TEXTURE_2D, tex);
        gl.TexImage2D(ffi::TEXTURE_2D, 0, ffi::RGBA as i32, w, h, 0, ffi::RGBA, ffi::UNSIGNED_BYTE, std::ptr::null());
        gl.TexParameteri(ffi::TEXTURE_2D, ffi::TEXTURE_MIN_FILTER, ffi::LINEAR as i32);
        gl.TexParameteri(ffi::TEXTURE_2D, ffi::TEXTURE_MAG_FILTER, ffi::LINEAR as i32);
        gl.TexParameteri(ffi::TEXTURE_2D, ffi::TEXTURE_WRAP_S, ffi::CLAMP_TO_EDGE as i32);
        gl.TexParameteri(ffi::TEXTURE_2D, ffi::TEXTURE_WRAP_T, ffi::CLAMP_TO_EDGE as i32);
        let mut fbo = 0;
        gl.GenFramebuffers(1, &mut fbo);
        gl.BindFramebuffer(ffi::FRAMEBUFFER, fbo);
        gl.FramebufferTexture2D(ffi::FRAMEBUFFER, ffi::COLOR_ATTACHMENT0, ffi::TEXTURE_2D, tex, 0);
        Level { tex, fbo, w, h }
    }
}

/// Copy and blur what's under `rect` (framebuffer pixels, GL) into the state's textures.
unsafe fn blur_under(
    gl: &ffi::Gles2,
    k: &Kawase,
    fb: Size<i32, Physical>,
    rect: [f32; 4],
    st: &mut FrostState,
    instancing: bool,
) -> bool {
    unsafe {
        if let Ok(mut g) = GARBAGE.lock() {
            for (tex, fbo) in g.drain(..) {
                gl.DeleteFramebuffers(1, &fbo);
                gl.DeleteTextures(1, &tex);
            }
        }
        // the capture: the surface plus room for the blur to reach in, inside the framebuffer
        let x0 = (rect[0] as i32 - PAD).max(0);
        let y0 = (rect[1] as i32 - PAD).max(0);
        let x1 = (rect[0] as i32 + rect[2] as i32 + PAD).min(fb.w);
        let y1 = (rect[1] as i32 + rect[3] as i32 + PAD).min(fb.h);
        let (cw, ch) = (x1 - x0, y1 - y0);
        if cw < 8 || ch < 8 {
            return false;
        }
        // state to put back
        let mut fbo = 0;
        gl.GetIntegerv(ffi::FRAMEBUFFER_BINDING, &mut fbo);
        let mut vp = [0i32; 4];
        gl.GetIntegerv(ffi::VIEWPORT, vp.as_mut_ptr());
        let mut prog = 0;
        gl.GetIntegerv(ffi::CURRENT_PROGRAM, &mut prog);
        let mut abuf = 0;
        gl.GetIntegerv(ffi::ARRAY_BUFFER_BINDING, &mut abuf);
        let mut active = 0;
        gl.GetIntegerv(ffi::ACTIVE_TEXTURE, &mut active);
        let blend = gl.IsEnabled(ffi::BLEND) == ffi::TRUE;
        let scissor = gl.IsEnabled(ffi::SCISSOR_TEST) == ffi::TRUE;
        gl.Disable(ffi::BLEND);
        gl.Disable(ffi::SCISSOR_TEST);
        gl.ActiveTexture(ffi::TEXTURE0);

        // the levels: a half, a quarter, an eighth, a sixteenth
        let sizes: Vec<(i32, i32)> = (1..=LEVELS).map(|i| ((cw >> i).max(1), (ch >> i).max(1))).collect();
        if st.levels.len() != LEVELS || st.levels.iter().zip(&sizes).any(|(l, s)| (l.w, l.h) != *s) {
            if let Ok(mut g) = GARBAGE.lock() {
                g.extend(st.levels.drain(..).map(|l| (l.tex, l.fbo)));
            }
            st.levels = sizes.iter().map(|(w, h)| level(gl, *w, *h)).collect();
        }
        let l0 = &st.levels[0];
        gl.BindFramebuffer(ffi::READ_FRAMEBUFFER, fbo as u32);
        gl.BindFramebuffer(ffi::DRAW_FRAMEBUFFER, l0.fbo);
        gl.BlitFramebuffer(x0, y0, x1, y1, 0, 0, l0.w, l0.h, ffi::COLOR_BUFFER_BIT, ffi::LINEAR);

        gl.BindBuffer(ffi::ARRAY_BUFFER, 0);
        let pass = |p: &(u32, i32, i32, i32, i32), from: &Level, to: &Level| {
            gl.BindFramebuffer(ffi::FRAMEBUFFER, to.fbo);
            gl.Viewport(0, 0, to.w, to.h);
            gl.UseProgram(p.0);
            gl.BindTexture(ffi::TEXTURE_2D, from.tex);
            gl.Uniform1i(p.1, 0);
            gl.Uniform2f(p.2, 0.5 / from.w as f32, 0.5 / from.h as f32);
            gl.Uniform1f(p.3, 1.4);
            let pos = p.4 as u32;
            gl.EnableVertexAttribArray(pos);
            if instancing {
                gl.VertexAttribDivisor(pos, 0);
            }
            gl.VertexAttribPointer(pos, 2, ffi::FLOAT, ffi::FALSE, 0, QUAD.as_ptr() as *const _);
            gl.DrawArrays(ffi::TRIANGLE_STRIP, 0, 4);
            gl.DisableVertexAttribArray(pos);
        };
        for i in 0..LEVELS - 1 {
            pass(&k.down, &st.levels[i], &st.levels[i + 1]);
        }
        for i in (0..LEVELS - 1).rev() {
            pass(&k.up, &st.levels[i + 1], &st.levels[i]);
        }

        gl.BindFramebuffer(ffi::FRAMEBUFFER, fbo as u32);
        gl.Viewport(vp[0], vp[1], vp[2], vp[3]);
        gl.UseProgram(prog as u32);
        gl.BindBuffer(ffi::ARRAY_BUFFER, abuf as u32);
        gl.BindTexture(ffi::TEXTURE_2D, 0);
        gl.ActiveTexture(active as u32);
        if blend {
            gl.Enable(ffi::BLEND);
            gl.BlendFunc(ffi::ONE, ffi::ONE_MINUS_SRC_ALPHA);
        }
        if scissor {
            gl.Enable(ffi::SCISSOR_TEST);
        }
        st.rect = [x0 as f32, y0 as f32, cw as f32, ch as f32];
        true
    }
}

/// One of the shell's glass surfaces: drawn over a blur of what's behind it.
#[derive(Debug)]
pub struct Frosted<E> {
    inner: E,
}

impl<E> Frosted<E> {
    pub fn new(inner: E) -> Self {
        Self { inner }
    }
}

impl<E: Element> Element for Frosted<E> {
    fn id(&self) -> &Id {
        self.inner.id()
    }
    fn current_commit(&self) -> CommitCounter {
        self.inner.current_commit()
    }
    fn location(&self, scale: Scale<f64>) -> Point<i32, Physical> {
        self.inner.location(scale)
    }
    fn src(&self) -> Rectangle<f64, BufferCoords> {
        self.inner.src()
    }
    fn transform(&self) -> Transform {
        self.inner.transform()
    }
    fn geometry(&self, scale: Scale<f64>) -> Rectangle<i32, Physical> {
        self.inner.geometry(scale)
    }
    fn damage_since(&self, scale: Scale<f64>, commit: Option<CommitCounter>) -> DamageSet<i32, Physical> {
        self.inner.damage_since(scale, commit)
    }
    fn opaque_regions(&self, scale: Scale<f64>) -> OpaqueRegions<i32, Physical> {
        self.inner.opaque_regions(scale)
    }
    fn alpha(&self) -> f32 {
        self.inner.alpha()
    }
    fn kind(&self) -> Kind {
        self.inner.kind()
    }
    fn is_framebuffer_effect(&self) -> bool {
        FROST.load(Ordering::Relaxed)
    }
}

impl<R: Look, E: RenderElement<R>> RenderElement<R> for Frosted<E> {
    fn capture_framebuffer(
        &self,
        frame: &mut R::Frame<'_, '_>,
        _src: Rectangle<f64, BufferCoords>,
        dst: Rectangle<i32, Physical>,
        cache: &UserDataMap,
    ) -> Result<(), R::Error> {
        let gles = R::gles_frame(frame);
        cache.insert_if_missing(|| RefCell::new(FrostState::default()));
        let mut st = cache.get::<RefCell<FrostState>>().unwrap().borrow_mut();
        st.ok = false;
        note("capture asked for");
        if !gles.capabilities().contains(&Capability::Blit) {
            note("no blit on this GPU");
            return Ok(());
        }
        let Some(rect) = to_gl(gles, dst.to_f64()) else {
            note("output turned: no frost");
            return Ok(());
        };
        let Some(k) = kawase(gles) else {
            note("no blur shaders");
            return Ok(());
        };
        let fb = gles.output_size();
        let instancing = gles.capabilities().contains(&Capability::Instancing);
        st.ok = gles
            .with_context(|gl| unsafe { blur_under(gl, &k, fb, rect, &mut st, instancing) })
            .map_err(R::gles_error)?;
        note(if st.ok { "captured and blurred" } else { "capture failed" });
        Ok(())
    }

    fn draw(
        &self,
        frame: &mut R::Frame<'_, '_>,
        src: Rectangle<f64, BufferCoords>,
        dst: Rectangle<i32, Physical>,
        damage: &[Rectangle<i32, Physical>],
        opaque_regions: &[Rectangle<i32, Physical>],
        cache: Option<&UserDataMap>,
    ) -> Result<(), R::Error> {
        let state = cache.and_then(|c| c.get::<RefCell<FrostState>>());
        let ready = state.map(|s| {
            let s = s.borrow();
            (s.ok && !s.levels.is_empty()).then(|| (s.levels[0].tex, s.rect))
        });
        let gles = R::gles_frame(frame);
        note(match (&ready, programs_in(gles).is_some()) {
            (None, _) => "drawn without a capture",
            (Some(None), _) => "drawn: capture not ready",
            (Some(Some(_)), false) => "drawn: no programs",
            (Some(Some(_)), true) => "drawn frosted",
        });
        let set = match (ready.flatten(), programs_in(gles)) {
            (Some((tex, rect)), Some(p)) => {
                gles.with_context(|gl| unsafe {
                    gl.ActiveTexture(ffi::TEXTURE1);
                    gl.BindTexture(ffi::TEXTURE_2D, tex);
                    gl.ActiveTexture(ffi::TEXTURE0);
                })
                .map_err(R::gles_error)?;
                gles.override_default_tex_program(
                    p.frost.clone(),
                    vec![
                        Uniform::new("bg", 1i32),
                        Uniform::new("bg_rect", (rect[0], rect[1], rect[2], rect[3])),
                        Uniform::new("frost", 1.0f32),
                    ],
                );
                true
            }
            _ => false,
        };
        let res = self.inner.draw(frame, src, dst, damage, opaque_regions, cache);
        if set {
            let gles = R::gles_frame(frame);
            gles.clear_tex_program_override();
            gles.with_context(|gl| unsafe {
                gl.ActiveTexture(ffi::TEXTURE1);
                gl.BindTexture(ffi::TEXTURE_2D, 0);
                gl.ActiveTexture(ffi::TEXTURE0);
            })
            .map_err(R::gles_error)?;
        }
        res
    }

    fn underlying_storage(&self, _renderer: &mut R) -> Option<UnderlyingStorage<'_>> {
        None
    }
}

/// Zoom (access.rs): drawn over everything but the pointer, it takes a part of what's on the screen and spreads it
/// over the whole screen. A new element every frame, so everything under it is drawn again every frame.
#[derive(Debug)]
pub struct ZoomElement {
    id: Id,
    commit: CommitCounter,
    /// the whole screen, and the part of it shown (physical pixels)
    whole: Rectangle<i32, Physical>,
    part: Rectangle<f64, Physical>,
}

impl ZoomElement {
    /// `at`: the pointer, in the screen's pixels (it stays where it is on the screen, and so does what's under it)
    pub fn new(whole: Rectangle<i32, Physical>, zoom: f64, at: Point<f64, Physical>) -> Self {
        let (w, h) = (whole.size.w as f64 / zoom, whole.size.h as f64 / zoom);
        let x = (at.x - at.x / zoom).clamp(0.0, whole.size.w as f64 - w);
        let y = (at.y - at.y / zoom).clamp(0.0, whole.size.h as f64 - h);
        Self { id: Id::new(), commit: CommitCounter::default(), whole, part: Rectangle::new((x, y).into(), (w, h).into()) }
    }
}

impl Element for ZoomElement {
    fn id(&self) -> &Id {
        &self.id
    }
    fn current_commit(&self) -> CommitCounter {
        self.commit
    }
    fn src(&self) -> Rectangle<f64, BufferCoords> {
        Rectangle::from_size((self.whole.size.w as f64, self.whole.size.h as f64).into())
    }
    fn geometry(&self, _scale: Scale<f64>) -> Rectangle<i32, Physical> {
        self.whole
    }
    fn opaque_regions(&self, _scale: Scale<f64>) -> OpaqueRegions<i32, Physical> {
        OpaqueRegions::default()
    }
    fn kind(&self) -> Kind {
        Kind::Unspecified
    }
}

impl<R: Look> RenderElement<R> for ZoomElement {
    fn draw(
        &self,
        frame: &mut R::Frame<'_, '_>,
        _src: Rectangle<f64, BufferCoords>,
        _dst: Rectangle<i32, Physical>,
        _damage: &[Rectangle<i32, Physical>],
        _opaque_regions: &[Rectangle<i32, Physical>],
        _cache: Option<&UserDataMap>,
    ) -> Result<(), R::Error> {
        let gles = R::gles_frame(frame);
        if !gles.capabilities().contains(&Capability::Blit) {
            return Ok(());
        }
        let (Some(to), Some(from)) = (to_gl(gles, self.whole.to_f64()), to_gl(gles, self.part)) else {
            return Ok(());
        };
        gles.with_context(|gl| unsafe {
            let mut fbo = 0;
            gl.GetIntegerv(ffi::FRAMEBUFFER_BINDING, &mut fbo);
            let scissor = gl.IsEnabled(ffi::SCISSOR_TEST) == ffi::TRUE;
            gl.Disable(ffi::SCISSOR_TEST);
            let (fx, fy, fw, fh) = (from[0] as i32, from[1] as i32, from[2].ceil() as i32, from[3].ceil() as i32);
            let copy = level(gl, fw.max(1), fh.max(1));
            gl.BindFramebuffer(ffi::READ_FRAMEBUFFER, fbo as u32);
            gl.BindFramebuffer(ffi::DRAW_FRAMEBUFFER, copy.fbo);
            gl.BlitFramebuffer(fx, fy, fx + fw, fy + fh, 0, 0, fw, fh, ffi::COLOR_BUFFER_BIT, ffi::NEAREST);
            gl.BindFramebuffer(ffi::READ_FRAMEBUFFER, copy.fbo);
            gl.BindFramebuffer(ffi::DRAW_FRAMEBUFFER, fbo as u32);
            let (tx, ty, tw, th) = (to[0] as i32, to[1] as i32, to[2] as i32, to[3] as i32);
            gl.BlitFramebuffer(0, 0, fw, fh, tx, ty, tx + tw, ty + th, ffi::COLOR_BUFFER_BIT, ffi::LINEAR);
            gl.BindFramebuffer(ffi::FRAMEBUFFER, fbo as u32);
            gl.DeleteFramebuffers(1, &copy.fbo);
            gl.DeleteTextures(1, &copy.tex);
            gl.BindTexture(ffi::TEXTURE_2D, 0);
            if scissor {
                gl.Enable(ffi::SCISSOR_TEST);
            }
        })
        .map_err(R::gles_error)
    }

    fn underlying_storage(&self, _renderer: &mut R) -> Option<UnderlyingStorage<'_>> {
        None
    }
}
