# Coding with Jarvis and TUKI

Coding mode uses TUKI and the locally configured `coder_model`. The coding workspace is
`Documents\Jarvis Code` by default. Setup lets you choose another workspace. Coding tools
only edit files inside that workspace, which is separate from the selected folders used by
general File tasks.

## A small project workflow

1. Put a project in your coding workspace, for example `Jarvis Code\budget\budget.py`.
2. Select Coding mode. Type `/fix budget/budget.py | handle an empty list`. To edit two
   existing files together, separate them with a comma:
   `/fix budget/budget.py, budget/helpers.py | handle empty input and update the helper`.
3. Review the diff and any syntax-check result. Use `/diff` to read a long proposal in
   full. Nothing is saved at this point.
4. Type `/apply` to save the proposed changes, or make a new request instead.
5. Type `/test budget/budget.py` to preview the detected test command. Confirm only if
   you trust the project code and want it to run on this PC. If tests fail, use
   `/fix-tests budget/budget.py | fix the reported failure`, then review another diff.
6. Type `/build budget/budget.py` to preview the build command. Python projects use
   `python -m compileall`, which byte-compiles files without importing or running them.
   Node projects use `npm run build` when the project defines it, which runs project code.
   Both need your confirmation.
7. Type `/undo` to restore the applied edit if those files have not changed again. The last
   applied edit is saved in Jarvis's local database, so `/undo` also works after a restart.

When `/fix-tests` uses failed test or build output, Jarvis adds up to three workspace files named
in that output (for example traceback paths) as read-only context.

You can add up to three read-only context files after the change request, for example
`/fix budget/budget.py | handle empty input | budget/rules.txt`. Jarvis also picks up to three
related files itself: modules the target imports, files that import it, its tests, and files
named in your request. The preview lists every file sent as context under
"Read-only context sent to the model". Set `auto_context` to `false` in `config.json` to turn this off.

Context is bounded. The project scan stops after 5,000 entries, skips `.git`, virtual
environments, `node_modules`, build folders and links, and the model sees at most 200 file names.
File contents per request are limited to 12,000 characters on the Standard profile and
4,096 on the 8 GB low-memory profile, whose model has a 2,048-token context. Automatic
context files that do not fit are left out; files you name that do not fit stop the request.
Paths that go through a link or junction are refused. Select up to six editable files per request.
If its patch quotes lines that do not match, Jarvis requests one repair from the model.
An unrepairable patch saves nothing. More attempts can be made with a narrower request.

## What checks actually do

| Change | Before Apply | After Apply |
|---|---|---|
| Python | Compiles proposed text without importing or running it | `/test` can run detected pytest or unittest tests after approval |
| JSON | Parses proposed text | No built-in semantic schema validation |
| JavaScript | `node --check` when Node is installed | `/test` can run `npm test` after approval when a test script exists |
| Other languages | Shows the diff and says no syntax checker is available | Run your own build or test command separately |

The test command runs project code under your Windows account after your confirmation.
The 120-second timeout, reduced environment and attempted process limits are useful
boundaries, not a security guarantee. Do not approve tests from a project you do not trust.
Python and JavaScript program runs through the separate Run skill also require approval.

## Current limits and how to test them

| Limit | Reproducible check | Expected result |
|---|---|---|
| Ambiguous patch | Ask TUKI to replace a line that occurs twice | The proposal is rejected or repaired with an exact match; no file is saved automatically |
| More than six editable files | List seven paths before `|` in `/fix` | Explicit six-file limit; no model request or saved edit |
| Changed file after preview | Preview a patch, change its target in an editor, then `/apply` | Jarvis refuses to overwrite your newer edit |
| Invalid Python or JSON | Ask for a deliberately invalid change in a disposable test file | Syntax error shown; file unchanged |
| No detected tests | Use `/test` in a project without Python tests or an npm test script | Jarvis reports no test command found |
| Link inside the workspace | Make a symbolic link in the project and `/fix` it | Refused, nothing sent to the model |
| Large project | Put more than 5,000 files in a project and `/fix` one file | Preview works; the project list is marked truncated |
| Test or build timeout | A test that sleeps longer than 120 seconds | Stopped and reported as no result |
| Undo after restart | Apply, restart Jarvis, `/undo` | Restored if the files are unchanged |
| Low-memory model quality | Run the same small fix on both profiles and compare the diffs and results | Record what actually happened; a smaller model can produce invalid patches |

The automated suite checks relevant-file selection, context budgets, link refusal, bounded scans,
malformed and conflicting patches, timeouts, approved builds, undo after restart, patch rejection, a repaired patch, multi-file apply and undo,
syntax failures, changed-file protection, rollback on a failed write, and test approval.
It uses stubbed model responses. It does not measure a real model's coding accuracy,
compile every language, or prove that generated code is correct. For hardware timings,
see [Benchmarks](Benchmarks.md). Report a failed real-world task with the exact prompt,
model name, diff or error, and test output, after removing private information.
