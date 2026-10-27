//! Desktop front end. Packing runs the command-line core (this same executable with
//! `pack`) as a child process and follows its JSON progress lines; the window only
//! browses clips, previews frames and shows progress.
use cdng_image::{
    Effort,
    dng::{self, Preview},
    pack::{Clip, list_clips},
};
use eframe::egui;
use std::{
    collections::{HashMap, HashSet},
    io::{BufRead, BufReader, Write},
    path::PathBuf,
    process::{Child, ChildStdin, Command, Stdio},
    sync::{
        Arc, Mutex,
        atomic::{AtomicU64, Ordering},
        mpsc,
    },
    time::{Duration, Instant},
};

const PREVIEW_THREADS: usize = 4;
const LOOKAHEAD: usize = 8;
// Layout (points). Everything is measured from one content width so edges line up.
const LIST_W: f32 = 240.; // clip list column
const GAP: f32 = 12.; // between columns
const LABEL_W: f32 = 56.; // Source / Save to
const PICK_W: f32 = 72.; // Choose… buttons
const LINE_H: f32 = 28.; // one control row
const INFO_H: f32 = 18.; // preview info line

enum JobEvent {
    Line(serde_json::Value),
    Exited { error: String },
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum Choice {
    Lj92,
    Jxl,
    Temporal,
}

impl Choice {
    fn extension(self) -> &'static str {
        if self == Self::Temporal { "cdngt" } else if cfg!(target_os = "macos") { "dmg" } else { "iso" }
    }

    fn codec(self) -> &'static str {
        match self {
            Self::Lj92 => "lj92",
            Self::Jxl => "jxl",
            Self::Temporal => "temporal",
        }
    }

    fn has_effort(self) -> bool {
        self == Self::Lj92 || !cfg!(target_os = "macos")
    }
}

#[cfg(target_os = "macos")]
enum MountEvent {
    Status(String),
    Finished(Result<(), String>),
}

struct Job {
    child: Child,
    stdin: Option<ChildStdin>,
    rx: mpsc::Receiver<JobEvent>,
    cancelling: bool,
    paused: bool,
    started: Instant,
    completed: bool,
    codec_preparing: bool,
}

/// Pauses or resumes the core process (SIGSTOP / SIGCONT).
fn signal_core(child: &Child, resume: bool) {
    #[cfg(unix)]
    {
        unsafe extern "C" {
            fn kill(pid: i32, sig: i32) -> i32;
        }
        // SIGCONT / SIGSTOP differ between BSD and Linux
        let (cont, stop) = if cfg!(target_os = "linux") { (18, 19) } else { (19, 17) };
        unsafe { kill(child.id() as i32, if resume { cont } else { stop }) };
    }
}

/// Frame previews: a few decoder threads fill a small cache ahead of playback.
struct Player {
    jobs: mpsc::Sender<(u64, usize, PathBuf)>,
    results: mpsc::Receiver<(u64, usize, Result<Preview, String>)>,
    generation: Arc<AtomicU64>,
    cache: HashMap<usize, egui::ColorImage>,
    inflight: HashSet<usize>,
    shown: Option<usize>,
    texture: Option<egui::TextureHandle>,
    frame: usize,
    playing: bool,
    compression_active: bool,
    play_from: (Instant, usize),
    fps: f64,
    info: String,
    /// set when the closed preview box is clicked
    wants_open: bool,
}

impl Player {
    fn new(ctx: &egui::Context) -> Self {
        let (jobs, rx) = mpsc::channel::<(u64, usize, PathBuf)>();
        let rx = Arc::new(Mutex::new(rx));
        let (tx, results) = mpsc::channel();
        let generation = Arc::new(AtomicU64::new(0));
        for _ in 0..PREVIEW_THREADS {
            let (rx, tx, generation, ctx) = (rx.clone(), tx.clone(), generation.clone(), ctx.clone());
            std::thread::spawn(move || loop {
                let Ok((id, frame, path)) = rx.lock().unwrap().recv() else { break };
                if id != generation.load(Ordering::Relaxed) {
                    continue; // clip changed meanwhile
                }
                let result = std::panic::catch_unwind(|| {
                    std::fs::read(&path).map_err(anyhow::Error::from).and_then(|d| dng::preview(&d))
                });
                let result = match result {
                    Ok(r) => r.map_err(|e| format!("{e:#}")),
                    Err(_) => Err("This frame cannot be previewed".into()),
                };
                if id != generation.load(Ordering::Relaxed) {
                    continue; // packing or a clip change invalidated this decode
                }
                if tx.send((id, frame, result)).is_err() {
                    break;
                }
                ctx.request_repaint();
            });
        }
        Self {
            jobs,
            results,
            generation,
            cache: HashMap::new(),
            inflight: HashSet::new(),
            shown: None,
            texture: None,
            frame: 0,
            playing: false,
            compression_active: false,
            play_from: (Instant::now(), 0),
            fps: 24.,
            info: String::new(),
            wants_open: false,
        }
    }

    fn reset(&mut self, frame: usize) {
        self.generation.fetch_add(1, Ordering::Relaxed);
        self.cache.clear();
        self.inflight.clear();
        self.shown = None; // the old texture stays up until the new clip's frame is decoded
        self.frame = frame;
        self.playing = false;
        self.info.clear();
    }

    /// Keep the displayed frame, but release queued preview work to the packer.
    /// A decode already running may finish; its obsolete result is discarded.
    fn set_compressing(&mut self, active: bool) {
        if active && !self.compression_active {
            self.generation.fetch_add(1, Ordering::Relaxed);
            self.inflight.clear();
            self.playing = false;
            self.wants_open = false;
        }
        self.compression_active = active;
        if active {
            while self.results.try_recv().is_ok() {}
        }
    }

