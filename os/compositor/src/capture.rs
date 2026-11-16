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
            c.parts.push(format!(
                "{{\"path\":{:?},\"w\":{},\"h\":{},{}}}",
                path.to_string_lossy(),
                shot.w,
                shot.h,
                name
            ));
        }
        c.left = c.left.saturating_sub(1);
        if c.left == 0 {
            let _ = c.tx.send(format!("[{}]", c.parts.join(",")));
        }
    }
}

fn draw<R, E>(renderer: &mut R, output: &Output, elements: &[E], clear: Color32F) -> Result<Shot, String>
where
    R: Renderer + Offscreen<GlesRenderbuffer> + Bind<GlesRenderbuffer> + ExportMem,
    E: RenderElement<R>,
{
    let mode = output.current_mode().ok_or("no mode")?;
    let size = size_of(output).ok_or("no mode")?;
    let mut target: GlesRenderbuffer = renderer.create_buffer(Fourcc::Argb8888, size).map_err(|e| e.to_string())?;
    let mut fb = renderer.bind(&mut target).map_err(|e| e.to_string())?;
    let mut tracker = OutputDamageTracker::new(mode.size, output.current_scale().fractional_scale(), output.current_transform());
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

/// Copy a picture into the app's buffer (shared memory, Argb8888 or Xrgb8888, the size we asked for).
fn fill(frame: &Frame, shot: &Shot) -> bool {
    let buffer = frame.buffer();
    shm::with_buffer_contents_mut(&buffer, |ptr, len, data| {
        if data.width != shot.w || data.height != shot.h {
            return false;
        }
        let row = shot.w as usize * 4;
        let (offset, stride) = (data.offset as usize, data.stride as usize);
        if stride < row || offset + stride * (shot.h as usize - 1) + row > len {
            return false;
        }
        for y in 0..shot.h as usize {
            // SAFETY: inside the pool, checked above
            unsafe {
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
