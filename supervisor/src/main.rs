//! tracker.exe - small supervisor for the embedded-Python tracker.
//!
//! Runs `python\python.exe -m tracker <args>` next to this exe and keeps it alive:
//!   * exit 75 (EXIT_RESTART): the GPU selection changed. Relaunch WITHOUT the old `--gpu`
//!     (the new card is read from config.json). The old process is fully gone first, so the
//!     `tracker.lock` hand-over cannot race any more.
//!   * crash (any other non-zero code) of `live`: relaunch after a short delay; gives up after
//!     MAX_CRASHES crashes inside CRASH_WINDOW.
//!   * 0 / 130 / Ctrl+C: pass the code through and stop.
//! On Windows the child lives in a kill-on-close job object: killing tracker.exe (installer
//! update, Task Manager) never leaves an orphan python.exe behind.
//! Same command line as before, so StartTracker.bat, Offline.bat and track.lua are unchanged.

use std::collections::VecDeque;
use std::env;
use std::path::PathBuf;
use std::process::{Command, ExitCode};
use std::thread::sleep;
use std::time::{Duration, Instant};

const EXIT_RESTART: i32 = 75;
const EXIT_INTERRUPT: i32 = 130;
const STATUS_CONTROL_C_EXIT: i32 = 0xC000013Au32 as i32;
const MAX_CRASHES: usize = 5;
const CRASH_WINDOW: Duration = Duration::from_secs(60);
const CRASH_DELAY: Duration = Duration::from_secs(2);

#[derive(Debug, PartialEq, Eq)]
enum Action {
    Exit(i32),
    Restart { strip_gpu: bool, delay: Duration },
    GiveUp(i32),
}

/// Drops `--gpu X` / `--gpu=X` so the relaunched tracker reads the new card from config.
fn strip_gpu(args: &[String]) -> Vec<String> {
    let mut out = Vec::with_capacity(args.len());
    let mut skip = false;
    for a in args {
        if skip {
            skip = false;
        } else if a == "--gpu" {
            skip = true;
        } else if !a.starts_with("--gpu=") {
            out.push(a.clone());
        }
    }
    out
}

/// Only the long-running `live` service is restarted after a crash; one-shot commands
/// (offline, detect, providers, --version ...) report their own exit code.
fn is_live(args: &[String]) -> bool {
    args.iter().any(|a| a == "live")
}

fn decide(code: i32, live: bool, crashes: &mut VecDeque<Instant>, now: Instant) -> Action {
    match code {
        EXIT_RESTART => Action::Restart { strip_gpu: true, delay: Duration::ZERO },
        0 | EXIT_INTERRUPT => Action::Exit(code),
        STATUS_CONTROL_C_EXIT => Action::Exit(EXIT_INTERRUPT),
        c if !live => Action::Exit(c),
        c => {
            while crashes.front().is_some_and(|t| now.duration_since(*t) > CRASH_WINDOW) {
                crashes.pop_front();
            }
            crashes.push_back(now);
            if crashes.len() > MAX_CRASHES {
                Action::GiveUp(c)
            } else {
                Action::Restart { strip_gpu: false, delay: CRASH_DELAY }
            }
        }
    }
}

fn app_dir() -> PathBuf {
    env::current_exe()
        .ok()
        .and_then(|p| p.parent().map(|d| d.to_path_buf()))
        .unwrap_or_else(|| PathBuf::from("."))
}

fn python_exe(root: &std::path::Path) -> PathBuf {
    match env::var_os("TAKIPLI_PYTHON") {
        Some(p) if !p.is_empty() => PathBuf::from(p),
        _ => root.join("python").join("python.exe"),
    }
}

fn main() -> ExitCode {
    let root = app_dir();
    let py = python_exe(&root);
    if !py.is_file() {
        eprintln!("[HATA] {} bulunamadi; paket eksik, uygulamayi yeniden kur.", py.display());
        return ExitCode::from(2);
    }
    sys::init();
    let mut args: Vec<String> = env::args().skip(1).collect();
    let live = is_live(&args);
    let mut crashes: VecDeque<Instant> = VecDeque::new();
    loop {
        let spawned = Command::new(&py)
            .arg("-m")
            .arg("tracker")
            .args(&args)
            .current_dir(&root)
            .env("TAKIPLI_SUPERVISED", "1")
            .env("PYTHONUTF8", "1")
            .spawn();
        let mut child = match spawned {
            Ok(c) => c,
            Err(e) => {
                eprintln!("[HATA] python baslatilamadi ({}): {e}", py.display());
                return ExitCode::from(3);
            }
        };
        sys::adopt(&child);
        let code = match child.wait() {
            Ok(st) => st.code().unwrap_or(1),
            Err(e) => {
                eprintln!("[HATA] surec beklenemedi: {e}");
                1
            }
        };
        match decide(code, live, &mut crashes, Instant::now()) {
            Action::Exit(c) => return exit_code(c),
            Action::GiveUp(c) => {
                eprintln!("[HATA] takip {MAX_CRASHES}+ kez coktu ({}s icinde); vazgecildi (kod {c}).",
                          CRASH_WINDOW.as_secs());
                return exit_code(c);
            }
            Action::Restart { strip_gpu: strip, delay } => {
                if strip {
                    args = strip_gpu(&args);
                    eprintln!("[OK] ekran karti degisti; takip yeniden baslatiliyor.");
                } else {
                    eprintln!("[UYARI] takip cikis kodu {code}; {}s sonra yeniden baslatilacak.",
                              delay.as_secs());
                }
                if !delay.is_zero() {
                    sleep(delay);
                }
            }
        }
    }
}

