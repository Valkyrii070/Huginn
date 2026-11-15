//! huginn-compositor: Huginn OS's own Wayland compositor.
//!
//!     huginn-compositor            on the computer's screens (a session started from the sign-in screen)
//!     huginn-compositor --winit    in a window of another desktop (testing)

fn main() {
    if let Ok(env_filter) = tracing_subscriber::EnvFilter::try_from_default_env() {
        tracing_subscriber::fmt().compact().with_env_filter(env_filter).init();
    } else {
        tracing_subscriber::fmt()
            .compact()
            .with_env_filter(tracing_subscriber::EnvFilter::new("info"))
            .init();
    }
    profiling::register_thread!("Main Thread");

    let mut args: Vec<String> = std::env::args().skip(1).collect();
    if let Some(i) = args.iter().position(|a| a == "--") {
        let session = args.split_off(i + 1);
        args.pop();
        let _ = huginn_compositor::huginn::SESSION.set(session);
    }
    if args.iter().any(|a| a == "--help" || a == "-h") {
        #[allow(clippy::disallowed_macros)]
        {
            println!("huginn-compositor [--winit] [-- SESSION COMMAND…]");
            println!("  (no option)  run on the computer's screens, from a session");
            println!("  --winit      run in a window of another desktop, for testing");
            println!("  -- COMMAND   start this once listening (WAYLAND_DISPLAY and DISPLAY set); end when it ends");
        }
        return;
    }
    if args.iter().any(|a| a == "--winit") {
        #[cfg(feature = "winit")]
        {
            tracing::info!("Starting in a window (winit)");
            huginn_compositor::winit::run_winit();
        }
        return;
    }
    #[cfg(feature = "udev")]
    {
        tracing::info!("Starting on the computer's screens (udev)");
        huginn_compositor::udev::run_udev();
    }
}
