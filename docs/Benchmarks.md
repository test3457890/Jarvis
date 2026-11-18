# Benchmarks

## Status

No benchmark results are published for 1.2.0. The changes in this release were developed and tested
in a Linux environment with mocked model responses. They have **not** been measured on an 8 GB
Windows PC, so this release makes no claim of faster replies or better answer quality.

## How to record results on the target PC

From the Jarvis folder, after the setup wizard finishes:

```powershell
& .\.venv\Scripts\python.exe -m scripts.benchmark
& .\.venv\Scripts\python.exe -m scripts.benchmark --audio sample.wav --expected "Jarvis read my briefing"
```

The report is saved in the local Jarvis benchmarks folder with the hardware details. Record, for both
the Standard and the 8 GB low-memory profile:

| Measure | Standard | Low memory |
|---|---|---|
| Time to first text, Jarvis everyday question | not measured | not measured |
| Time to first text, TUKI technical question | not measured | not measured |
| Coding proposal time for a small fix | not measured | not measured |
| Peak memory during a reply | not measured | not measured |
| Speech word error rate on the labelled sample | not measured | not measured |

## Known limitations
- Model quality depends on the installed Ollama models. Smaller low-memory models produce weaker
  patches and are more likely to return a SEARCH block that does not match. Jarvis then saves nothing.
- Unloading models after each reply (low-memory profile) saves memory and adds load time.
