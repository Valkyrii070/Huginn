//! Pictures of the screen: for apps through ext-image-copy-capture (screen sharing through the desktop portal,
//! screenshot tools), and for Huginn itself over the bus (`Capture`: Print, the Screenshot app and the portal's
//! Screenshot).
//!
//! A request waits on its output until the output is next drawn; the backend then hands the same elements it drew
//! to `serve`, which draws them again into a buffer of their own and copies that out. The cursor is drawn only when
//! asked for (sharing usually wants it, a screenshot doesn't).

use std::{cell::RefCell, path::PathBuf, rc::Rc, sync::mpsc, time::Duration};

use smithay::{
    backend::{
        allocator::Fourcc,
        renderer::{
            Bind, Color32F, ExportMem, Offscreen, Renderer, TextureMapping,
            damage::OutputDamageTracker,
            element::RenderElement,
            gles::GlesRenderbuffer,
        },
    },
    output::Output,
    utils::{Rectangle, Size, Transform},
    wayland::{
        image_copy_capture::{CaptureFailureReason, Frame},
        shm,
    },
};
use tracing::warn;

/// One output's picture: Argb8888 rows (B, G, R, A in memory), `stride` bytes apart.
pub struct Shot {
    pub w: i32,
    pub h: i32,
    pub stride: usize,
    pub bytes: Vec<u8>,
}

/// Everything a bus `Capture` is waiting for: one picture per output, then the answer.
pub struct Collect {
    pub left: usize,
    pub parts: Vec<String>,
    pub tx: mpsc::Sender<String>,
    /// the files written, taken away again if no one is waiting any more
    pub files: Vec<PathBuf>,
}

#[derive(Default)]
struct Pending {
    frames: Vec<(Frame, bool)>,
    shots: Vec<(Rc<RefCell<Collect>>, String)>,
}

fn pending(output: &Output) -> &RefCell<Pending> {
    output.user_data().insert_if_missing(|| RefCell::new(Pending::default()));
    output.user_data().get::<RefCell<Pending>>().unwrap()
}

/// An app's frame, filled the next time `output` is drawn (with the cursor if `cursor`).
pub fn ask_frame(output: &Output, frame: Frame, cursor: bool) {
    pending(output).borrow_mut().frames.push((frame, cursor));
}

/// Huginn's own picture of `output`, described as JSON by `name` (its place on the desktop) once taken.
pub fn ask_shot(output: &Output, collect: Rc<RefCell<Collect>>, name: String) {
    pending(output).borrow_mut().shots.push((collect, name));
}

pub fn wanted(output: &Output) -> bool {
    let p = pending(output).borrow();
    !p.frames.is_empty() || !p.shots.is_empty()
}

/// The size of `output`'s pictures, in pixels, the right way up.
pub fn size_of(output: &Output) -> Option<Size<i32, smithay::utils::Buffer>> {
    let mode = output.current_mode()?;
    let size = output.current_transform().transform_size(mode.size);
    Some(Size::from((size.w, size.h)))
}

/// Draw what's waiting on `output`. `elements` are what was just drawn on it, front first; the first `cursor` of
/// them are the cursor (and anything dragged with it).
pub fn serve<R, E>(renderer: &mut R, output: &Output, elements: &[E], cursor: usize, clear: Color32F, presented: Duration)
where
    R: Renderer + Offscreen<GlesRenderbuffer> + Bind<GlesRenderbuffer> + ExportMem,
    E: RenderElement<R>,
{
    if !wanted(output) {
        return;
    }
    let Pending { frames, shots } = std::mem::take(&mut *pending(output).borrow_mut());
    let mut with: Option<Shot> = None;
    let mut without: Option<Shot> = None;
    let take = |renderer: &mut R, cursor_too: bool| -> Option<Shot> {
        let from = if cursor_too { 0 } else { cursor.min(elements.len()) };
        match draw(renderer, output, &elements[from..], clear) {
            Ok(shot) => Some(shot),
            Err(err) => {
                warn!("A picture of the screen failed: {err}");
                None
            }
        }
    };
    for (frame, cursor_too) in frames {
        let shot = if cursor_too { &mut with } else { &mut without };
        if shot.is_none() {
            *shot = take(renderer, cursor_too);
        }
        match shot {
            Some(shot) if fill(&frame, shot) => frame.success(Transform::Normal, None, presented),
            _ => frame.fail(CaptureFailureReason::Unknown),
        }
    }
    for (collect, name) in shots {
        if without.is_none() {
            without = take(renderer, false);
        }
        let part = without.as_ref().and_then(|shot| save(shot).map(|path| (path, shot)));
        let mut c = collect.borrow_mut();
        if let Some((path, shot)) = part {
            c.files.push(path.clone());
            c.parts.push(format!(
                "{{\"path\":{:?},\"w\":{},\"h\":{},{}}}",
                path.to_string_lossy(),
                shot.w,
                shot.h,
                name
            ));
        }
        c.left = c.left.saturating_sub(1);
        if c.left == 0 && c.tx.send(format!("[{}]", c.parts.join(","))).is_err() {
            for f in &c.files {
                let _ = std::fs::remove_file(f);
            }
        }
    }
}

