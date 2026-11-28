# Spatial Intelligence development handoff

Date: November 28, 2026
Branch: `feature/jarvis-spatial-intelligence`
Base: Command Center `6dd123e4e067ffdf174bc9f5e0c017334fae0ea6`

## Implemented first slice

The existing Command Center React HUD has an Intelligence Canvas view. Verified reply events appear as plain-text summary cards labeled **actual**. A bounded visual event decoder accepts summary, HTTPS source, comparison and progress cards. Other shapes are discarded. The provisional `visual` SSE event is displayed as **placeholder** regardless of model-supplied provenance; it cannot assert a verified finding. React renders fixed components and never evaluates event HTML or JavaScript. Users can reorder and remove cards, clear the canvas and export the cards as JSON. Up to 40 cards reopen from this browser profile using localStorage; corrupted, oversized or invalid saved entries are rejected. Camera frames remain in browser memory only, and Stop clears the temporary image. No camera data or credentials are persisted or uploaded by this frontend.

## Scope and security boundary

The protocol is currently a frontend consumer. A minimal browser-local camera preview is now available in the existing Smart Home & Cameras workspace. It requests permission on Start, shows an activity badge, supports browser-reported devices and role/resolution/frame-rate choices, captures a temporary in-memory frame, and stops media tracks on Stop, workspace exit or Lockdown. A cancellation token closes tracks if a permission request resolves after Stop. There is still no object analysis, multi-camera orchestration, backend camera access, marker detection, gestures, data-driven source verification, backend workspace persistence or import. External images and video URLs are intentionally excluded pending a server-side media authorization and privacy design. HTTPS source links only open when the user clicks them. Browser localStorage is specific to the profile, may be cleared by the browser, and is readable to scripts on the same origin. Do not put sensitive data on this canvas. The existing loopback authentication, approval and Lockdown flows remain responsible for real actions; visual events grant no authority.

## Verification

Three committed Node tests passed on CI (unsafe URLs/HTML, invalid progress/tables, corrupted saved data). The strict TypeScript/Vite production build passed and rebuilt the checked-in HUD assets. CI on the implementation branch: legacy HUD 73/73 and modern browser 32/32, including a synthetic canvas reload/reorder/export check; Linux Python 405 passed, 11 skipped; Rust policy tests and Windows installer passed. Windows Python 406 passed, 10 skipped. All six jobs passed in [CI run 46188663762](https://github.com/test3457890/Jarvis/actions/runs/46188663762) on code commit `475307d3`; later commits changed only this handoff and the screenshot. The optional camera path is tested only with a synthetic browser MediaStream fixture; no hardware-dependent webcam, microphone, GPU, spatial measurement or gesture claim is made. The screenshot at `docs/screenshots/command-center-intelligence-canvas.png` was captured in an authenticated Playwright browser with visibly labeled synthetic fixture content.

## Next implementation milestones

1. Add an authenticated backend visual-event emitter bound to actual task results, provenance evidence and per-task identifiers, with tests against forged provenance and oversized payloads.
2. Validate real built-in/USB camera permission, disconnection and preview behavior on Windows. Extend the browser-local preview into separately authorized multi-camera pipelines with resource limits and synthetic frame analysis tests.
3. Add calibrated marker coordinates and uncertainty reporting, then opt-in gestures with cancellation and no sensitive-action authority.
4. Add workshop cards and safe local file previews, persist workspaces in the existing database with retention settings, and audit the frontend end to end.
5. Measure GPU/CPU budget on the named Windows workstation and preserve the Kokoro neural voice path.

Public repository metadata was inspected for Huw Prosser's Fury and ArUco projects, jarvis-mlx, web-whisper, clap-detection and God’s Eye View. Detailed code and license audits remain pending. No third-party source or media was copied.

## Try this branch on Windows

1. Download the source ZIP for `feature/jarvis-spatial-intelligence` from GitHub or check out that branch in a separate working directory. Do not overwrite a Command Center development checkout.
2. Follow `README.md` and run `install.ps1` in PowerShell for the existing Jarvis setup; preserve your existing user data and model settings.
3. Start Jarvis normally, open `http://127.0.0.1:8765/command-center`, and choose **Intelligence Canvas** in the top bar. Send a normal assistant message to add a response card. Use the card controls to move/remove it, **Export JSON** to download a copy, or **Clear canvas** to remove local cards.
4. The saved cards reopen only in the same browser profile. Export a copy before clearing browser storage or changing profiles. Do not place confidential material on this canvas yet.

## Feature completion matrix

| Capability | Current state |
|---|---|
| Typed, bounded text/source/table/progress cards | Implemented and tested in browser/build CI |
| Browser-local card persistence, reordering and JSON export | Implemented and tested with synthetic fixture |
| Authenticated backend visual result producer and evidence binding | Not implemented |
| Local browser camera preview and cancellation | Implemented; synthetic browser test pending CI, real hardware untested |
| Multi-camera orchestration, gesture control, marker tracking and physical measurements | Not implemented; requires hardware testing |
| Workshop, 3D assets, device adapters and cinematic sound effects | Not implemented |
| Windows host resource measurements and new hardware screenshots | Not measured in this branch |

## Local camera privacy and test boundary

Open **Smart Home & Cameras** in the Command Center and choose **Start camera**. Your browser asks for permission; browser-level permission settings remain authoritative. **Stop camera** stops local tracks immediately, including after a late permission response. Leaving that workspace or turning on Lockdown also stops the preview. **Capture frame** displays one still image only in browser memory; Stop clears it. No camera frame is sent to an assistant, model provider, remote endpoint or browser storage. Use the operating system's physical privacy switch when desired. Camera preview was tested using a generated browser MediaStream, so device enumeration, driver compatibility, actual capture quality and GPU impact remain unverified on the Windows workstation.
