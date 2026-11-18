# Windows Defender and the Jarvis launcher

## What changed in 1.2.0

- `Jarvis.bat` is no longer shipped or needed. `install.ps1` creates a Start menu shortcut and a
  `Start Jarvis` shortcut in the program folder. Both point straight at
  `.venv\Scripts\python.exe -m jarvis`. There is no batch file, script host or extra launcher program.
- The `HF_HUB_OFFLINE` setting that the batch file used to set is now applied inside Jarvis.
- PowerShell fallback, from the Jarvis folder:

  ```powershell
  & .\.venv\Scripts\python.exe -m jarvis
  ```

- Existing installs keep their old `Jarvis.bat`. The updater leaves it alone because it is not part
  of the new release manifest. It still works, but the shortcut is the supported launcher.

## What was investigated

The work for this release ran in a Linux environment without Windows or Microsoft Defender, so the
original Defender report could not be reproduced there. No detection name was available. These are
the likely causes, from most to least likely, and how to tell them apart on the affected PC:

| Possible cause | How to check | Notes |
|---|---|---|
| The downloaded ZIP or its extracted files carry the Mark of the Web, and SmartScreen or Defender reacts to an unsigned script from the internet | `scripts\check_defender.ps1` lists `Zone.Identifier` data for each file | Batch files and PowerShell scripts from the internet are a common heuristic trigger. The removed `Jarvis.bat` was only six lines that ran Python. |
| A heuristic on the batch file content | The diagnostic scans each file separately with `MpCmdRun.exe` and names any flagged file | The old file only changed folder, set one environment variable and ran Python. |
| A detection on a dependency installed into `.venv` | Defender's protection history shows the path | The diagnostic skips `.venv`. Check Protection history in Windows Security for paths there. |
| `-ExecutionPolicy Bypass` on the command line | Protection history shows `powershell.exe` with the command line | The setting applies to that one process only. It does not change the system policy. |

Run the read-only diagnostic on the affected PC and report the threat name and file:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\check_defender.ps1 -Path "C:\Users\you\Downloads\Jarvis1.2.0.zip"
```

It does not change Defender settings, add exclusions or remove download markers.

## What Jarvis does not do

Jarvis does not disable Defender, ask for an antivirus exclusion, hide its files or processes,
or claim to be signed. The release ZIP and scripts are **not code-signed** today. Verify downloads
with the published `SHA256SUMS.txt` value. That proves the file matches the release. It does not
prove who built it.

## Legitimate signing and packaging path

1. **Sign the PowerShell scripts and any future executable** with an Authenticode certificate.
   Options include an organization-validated code-signing certificate from a public CA,
   Microsoft's Trusted Signing (Azure Artifact Signing) service, or a free open-source signing
   programme such as SignPath Foundation. Sign in CI with `signtool` or `Set-AuthenticodeSignature`
   and timestamp every signature.
2. **Publish signed releases only from the release workflow**, with the signing key held by the
   signing service rather than in the repository.
3. **Consider an MSIX or MSI installer** once signing exists. A signed installer can create the
   shortcut and install Python packages in one trusted step.
4. **Report false positives** with the file and detection name through Microsoft's file submission
   portal (https://www.microsoft.com/wdsi/filesubmission). Do this only after confirming the file
   matches the published checksum.
5. Reputation for a new signature still builds over time, so SmartScreen can warn at first even
   after signing.