fn draw<R, E>(renderer: &mut R, output: &Output, elements: &[E], clear: Color32F) -> Result<Shot, String>
where
    R: Renderer + Offscreen<GlesRenderbuffer> + Bind<GlesRenderbuffer> + ExportMem,
    E: RenderElement<R>,
{
    let size = size_of(output).ok_or("no mode")?;
    draw_at(renderer, size, output.current_scale().fractional_scale(), elements, clear)
}

/// Elements drawn into a buffer of their own, `size` pixels, and copied out: the first row first (OpenGL keeps
/// rows bottom up, so the picture is drawn turned over).
fn draw_at<R, E>(
    renderer: &mut R,
    size: Size<i32, smithay::utils::Buffer>,
    scale: f64,
    elements: &[E],
    clear: Color32F,
) -> Result<Shot, String>
where
    R: Renderer + Offscreen<GlesRenderbuffer> + Bind<GlesRenderbuffer> + ExportMem,
    E: RenderElement<R>,
{
    let mut target: GlesRenderbuffer = renderer.create_buffer(Fourcc::Argb8888, size).map_err(|e| e.to_string())?;
    let mut fb = renderer.bind(&mut target).map_err(|e| e.to_string())?;
    let mut tracker = OutputDamageTracker::new((size.w, size.h), scale, Transform::Flipped180);
    tracker
        .render_output(renderer, &mut fb, 0, elements, clear)
        .map_err(|e| format!("{e:?}"))?;
    let mapping = renderer
        .copy_framebuffer(&fb, Rectangle::from_size(size), Fourcc::Argb8888)
        .map_err(|e| e.to_string())?;
    let flipped = mapping.flipped();
    let bytes = renderer.map_texture(&mapping).map_err(|e| e.to_string())?;
    let stride = size.w as usize * 4;
    let mut out = Vec::with_capacity(stride * size.h as usize);
    for row in 0..size.h as usize {
        let row = if flipped { size.h as usize - 1 - row } else { row };
        out.extend_from_slice(bytes.get(row * stride..(row + 1) * stride).ok_or("short picture")?);
    }
    Ok(Shot { w: size.w, h: size.h, stride, bytes: out })
}

// ------------------------------------------------------------------------------------------------- one window
/// What a picture of one window is for.
pub enum WindowAsk {
    /// a small picture for the shell's window cards (the dock): its file, as JSON
    Card(mpsc::Sender<String>),
    /// the window as it was when it was asked to close: it fades out once it's gone
    Ghost,
    /// an app's frame of one window (sharing one window): its session, and whether to draw the pointer
    Frame(Frame, smithay::wayland::image_copy_capture::SessionRef, bool),
}

/// The window behind a handle in the list other programs see.
pub fn toplevel_window(
    toplevels: &[(u64, smithay::wayland::foreign_toplevel_list::ForeignToplevelHandle)],
    handle: &smithay::wayland::foreign_toplevel_list::ForeignToplevelHandle,
) -> Option<u64> {
    toplevels.iter().find(|(_, h)| h.matches(handle)).map(|(id, _)| *id)
}