    /// Requests what is needed, takes finished decodes, picks the frame to show.
    fn update(&mut self, ctx: &egui::Context, frames: &[PathBuf]) {
        if self.compression_active {
            while self.results.try_recv().is_ok() {}
            return;
        }
        let count = frames.len();
        if count == 0 {
            return;
        }
        let id = self.generation.load(Ordering::Relaxed);
        while let Ok((rid, frame, result)) = self.results.try_recv() {
            if rid != id {
                continue;
            }
            self.inflight.remove(&frame);
            match result {
                Ok(p) => {
                    self.fps = p.fps;
                    self.info = format!("{} × {} · {} bit · {:.2} fps", p.source_width, p.source_height, p.bits, p.fps);
                    self.cache.insert(frame, egui::ColorImage::from_rgb([p.width, p.height], &p.rgb));
                }
                Err(e) => {
                    self.info = format!("Preview failed: {e}");
                    self.playing = false;
                }
            }
        }
        if self.playing {
            let elapsed = self.play_from.0.elapsed().as_secs_f64();
            self.frame = (self.play_from.1 + (elapsed * self.fps) as usize) % count;
        }
        let wanted: Vec<usize> = if self.playing {
            (0..LOOKAHEAD).map(|k| (self.frame + k) % count).collect()
        } else {
            vec![self.frame]
        };
        for f in wanted {
            if !self.cache.contains_key(&f) && self.inflight.insert(f) {
                let _ = self.jobs.send((id, f, frames[f].clone()));
            }
        }
        // show the requested frame when it is ready; while playing, otherwise the
        // newest ready frame at or before it (decoding fell behind: frames are dropped)
        let target = if self.cache.contains_key(&self.frame) {
            Some(self.frame)
        } else if self.playing {
            (1..LOOKAHEAD).map(|k| (self.frame + count - k) % count).find(|f| self.cache.contains_key(f))
        } else {
            None
        };
        if let Some(t) = target.filter(|t| Some(*t) != self.shown) {
            self.texture = Some(ctx.load_texture("preview", self.cache[&t].clone(), egui::TextureOptions::LINEAR));
            self.shown = Some(t);
        }
        let keep = |f: usize| (f + count - self.frame) % count < LOOKAHEAD + 2 || (self.frame + count - f) % count < 4;
        self.cache.retain(|f, _| keep(*f));
        if self.playing {
            ctx.request_repaint_after(Duration::from_secs_f64(1. / self.fps.max(1.)));
        }
    }

    /// Picture box (fixed `w` x `h`; the frame is fitted inside, so loading or switching
    /// clips never changes its size), then the transport row and the info line.
    fn ui(&mut self, ui: &mut egui::Ui, count: usize, w: f32, h: f32, enabled: bool) {
        let (rect, response) = ui.allocate_exact_size(egui::vec2(w, h), egui::Sense::click());
        ui.painter().rect_filled(rect, 4., egui::Color32::from_gray(30));
        if !enabled {
            let hint = if self.compression_active { "Preview paused while compressing" } else { "Click to show preview" };
            ui.painter().text(rect.center(), egui::Align2::CENTER_CENTER, hint,
                              egui::FontId::proportional(14.), egui::Color32::from_gray(150));
            if !self.compression_active && response.clicked() {
                self.wants_open = true;
            }
        } else if let Some(texture) = &self.texture {
            let size = texture.size_vec2();
            let fit = egui::Rect::from_center_size(rect.center(), size * (rect.width() / size.x).min(rect.height() / size.y));
            ui.painter().image(texture.id(), fit, egui::Rect::from_min_max(egui::pos2(0., 0.), egui::pos2(1., 1.)), egui::Color32::WHITE);
        }
        if enabled && self.shown.is_none() && !self.inflight.is_empty() {
            ui.put(egui::Rect::from_center_size(rect.center(), egui::vec2(24., 24.)), egui::Spinner::new());
        }
        ui.add_enabled_ui(enabled && count > 0 && !self.compression_active, |ui| {
            ui.allocate_ui_with_layout(egui::vec2(w, LINE_H), egui::Layout::left_to_right(egui::Align::Center), |ui| {
                let button = |label: &str| egui::Button::new(label).min_size(egui::vec2(LINE_H, LINE_H - 4.));
                if ui.add(button(if self.playing { "⏸" } else { "▶" })).clicked() {
                    self.playing = !self.playing;
                    self.play_from = (Instant::now(), self.frame);
                }
                if ui.add(button("‹")).clicked() {
                    self.playing = false;
                    self.frame = self.frame.saturating_sub(1);
                }
                if ui.add(button("›")).clicked() {
                    self.playing = false;
                    self.frame = (self.frame + 1).min(count.saturating_sub(1));
                }
                let counter = format!("{} / {count}", self.frame + 1);
                let counter_w = 84.;
                ui.spacing_mut().slider_width = (ui.available_width() - counter_w - 8.).max(40.);
                let mut f = self.frame;
                // a zero-length range makes the slider geometry NaN (no clip yet)
                if ui.add(egui::Slider::new(&mut f, 0..=count.saturating_sub(1).max(1)).show_value(false)).changed() {
                    self.playing = false;
                    self.frame = f.min(count.saturating_sub(1));
                }
                ui.allocate_ui_with_layout(egui::vec2(counter_w, LINE_H), egui::Layout::right_to_left(egui::Align::Center), |ui| {
                    ui.label(counter);
                });
            });
        });
        ui.allocate_ui_with_layout(egui::vec2(w, INFO_H), egui::Layout::left_to_right(egui::Align::Center), |ui| {
            if enabled {
                ui.small(&self.info);
            }
        });
    }
}

struct App {
    source: String,
    output: String,
    effort: Effort,
    choice: Choice,
    preview_open: bool,
    job: Option<Job>,
    progress: f32,
    status: String,
    elapsed_seconds: Option<f64>,
    clips: Vec<(Clip, bool)>,
    active: Option<usize>,
    player: Player,
    scan_rx: Option<mpsc::Receiver<(String, Result<Vec<Clip>, String>)>>,
    scan_source: String,
    scanning: bool,
    remembered: HashMap<String, bool>,
    completed_archive: Option<PathBuf>,
    #[cfg(target_os = "macos")]
    mount_rx: Option<mpsc::Receiver<MountEvent>>,
    #[cfg(target_os = "macos")]
    mount_status: String,
}

