# Jarvis upgrade status

The 1.1.0 release provides the following upgrades.

| Area | Delivered behavior |
|---|---|
| Setup | HUD profile and document-folder controls, CLI setup, prerequisite errors and recoverable installer downloads |
| Low memory | Smaller models, shorter context, keyword recall and configurable model residency |
| Voice | Streaming drafts, sentence playback in Talk mode, Stop button, Escape key and queued-speech cancellation |
| Documents | Selected local PDF, Word, Markdown and text extraction with page or section references and bounded current-file searches |
| Fact-checking | Approved HTTPS page reads, pinned public-address connections, extracted source text and claim assessment |
| Desktop files | Confirmed copy/move inside Jarvis Code, persistent job state, resume, history and undo |
| Browser | Existing website-opening skill, with source reading as a separately approved operation |
| Memory | Fact editing/deletion/export, conversation deletion and transactional database backup/restore with rescue snapshots |
| Releases | Versioned source ZIP, SHA256 checksums, manifest validation and source updater with backup/restore |
| Evaluation | Reproducible automated tests, live browser checks, runtime reply timing and local model/speech benchmark commands |

The document search reads current files on demand. Persistent indexing, OCR and broad browser form automation remain future extensions. Early sentence playback applies to Talk mode. Action modes wait for completed tool processing before speech. Stop cancels pending approvals and stops speech at the next worker checkpoint. Requests waiting on network I/O may take until a chunk arrives or the request times out. A completed file action can be reversed through its supported undo command.

Hardware benchmarks and microphone validation must be collected on the target PC. Published automation results establish the tested behavior. They do not measure model intelligence, voice quality or comparative ranking among other GitHub projects.
