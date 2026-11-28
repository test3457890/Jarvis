use std::env;
use std::path::Path;
use std::process;

use jarvis_core::{summarize_audit_file, validate_loopback_http, validate_relative_workspace_path};

fn main() {
    let args: Vec<String> = env::args().collect();
    match args.get(1).map(String::as_str) {
        Some("check-endpoint") => {
            let Some(url) = args.get(2) else {
                eprintln!("usage: jarvis-core check-endpoint <url>");
                process::exit(2);
            };
            match validate_loopback_http(url) {
                Ok(clean) => println!("OK: {}", clean),
                Err(msg) => {
                    eprintln!("REJECTED: {}", msg);
                    process::exit(1);
                }
            }
        }
        Some("check-path") => {
            let Some(path) = args.get(2) else {
                eprintln!("usage: jarvis-core check-path <relative-path>");
                process::exit(2);
            };
            match validate_relative_workspace_path(path) {
                Ok(()) => println!("OK: {}", path),
                Err(msg) => {
                    eprintln!("REJECTED: {}", msg);
                    process::exit(1);
                }
            }
        }
        Some("audit") => {
            let Some(file) = args.get(2) else {
                eprintln!("usage: jarvis-core audit <actions.log>");
                process::exit(2);
            };
            match summarize_audit_file(Path::new(file)) {
                Ok(s) => println!(
                    "lines={} valid={} malformed={} blocked={}",
                    s.total_lines, s.valid_json_objects, s.malformed_lines, s.blocked_events
                ),
                Err(err) => {
                    eprintln!("ERROR: {}", err);
                    process::exit(1);
                }
            }
        }
        _ => {
            println!("jarvis-core 0.1.0 — native Rust policy and audit verifier");
            println!("Commands: check-endpoint <url> | check-path <relpath> | audit <actions.log>");
        }
    }
}