/// Spawns this executable's command-line core and forwards its output lines.
fn spawn_core(args: &[String]) -> Result<Job, String> {
    let started = Instant::now();
    let exe = std::env::current_exe().map_err(|e| e.to_string())?;
    let mut child = Command::new(exe)
        .args(args)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .map_err(|e| format!("Could not start the core: {e}"))?;
    let (tx, rx) = mpsc::channel();
    let stdout = child.stdout.take().unwrap();
    let stderr = child.stderr.take().unwrap();
    let err_text = Arc::new(Mutex::new(String::new()));
    let err_reader = {
        let err_text = err_text.clone();
        std::thread::spawn(move || {
            for line in BufReader::new(stderr).lines().map_while(Result::ok) {
                let mut e = err_text.lock().unwrap();
                e.push_str(&line);
                e.push('\n');
            }
        })
    };
    let pid = child.id();
    std::thread::spawn(move || {
        for line in BufReader::new(stdout).lines().map_while(Result::ok) {
            if let Ok(v) = serde_json::from_str(&line) {
                let _ = tx.send(JobEvent::Line(v));
            }
        }
        let _ = err_reader.join();
        let _ = pid;
        let error = err_text.lock().unwrap().trim().to_string();
        let _ = tx.send(JobEvent::Exited { error });
    });
    Ok(Job { stdin: child.stdin.take(), child, rx, cancelling: false, paused: false, codec_preparing: false,
        started, completed: false })
}

impl App {
    fn new(cc: &eframe::CreationContext<'_>, initial_source: Option<PathBuf>) -> Self {
        Self::with_context(&cc.egui_ctx, initial_source)
    }

    fn with_context(ctx: &egui::Context, initial_source: Option<PathBuf>) -> Self {
        ctx.set_visuals(egui::Visuals::light());
        for path in ["/System/Library/Fonts/STHeiti Light.ttc", "C:\\Windows\\Fonts\\msjh.ttc", "C:\\Windows\\Fonts\\msyh.ttc"] {
            if let Ok(bytes) = std::fs::read(path) {
                let mut fonts = egui::FontDefinitions::default();
                fonts.font_data.insert("cjk".into(), egui::FontData::from_owned(bytes).into());
                fonts.families.entry(egui::FontFamily::Proportional).or_default().insert(0, "cjk".into());
                ctx.set_fonts(fonts);
                break;
            }
        }
        let mut app = Self {
            source: String::new(),
            output: String::new(),
            effort: Effort::Max,
            choice: Choice::Lj92,
            preview_open: false,
            job: None,
            progress: 0.,
            status: String::new(),
            elapsed_seconds: None,
            clips: Vec::new(),
            active: None,
            player: Player::new(ctx),
            scan_rx: None,
            scan_source: String::new(),
            scanning: false,
            remembered: HashMap::new(),
            completed_archive: None,
            #[cfg(target_os = "macos")]
            mount_rx: None,
            #[cfg(target_os = "macos")]
            mount_status: String::new(),
        };
        if let Some(source) = initial_source {
            app.set_source(source);
        }
        app
    }

    fn running(&self) -> bool {
        self.job.is_some()
    }

    fn set_source(&mut self, p: PathBuf) {
        self.source = p.display().to_string();
        if self.output.is_empty() {
            self.output = p
                .with_file_name(format!("{}.{}", p.file_name().unwrap_or_default().to_string_lossy(), self.choice.extension()))
                .display()
                .to_string();
        }
        self.begin_scan();
    }

    fn normalize_output_extension(&mut self) {
        if !self.output.is_empty() {
            self.output = PathBuf::from(&self.output).with_extension(self.choice.extension()).display().to_string();
        }
    }

    fn pack_args(&self) -> Vec<String> {
        let mut args = vec!["pack".into(), self.source.clone(), self.output.clone(),
            "--codec".into(), self.choice.codec().into()];
        // macOS codes both JPEG XL formats on Metal with one setting.
        if self.choice.has_effort() {
            let effort = match self.effort {
                Effort::Fast => "fast",
                Effort::Balanced => "balanced",
                Effort::Max => "max",
            };
            args.extend(["--effort".into(), effort.into()]);
        }
        for (c, selected) in &self.clips {
            if !selected {
                args.push("--exclude-clip".into());
                args.push(c.relative.clone());
            }
        }
        args
    }

    fn start(&mut self) {
        if self.source.is_empty() || self.output.is_empty() {
            self.status = "Choose a source folder and where to save".into();
            return;
        }
        self.normalize_output_extension();
        let args = self.pack_args();
        self.completed_archive = None;
        self.player.set_compressing(true);
        match spawn_core(&args) {
            Ok(job) => {
                self.job = Some(job);
                self.progress = 0.;
                self.status = "Preparing…".into();
                self.elapsed_seconds = Some(0.);
            }
            Err(e) => {
                self.player.set_compressing(false);
                self.status = e;
            }
        }
    }

