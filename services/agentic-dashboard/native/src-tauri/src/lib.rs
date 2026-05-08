use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::collections::BTreeSet;
use std::env;
use std::fs;
use std::io::{BufRead, BufReader, Read};
use std::path::{Path, PathBuf};
use std::process::{Command as ProcessCommand, Stdio};
use std::time::{SystemTime, UNIX_EPOCH};
use tauri::{AppHandle, Emitter, Manager};

const BACKEND_CLI: &str = "scripts/dashboard_backend_cli.py";
const RECENT_CONFIG_FILE: &str = "recent-targets.json";
const MAX_RECENT_TARGETS: usize = 12;
const ALLOWED_EDITOR_COMMANDS: &[&str] = &["code", "cursor", "zed", "subl"];
const DEFAULT_AUTOMATION_PATH: &str = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin";

const READ_ONLY_BACKEND_COMMANDS: &[&str] = &[
    "project.load_snapshot",
    "project.list_recent",
    "diagnostics.environment",
    "brief.load",
    "brief.scaffold_preview",
    "inbox.load",
    "run.load",
    "run.load_log",
    "observatory.snapshot",
    "review.load",
    "diagnostics.run_checks",
    "advanced.list_files",
    "advanced.load_file",
    "advanced.validate_file",
];

const MUTATING_BACKEND_COMMANDS: &[&str] = &[
    "brief.save_draft",
    "brief.scaffold_bootstrap",
    "context.import",
    "inbox.send_note",
    "inbox.reply_request",
    "run.once",
    "schedule.start",
    "schedule.pause",
    "schedule.remove",
    "safety.run_check",
    "worker.run_read_only",
    "worker.run_write",
    "worker.run_integrator",
    "observatory.generate_html",
    "observatory.load_html",
    "review.export_bundle",
    "review.mark_reviewed",
    "advanced.save_file",
    "advanced.export_debug_bundle",
];

#[derive(Debug, Serialize)]
struct CommandError {
    kind: String,
    message: String,
    details: Value,
}

impl CommandError {
    fn new(kind: impl Into<String>, message: impl Into<String>, details: Value) -> Self {
        Self {
            kind: kind.into(),
            message: message.into(),
            details,
        }
    }

