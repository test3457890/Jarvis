# Spatial Intelligence development handoff

Date: November 28, 2026
Branch: `feature/jarvis-spatial-intelligence`
Base: Command Center `6dd123e4e067ffdf174bc9f5e0c017334fae0ea6`

## Implemented first slice

The existing Command Center React HUD has an Intelligence Canvas view. Verified reply events appear as plain-text summary cards labeled **actual**. A bounded visual event decoder accepts summary, HTTPS source, comparison and progress cards. Other shapes are discarded. The provisional `visual` SSE event is displayed as **placeholder** regardless of model-supplied provenance; it cannot assert a verified finding. React renders fixed components and never evaluates event HTML or JavaScript. Users can reorder and remove cards, clear the canvas and export the cards as JSON. Up to 40 cards reopen from this browser profile using localStorage; corrupted, oversized or invalid saved entries are rejected. No frames, images or credentials are stored by this feature.

## Scope and security boundary

The protocol is currently a frontend consumer. No camera pipeline, marker detection, gestures, data-driven source verification, backend workspace persistence or import exists yet. External images and video URLs are intentionally excluded pending a server-side media authorization and privacy design. HTTPS source links only open when the user clicks them. Browser localStorage is specific to the profile, may be cleared by the browser, and is readable to scripts on the same origin. Do not put sensitive data on this canvas. The existing loopback authentication, approval and Lockdown flows remain responsible for real actions; visual events grant no authority.

## Verification

Six local Node 24 validation checks passed for rejected dangerous URL schemes, URL credentials, invalid progress, malformed tables, discarded unsupported fields and corrupted persistence. A frontend production build and full Python/Rust/browser regression gates need CI or a Windows development host with dependencies. No hardware-dependent webcam, microphone, GPU, spatial measurement or gesture claim is made.

## Next implementation milestones

1. Add an authenticated backend visual-event emitter bound to actual task results, provenance evidence and per-task identifiers, with tests against forged provenance and oversized payloads.
2. Add camera lifecycle with explicit device selection, live indicator, immediate stop and synthetic frame tests. Run real hardware checks on Windows separately.
3. Add calibrated marker coordinates and uncertainty reporting, then opt-in gestures with cancellation and no sensitive-action authority.
4. Add workshop cards and safe local file previews, persist workspaces in the existing database with retention settings, and audit the frontend end to end.
5. Measure GPU/CPU budget on the named Windows workstation and preserve the Kokoro neural voice path.

Architectural references reviewed: Huw Prosser's public Fury and ArUco repositories, jarvis-mlx, web-whisper, clap-detection and God’s Eye View. No third-party source or media was copied; dependency licensing must be verified before future reuse.