    #[cfg(target_os = "macos")]
    fn start_mount(&mut self, path: PathBuf) {
        let result = (|| -> Result<_, String> {
            Command::new(std::env::current_exe().map_err(|e| e.to_string())?)
                .arg("mount").arg(path).stdin(Stdio::null())
                .stdout(Stdio::piped()).stderr(Stdio::piped()).spawn()
                .map_err(|e| format!("Could not mount archive: {e}"))
        })();
        let mut child = match result {
            Ok(child) => child,
            Err(error) => { self.mount_status = error; return; }
        };
        let (tx, rx) = mpsc::channel();
        let stdout = child.stdout.take().unwrap();
        let stderr = child.stderr.take().unwrap();
        // The mount serves reads until Finder ejects it, separately from packing.
        std::thread::spawn(move || {
            let errors = std::thread::spawn(move || {
                BufReader::new(stderr).lines().map_while(Result::ok).collect::<Vec<_>>().join("\n")
            });
            for line in BufReader::new(stdout).lines().map_while(Result::ok) {
                if let Ok(value) = serde_json::from_str::<serde_json::Value>(&line) {
                    if value["mounted"].is_string() || value["already_mounted"].is_string() {
                        let _ = tx.send(MountEvent::Status("Mounted in Finder · eject the volume when finished".into()));
                    } else if value["ejected"].is_string() {
                        let _ = tx.send(MountEvent::Status("Archive ejected".into()));
                    }
                }
            }
            let status = child.wait();
            let error = errors.join().unwrap_or_default();
            let result = match status {
                Ok(status) if status.success() => Ok(()),
                Ok(_) => Err(if error.trim().is_empty() { "Could not mount archive".into() } else { error }),
                Err(e) => Err(format!("Could not mount archive: {e}")),
            };
            let _ = tx.send(MountEvent::Finished(result));
        });
        self.mount_rx = Some(rx);
        self.mount_status = "Mounting archive…".into();
    }

    fn toggle_pause(&mut self) {
        if let Some(job) = &mut self.job
            && !job.cancelling
        {
            job.paused = !job.paused;
            signal_core(&job.child, !job.paused);
            self.status = if job.paused { "Paused".into() } else { "Resuming…".into() };
        }
    }

    fn cancel(&mut self) {
        if let Some(job) = &mut self.job {
            job.cancelling = true;
            if job.paused {
                job.paused = false;
                signal_core(&job.child, true); // a stopped core cannot read "cancel"
            }
            if let Some(stdin) = &mut job.stdin {
                let _ = stdin.write_all(b"cancel\n");
                let _ = stdin.flush();
            }
            self.status = "Cancelling…".into();
        }
    }

    fn begin_scan(&mut self) {
        if self.source.is_empty() || self.scanning || self.running() {
            return;
        }
        self.remembered = if self.scan_source == self.source {
            self.clips.iter().map(|(c, s)| (c.relative.clone(), *s)).collect()
        } else {
            HashMap::new()
        };
        let source = self.source.clone();
        self.scan_source = source.clone();
        self.scanning = true;
        self.clips.clear();
        self.active = None;
        self.player.reset(0);
        let (tx, rx) = mpsc::channel();
        self.scan_rx = Some(rx);
        std::thread::spawn(move || {
            let result = list_clips(std::path::Path::new(&source)).map_err(|e| format!("{e:#}"));
            let _ = tx.send((source, result));
        });
    }

    fn poll(&mut self) {
        #[cfg(target_os = "macos")]
        {
            let mut mount_finished = false;
            if let Some(rx) = &self.mount_rx {
                while let Ok(event) = rx.try_recv() {
                    match event {
                        MountEvent::Status(status) => self.mount_status = status,
                        MountEvent::Finished(result) => {
                            mount_finished = true;
                            if let Err(error) = result { self.mount_status = error; }
                        }
                    }
                }
            }
            if mount_finished { self.mount_rx = None; }
        }
        if let Some((source, result)) = self.scan_rx.as_ref().and_then(|r| r.try_recv().ok()) {
            self.scanning = false;
            self.scan_rx = None;
            if source == self.source {
                match result {
                    Ok(clips) => {
                        self.clips = clips
                            .into_iter()
                            .map(|c| {
                                let selected = *self.remembered.get(&c.relative).unwrap_or(&true);
                                (c, selected)
                            })
                            .collect();
                        if !self.clips.is_empty() {
                            self.select_clip(0);
                        }
                        self.status.clear();
                    }
                    Err(e) => {
                        self.status = e;
                        self.scan_source.clear();
                    }
                }
            }
        }
        let mut finished = None;
        if let Some(job) = &mut self.job {
            if !job.completed {
                self.elapsed_seconds = Some(job.started.elapsed().as_secs_f64());
            }
            while let Ok(event) = job.rx.try_recv() {
                match event {
                    JobEvent::Line(p) => {
                        // Track the core even while paused: a ready event may have
                        // been queued just before SIGSTOP and will not be repeated.
                        if p["stage"] == "codec" {
                            if p["phase"] == "initialize" {
                                job.codec_preparing = true;
                            } else if p["phase"] == "ready" {
                                job.codec_preparing = false;
                            }
                        }
                        if !job.paused && !job.cancelling && let (Some(done), Some(total)) = (p["done"].as_u64(), p["total"].as_u64()) {
                            self.progress = done as f32 / total.max(1) as f32;
                            let stage = if p["stage"] == "verify" { "Verifying" } else { "Compressing" };
                            if !job.codec_preparing {
                                self.status = format!("{stage} {done} / {total}");
                            }
                        }
                        if p["stage"] == "done" {
                            job.completed = true;
                            let r = &p["result"];
                            let (src, img) = (r["source_bytes"].as_f64().unwrap_or(0.), r["image_bytes"].as_f64().unwrap_or(0.));
                            self.status = format!(
                                "Done · {:.1}% smaller",
                                100. * (1. - img / src.max(1.))
                            );
                            self.elapsed_seconds = Some(job.started.elapsed().as_secs_f64());
                        } else if !job.paused && !job.cancelling && p["stage"] == "codec" {
                            if let Some(name) = p["name"].as_str() {
                                self.status = name.to_owned();
                            }
                        } else if !job.paused && !job.cancelling && p["stage"] == "finalize" {
                            self.status = if self.choice == Choice::Temporal { "Finishing archive…" } else { "Finishing disk image…" }.into();
                        }
                    }
                    JobEvent::Exited { error } => finished = Some(error),
                }
            }
        }
        if let Some(error) = finished {
            let mut job = self.job.take().unwrap();
            let ok = job.child.wait().is_ok_and(|s| s.success());
            self.elapsed_seconds = Some(job.started.elapsed().as_secs_f64());
            if job.cancelling {
                self.status = "Cancelled".into();
                self.progress = 0.;
            } else if ok {
                self.progress = 1.;
                if job.completed && self.choice == Choice::Temporal {
                    self.completed_archive = Some(PathBuf::from(&self.output));
                }
            } else {
                self.status = error.lines().last().unwrap_or("Failed").to_string();
            }
        }
    }

