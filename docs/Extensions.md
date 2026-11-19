# Writing a Jarvis extension

Extensions add tools to Jarvis without changing its code. Nothing loads by default.

## Layout

```
%APPDATA%\Jarvis\extensions\word-count\
    extension.json
    main.py
```

A working example is in `docs/examples/extensions/word-count`. Copy that folder into the
extensions folder, open **Apps and extensions** in the HUD, and select **Enable**.

## Manifest (`extension.json`)

| Field | Meaning |
|---|---|
| `id` | Lowercase letters, digits and dashes. Must match the folder name. |
| `name`, `version`, `description` | Shown to the user before enabling. |
| `entry` | A `.py` file inside the folder. |
| `permissions` | Any of `network`, `read_selected_folders`, `write_selected_folders`. Empty for none. |
| `network_hosts` | Host names the extension declares for review. Needs `network`; these names are not a network sandbox. |
| `tools` | 1 to 10 tools: `name`, `description`, `inputs`, `outputs`, optional `risky`. |
| `tests` | `{ "tool", "input", "expect" }` cases run by **Run its tests** or `python -m jarvis.extensions test <id>`. |

Inputs are `{ "type": "string" | "integer" | "number" | "boolean", "description", "required" }`.
Outputs map names to the same types. Jarvis checks both and rejects anything else.

Each tool is a Python function with the same name. It receives the inputs as keyword arguments
and returns a dict with the declared outputs.

## What Jarvis enforces

- **Approval:** the user enables each extension and approves exactly the permissions it declares.
  If a later version asks for more permissions or hosts, the extension turns off until approved again.
- **Confirmation:** tools marked `risky`, and every tool of an extension with `network` or
  `write_selected_folders`, show a preview and wait for Confirm. Lockdown blocks them.
- **Offline by default:** network tools are hidden while the Internet toggle is off. Without the
  granted `network` permission, the runner blocks Python's socket functions.
- **Extension tests:** an extension must be enabled and approved before its tests can run.
- **Separate process:** each call runs in a new Python process with a reduced environment,
  a 30-second limit and 100 KB of output. Results are treated as untrusted text.
- **Audit:** enabling, disabling and every tool call are written to `actions.log`.

## What Jarvis does not enforce

Extensions run as your Windows user. The process boundary and socket blocking stop mistakes, not
a deliberately hostile extension, which could read other files or start programs. The
`read_selected_folders` and `write_selected_folders` permissions tell the extension which folders
the user chose (in `JARVIS_SELECTED_FOLDERS`); they are not a file-system sandbox. Install only
extensions whose code you have read or whose author you trust.
`network_hosts` is shown during approval but is not an enforced host allowlist. An enabled extension
with network permission can contact other hosts while Internet is on.
