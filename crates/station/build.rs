use std::process::Command;

fn main() {
    // Capture git SHA at compile time for version stamping.
    //
    // Priority:
    //   1. GIT_SHA env var (set by Dockerfile ARG from CI --set-build-env-vars)
    //   2. git rev-parse --short HEAD (local dev with .git/ available)
    //   3. "unknown" (fallback)
    //
    // Docker builds exclude .git/ for image size, so git rev-parse fails there.
    // The CI pipeline injects GIT_SHA via gcloud --set-build-env-vars.
    let git_sha = std::env::var("GIT_SHA")
        .ok()
        .filter(|s| !s.is_empty() && s != "unknown")
        .unwrap_or_else(|| {
            Command::new("git")
                .args(["rev-parse", "--short", "HEAD"])
                .output()
                .ok()
                .filter(|o| o.status.success())
                .and_then(|o| String::from_utf8(o.stdout).ok())
                .map(|s| s.trim().to_string())
                .unwrap_or_else(|| "unknown".to_string())
        });

    println!("cargo:rustc-env=GIT_SHA={git_sha}");

    // Re-run when SHA source changes.
    println!("cargo:rerun-if-env-changed=GIT_SHA");
    println!("cargo:rerun-if-changed=../../.git/HEAD");
    println!("cargo:rerun-if-changed=../../.git/refs/heads/");
}