    fn select_clip(&mut self, i: usize) {
        self.active = Some(i);
        self.player.reset(self.clips[i].0.frames.len() / 2);
    }

    fn clip_header(&mut self, ui: &mut egui::Ui) {
        let selected = self.clips.iter().filter(|(_, s)| *s).count();
        ui.strong(format!("Clips {selected} / {}", self.clips.len()));
        if self.scanning {
            ui.spinner();
        }
        ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
            if ui.small_button("None").clicked() {
                self.clips.iter_mut().for_each(|(_, s)| *s = false);
            }
            if ui.small_button("All").clicked() {
                self.clips.iter_mut().for_each(|(_, s)| *s = true);
            }
        });
    }

    fn clip_list(&mut self, ui: &mut egui::Ui, h: f32) {
        let mut clicked = None;
        egui::Frame::new().fill(egui::Color32::WHITE).corner_radius(4.).inner_margin(4).show(ui, |ui| {
            egui::ScrollArea::vertical().id_salt("clips").auto_shrink([false, false]).max_height(h - 8.).show(ui, |ui| {
                ui.set_min_height(h - 8.);
                for (i, (clip, selected)) in self.clips.iter_mut().enumerate() {
                    ui.horizontal(|ui| {
                        ui.checkbox(selected, "");
                        let name = if clip.relative.is_empty() { "/" } else { &clip.relative };
                        let label = egui::Button::selectable(self.active == Some(i), name);
                        if ui.add(label).clicked() {
                            clicked = Some(i);
                        }
                        ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                            ui.add_space(4.);
                            ui.weak(format!("{} frames", clip.frames.len()));
                        });
                    });
                }
            });
        });
        if let Some(i) = clicked {
            self.select_clip(i);
        }
    }

    /// Completed-file progress, with an activity pulse before the first file is ready.
    fn progress_bar(&self, ui: &mut egui::Ui, w: f32) {
        let (rect, _) = ui.allocate_exact_size(egui::vec2(w, 6.), egui::Sense::hover());
        ui.painter().rect_filled(rect, 3., egui::Color32::from_gray(225));
        if self.progress > 0. {
            let mut fill = rect;
            fill.set_width(rect.width() * self.progress.clamp(0., 1.));
            ui.painter().rect_filled(fill, 3., ui.visuals().selection.bg_fill);
        } else if self.job.as_ref().is_some_and(|j| !j.paused && !j.completed) {
            let phase = (ui.input(|i| i.time) * 0.7).fract() as f32;
            let width = rect.width() * 0.18;
            let left = rect.left() + phase * (rect.width() - width);
            let pulse = egui::Rect::from_min_size(egui::pos2(left, rect.top()), egui::vec2(width, rect.height()));
            ui.painter().rect_filled(pulse, 3., ui.visuals().selection.bg_fill);
        }
    }

    fn update_ui(&mut self, ctx: &egui::Context) {
        self.poll();
        let compressing = self.running();
        self.player.set_compressing(compressing);
        if self.running() || self.scanning {
            ctx.request_repaint_after(Duration::from_millis(100));
        }
        #[cfg(target_os = "macos")]
        if self.mount_rx.is_some() { ctx.request_repaint_after(Duration::from_millis(100)); }
        if ctx.input(|i| i.viewport().close_requested()) && self.running() {
            ctx.send_viewport_cmd(egui::ViewportCommand::CancelClose);
            self.cancel();
        }
        egui::CentralPanel::default()
            .frame(egui::Frame::new().fill(egui::Color32::from_rgb(248, 249, 252)).inner_margin(20))
            .show(ctx, |ui| {
                egui::ScrollArea::vertical().show(ui, |ui| {
                    let w = ui.available_width();
                    ui.spacing_mut().item_spacing = egui::vec2(8., 8.);
                    let idle = !self.running();
                    let row = |ui: &mut egui::Ui, add: &mut dyn FnMut(&mut egui::Ui)| {
                        ui.allocate_ui_with_layout(egui::vec2(w, LINE_H), egui::Layout::left_to_right(egui::Align::Center), |ui| add(ui));
                    };

                    // paths: label | field | button, right edge on the content edge
                    let field_w = w - LABEL_W - PICK_W - 16.;
                    ui.add_enabled_ui(idle, |ui| {
                        row(ui, &mut |ui| {
                            ui.allocate_ui_with_layout(egui::vec2(LABEL_W, LINE_H), egui::Layout::left_to_right(egui::Align::Center), |ui| {
                                ui.set_width(LABEL_W);
                                ui.label("Source");
                            });
                            ui.add_sized([field_w, LINE_H], egui::TextEdit::singleline(&mut self.source).vertical_align(egui::Align::Center));
                            if ui.add_sized([PICK_W, LINE_H], egui::Button::new("Choose…")).clicked()
                                && let Some(p) = rfd::FileDialog::new().pick_folder()
                            {
                                self.set_source(p);
                            }
                        });
                        row(ui, &mut |ui| {
                            ui.allocate_ui_with_layout(egui::vec2(LABEL_W, LINE_H), egui::Layout::left_to_right(egui::Align::Center), |ui| {
                                ui.set_width(LABEL_W);
                                ui.label("Save to");
                            });
                            ui.add_sized([field_w, LINE_H], egui::TextEdit::singleline(&mut self.output).vertical_align(egui::Align::Center));
                            if ui.add_sized([PICK_W, LINE_H], egui::Button::new("Choose…")).clicked() {
                                let ext = self.choice.extension();
                                if let Some(p) = rfd::FileDialog::new().add_filter(ext, &[ext]).save_file() {
                                    self.output = p.display().to_string();
                                    self.normalize_output_extension();
                                }
                            }
                        });
                    });
                    ui.add_space(12.);

                    // clips | preview: one fixed-size row, the picture box is 16:9 of its column
                    let preview_w = w - LIST_W - GAP;
                    let box_h = (preview_w * 9. / 16.).round();
                    let body_h = box_h + 8. + LINE_H + 8. + INFO_H;
                    ui.allocate_ui_with_layout(egui::vec2(w, LINE_H), egui::Layout::left_to_right(egui::Align::Center), |ui| {
                        ui.allocate_ui_with_layout(egui::vec2(LIST_W, LINE_H), egui::Layout::left_to_right(egui::Align::Center), |ui| {
                            ui.set_width(LIST_W);
                            ui.add_enabled_ui(idle, |ui| self.clip_header(ui));
                        });
                        ui.add_space(GAP - 8.);
                        ui.strong("Preview");
                        ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                            if self.preview_open && ui.small_button("Hide").clicked() {
                                self.preview_open = false;
                            }
                        });
                    });
                    ui.allocate_ui_with_layout(egui::vec2(w, body_h), egui::Layout::left_to_right(egui::Align::TOP), |ui| {
                        ui.allocate_ui_with_layout(egui::vec2(LIST_W, body_h), egui::Layout::top_down(egui::Align::LEFT), |ui| {
                            ui.set_width(LIST_W);
                            ui.add_enabled_ui(idle, |ui| self.clip_list(ui, body_h));
                        });
                        ui.add_space(GAP - 8.);
                        ui.allocate_ui_with_layout(egui::vec2(preview_w, body_h), egui::Layout::top_down(egui::Align::LEFT), |ui| {
                            ui.set_width(preview_w);
                            let frames = self.active.map(|i| self.clips[i].0.frames.clone()).unwrap_or_default();
                            let open = self.preview_open && !frames.is_empty();
                            if open {
                                self.player.update(ui.ctx(), &frames);
                            } else {
                                self.player.playing = false; // closed: no decoding
                            }
                            self.player.ui(ui, frames.len(), preview_w, box_h, open);
                            if std::mem::take(&mut self.player.wants_open) {
                                self.preview_open = true;
                            }
                        });
                    });
                    ui.add_space(16.);

                    ui.add_enabled_ui(idle, |ui| {
                        let previous_choice = self.choice;
                        row(ui, &mut |ui| {
                            ui.radio_value(&mut self.choice, Choice::Lj92, if cfg!(target_os = "macos") { "LJ92 + DMG" } else { "LJ92 + ISO" });
                            ui.add_space(12.);
                            ui.radio_value(&mut self.choice, Choice::Jxl, if cfg!(target_os = "macos") { "JPEG XL + DMG" } else { "JPEG XL + ISO" })
                                .on_hover_text("Lossless JPEG XL archive. Conversion for DaVinci Resolve is not available for this format yet; choose LJ92 for Resolve.");
                            ui.add_space(12.);
                            ui.radio_value(&mut self.choice, Choice::Temporal, "Temporal JXL")
                                .on_hover_text("Lossless compression across up to 8 consecutive frames. Compares temporal and independent representations and keeps the smaller one. Saves a .cdngt archive; requires this app to mount on macOS or extract on other platforms.");
                        });
                        if self.choice != previous_choice { self.normalize_output_extension(); }
                        row(ui, &mut |ui| {
                            if self.choice.has_effort() {
                                egui::ComboBox::from_id_salt("effort")
                                    .selected_text(effort_label(self.effort))
                                    .show_ui(ui, |ui| {
                                        for e in [Effort::Max, Effort::Balanced, Effort::Fast] {
                                            ui.selectable_value(&mut self.effort, e, effort_label(e));
                                        }
                                    }).response.on_hover_text("Smallest is the default: compression ratio takes priority. Faster modes can produce larger files.");
                            }
                            if self.choice == Choice::Jxl {
                                ui.add_space(8.);
                                ui.weak("Resolve conversion pending");
                            } else if self.choice == Choice::Temporal {
                                ui.weak(if cfg!(target_os = "macos") {
                                    "App-mounted archive · requires this app"
                                } else { "App archive · extract with this app" });
                            }
                        });
                    });
                    ui.add_space(12.);
                    self.progress_bar(ui, w);
                    row(ui, &mut |ui| {
                        ui.label(if self.status.is_empty() { " " } else { &self.status });
                        if let Some(seconds) = self.elapsed_seconds {
                            ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                                ui.monospace(format_seconds(seconds))
                                    .on_hover_text("Elapsed time from Start to completion, including startup, compression, packing, verification and pauses");
                            });
                        }
                    });
                    row(ui, &mut |ui| {
                        let can_start = idle && !self.scanning && self.clips.iter().any(|(_, s)| *s);
                        let size = egui::vec2(96., 32.);
                        if ui.add_enabled(can_start, egui::Button::new("Start").min_size(size)).clicked() {
                            self.start();
                        }
                        let paused = self.job.as_ref().is_some_and(|j| j.paused);
                        if ui.add_enabled(!idle, egui::Button::new(if paused { "Resume" } else { "Pause" }).min_size(size)).clicked() {
                            self.toggle_pause();
                        }
                        if ui.add_enabled(!idle, egui::Button::new("Cancel").min_size(size)).clicked() {
                            self.cancel();
                        }
                        #[cfg(target_os = "macos")]
                        if self.completed_archive.is_some()
                            && ui.add_enabled(idle && self.mount_rx.is_none(), egui::Button::new("Mount archive").min_size(size)).clicked()
                        {
                            self.start_mount(self.completed_archive.clone().unwrap());
                        }
                        #[cfg(target_os = "macos")]
                        if ui.add_enabled(idle && self.mount_rx.is_none(), egui::Button::new("Open archive…").min_size(size)).clicked()
                            && let Some(path) = rfd::FileDialog::new().add_filter("CDNG archive", &["cdngt", "cdngj"]).pick_file()
                        {
                            self.start_mount(path);
                        }
                    });
                    #[cfg(target_os = "macos")]
                    if !self.mount_status.is_empty() {
                        ui.label(&self.mount_status);
                    }
                });
            });
    }
}

