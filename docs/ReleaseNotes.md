Jarvis 1.2.1 improves the 1.2.0 coding workflow. When a model returns a patch with unmatched SEARCH text or an invalid edit format, Jarvis asks it to repair the patch once against the same file content. The proposed change still needs review and Apply. Requests selecting more than six editable files are rejected explicitly. A new coding guide documents checks and limits, and the source ZIP includes the README screenshots.

The release is not code-signed. Verify the ZIP with SHA256SUMS.txt. Close Jarvis before running upgrade.ps1. The updater replaces shipped program files only and keeps your settings, data and the old Jarvis.bat. Run install.ps1 afterwards to refresh packages and create the shortcut.

Automated tests run on Linux and Windows in CI. Actual coding quality, performance on an 8 GB Windows PC, and Defender behavior still need target-PC testing. See docs/Coding Guide.md, docs/Benchmarks.md and CHANGELOG.md.
