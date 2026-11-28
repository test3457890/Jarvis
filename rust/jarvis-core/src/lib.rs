//! Jarvis Core Rust Foundation
//!
//! Zero-dependency native Rust library providing fast, deterministic validation for:
//! - Loopback-only local endpoint verification (strictly 127.0.0.1 with explicit port, no credentials)
//! - Workspace path traversal and Windows reserved device name checks
//! - Redacted JSONL audit log verification and summary counters

use std::path::Path;

const WINDOWS_RESERVED: &[&str] = &[
    "CON", "PRN", "AUX", "NUL",
    "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9",
    "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9",
];

/// Validate that a URL is strictly a numeric loopback HTTP endpoint (`http://127.0.0.1:<port>`)
/// with no embedded credentials, query string, fragment, or extra path segments.
pub fn validate_loopback_http(url: &str) -> Result<String, &'static str> {
    if url.bytes().any(|b| b < 33) {
        return Err("URL contains control or whitespace characters");
    }
    let rest = url
        .strip_prefix("http://127.0.0.1:")
        .ok_or("Endpoint must use http://127.0.0.1:<port>")?;
    if rest.contains('@') || rest.contains('?') || rest.contains('#') {
        return Err("Credentials, query strings, and fragments are forbidden");
    }
    let port_part = rest.strip_suffix('/').unwrap_or(rest);
    if port_part.contains('/') || port_part.is_empty() {
        return Err("Extra path segments are forbidden");
    }
    let port: u16 = port_part.parse().map_err(|_| "Invalid port number")?;
    if port == 0 {
        return Err("Port 0 is invalid");
    }
    Ok(format!("http://127.0.0.1:{}", port))
}

/// Check whether a relative workspace path is safe against traversal, `.git` access,
/// drive prefixes, and Windows reserved device names.
pub fn validate_relative_workspace_path(rel: &str) -> Result<(), &'static str> {
    if rel.is_empty() || rel.len() > 512 {
        return Err("Path must be between 1 and 512 characters");
    }
    if rel.starts_with('/') || rel.starts_with('\\') || rel.contains(':') {
        return Err("Absolute paths and drive prefixes are forbidden");
    }
    for segment in rel.split(['/', '\\']) {
        if segment.is_empty() || segment == "." || segment == ".." {
            return Err("Path traversal or empty segment detected");
        }
        if segment.eq_ignore_ascii_case(".git") {
            return Err("Access to .git directory is forbidden");
        }
        let stem = segment.split('.').next().unwrap_or("");
        if WINDOWS_RESERVED
            .iter()
            .any(|r| r.eq_ignore_ascii_case(stem))
        {
            return Err("Windows reserved device name is forbidden");
        }
    }
    Ok(())
}

#[derive(Debug, Default, PartialEq, Eq)]
pub struct AuditSummary {
    pub total_lines: usize,
    pub valid_json_objects: usize,
    pub malformed_lines: usize,
    pub blocked_events: usize,
}

/// Inspect a JSONL audit log stream (such as `%APPDATA%\Jarvis\actions.log`) and count
/// valid entries, malformed lines, and defensive block events.
pub fn summarize_audit_log(contents: &str) -> AuditSummary {
    let mut summary = AuditSummary::default();
    for line in contents.lines() {
        let trimmed = line.trim();
        if trimmed.is_empty() {
            continue;
        }
        summary.total_lines += 1;
        if trimmed.starts_with('{') && trimmed.ends_with('}') && trimmed.contains("\"action\"") {
            summary.valid_json_objects += 1;
            if trimmed.contains("blocked") || trimmed.contains("rate_limited") {
                summary.blocked_events += 1;
            }
        } else {
            summary.malformed_lines += 1;
        }
    }
    summary
}

pub fn summarize_audit_file(path: &Path) -> std::io::Result<AuditSummary> {
    let data = std::fs::read_to_string(path)?;
    Ok(summarize_audit_log(&data))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn accepts_valid_loopback_endpoints() {
        assert_eq!(
            validate_loopback_http("http://127.0.0.1:8081").unwrap(),
            "http://127.0.0.1:8081"
        );
        assert_eq!(
            validate_loopback_http("http://127.0.0.1:11434/").unwrap(),
            "http://127.0.0.1:11434"
        );
    }

    #[test]
    fn rejects_unsafe_endpoints() {
        for bad in [
            "https://127.0.0.1:8081",
            "http://localhost:8081",
            "http://example.com:8081",
            "http://user:pass@127.0.0.1:8081",
            "http://127.0.0.1:8081/v1",
            "http://127.0.0.1:0",
            "http://127.0.0.1:99999",
            "http://127.0.0.1:8081?x=1",
        ] {
            assert!(validate_loopback_http(bad).is_err(), "should reject {}", bad);
        }
    }

    #[test]
    fn validates_workspace_paths() {
        assert!(validate_relative_workspace_path("src/app.py").is_ok());
        assert!(validate_relative_workspace_path("budget/test_budget.py").is_ok());
        for bad in [
            "../secret.txt",
            "a/../../b.py",
            ".git/config",
            "C:\\Windows\\win.ini",
            "folder/CON.txt",
            "NUL",
            "/etc/passwd",
        ] {
            assert!(
                validate_relative_workspace_path(bad).is_err(),
                "should reject {}",
                bad
            );
        }
    }

    #[test]
    fn summarizes_audit_logs() {
        let log = r#"{"time":"2026-11-27 12:00:00","action":"lockdown_blocked","detail":{"skill":"power"}}
{"time":"2026-11-27 12:01:00","action":"code_edit_applied","detail":{"files":["a.py"]}}
corrupted line
{"time":"2026-11-27 12:02:00","action":"network_blocked","detail":{"purpose":"test"}}
"#;
        let s = summarize_audit_log(log);
        assert_eq!(s.total_lines, 4);
        assert_eq!(s.valid_json_objects, 3);
        assert_eq!(s.malformed_lines, 1);
        assert_eq!(s.blocked_events, 2);
    }
}