    fn io(message: impl Into<String>, error: std::io::Error) -> Self {
        Self::new(
            "io_error",
            message,
            json!({ "exception": error.to_string() }),
        )
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
struct RecentTarget {
    path: String,
    name: String,
    last_opened_at: u64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
struct AdvancedSettings {
    review_export_dir: String,
    preferred_editor_command: String,
    schedule_cadence_minutes: u64,
    human_bridge_mode: String,
    appearance: String,
    density: String,
}

impl Default for AdvancedSettings {
    fn default() -> Self {
        Self {
            review_export_dir: String::new(),
            preferred_editor_command: String::new(),
            schedule_cadence_minutes: 60,
            human_bridge_mode: "file_only".to_string(),
            appearance: "system".to_string(),
            density: "comfortable".to_string(),
        }
    }
}

#[derive(Debug, Default, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
struct NativeConfig {
    #[serde(default)]
    recent_targets: Vec<RecentTarget>,
    #[serde(default)]
    advanced_settings: AdvancedSettings,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
struct ProjectLoadResult {
    target: RecentTarget,
    snapshot: Value,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
struct PickedContextFile {
    path: String,
    name: String,
    size_bytes: u64,
    file_type: String,
}

fn unix_now() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_secs())
        .unwrap_or(0)
}

fn target_name(path: &Path) -> String {
    path.file_name()
        .and_then(|name| name.to_str())
        .map(str::to_string)
        .filter(|name| !name.is_empty())
        .unwrap_or_else(|| path.display().to_string())
}

fn validate_target_path(raw: &str) -> Result<PathBuf, CommandError> {
    if raw.trim().is_empty() {
        return Err(CommandError::new(
            "invalid_target",
            "A target path is required.",
            json!({}),
        ));
    }

    let path = PathBuf::from(raw);
    let resolved = path.canonicalize().map_err(|error| {
        CommandError::new(
            "invalid_target",
            "Could not resolve target path.",
            json!({ "target": raw, "exception": error.to_string() }),
        )
    })?;

    if !resolved.is_dir() {
        return Err(CommandError::new(
            "invalid_target",
            "Target path must be a directory.",
            json!({ "target": resolved }),
        ));
    }

    Ok(resolved)
}

fn validate_review_dir(raw: &str) -> Result<PathBuf, CommandError> {
    if raw.trim().is_empty() {
        return Err(CommandError::new(
            "invalid_review_dir",
            "A review directory is required.",
            json!({}),
        ));
    }

    let path = PathBuf::from(raw);
    if path.exists() && !path.is_dir() {
        return Err(CommandError::new(
            "invalid_review_dir",
            "Review path exists but is not a directory.",
            json!({ "reviewDir": raw }),
        ));
    }

    fs::create_dir_all(&path)
        .map_err(|error| CommandError::io("Could not create review directory.", error))?;
    path.canonicalize().map_err(|error| {
        CommandError::new(
            "invalid_review_dir",
            "Could not resolve review directory.",
            json!({ "reviewDir": raw, "exception": error.to_string() }),
        )
    })
}

fn validate_output_dir(raw: &str) -> Result<PathBuf, CommandError> {
    if raw.trim().is_empty() {
        return Err(CommandError::new(
            "invalid_output_dir",
            "An output directory is required.",
            json!({}),
        ));
    }

    let path = PathBuf::from(raw);
    if path.exists() && !path.is_dir() {
        return Err(CommandError::new(
            "invalid_output_dir",
            "Output path exists but is not a directory.",
            json!({ "outputDir": raw }),
        ));
    }

    fs::create_dir_all(&path)
        .map_err(|error| CommandError::io("Could not create output directory.", error))?;
    path.canonicalize().map_err(|error| {
        CommandError::new(
            "invalid_output_dir",
            "Could not resolve output directory.",
            json!({ "outputDir": raw, "exception": error.to_string() }),
        )
    })
}

fn validate_observatory_html_path(raw: &str) -> Result<PathBuf, CommandError> {
    if raw.trim().is_empty() {
        return Err(CommandError::new(
            "invalid_observatory_path",
            "An Observatory HTML path is required.",
            json!({}),
        ));
    }
    let path = PathBuf::from(raw);
    let resolved = path.canonicalize().map_err(|error| {
        CommandError::new(
            "invalid_observatory_path",
            "Could not resolve Observatory HTML path.",
            json!({ "path": raw, "exception": error.to_string() }),
        )
    })?;
    if !resolved.is_file() {
        return Err(CommandError::new(
            "invalid_observatory_path",
            "Observatory path must be a file.",
            json!({ "path": resolved }),
        ));
    }
    if resolved.file_name().and_then(|name| name.to_str()) != Some("Diffmogger-observatory.html") {
        return Err(CommandError::new(
            "invalid_observatory_path",
            "Only generated Diffmogger Observatory HTML files can be opened.",
            json!({ "path": resolved }),
        ));
    }
    Ok(resolved)
}

fn validate_review_artifact_path(raw: &str) -> Result<PathBuf, CommandError> {
    if raw.trim().is_empty() {
        return Err(CommandError::new(
            "invalid_review_artifact",
            "A review artifact path is required.",
            json!({}),
        ));
    }
    let path = PathBuf::from(raw);
    let resolved = path.canonicalize().map_err(|error| {
        CommandError::new(
            "invalid_review_artifact",
            "Could not resolve review artifact path.",
            json!({ "path": raw, "exception": error.to_string() }),
        )
    })?;
    if !resolved.is_file() {
        return Err(CommandError::new(
            "invalid_review_artifact",
            "Review artifact path must be a file.",
            json!({ "path": resolved }),
        ));
    }
    let allowed = matches!(
        resolved.file_name().and_then(|name| name.to_str()),
        Some("Diffmogger-observatory.html") | Some("Diffmogger-self-review.md")
    );
    if !allowed {
        return Err(CommandError::new(
            "invalid_review_artifact",
            "Only generated Diffmogger review artifacts can be opened.",
            json!({ "path": resolved }),
        ));
    }
    Ok(resolved)
}

fn kit_root() -> Result<PathBuf, CommandError> {
    if let Some(raw) = std::env::var_os("DIFFMOGGER_KIT_ROOT") {
        let candidate = PathBuf::from(raw);
        return validate_kit_root(&candidate);
    }

    let manifest_dir = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    let candidate = manifest_dir
        .ancestors()
        .nth(4)
        .map(Path::to_path_buf)
        .ok_or_else(|| {
            CommandError::new(
                "kit_root_not_found",
                "Could not locate the Diffmogger source checkout.",
                json!({ "manifestDir": manifest_dir }),
            )
        })?;
    validate_kit_root(&candidate)
}

fn validate_kit_root(candidate: &Path) -> Result<PathBuf, CommandError> {
    let resolved = candidate.canonicalize().map_err(|error| {
        CommandError::new(
            "kit_root_not_found",
            "Could not resolve the Diffmogger source checkout.",
            json!({ "path": candidate, "exception": error.to_string() }),
        )
    })?;
    let cli = resolved.join(BACKEND_CLI);
    if !cli.is_file() {
        return Err(CommandError::new(
            "backend_cli_missing",
            "Diffmogger backend CLI was not found.",
            json!({ "expectedPath": cli }),
        ));
    }
    Ok(resolved)
}

fn app_config_path(app: &AppHandle) -> Result<PathBuf, CommandError> {
    let dir = app.path().app_config_dir().map_err(|error| {
        CommandError::new(
            "config_path_error",
            "Could not resolve the app-local config directory.",
            json!({ "exception": error.to_string() }),
        )
    })?;
    fs::create_dir_all(&dir)
        .map_err(|error| CommandError::io("Could not create app-local config directory.", error))?;
    Ok(dir.join(RECENT_CONFIG_FILE))
}

fn read_native_config(app: &AppHandle) -> Result<NativeConfig, CommandError> {
    let path = app_config_path(app)?;
    if !path.exists() {
        return Ok(NativeConfig::default());
    }

    let text = fs::read_to_string(&path)
        .map_err(|error| CommandError::io("Could not read app-local config.", error))?;
    if text.trim().is_empty() {
        return Ok(NativeConfig::default());
    }

    serde_json::from_str(&text).or_else(|_| Ok(NativeConfig::default()))
}

fn write_native_config(app: &AppHandle, config: &NativeConfig) -> Result<(), CommandError> {
    let path = app_config_path(app)?;
    let tmp_path = path.with_extension("json.tmp");
    let text = serde_json::to_string_pretty(config).map_err(|error| {
        CommandError::new(
            "config_serialize_error",
            "Could not serialize app-local config.",
            json!({ "exception": error.to_string() }),
        )
    })?;
    fs::write(&tmp_path, text)
        .map_err(|error| CommandError::io("Could not write app-local config.", error))?;
    fs::rename(&tmp_path, &path)
        .map_err(|error| CommandError::io("Could not replace app-local config.", error))?;
    Ok(())
}

fn sanitize_advanced_settings(settings: AdvancedSettings) -> Result<AdvancedSettings, CommandError> {
    if settings.preferred_editor_command.contains('\n') || settings.preferred_editor_command.contains('\r') {
        return Err(CommandError::new(
            "invalid_settings",
            "Preferred editor command must be a single line.",
            json!({}),
        ));
    }
    if !settings.review_export_dir.trim().is_empty() {
        let path = PathBuf::from(settings.review_export_dir.trim());
        if path.exists() && !path.is_dir() {
            return Err(CommandError::new(
                "invalid_settings",
                "Review export directory must be a directory.",
                json!({ "reviewExportDir": settings.review_export_dir }),
            ));
        }
    }
    let human_bridge_mode = match settings.human_bridge_mode.as_str() {
        "file_only" | "local_notifier" | "discord_notifier" | "disabled" => settings.human_bridge_mode,
        _ => "file_only".to_string(),
    };
    let appearance = match settings.appearance.as_str() {
        "system" | "light" | "dark" => settings.appearance,
        _ => "system".to_string(),
    };
    let density = match settings.density.as_str() {
        "compact" | "comfortable" => settings.density,
        _ => "comfortable".to_string(),
    };
    Ok(AdvancedSettings {
        review_export_dir: settings.review_export_dir.trim().to_string(),
        preferred_editor_command: settings.preferred_editor_command.trim().to_string(),
        schedule_cadence_minutes: settings.schedule_cadence_minutes.clamp(5, 1440),
        human_bridge_mode,
        appearance,
        density,
    })
}

fn add_recent_target(app: &AppHandle, target: &Path) -> Result<RecentTarget, CommandError> {
    let target = validate_target_path(&target.display().to_string())?;
    let canonical = target.display().to_string();
    let recent = RecentTarget {
        path: canonical.clone(),
        name: target_name(&target),
        last_opened_at: unix_now(),
    };

    let mut config = read_native_config(app)?;
    let mut seen = BTreeSet::new();
    let mut next = vec![recent.clone()];
    seen.insert(canonical);

    for item in config.recent_targets.drain(..) {
        if seen.insert(item.path.clone()) {
            next.push(item);
        }
    }

    next.truncate(MAX_RECENT_TARGETS);
    config.recent_targets = next;
    write_native_config(app, &config)?;
    Ok(recent)
}

#[tauri::command]
fn get_advanced_settings(app: AppHandle) -> Result<AdvancedSettings, CommandError> {
    Ok(read_native_config(&app)?.advanced_settings)
}

#[tauri::command]
fn update_advanced_settings(
    app: AppHandle,
    settings: AdvancedSettings,
) -> Result<AdvancedSettings, CommandError> {
    let sanitized = sanitize_advanced_settings(settings)?;
    let mut config = read_native_config(&app)?;
    config.advanced_settings = sanitized.clone();
    write_native_config(&app, &config)?;
    Ok(sanitized)
}

fn backend_command_allowed(command: &str) -> bool {
    READ_ONLY_BACKEND_COMMANDS.contains(&command) || MUTATING_BACKEND_COMMANDS.contains(&command)
}

fn backend_command_requires_target(command: &str) -> bool {
    !matches!(command, "project.list_recent" | "diagnostics.environment")
}

fn backend_command_requires_review_dir(command: &str) -> bool {
    matches!(
        command,
        "observatory.generate_html" | "observatory.load_html" | "review.export_bundle"
    )
}

fn backend_command_requires_output_dir(command: &str) -> bool {
    command == "advanced.export_debug_bundle"
}

fn path_with_native_toolchain() -> (String, String) {
    let native_path = env::var("PATH").unwrap_or_default();
    let automation_path = env::var("CODEX_AUTOMATION_PATH")
        .ok()
        .filter(|value| !value.trim().is_empty())
        .unwrap_or_else(|| DEFAULT_AUTOMATION_PATH.to_string());
    let mut seen = BTreeSet::new();
    let mut paths: Vec<PathBuf> = Vec::new();

    for raw in [&automation_path, &native_path] {
        for item in env::split_paths(raw) {
            let key = item.display().to_string();
            if !key.is_empty() && seen.insert(key) {
                paths.push(item);
            }
        }
    }

    let effective = env::join_paths(paths)
        .map(|value| value.to_string_lossy().to_string())
        .unwrap_or_else(|_| {
            if native_path.is_empty() {
                automation_path
            } else {
                format!("{automation_path}:{native_path}")
            }
        });
    (native_path, effective)
}

fn executable_on_path(binary: &str, path: &str) -> Option<PathBuf> {
    for dir in env::split_paths(path) {
        let candidate = dir.join(binary);
        if candidate.is_file() {
            return Some(candidate);
        }
    }
    None
}

fn backend_python_executable(path: &str) -> String {
    executable_on_path("python3", path)
        .map(|path| path.display().to_string())
        .unwrap_or_else(|| "python3".to_string())
}

fn prepare_backend_process(args: &[String]) -> ProcessCommand {
    let (native_path, backend_path) = path_with_native_toolchain();
    let python = backend_python_executable(&backend_path);
    let mut command = ProcessCommand::new(python);
    command
        .args(args)
        .env("PATH", &backend_path)
        .env("PYTHONUNBUFFERED", "1")
        .env("DIFFMOGGER_NATIVE_APP_PATH", native_path)
        .env("DIFFMOGGER_BACKEND_PATH", backend_path);
    command
}

#[allow(clippy::too_many_arguments)]
fn build_backend_args(
    command: &str,
    target: Option<&str>,
    review_dir: Option<&str>,
    output_dir: Option<&str>,
    file_key: Option<&str>,
    intake_json: Option<&str>,
    files_json: Option<&str>,
    project_name: Option<&str>,
    ownership: Option<&str>,
    request_id: Option<&str>,
    body: Option<&str>,
    intent: Option<&str>,
    related: Option<&str>,
    force: Option<bool>,
    run_codex: Option<bool>,
    stream_jsonl: bool,
) -> Result<(PathBuf, Vec<String>), CommandError> {
    if !backend_command_allowed(command) {
        return Err(CommandError::new(
            "command_not_allowed",
            "Backend command is not allowed by the native shell.",
            json!({ "command": command }),
        ));
    }

    let root = kit_root()?;
    let cli = root.join(BACKEND_CLI);
    let mut args = vec![cli.display().to_string()];
    if stream_jsonl {
        args.push("--stream-jsonl".to_string());
    }
    args.push(command.to_string());

    if backend_command_requires_target(command) {
        let raw_target = target.ok_or_else(|| {
            CommandError::new(
                "invalid_target",
                "A target path is required for this backend command.",
                json!({ "command": command }),
            )
        })?;
        let resolved = validate_target_path(raw_target)?;
        args.push("--target".to_string());
        args.push(resolved.display().to_string());
    }

    if backend_command_requires_review_dir(command) {
        let raw_review_dir = review_dir.ok_or_else(|| {
            CommandError::new(
                "invalid_review_dir",
                "A review directory is required for this backend command.",
                json!({ "command": command }),
            )
        })?;
        let resolved = validate_review_dir(raw_review_dir)?;
        args.push("--review-dir".to_string());
        args.push(resolved.display().to_string());
    }

    if backend_command_requires_output_dir(command) {
        let raw_output_dir = output_dir.ok_or_else(|| {
            CommandError::new(
                "invalid_output_dir",
                "An output directory is required for this backend command.",
                json!({ "command": command }),
            )
        })?;
        let resolved = validate_output_dir(raw_output_dir)?;
        args.push("--output-dir".to_string());
        args.push(resolved.display().to_string());
    }

    if matches!(command, "advanced.load_file" | "advanced.save_file" | "advanced.validate_file") {
        let key = file_key.ok_or_else(|| {
            CommandError::new(
                "invalid_file_key",
                "A file key is required for this Advanced file command.",
                json!({ "command": command }),
            )
        })?;
        args.push("--file-key".to_string());
        args.push(key.to_string());
    }

    if command == "advanced.save_file" {
        let content = body.ok_or_else(|| {
            CommandError::new(
                "missing_content",
                "Replacement file content is required for advanced.save_file.",
                json!({ "command": command }),
            )
        })?;
        args.push("--content".to_string());
        args.push(content.to_string());
    }

    if matches!(command, "brief.save_draft" | "brief.scaffold_bootstrap") {
        let payload = intake_json.ok_or_else(|| {
            CommandError::new(
                "invalid_intake",
                "An intake JSON payload is required for this backend command.",
                json!({ "command": command }),
            )
        })?;
        args.push("--intake-json".to_string());
        args.push(payload.to_string());
    }

    if command == "context.import" {
        let payload = files_json.ok_or_else(|| {
            CommandError::new(
                "invalid_context_files",
                "A JSON list of context file paths is required for context.import.",
                json!({ "command": command }),
            )
        })?;
        args.push("--files-json".to_string());
        args.push(payload.to_string());
        if let Some(name) = project_name.filter(|value| !value.trim().is_empty()) {
            args.push("--project-name".to_string());
            args.push(name.to_string());
        }
    }

    if command == "worker.run_write" {
        let scope = ownership.ok_or_else(|| {
            CommandError::new(
                "invalid_ownership",
                "An ownership scope is required for worker.run_write.",
                json!({ "command": command }),
            )
        })?;
        args.push("--ownership".to_string());
        args.push(scope.to_string());
    }

    if matches!(command, "inbox.send_note" | "inbox.reply_request") {
        let message = body.ok_or_else(|| {
            CommandError::new(
                "missing_body",
                "A message body is required for this inbox command.",
                json!({ "command": command }),
            )
        })?;
        args.push("--body".to_string());
        args.push(message.to_string());
        if let Some(value) = intent.filter(|value| !value.trim().is_empty()) {
            args.push("--intent".to_string());
            args.push(value.to_string());
        }
    }

    if command == "inbox.send_note" {
        if let Some(value) = related.filter(|value| !value.trim().is_empty()) {
            args.push("--related".to_string());
            args.push(value.to_string());
        }
    }

    if command == "inbox.reply_request" {
        let id = request_id.ok_or_else(|| {
            CommandError::new(
                "missing_request_id",
                "A request id is required for inbox.reply_request.",
                json!({ "command": command }),
            )
        })?;
        args.push("--request-id".to_string());
        args.push(id.to_string());
    }

    if command == "review.mark_reviewed" {
        if let Some(note) = body.filter(|value| !value.trim().is_empty()) {
            args.push("--note".to_string());
            args.push(note.to_string());
        }
    }

    if command == "brief.scaffold_bootstrap" {
        if force.unwrap_or(false) {
            args.push("--force".to_string());
        }
        if run_codex.unwrap_or(false) {
            args.push("--run-codex".to_string());
        }
    }

    Ok((root, args))
}

#[allow(clippy::too_many_arguments)]
fn run_python_backend(
    command: &str,
    target: Option<&str>,
    review_dir: Option<&str>,
    output_dir: Option<&str>,
    file_key: Option<&str>,
    intake_json: Option<&str>,
    files_json: Option<&str>,
    project_name: Option<&str>,
    ownership: Option<&str>,
    request_id: Option<&str>,
    body: Option<&str>,
    intent: Option<&str>,
    related: Option<&str>,
    force: Option<bool>,
    run_codex: Option<bool>,
) -> Result<Value, CommandError> {
    let (root, args) = build_backend_args(
        command,
        target,
        review_dir,
        output_dir,
        file_key,
        intake_json,
        files_json,
        project_name,
        ownership,
        request_id,
        body,
        intent,
        related,
        force,
        run_codex,
        false,
    )?;

    let output = prepare_backend_process(&args)
        .current_dir(&root)
        .output()
        .map_err(|error| {
            CommandError::new(
                "backend_process_failed",
                "Could not run the Diffmogger backend CLI.",
                json!({ "exception": error.to_string() }),
            )
        })?;

    let stdout = String::from_utf8_lossy(&output.stdout);
    let stderr = String::from_utf8_lossy(&output.stderr);
    let payload: Value = serde_json::from_str(stdout.trim()).map_err(|error| {
        CommandError::new(
            "backend_json_error",
            "Backend CLI did not return valid JSON.",
            json!({
                "command": command,
                "exitCode": output.status.code(),
                "stdout": stdout.trim(),
                "stderr": stderr.trim(),
                "exception": error.to_string()
            }),
        )
    })?;

    if payload.get("schema_version").is_none() || payload.get("ok").is_none() {
        return Err(CommandError::new(
            "backend_contract_error",
            "Backend CLI JSON did not include the expected envelope.",
            json!({ "command": command, "payload": payload }),
        ));
    }

    Ok(payload)
}

#[tauri::command]
fn list_recent_projects(app: AppHandle) -> Result<Vec<RecentTarget>, CommandError> {
    Ok(read_native_config(&app)?.recent_targets)
}

#[tauri::command]
fn load_project_snapshot(app: AppHandle, target: String) -> Result<Value, CommandError> {
    let resolved = validate_target_path(&target)?;
    let snapshot = run_python_backend(
        "project.load_snapshot",
        Some(&resolved.display().to_string()),
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        None,
    )?;

    if snapshot.get("ok").and_then(Value::as_bool).unwrap_or(false) {
        add_recent_target(&app, &resolved)?;
    }

    Ok(snapshot)
}

#[tauri::command]
fn select_project_folder(app: AppHandle) -> Result<Option<ProjectLoadResult>, CommandError> {
    let picked = rfd::FileDialog::new()
        .set_title("Choose Diffmogger project folder")
        .pick_folder();
    let Some(folder) = picked else {
        return Ok(None);
    };

    let resolved = validate_target_path(&folder.display().to_string())?;
    let snapshot = run_python_backend(
        "project.load_snapshot",
        Some(&resolved.display().to_string()),
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        None,
    )?;

    let recent = if snapshot.get("ok").and_then(Value::as_bool).unwrap_or(false) {
        add_recent_target(&app, &resolved)?
    } else {
        RecentTarget {
            path: resolved.display().to_string(),
            name: target_name(&resolved),
            last_opened_at: unix_now(),
        }
    };

    Ok(Some(ProjectLoadResult {
        target: recent,
        snapshot,
    }))
}

#[tauri::command]
fn run_backend_command(
    command: String,
    target: Option<String>,
    review_dir: Option<String>,
    output_dir: Option<String>,
    file_key: Option<String>,
    intake_json: Option<String>,
    files_json: Option<String>,
    project_name: Option<String>,
    ownership: Option<String>,
    request_id: Option<String>,
    body: Option<String>,
    intent: Option<String>,
    related: Option<String>,
    force: Option<bool>,
    run_codex: Option<bool>,
) -> Result<Value, CommandError> {
    run_python_backend(
        &command,
        target.as_deref(),
        review_dir.as_deref(),
        output_dir.as_deref(),
        file_key.as_deref(),
        intake_json.as_deref(),
        files_json.as_deref(),
        project_name.as_deref(),
        ownership.as_deref(),
        request_id.as_deref(),
        body.as_deref(),
        intent.as_deref(),
        related.as_deref(),
        force,
        run_codex,
    )
}

#[tauri::command]
#[allow(clippy::too_many_arguments)]
fn run_backend_command_streamed(
    app: AppHandle,
    run_id: String,
    command: String,
    target: Option<String>,
    review_dir: Option<String>,
    output_dir: Option<String>,
    file_key: Option<String>,
    intake_json: Option<String>,
    files_json: Option<String>,
    project_name: Option<String>,
    ownership: Option<String>,
    request_id: Option<String>,
    body: Option<String>,
    intent: Option<String>,
    related: Option<String>,
    force: Option<bool>,
    run_codex: Option<bool>,
) -> Result<Value, CommandError> {
    let (root, args) = build_backend_args(
        &command,
        target.as_deref(),
        review_dir.as_deref(),
        output_dir.as_deref(),
        file_key.as_deref(),
        intake_json.as_deref(),
        files_json.as_deref(),
        project_name.as_deref(),
        ownership.as_deref(),
        request_id.as_deref(),
        body.as_deref(),
        intent.as_deref(),
        related.as_deref(),
        force,
        run_codex,
        true,
    )?;

    let mut child = prepare_backend_process(&args)
        .current_dir(&root)
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .map_err(|error| {
            CommandError::new(
                "backend_process_failed",
                "Could not start the Diffmogger backend CLI.",
                json!({ "exception": error.to_string() }),
            )
        })?;

    let stdout = child.stdout.take().ok_or_else(|| {
        CommandError::new(
            "backend_process_failed",
            "Could not capture backend stdout.",
            json!({ "command": command }),
        )
    })?;
    let mut final_payload: Option<Value> = None;
    for line in BufReader::new(stdout).lines() {
        let line =
            line.map_err(|error| CommandError::io("Could not read backend stdout.", error))?;
        if line.trim().is_empty() {
            continue;
        }
        let payload: Value = serde_json::from_str(line.trim()).map_err(|error| {
            CommandError::new(
                "backend_json_error",
                "Backend CLI stream emitted invalid JSON.",
                json!({ "command": command, "line": line, "exception": error.to_string() }),
            )
        })?;
        if payload.get("event").and_then(Value::as_str) == Some("log") {
            app.emit(
                "backend-log",
                json!({
                    "runId": run_id,
                    "command": command,
                    "stage": payload.get("stage").and_then(Value::as_str).unwrap_or("backend"),
                    "level": payload.get("level").and_then(Value::as_str).unwrap_or("info"),
                    "message": payload.get("message").and_then(Value::as_str).unwrap_or(""),
                    "data": payload.get("data").cloned().unwrap_or_else(|| json!({}))
                }),
            )
            .map_err(|error| {
                CommandError::new(
                    "event_emit_failed",
                    "Could not emit backend progress event.",
                    json!({ "exception": error.to_string() }),
                )
            })?;
        } else {
            final_payload = Some(payload);
        }
    }

    let status = child.wait().map_err(|error| {
        CommandError::new(
            "backend_process_failed",
            "Backend process wait failed.",
            json!({ "exception": error.to_string() }),
        )
    })?;
    let mut stderr = String::new();
    if let Some(mut stderr_pipe) = child.stderr.take() {
        stderr_pipe
            .read_to_string(&mut stderr)
            .map_err(|error| CommandError::io("Could not read backend stderr.", error))?;
    }
    let payload = final_payload.ok_or_else(|| {
        CommandError::new(
            "backend_json_error",
            "Backend CLI stream did not return a final JSON envelope.",
            json!({ "command": command, "exitCode": status.code(), "stderr": stderr.trim() }),
        )
    })?;
    if payload.get("schema_version").is_none() || payload.get("ok").is_none() {
        return Err(CommandError::new(
            "backend_contract_error",
            "Backend CLI JSON did not include the expected envelope.",
            json!({ "command": command, "payload": payload, "exitCode": status.code() }),
        ));
    }
    Ok(payload)
}

#[tauri::command]
fn open_observatory_file(path: String) -> Result<(), CommandError> {
    let resolved = validate_observatory_html_path(&path)?;
    open_path(&resolved, "Could not open the generated Observatory HTML in the default browser.")
}

#[tauri::command]
fn open_review_artifact(path: String) -> Result<(), CommandError> {
    let resolved = validate_review_artifact_path(&path)?;
    open_path(&resolved, "Could not open the generated review artifact.")
}

#[tauri::command]
fn reveal_review_artifact(path: String) -> Result<(), CommandError> {
    let resolved = validate_review_artifact_path(&path)?;
    reveal_path(&resolved)
}

fn open_path(resolved: &Path, message: &str) -> Result<(), CommandError> {
    #[cfg(target_os = "macos")]
    let mut command = {
        let mut command = ProcessCommand::new("open");
        command.arg(resolved);
        command
    };
    #[cfg(target_os = "windows")]
    let mut command = {
        let mut command = ProcessCommand::new("cmd");
        command.args(["/C", "start", ""]).arg(resolved);
        command
    };
    #[cfg(all(not(target_os = "macos"), not(target_os = "windows")))]
    let mut command = {
        let mut command = ProcessCommand::new("xdg-open");
        command.arg(resolved);
        command
    };
    let status = command.status().map_err(|error| {
        CommandError::new(
            "open_failed",
            message,
            json!({ "path": resolved, "exception": error.to_string() }),
        )
    })?;
    if !status.success() {
        return Err(CommandError::new(
            "open_failed",
            "The OS browser opener returned a non-zero status.",
            json!({ "path": resolved, "status": status.code() }),
        ));
    }
    Ok(())
}

fn run_editor_command(binary: &str, target: &Path) -> Result<(), CommandError> {
    let args: &[&str] = match binary {
        "code" | "cursor" => &["--reuse-window"],
        _ => &[],
    };
    let status = ProcessCommand::new(binary)
        .args(args)
        .arg(target)
        .status()
        .map_err(|error| {
            CommandError::new(
                "editor_open_failed",
                "Could not open the project in the selected editor.",
                json!({ "editor": binary, "target": target, "exception": error.to_string() }),
            )
        })?;
    if !status.success() {
        return Err(CommandError::new(
            "editor_open_failed",
            "The editor command returned a non-zero status.",
            json!({ "editor": binary, "target": target, "status": status.code() }),
        ));
    }
    Ok(())
}

fn editor_binary_from_settings(settings: &AdvancedSettings) -> Option<String> {
    let first_token = settings
        .preferred_editor_command
        .split_whitespace()
        .next()
        .unwrap_or("")
        .trim();
    if first_token.is_empty() {
        return None;
    }
    let name = Path::new(first_token)
        .file_name()
        .and_then(|value| value.to_str())
        .unwrap_or(first_token);
    if ALLOWED_EDITOR_COMMANDS.contains(&name) {
        return Some(first_token.to_string());
    }
    None
}

fn reveal_path(resolved: &Path) -> Result<(), CommandError> {
    #[cfg(target_os = "macos")]
    let mut command = {
        let mut command = ProcessCommand::new("open");
        command.arg("-R").arg(resolved);
        command
    };
    #[cfg(target_os = "windows")]
    let mut command = {
        let mut command = ProcessCommand::new("explorer");
        command.arg(format!("/select,{}", resolved.display()));
        command
    };
    #[cfg(all(not(target_os = "macos"), not(target_os = "windows")))]
    let mut command = {
        let mut command = ProcessCommand::new("xdg-open");
        command.arg(resolved.parent().unwrap_or_else(|| Path::new(".")));
        command
    };
    let status = command.status().map_err(|error| {
        CommandError::new(
            "reveal_failed",
            "Could not reveal the managed file.",
            json!({ "path": resolved, "exception": error.to_string() }),
        )
    })?;
    if !status.success() {
        return Err(CommandError::new(
            "reveal_failed",
            "The OS file revealer returned a non-zero status.",
            json!({ "path": resolved, "status": status.code() }),
        ));
    }
    Ok(())
}

fn managed_file_path(target: &str, file_key: &str) -> Result<PathBuf, CommandError> {
    let resolved_target = validate_target_path(target)?;
    let target_text = resolved_target.display().to_string();
    let payload = run_python_backend(
        "advanced.load_file",
        Some(&target_text),
        None,
        None,
        Some(file_key),
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        None,
    )?;
    if !payload.get("ok").and_then(Value::as_bool).unwrap_or(false) {
        return Err(CommandError::new(
            "managed_file_lookup_failed",
            payload
                .get("message")
                .and_then(Value::as_str)
                .unwrap_or("Could not resolve managed file."),
            json!({ "payload": payload }),
        ));
    }
    let raw_path = payload
        .get("data")
        .and_then(|data| data.get("file"))
        .and_then(|file| file.get("path"))
        .and_then(Value::as_str)
        .ok_or_else(|| {
            CommandError::new(
                "managed_file_lookup_failed",
                "Backend did not return a managed file path.",
                json!({ "fileKey": file_key }),
            )
        })?;
    let resolved = PathBuf::from(raw_path).canonicalize().map_err(|error| {
        CommandError::new(
            "managed_file_missing",
            "Managed file does not exist yet.",
            json!({ "path": raw_path, "exception": error.to_string() }),
        )
    })?;
    if !resolved.starts_with(&resolved_target) {
        return Err(CommandError::new(
            "managed_file_outside_target",
            "Managed file resolved outside the target.",
            json!({ "target": resolved_target, "path": resolved }),
        ));
    }
    Ok(resolved)
}

#[tauri::command]
fn open_managed_file(target: String, file_key: String) -> Result<(), CommandError> {
    let resolved = managed_file_path(&target, &file_key)?;
    open_path(&resolved, "Could not open the managed file in the default editor.")
}

#[tauri::command]
fn reveal_managed_file(target: String, file_key: String) -> Result<(), CommandError> {
    let resolved = managed_file_path(&target, &file_key)?;
    reveal_path(&resolved)
}

#[tauri::command]
fn reveal_project(target: String) -> Result<(), CommandError> {
    let resolved = validate_target_path(&target)?;
    reveal_path(&resolved)
}

#[tauri::command]
fn open_project_in_editor(app: AppHandle, target: String) -> Result<(), CommandError> {
    let resolved = validate_target_path(&target)?;
    let settings = read_native_config(&app)?.advanced_settings;
    if let Some(binary) = editor_binary_from_settings(&settings) {
        return run_editor_command(&binary, &resolved);
    }
    for binary in ALLOWED_EDITOR_COMMANDS {
        if which_on_path(binary).is_some() {
            return run_editor_command(binary, &resolved);
        }
    }
    open_path(
        &resolved,
        "Could not open the project folder with the operating system opener.",
    )
}

fn which_on_path(binary: &str) -> Option<PathBuf> {
    let paths = std::env::var_os("PATH")?;
    for dir in std::env::split_paths(&paths) {
        let candidate = dir.join(binary);
        if candidate.is_file() {
            return Some(candidate);
        }
    }
    None
}

#[tauri::command]
fn select_context_files() -> Result<Vec<PickedContextFile>, CommandError> {
    let picked = rfd::FileDialog::new()
        .set_title("Choose context files")
        .pick_files();
    let Some(files) = picked else {
        return Ok(Vec::new());
    };

    let mut records = Vec::new();
    for file in files {
        let resolved = file.canonicalize().map_err(|error| {
            CommandError::new(
                "invalid_context_file",
                "Could not resolve selected context file.",
                json!({ "path": file, "exception": error.to_string() }),
            )
        })?;
        if !resolved.is_file() {
            return Err(CommandError::new(
                "invalid_context_file",
                "Selected context path must be a file.",
                json!({ "path": resolved }),
            ));
        }
        let metadata = fs::metadata(&resolved)
            .map_err(|error| CommandError::io("Could not read context file metadata.", error))?;
        let name = resolved
            .file_name()
            .and_then(|value| value.to_str())
            .map(str::to_string)
            .unwrap_or_else(|| resolved.display().to_string());
        let file_type = resolved
            .extension()
            .and_then(|value| value.to_str())
            .map(str::to_string)
            .filter(|value| !value.is_empty())
            .unwrap_or_else(|| "file".to_string());
        records.push(PickedContextFile {
            path: resolved.display().to_string(),
            name,
            size_bytes: metadata.len(),
            file_type,
        });
    }

    Ok(records)
}

#[tauri::command]
fn select_settings_directory() -> Result<Option<String>, CommandError> {
    let picked = rfd::FileDialog::new()
        .set_title("Choose directory")
        .pick_folder();
    let Some(folder) = picked else {
        return Ok(None);
    };
    let resolved = folder.canonicalize().map_err(|error| {
        CommandError::new(
            "invalid_settings_directory",
            "Could not resolve selected directory.",
            json!({ "path": folder, "exception": error.to_string() }),
        )
    })?;
    if !resolved.is_dir() {
        return Err(CommandError::new(
            "invalid_settings_directory",
            "Selected path must be a directory.",
            json!({ "path": resolved }),
        ));
    }
    Ok(Some(resolved.display().to_string()))
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .invoke_handler(tauri::generate_handler![
            list_recent_projects,
            load_project_snapshot,
            select_project_folder,
            select_context_files,
            select_settings_directory,
            get_advanced_settings,
            update_advanced_settings,
            run_backend_command_streamed,
            run_backend_command,
            open_observatory_file,
            open_review_artifact,
            reveal_review_artifact,
            open_managed_file,
            reveal_managed_file,
            reveal_project,
            open_project_in_editor
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn rejects_unallowlisted_backend_command() {
        let error = run_python_backend(
            "shell.exec",
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
        )
        .unwrap_err();

        assert_eq!(error.kind, "command_not_allowed");
    }

    #[test]
    fn loads_snapshot_through_python_backend_cli() {
        let root = kit_root().expect("Diffmogger kit root should resolve during native tests");
        let root_text = root.display().to_string();
        let payload = run_python_backend(
            "project.load_snapshot",
            Some(&root_text),
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
        )
        .expect("project.load_snapshot should return a JSON envelope");

        assert_eq!(payload["schema_version"], 1);
        assert_eq!(payload["ok"], true);
        assert_eq!(payload["command"], "project.load_snapshot");
        assert!(payload["data"]["target"]["path"].as_str().is_some());
    }

    #[test]
    fn validates_only_generated_observatory_html_paths() {
        let root = kit_root().expect("Diffmogger kit root should resolve during native tests");
        let valid_dir = root.join("target").join("native-test-observatory");
        fs::create_dir_all(&valid_dir).expect("test directory should be created");
        let valid = valid_dir.join("Diffmogger-observatory.html");
        fs::write(&valid, "<html></html>").expect("test html should be written");

        assert!(validate_observatory_html_path(&valid.display().to_string()).is_ok());
        assert!(
            validate_observatory_html_path(&root.join("README.md").display().to_string()).is_err()
        );

        let _ = fs::remove_file(valid);
        let _ = fs::remove_dir_all(valid_dir);
    }

    #[test]
    fn validates_only_generated_review_artifacts() {
        let root = kit_root().expect("Diffmogger kit root should resolve during native tests");
        let valid_dir = root.join("target").join("native-test-review");
        fs::create_dir_all(&valid_dir).expect("test directory should be created");
        let markdown = valid_dir.join("Diffmogger-self-review.md");
        let html = valid_dir.join("Diffmogger-observatory.html");
        let other = valid_dir.join("notes.md");
        fs::write(&markdown, "# Review\n").expect("test markdown should be written");
        fs::write(&html, "<html></html>").expect("test html should be written");
        fs::write(&other, "# Notes\n").expect("test notes should be written");

        assert!(validate_review_artifact_path(&markdown.display().to_string()).is_ok());
        assert!(validate_review_artifact_path(&html.display().to_string()).is_ok());
        assert!(validate_review_artifact_path(&other.display().to_string()).is_err());

        let _ = fs::remove_dir_all(valid_dir);
    }
}