impl eframe::App for App {
    fn update(&mut self, ctx: &egui::Context, _frame: &mut eframe::Frame) {
        self.update_ui(ctx);
    }
}

impl Drop for App {
    fn drop(&mut self) {
        // never leave a core running without its window
        self.cancel();
        if let Some(job) = &mut self.job {
            let _ = job.child.wait();
        }
    }
}

fn effort_label(e: Effort) -> &'static str {
    match e {
        Effort::Fast => "Fastest",
        Effort::Balanced => "Faster",
        Effort::Max => "Smallest",
    }
}

fn format_seconds(seconds: f64) -> String {
    format!("{seconds:05.2}s")
}

pub fn run(initial_source: Option<PathBuf>) -> eframe::Result {
    eframe::run_native(
        "CDNG Image",
        eframe::NativeOptions {
            viewport: egui::ViewportBuilder::default().with_inner_size([720., 680.]).with_min_inner_size([640., 480.]),
            ..Default::default()
        },
        Box::new(move |cc| Ok(Box::new(App::new(cc, initial_source)))),
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    fn controlled_player(ctx: &egui::Context) -> (Player, mpsc::Receiver<(u64, usize, PathBuf)>, mpsc::Sender<(u64, usize, Result<Preview, String>)>) {
        let mut player = Player::new(ctx);
        // Replace the channels before any work is requested. The real idle
        // workers see a disconnected job channel and exit without decoding.
        let (jobs, requests) = mpsc::channel();
        let (results, received) = mpsc::channel();
        player.jobs = jobs;
        player.results = received;
        (player, requests, results)
    }

    #[test]
    fn packing_quiesces_preview_preserves_frame_and_resumes_requests() {
        let ctx = egui::Context::default();
        let (mut player, requests, results) = controlled_player(&ctx);
        let frames: Vec<_> = (0..12).map(|i| PathBuf::from(format!("{i}.dng"))).collect();
        let image = egui::ColorImage::from_rgb([1, 1], &[1, 2, 3]);
        player.texture = Some(ctx.load_texture("retained", image.clone(), egui::TextureOptions::LINEAR));
        let texture_id = player.texture.as_ref().unwrap().id();
        player.cache.insert(2, image);
        player.shown = Some(2);
        player.frame = 2;
        player.info = "retained frame details".into();
        player.playing = true;
        player.play_from = (Instant::now(), 2);
        player.update(&ctx, &frames);
        let pending: Vec<_> = requests.try_iter().collect();
        assert!(!pending.is_empty(), "playback should have queued its lookahead");
        let old_generation = player.generation.load(Ordering::Relaxed);

        player.set_compressing(true);
        let packing_generation = player.generation.load(Ordering::Relaxed);
        assert_ne!(packing_generation, old_generation);
        assert!(pending.iter().all(|(id, _, _)| *id != packing_generation));
        assert!(player.inflight.is_empty());
        assert!(!player.playing);
        results.send((old_generation, 3, Err("late obsolete decode".into()))).unwrap();
        player.update(&ctx, &frames);
        player.set_compressing(true);
        assert_eq!(player.generation.load(Ordering::Relaxed), packing_generation);
        assert!(requests.try_recv().is_err(), "packing must not schedule new preview work");
        assert!(player.results.try_recv().is_err(), "obsolete results should be drained");
        assert_eq!(player.frame, 2);
        assert_eq!(player.shown, Some(2));
        assert_eq!(player.texture.as_ref().unwrap().id(), texture_id);
        assert!(player.cache.contains_key(&2));
        assert_eq!(player.info, "retained frame details");

        player.set_compressing(false);
        assert!(!player.playing, "finishing packing must not restart playback by itself");
        player.frame = 3;
        results.send((old_generation, 3, Err("another late decode".into()))).unwrap();
        player.update(&ctx, &frames);
        assert_eq!(requests.try_recv().unwrap(), (packing_generation, 3, frames[3].clone()));
        assert!(requests.try_recv().is_err());
        assert_eq!(player.info, "retained frame details");
    }

    #[test]
    fn preview_playback_control_is_disabled_until_packing_finishes() {
        let ctx = egui::Context::default();
        let (mut player, _requests, _results) = controlled_player(&ctx);
        let render = |player: &mut Player, events| ctx.run(egui::RawInput {
            screen_rect: Some(egui::Rect::from_min_size(egui::Pos2::ZERO, egui::vec2(400., 300.))),
            events,
            ..Default::default()
        }, |ctx| {
            egui::CentralPanel::default().show(ctx, |ui| player.ui(ui, 12, 320., 180., true));
        });
        for active in [true, false] {
            player.set_compressing(active);
            let out = render(&mut player, vec![]);
            let button = out.shapes.iter().find_map(|s| match &s.shape {
                egui::Shape::Text(text) if text.galley.job.text == "▶" => Some(s.shape.visual_bounding_rect().center()),
                _ => None,
            }).expect("playback button should remain visible");
            for pressed in [true, false] {
                render(&mut player, vec![
                    egui::Event::PointerMoved(button),
                    egui::Event::PointerButton { pos: button, button: egui::PointerButton::Primary,
                        pressed, modifiers: egui::Modifiers::NONE },
                ]);
            }
            assert_eq!(player.playing, !active, "playback should be interactive only after packing");
        }
    }

    fn draw(app: &mut App, ctx: &egui::Context, size: egui::Vec2, pos: egui::Pos2) -> egui::FullOutput {
        ctx.run(
            egui::RawInput {
                screen_rect: Some(egui::Rect::from_min_size(egui::Pos2::ZERO, size)),
                events: vec![egui::Event::PointerMoved(pos)],
                ..Default::default()
            },
            |ctx| app.update_ui(ctx),
        )
    }

    #[test]
    fn choosing_each_method_updates_filename_and_core_arguments() {
        let ctx = egui::Context::default();
        let mut app = App::with_context(&ctx, None);
        app.source = "/source clips".into();
        app.output = "/output folder/movie.dmg".into();
        app.clips = vec![(Clip { relative: "excluded clip".into(), frames: vec![], bytes: 0 }, false)];
        let size = egui::vec2(720., 640.);
        for choice in [Choice::Temporal, Choice::Jxl, Choice::Lj92] {
            let label = match choice {
                Choice::Temporal => "Temporal JXL",
                Choice::Jxl => if cfg!(target_os = "macos") { "JPEG XL + DMG" } else { "JPEG XL + ISO" },
                Choice::Lj92 => if cfg!(target_os = "macos") { "LJ92 + DMG" } else { "LJ92 + ISO" },
            };
            let out = draw(&mut app, &ctx, size, egui::Pos2::ZERO);
            let button = out.shapes.iter().find_map(|s| match &s.shape {
                egui::Shape::Text(text) if text.galley.job.text == label => Some(s.shape.visual_bounding_rect().center()),
                _ => None,
            }).expect("all three methods should be visible");
            for pressed in [true, false] {
                let _ = ctx.run(egui::RawInput {
                    screen_rect: Some(egui::Rect::from_min_size(egui::Pos2::ZERO, size)),
                    events: vec![egui::Event::PointerMoved(button), egui::Event::PointerButton {
                        pos: button, button: egui::PointerButton::Primary, pressed,
                        modifiers: egui::Modifiers::NONE,
                    }], ..Default::default()
                }, |ctx| app.update_ui(ctx));
            }
            assert_eq!(app.choice, choice);
            assert_eq!(PathBuf::from(&app.output).extension().unwrap(), choice.extension());
            let args = app.pack_args();
            assert_eq!(&args[..5], ["pack", "/source clips", app.output.as_str(), "--codec", choice.codec()]);
            assert!(args.windows(2).any(|a| a == ["--exclude-clip", "excluded clip"]));
            assert_eq!(args.windows(2).any(|a| a == ["--effort", "max"]), choice.has_effort());
        }
        app.output = "/output folder/typed-without-extension".into();
        app.choice = Choice::Temporal;
        app.normalize_output_extension();
        assert_eq!(app.output, "/output folder/typed-without-extension.cdngt");
    }

    /// Empty text has an empty (inf..-inf) mesh, so text is judged by its position and layout box.
    fn nan_shape(shape: &egui::Shape) -> bool {
        match shape {
            egui::Shape::Text(t) => t.pos.any_nan() || t.galley.rect.any_nan(),
            egui::Shape::Vec(v) => v.iter().any(nan_shape),
            other => other.visual_bounding_rect().any_nan(),
        }
    }

    #[cfg(unix)]
    #[test]
    fn paused_job_keeps_queued_codec_ready_transition() {
        let ctx = egui::Context::default();
        let mut app = App::with_context(&ctx, None);
        let (tx, rx) = mpsc::channel();
        let child = Command::new("/usr/bin/true").spawn().unwrap();
        app.job = Some(Job {
            child, stdin: None, rx, cancelling: false, paused: true,
            started: Instant::now(), completed: false, codec_preparing: false,
        });
        app.status = "Paused".into();
        for phase in ["initialize", "ready"] {
            tx.send(JobEvent::Line(serde_json::json!({
                "stage":"codec", "phase":phase, "name":"Preparing JPEG XL…"
            }))).unwrap();
        }
        app.poll();
        assert!(!app.job.as_ref().unwrap().codec_preparing);
        assert_eq!(app.status, "Paused");
        app.job.as_mut().unwrap().paused = false;
        tx.send(JobEvent::Line(serde_json::json!({
            "stage":"compress", "done":3, "total":10
        }))).unwrap();
        app.poll();
        assert_eq!(app.status, "Compressing 3 / 10");
        assert_eq!(app.progress, 0.3);
        app.job.take().unwrap().child.wait().unwrap();
    }

    #[test]
    fn pointer_over_window_does_not_panic() {
        let ctx = egui::Context::default();
        let mut app = App::with_context(&ctx, None);
        assert_eq!(app.effort, Effort::Max, "Compression ratio must take priority by default");
        app.elapsed_seconds = Some(12.34);
        for populated in [false, true] {
            if populated {
                app.clips = (0..3)
                    .map(|i| (Clip { relative: format!("clip-{i}"), frames: vec![PathBuf::new(); 3], bytes: 1234 }, true))
                    .collect();
                app.active = Some(0);
            }
            for (choice, progress, size) in [(Choice::Lj92, 0., egui::vec2(720., 640.)), (Choice::Jxl, 0.5, egui::vec2(640., 480.)), (Choice::Temporal, 1., egui::vec2(1600., 1000.))] {
                app.choice = choice;
                app.progress = progress;
                for y in (0..size.y as usize).step_by(20) {
                    for x in (0..size.x as usize).step_by(40) {
                        // every painted shape must have real coordinates (ctx.used_rect() is not
                        // usable here: after a pass egui swaps in the previous pass's state)
                        let out = draw(&mut app, &ctx, size, egui::pos2(x as f32, y as f32));
                        for c in &out.shapes {
                            assert!(!c.clip_rect.any_nan() && !nan_shape(&c.shape),
                                    "NaN geometry (populated {populated}, size {size:?}, pointer {x},{y}): {:?}", c.shape);
                        }
                    }
                }
            }
        }
    }
}
