# Jarvis upgrade plan

## First delivery

The installer and runtime offer standard and low-memory profiles. Low-memory uses qwen3:4b, qwen2.5-coder:1.5b, a 2048-token context, base.en speech recognition, keyword memory recall, and zero chat keep-alive. Model quality and speed require measurement on the target PC.

## Remaining deliveries

1. Installation and releases. Add a setup screen, recoverable prerequisite checks, versioned release packages, an upgrade backup, and restoration of the previous version. Verify a clean Windows install and a failed upgrade recovery.
2. Voice. Add streamed replies, sentence playback, an interrupt control, and measured wake-word accuracy. Verify that cancellation cannot approve a pending action or execute a partial tool call.
3. Documents. Add explicit folder selection, PDF and Word extraction, a local index, and file/page citations. Verify changed and deleted documents and keep permission checks on every read.
4. Fact-checking. Add approved full-page retrieval, source comparison, and claim-level evidence. Verify redirects, private network destinations, and embedded instructions before enabling retrieval.
5. Desktop tasks. Add task previews, progress, cancellation, and resumable steps for supported browser and file workflows. Verify partial failures and undo where supported.
6. Memory controls. Add review, edit, deletion, export, and transactional backup/restore in the HUD. Include the saved conversation and remembered facts in deletion choices.
7. Published evaluation. Measure installation success, time to first reply, full response time, memory use, speech recognition, document citation accuracy, and task completion on named hardware. Publish measured results with the tested version.

These remaining deliveries are planned work. A passing mocked service test does not establish model accuracy or performance on a user's hardware.