/// The size of a window's pictures for sharing: everything it draws (shadow too), at its screen's scale.
pub fn window_size(space: &smithay::desktop::Space<crate::shell::WindowElement>, id: u64) -> Option<Size<i32, smithay::utils::Buffer>> {
    use smithay::desktop::space::SpaceElement;
    let w = space.elements().find(|w| crate::huginn::window_id(w) == id)?;
    let scale = space.outputs_for_element(w).first().map_or(1.0, |o| o.current_scale().fractional_scale());
    let b = w.bbox();
    Some(((b.size.w as f64 * scale).ceil() as i32, (b.size.h as f64 * scale).ceil() as i32).into())
}

/// A closed window fading out: its last picture, where it was (desktop, logical), since when it's been gone.
pub struct Ghost {
    pub id: u64,
    pub buffer: smithay::backend::renderer::element::memory::MemoryRenderBuffer,
    pub at: smithay::utils::Point<i32, smithay::utils::Logical>,
    pub size: smithay::utils::Size<i32, smithay::utils::Logical>,
    pub gone: Option<std::time::Instant>,
    pub asked: std::time::Instant,
}

thread_local! {
    static WINDOWS: RefCell<Vec<(u64, WindowAsk)>> = const { RefCell::new(Vec::new()) };
    pub static GHOSTS: RefCell<Vec<Ghost>> = const { RefCell::new(Vec::new()) };
}

pub fn ask_window(id: u64, ask: WindowAsk) {
    WINDOWS.with(|w| w.borrow_mut().push((id, ask)));
}

/// Pictures of windows on `output` that were asked for: drawn alone, at the output's scale (cards: smaller).
pub fn serve_windows<R>(renderer: &mut R, space: &smithay::desktop::Space<crate::shell::WindowElement>, output: &Output)
where
    R: crate::look::Look + Offscreen<GlesRenderbuffer> + Bind<GlesRenderbuffer> + ExportMem,
    R::TextureId: Clone + Send + 'static,
{
    use smithay::{backend::renderer::element::AsRenderElements, desktop::space::SpaceElement};
    if WINDOWS.with(|w| w.borrow().is_empty()) {
        return;
    }
    let asks = WINDOWS.with(|w| std::mem::take(&mut *w.borrow_mut()));
    let mut later = Vec::new();
    for (id, ask) in asks {
        let Some(window) = space.elements().find(|w| crate::huginn::window_id(w) == id) else {
            match ask {
                WindowAsk::Card(tx) => {
                    let _ = tx.send(String::new());
                }
                WindowAsk::Frame(frame, ..) => frame.fail(CaptureFailureReason::Unknown), // minimised, or on another space
                WindowAsk::Ghost => {}
            }
            continue;
        };
        if !space.outputs_for_element(window).contains(output) {
            later.push((id, ask));
            continue;
        }
        // shared windows are the window itself (no shadow, which changes with focus); the rest everything it draws
        let sharing = matches!(ask, WindowAsk::Frame(..));
        let bbox = if sharing { window.geometry() } else { window.bbox() };
        let Some(loc) = space.element_location(window) else { continue };
        let out_scale = output.current_scale().fractional_scale();
        let mut scale = match ask {
            WindowAsk::Card(_) => (360.0 / bbox.size.w.max(1) as f64).min(1.0) * out_scale,
            WindowAsk::Ghost | WindowAsk::Frame(..) => out_scale,
        };
        let mut size: Size<i32, smithay::utils::Buffer> =
            ((bbox.size.w as f64 * scale).ceil() as i32, (bbox.size.h as f64 * scale).ceil() as i32).into();
        if size.w < 2 || size.h < 2 {
            if let WindowAsk::Frame(frame, ..) = ask {
                frame.fail(CaptureFailureReason::Unknown);
            }
            continue;
        }
        // a shared window that changed size: this frame fits it into the buffers the app has, and the app is told
        // the new size for the next ones
        if let WindowAsk::Frame(_, session, _) = &ask
            && let Some(mut c) = session.current_constraints()
            && c.size != size
        {
            let fit = (c.size.w as f64 / size.w as f64).min(c.size.h as f64 / size.h as f64);
            scale *= fit;
            c.size = size;
            session.update_constraints(c);
            size = Size::from(((bbox.size.w as f64 * scale).floor().max(1.0) as i32, (bbox.size.h as f64 * scale).floor().max(1.0) as i32));
        }
        let at = smithay::utils::Point::<i32, smithay::utils::Physical>::from((
            (-(bbox.loc.x as f64) * scale).round() as i32,
            (-(bbox.loc.y as f64) * scale).round() as i32,
        ));
        let elements: Vec<crate::shell::WindowRenderElement<R>> =
            AsRenderElements::<R>::render_elements(window, renderer, at, scale.into(), 1.0);
        let shot = match draw_at(renderer, size, scale, &elements, [0.0, 0.0, 0.0, 0.0].into()) {
            Ok(shot) => shot,
            Err(err) => {
                warn!("A picture of a window failed: {err}");
                if let WindowAsk::Card(tx) = ask {
                    let _ = tx.send(String::new());
                }
                continue;
            }
        };
        match ask {
            WindowAsk::Card(tx) => {
                let answer = save(&shot).map_or(String::new(), |p| {
                    format!("{{\"path\":{:?},\"w\":{},\"h\":{}}}", p.to_string_lossy(), shot.w, shot.h)
                });
                let _ = tx.send(answer);
            }
            WindowAsk::Frame(frame, _, _) => {
                if fill(&frame, &shot) {
                    frame.success(Transform::Normal, None, presented_now());
                } else {
                    frame.fail(CaptureFailureReason::Unknown);
                }
            }
            WindowAsk::Ghost => {
                let buffer = smithay::backend::renderer::element::memory::MemoryRenderBuffer::from_slice(
                    &shot.bytes,
                    Fourcc::Argb8888,
                    (shot.w, shot.h),
                    1,
                    Transform::Normal,
                    None,
                );
                let now = std::time::Instant::now();
                GHOSTS.with(|g| g.borrow_mut().push(Ghost { id, buffer, at: loc + bbox.loc, size: bbox.size, gone: None, asked: now }));
            }
        }
    }
    WINDOWS.with(|w| w.borrow_mut().extend(later));
}

