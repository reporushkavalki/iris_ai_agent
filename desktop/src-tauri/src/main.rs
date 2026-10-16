// Iris for Windows: a small window around the Iris backend.
//
//  1. shows a start-up screen at once,
//  2. starts the bundled backend (iris-server.exe, hidden) on a free local port with a random secret,
//  3. when the backend answers, loads it in the window,
//  4. stops the backend when the window closes (and the backend also stops by itself if this program dies).
//
// The Iris page itself runs from http://127.0.0.1 and is given no access to this program's internals.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::net::{Ipv4Addr, SocketAddr, TcpListener, TcpStream};
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use std::time::{Duration, Instant};

use tauri::{AppHandle, Manager, RunEvent, Url, WebviewUrl, WebviewWindow, WebviewWindowBuilder};

struct Server(Mutex<Option<Child>>);

/// Links to other websites open in the normal browser, never inside the Iris window.
const LINK_GUARD: &str = r#"
(function () {
  var ext = function (u) {
    try { var x = new URL(u, location.href);
      return /^(https?:|mailto:)$/.test(x.protocol) && x.hostname !== '127.0.0.1' && x.hostname !== 'tauri.localhost';
    } catch (e) { return false; }
  };
  document.addEventListener('click', function (e) {
    var a = e.target && e.target.closest ? e.target.closest('a[href]') : null;
    if (a && ext(a.href)) { e.preventDefault(); location.href = a.href; }
  }, true);
  var wo = window.open;
  window.open = function (u) { if (u && ext(u)) { location.href = u; return null; } return wo.apply(window, arguments); };
})();
"#;

fn free_port() -> u16 {
    TcpListener::bind((Ipv4Addr::LOCALHOST, 0))
        .and_then(|l| l.local_addr())
        .map(|a| a.port())
        .unwrap_or(8765)
}

fn make_token() -> String {
    let mut bytes = [0u8; 24];
    getrandom::getrandom(&mut bytes).expect("the system has no random number source");
    bytes.iter().map(|b| format!("{:02x}", b)).collect()
}

/// Windows hands out paths like \\?\C:\...; the backend is happier without that prefix.
fn plain(p: PathBuf) -> PathBuf {
    match p.to_str().and_then(|s| s.strip_prefix(r"\\?\")) {
        Some(rest) => PathBuf::from(rest),
        None => p,
    }
}

fn find_server(app: &AppHandle) -> Option<PathBuf> {
    let exe = if cfg!(windows) { "iris-server.exe" } else { "iris-server" };
    let mut roots: Vec<PathBuf> = Vec::new();
    if let Ok(r) = app.path().resource_dir() {
        roots.push(r);
    }
    if let Ok(me) = std::env::current_exe() {
        if let Some(dir) = me.parent() {
            roots.push(dir.to_path_buf());
        }
    }
    for root in roots {
        for rel in ["iris-server", "server/iris-server", "resources/iris-server", ""] {
            let p = root.join(rel).join(exe);
            if p.is_file() {
                return Some(plain(p));
            }
        }
    }
    None
}

fn start_server(exe: &PathBuf, port: u16, token: &str) -> std::io::Result<Child> {
    let mut cmd = Command::new(exe);
    cmd.env("IRIS_PACKAGED", "1")
        .env("IRIS_PORT", port.to_string())
        .env("IRIS_TOKEN", token)
        .env("IRIS_WATCH_STDIN", "1") // the backend stops when this pipe closes
        .env("NO_BROWSER", "1")
        .stdin(Stdio::piped())
        .stdout(Stdio::null())
        .stderr(Stdio::null());
    if let Some(dir) = exe.parent() {
        cmd.current_dir(dir);
    }
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        cmd.creation_flags(0x0800_0000); // CREATE_NO_WINDOW: no black console window
    }
    cmd.spawn()
}

fn fail(app: &AppHandle, msg: &str) {
    std::thread::sleep(Duration::from_millis(1200)); // let the start-up screen finish loading
    if let Some(w) = app.get_webview_window("main") {
        let text = serde_json::to_string(msg).unwrap_or_else(|_| "\"Iris could not start.\"".into());
        let _ = w.eval(&format!("window.irisFail && window.irisFail({})", text));
    }
}

fn boot(app: AppHandle) {
    let Some(exe) = find_server(&app) else {
        return fail(&app, "Iris could not find its engine (iris-server). Please reinstall Iris.");
    };
    let port = free_port();
    let token = make_token();
    match start_server(&exe, port, &token) {
        Ok(child) => *app.state::<Server>().0.lock().unwrap() = Some(child),
        Err(e) => return fail(&app, &format!("Iris could not start its engine: {e}")),
    }

    let addr = SocketAddr::from((Ipv4Addr::LOCALHOST, port));
    let started = Instant::now();
    loop {
        {
            let state = app.state::<Server>();
            let mut guard = state.0.lock().unwrap();
            if let Some(child) = guard.as_mut() {
                if let Ok(Some(status)) = child.try_wait() {
                    drop(guard);
                    return fail(&app, &format!("Iris stopped while starting ({status}). Try again; if it keeps happening, restart your computer."));
                }
            }
        }
        if TcpStream::connect_timeout(&addr, Duration::from_millis(300)).is_ok() {
            break;
        }
        if started.elapsed() > Duration::from_secs(90) {
            return fail(&app, "Iris is taking too long to start. Close it and try again.");
        }
        std::thread::sleep(Duration::from_millis(200));
    }

    let url = format!("http://127.0.0.1:{port}/?t={token}");
    if let (Some(w), Ok(u)) = (app.get_webview_window("main"), Url::parse(&url)) {
        let _ = w.navigate(u);
    }
}

fn stop_server(app: &AppHandle) {
    if let Some(mut child) = app.state::<Server>().0.lock().unwrap().take() {
        drop(child.stdin.take()); // lets the backend shut down by itself first
        std::thread::sleep(Duration::from_millis(300));
        let _ = child.kill();
        let _ = child.wait();
    }
}

fn build_window(app: &AppHandle) -> tauri::Result<WebviewWindow> {
    let b = WebviewWindowBuilder::new(app, "main", WebviewUrl::App("index.html".into()))
        .title("Iris")
        .inner_size(1360.0, 860.0)
        .min_inner_size(900.0, 600.0)
        .center()
        .initialization_script(LINK_GUARD)
        .on_navigation(|url: &Url| {
            let ours = matches!(url.scheme(), "tauri" | "about" | "data" | "blob")
                || matches!(url.host_str(), Some("127.0.0.1") | Some("tauri.localhost"));
            if !ours && matches!(url.scheme(), "http" | "https" | "mailto" | "solana") {   // wallet links go to a wallet app, the rest to the browser
                let _ = open::that(url.as_str());
            }
            ours
        });
    // Windows only: let Iris speak without waiting for a click (same flags Tauri uses by default, plus autoplay).
    #[cfg(windows)]
    let b = b.additional_browser_args(
        "--autoplay-policy=no-user-gesture-required --disable-features=msWebOOUI,msPdfOOUI,msSmartScreenProtection",
    );
    b.build()
}

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            if let Some(w) = app.get_webview_window("main") {
                let _ = w.unminimize();
                let _ = w.show();
                let _ = w.set_focus();
            }
        }))
        .manage(Server(Mutex::new(None)))
        .setup(|app| {
            build_window(app.handle())?;
            let handle = app.handle().clone();
            std::thread::spawn(move || boot(handle));
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building Iris")
        .run(|app, event| {
            if let RunEvent::Exit = event {
                stop_server(app);
            }
        });
}