fn exit_code(c: i32) -> ExitCode {
    ExitCode::from(u8::try_from(c).unwrap_or(1))
}

#[cfg(windows)]
mod sys {
    use std::ffi::c_void;
    use std::os::windows::io::AsRawHandle;
    use std::process::Child;
    use std::ptr::null_mut;
    use std::sync::atomic::{AtomicPtr, Ordering};

    type Handle = *mut c_void;
    static JOB: AtomicPtr<c_void> = AtomicPtr::new(null_mut());

    #[repr(C)]
    struct BasicLimit {
        per_process_user_time: i64,
        per_job_user_time: i64,
        limit_flags: u32,
        min_working_set: usize,
        max_working_set: usize,
        active_process_limit: u32,
        affinity: usize,
        priority_class: u32,
        scheduling_class: u32,
    }
    #[repr(C)]
    struct IoCounters([u64; 6]);
    #[repr(C)]
    struct ExtLimit {
        basic: BasicLimit,
        io: IoCounters,
        process_memory_limit: usize,
        job_memory_limit: usize,
        peak_process_memory: usize,
        peak_job_memory: usize,
    }

    const JOB_OBJECT_EXTENDED_LIMIT_INFORMATION: i32 = 9;
    const KILL_ON_JOB_CLOSE: u32 = 0x2000;

    #[link(name = "kernel32")]
    extern "system" {
        fn CreateJobObjectW(attrs: *mut c_void, name: *const u16) -> Handle;
        fn SetInformationJobObject(job: Handle, class: i32, info: *mut c_void, len: u32) -> i32;
        fn AssignProcessToJobObject(job: Handle, process: Handle) -> i32;
        fn SetConsoleCtrlHandler(handler: Option<unsafe extern "system" fn(u32) -> i32>, add: i32) -> i32;
    }

    /// Ctrl+C / Ctrl+Break reach python too (same console); the supervisor just must not die
    /// before it has read the child's exit code.
    unsafe extern "system" fn on_ctrl(kind: u32) -> i32 {
        if kind == 0 || kind == 1 { 1 } else { 0 }
    }

    pub fn init() {
        unsafe {
            SetConsoleCtrlHandler(Some(on_ctrl), 1);
            let job = CreateJobObjectW(null_mut(), std::ptr::null());
            if job.is_null() {
                return;
            }
            let mut info: ExtLimit = std::mem::zeroed();
            info.basic.limit_flags = KILL_ON_JOB_CLOSE;
            let ok = SetInformationJobObject(
                job,
                JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
                &mut info as *mut ExtLimit as *mut c_void,
                std::mem::size_of::<ExtLimit>() as u32,
            );
            if ok != 0 {
                JOB.store(job, Ordering::SeqCst);
            }
        }
    }

    pub fn adopt(child: &Child) {
        let job = JOB.load(Ordering::SeqCst);
        if !job.is_null() {
            unsafe {
                AssignProcessToJobObject(job, child.as_raw_handle() as Handle);
            }
        }
    }
}

#[cfg(not(windows))]
mod sys {
    pub fn init() {}
    pub fn adopt(_: &std::process::Child) {}
}

#[cfg(test)]
mod tests {
    use super::*;

    fn v(a: &[&str]) -> Vec<String> {
        a.iter().map(|s| s.to_string()).collect()
    }

    #[test]
    fn strips_both_gpu_forms() {
        assert_eq!(strip_gpu(&v(&["live", "--gpu", "dml:1", "--wait", "120"])), v(&["live", "--wait", "120"]));
        assert_eq!(strip_gpu(&v(&["--gpu=cpu", "live"])), v(&["live"]));
        assert_eq!(strip_gpu(&v(&["live"])), v(&["live"]));
    }

    #[test]
    fn restart_code_relaunches_without_gpu_and_is_not_a_crash() {
        let mut c = VecDeque::new();
        let a = decide(EXIT_RESTART, true, &mut c, Instant::now());
        assert_eq!(a, Action::Restart { strip_gpu: true, delay: Duration::ZERO });
        assert!(c.is_empty());
    }

    #[test]
    fn clean_and_interrupt_exits_pass_through() {
        let mut c = VecDeque::new();
        let now = Instant::now();
        assert_eq!(decide(0, true, &mut c, now), Action::Exit(0));
        assert_eq!(decide(EXIT_INTERRUPT, true, &mut c, now), Action::Exit(130));
        assert_eq!(decide(STATUS_CONTROL_C_EXIT, true, &mut c, now), Action::Exit(130));
    }

    #[test]
    fn one_shot_commands_never_restart() {
        let mut c = VecDeque::new();
        assert_eq!(decide(1, false, &mut c, Instant::now()), Action::Exit(1));
    }

    #[test]
    fn live_crashes_restart_then_give_up() {
        let mut c = VecDeque::new();
        let t0 = Instant::now();
        for _ in 0..MAX_CRASHES {
            assert!(matches!(decide(1, true, &mut c, t0), Action::Restart { strip_gpu: false, .. }));
        }
        assert_eq!(decide(1, true, &mut c, t0), Action::GiveUp(1));
    }

    #[test]
    fn old_crashes_expire() {
        let mut c = VecDeque::new();
        let t0 = Instant::now();
        for _ in 0..MAX_CRASHES {
            decide(1, true, &mut c, t0);
        }
        let later = t0 + CRASH_WINDOW + Duration::from_secs(1);
        assert!(matches!(decide(1, true, &mut c, later), Action::Restart { .. }));
    }

    #[test]
    fn live_detected_in_args() {
        assert!(is_live(&v(&["--config", "c.json", "live", "--wait", "120"])));
        assert!(!is_live(&v(&["offline", "a.mp4"])));
    }
}
