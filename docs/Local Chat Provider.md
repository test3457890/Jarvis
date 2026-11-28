# Optional local chat-completions provider

Ollama remains the default. In Setup, load provider settings, choose Local chat-completions server, enter its numeric-loopback HTTP base address and exact model ID, and save. For example, an already installed local service might listen at `http://127.0.0.1:8081`. Do not append `/v1`. List active provider models reads that saved service's `/v1/models` endpoint. No models or servers are downloaded or started by these controls.

The adapter implements non-streaming `/v1/chat/completions` with the message and tool-call conventions documented by the [llama.cpp server](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md). Protocol support is verified with a small real loopback HTTP fixture, not an installed inference model. Compatibility with a specific server/model/template still needs a real test.

## Behavior and boundaries

- Numeric `127.0.0.1`, an explicit valid port and HTTP are required. Credentials in URLs, extra paths, queries, fragments, remote hosts, redirects and system proxies are refused.
- One selected model handles everyday chat, TUKI and coding for this provider. Ollama role selections are retained for switching back. Model IDs are configuration, not proof that a model is installed or compatible.
- Chat history, selected document excerpts and tool context may be sent to the chosen local service as needed for the task. Keyword memory recall is used; the adapter does not silently depend on Ollama embeddings.
- Completed replies are supported. Ollama streaming, context options, keep-alive and thinking controls are not passed to this provider. Cancellation is checked before the request and after the response; Stop may wait for a blocking local request to finish or time out. Cancelled responses cannot issue tool calls.
- Response reads are bounded to 1 MB, text to 250,000 characters, tool calls to 16 and arguments to 32,000 characters. Incomplete, malformed, duplicate-ID and length-truncated tool calls are refused before any tool executes.
- Existing tool permissions, approval requirements, scoped coding, offline/Lockdown rules and injection screening still apply. The model cannot invoke manual-only tools.
- Vision, speech and optional image generation retain their separate setup. No cloud fallback, remote model endpoint, provider key storage or authenticated local server is included in this initial adapter.

## Verification still required

Start an authorized local inference server yourself, select an actually loaded compatible model ID, inspect a conversation, test a harmless calculator tool round trip, review a risky-action preview without executing it, test coding diff generation without applying it, Stop a response, stop the server, and verify a clear error without fallback. Record Windows hardware, model, server/template and performance results before calling that setup verified.