/// Copy a picture into the app's buffer (shared memory, Argb8888 or Xrgb8888, the size we asked for).
fn fill(frame: &Frame, shot: &Shot) -> bool {
    let buffer = frame.buffer();
    shm::with_buffer_contents_mut(&buffer, |ptr, len, data| {
        // the picture, top left; a smaller one (a shared window that just grew) on black
        if shot.w > data.width || shot.h > data.height {
            return false;
        }
        let row = shot.w as usize * 4;
        let (offset, stride) = (data.offset as usize, data.stride as usize);
        if stride < data.width as usize * 4 || offset + stride * data.height as usize > len {
            return false;
        }
        // SAFETY: inside the pool, checked above
        unsafe {
            if shot.w != data.width || shot.h != data.height {
                std::ptr::write_bytes(ptr.add(offset), 0, stride * data.height as usize);
            }
            for y in 0..shot.h as usize {
                std::ptr::copy_nonoverlapping(shot.bytes.as_ptr().add(y * shot.stride), ptr.add(offset + y * stride), row);
            }
        }
        true
    })
    .unwrap_or(false)
}

/// A picture as a file the shell reads (the same raw form huginn-grab writes): "HUGINNRAW w h stride 4\n" and the
/// rows (4: QImage's RGB32).
fn save(shot: &Shot) -> Option<PathBuf> {
    use std::{io::Write, os::unix::fs::OpenOptionsExt};
    static N: std::sync::atomic::AtomicU32 = std::sync::atomic::AtomicU32::new(0);
    let dir = std::env::var_os("XDG_RUNTIME_DIR").map(PathBuf::from)?;
    let n = N.fetch_add(1, std::sync::atomic::Ordering::Relaxed);
    let path = dir.join(format!("huginn-shot-{}-{n}.raw", std::process::id()));
    let mut file = std::fs::OpenOptions::new().write(true).create(true).truncate(true).mode(0o600).open(&path).ok()?;
    file.write_all(format!("HUGINNRAW {} {} {} 4\n", shot.w, shot.h, shot.stride).as_bytes()).ok()?;
    file.write_all(&shot.bytes).ok()?;
    Some(path)
}

fn presented_now() -> Duration {
    smithay::utils::Clock::<smithay::utils::Monotonic>::new().now().into()
}
