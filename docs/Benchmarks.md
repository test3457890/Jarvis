# Benchmarks

## Status

No benchmark results are published for 1.2.0. The changes in this release were developed and tested
in a Linux environment with mocked model responses. They have **not** been measured on an 8 GB
Windows PC, so this release makes no claim of faster replies or better answer quality.

## What the benchmark measures (since increment 2)

| Measure | How |
|---|---|
| Reply time | Wall time for one Jarvis and one TUKI prompt |
| First text and first sentence | Time to the first streamed token, and to the first complete sentence. Talk mode starts speaking at the first sentence, so this approximates the first spoken response. Audio playback time is not included. |
| Peak memory | Sampled every 0.2 s: the Jarvis process and all Ollama processes |
| Coding success (`--coding`) | Three small projects: valid proposal, applied, tests passed. The script asks before running generated code unless `--yes` is given |

`tests/test_benchmark_harness.py` checks the harness with stubbed models. Those are not results.

## How to record results on the target PC

From the Jarvis folder, after the setup wizard finishes:

```powershell
& .\.venv\Scripts\python.exe -m scripts.benchmark
& .\.venv\Scripts\python.exe -m scripts.benchmark --coding
& .\.venv\Scripts\python.exe -m scripts.benchmark --audio sample.wav --expected "Jarvis read my briefing"
```

The report is saved in the local Jarvis benchmarks folder with the hardware details. Record, for both
the Standard and the 8 GB low-memory profile:

| Measure | Standard | Low memory |
|---|---|---|
| Time to first text, Jarvis everyday question | not measured | not measured |
| Time to first text, TUKI technical question | not measured | not measured |
| Time to first complete sentence | not measured | not measured |
| Coding proposal time for a small fix | not measured | not measured |
| Coding suite: valid proposals / tests passed (of 3) | not measured | not measured |
| Peak memory during a reply | not measured | not measured |
| Speech word error rate on the labelled sample | not measured | not measured |

## Known limitations
- Model quality depends on the installed Ollama models. Smaller low-memory models produce weaker
  patches and are more likely to return a SEARCH block that does not match. Jarvis then saves nothing.
- Unloading models after each reply (low-memory profile) saves memory and adds load time.

## Document search (measured in the development container, not on Windows)

`python -m scripts.measure_document_search --ocr` on 2 CPUs, Linux, Python 3.13, local disk:

| Measure | Result |
|---|---|
| Search 200 text files and 20 text PDFs (search stops at 200 documents) | 0.07 to 0.16 s per query |
| OCR of 5 scanned PDF pages, first search | 0.59 s |
| Same OCR search again (session cache) | 0.003 s |

A persistent index was not added: searches at the current 200-document limit already finish in
well under a second here. Re-measure on the Windows PC. If searches there take more than a
second, or the limit is raised, an index becomes worth adding.
