"""Measure Jarvis with the models installed on this PC. Nothing here is simulated.

    python -m scripts.benchmark                    reply timing, first sentence, peak memory
    python -m scripts.benchmark --coding           also run the coding task suite
    python -m scripts.benchmark --audio a.wav --expected "Jarvis read my briefing"

The coding suite asks the configured coding model to fix three small projects in a temporary
folder. Running each project's tests executes the generated code, so the script asks before
every run unless --yes is given. Reports are saved in the local Jarvis benchmarks folder.
"""
import argparse
import json
import platform
import re
import tempfile
import threading
import time
from pathlib import Path

from jarvis import config

PROMPTS = [('jarvis', 'Rewrite this sentence clearly: We needs to finish the report today.'),
           ('tuki', 'Explain why visiting each of n items once takes O(n) time.')]

CODING_TASKS = [
    {"name": "empty-average",
     "files": {"stats.py": "def average(values):\n    return sum(values) / len(values)\n",
               "test_stats.py": "from stats import average\n\n\ndef test_empty():\n    assert average([]) == 0\n\n\n"
                                "def test_values():\n    assert average([2, 4]) == 3\n"},
     "target": "stats.py", "request": "average of an empty list should return 0"},
    {"name": "title-case",
     "files": {"names.py": "def tidy(name):\n    return name\n",
               "test_names.py": "from names import tidy\n\n\ndef test_tidy():\n    assert tidy('  ada LOVELACE ') == 'Ada Lovelace'\n"},
     "target": "names.py", "request": "tidy should strip spaces and title-case each word"},
    {"name": "two-files",
     "files": {"prices.py": "from tax import RATE\n\n\ndef with_tax(amount):\n    return amount\n",
               "tax.py": "RATE = 0.1\n",
               "test_prices.py": "from prices import with_tax\n\n\ndef test_tax():\n    assert round(with_tax(100), 2) == 110.0\n"},
     "target": "prices.py", "request": "apply RATE from tax.py in with_tax"},
]


class PeakMemory:
    """Samples resident memory of this process and any Ollama processes."""

    def __init__(self, interval=0.2):
        self.interval, self.peak, self.peak_ollama = interval, 0, 0
        self._stop = threading.Event()

    def __enter__(self):
        try:
            import psutil
        except ImportError:
            self.available = False
            return self
        self.available = True

        def sample():
            own = psutil.Process()
            while not self._stop.is_set():
                try:
                    self.peak = max(self.peak, own.memory_info().rss)
                    total = sum(p.info["memory_info"].rss for p in psutil.process_iter(["name", "memory_info"])
                                if p.info["name"] and "ollama" in p.info["name"].lower() and p.info["memory_info"])
                    self.peak_ollama = max(self.peak_ollama, total)
                except Exception:
                    pass
                self._stop.wait(self.interval)

        self._thread = threading.Thread(target=sample, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self._stop.set()
        if getattr(self, "_thread", None):
            self._thread.join(2)

    def report(self):
        if not self.available:
            return {"available": False}
        return {"jarvis_peak_mib": round(self.peak / 2 ** 20, 1), "ollama_peak_mib": round(self.peak_ollama / 2 ** 20, 1)}


def measure_reply(brain, assistant, prompt):
    measurements, first_sentence = [], {}
    started = time.perf_counter()

    def stream(text):
        if "seconds" not in first_sentence and re.search(r"[.!?](\s|$)", text):
            first_sentence["seconds"] = round(time.perf_counter() - started, 3)

    brain.assistant = assistant
    brain.on_metrics = measurements.append
    brain.on_stream = stream
    with PeakMemory() as memory_use:
        answer = brain._chat([{'role': 'user', 'content': prompt}], use_tools=False)
    return {'assistant': assistant, 'model': brain.model_used,
            'elapsed_seconds': round(time.perf_counter() - started, 3),
            # Time until the first complete sentence, which is when Talk mode starts speaking.
            'first_sentence_seconds': first_sentence.get("seconds"),
            'stream_metrics': measurements, 'memory': memory_use.report(),
            'answer': answer.get('content', '')}


def run_coding_suite(cfg, brain, approve):
    """Returns per-task results. approve(task_name) decides whether tests may run."""
    from jarvis import coder, skills
    results = []
    with tempfile.TemporaryDirectory() as workspace:
        coding_cfg = dict(cfg, code_dir=workspace, mode="coding")
        coder.attach(brain)
        for task in CODING_TASKS:
            folder = Path(workspace) / task["name"]
            folder.mkdir()
            for name, text in task["files"].items():
                (folder / name).write_text(text, encoding="utf-8")
            ctx = skills.Context(coding_cfg, brain.memory)
            row = {"task": task["name"], "model": coding_cfg.get("coder_model")}
            started = time.perf_counter()
            try:
                with PeakMemory() as memory_use:
                    preview = coder.propose_fix(ctx, f"{task['name']}/{task['target']}", task["request"])
                row["memory"] = memory_use.report()
                row["proposal_seconds"] = round(time.perf_counter() - started, 3)
                row["valid_proposal"] = ctx.code_proposal is not None
                if not row["valid_proposal"]:
                    row["detail"] = preview[:300]
                    results.append(row)
                    continue
                ctx.proposal_seen = True
                coder.apply_proposal(ctx)
                if not approve(task["name"]):
                    row["tests"] = "not run (not approved)"
                else:
                    code, out, err = coder._run_in_job(coder.test_command(folder), cwd=folder, timeout=120)
                    row["tests"] = "passed" if code == 0 else "failed"
                    row["test_output"] = (out + err)[-600:]
            except Exception as error:
                row["valid_proposal"] = row.get("valid_proposal", False)
                row["error"] = f"{type(error).__name__}: {error}"[:300]
            results.append(row)
    return results


def summarise_coding(results):
    ran = [r for r in results if r.get("tests") in ("passed", "failed")]
    return {"tasks": len(results), "valid_proposals": sum(bool(r.get("valid_proposal")) for r in results),
            "tests_run": len(ran), "tests_passed": sum(r["tests"] == "passed" for r in ran)}


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--audio', help='Optional local recording for speech evaluation')
    parser.add_argument('--expected', help='Expected transcript for that recording')
    parser.add_argument('--coding', action='store_true', help='Run the coding task suite with the real coding model')
    parser.add_argument('--yes', action='store_true', help='Run generated code in the coding suite without asking')
    args = parser.parse_args(argv)
    if args.audio and not args.expected:
        parser.error('--audio requires --expected')
    cfg = config.load()
    from jarvis import memory
    from jarvis.brain import Brain
    report = {'profile': cfg.get('performance_profile'), 'os': platform.system(), 'release': platform.release(),
              'python': platform.python_version(), 'processor': platform.machine(), 'responses': [],
              'note': 'Measured with the models installed on this PC.'}
    try:
        import psutil
        report['ram_gib'] = round(psutil.virtual_memory().total / 1024 ** 3, 2)
    except ImportError:
        pass
    with tempfile.TemporaryDirectory() as tmp:
        memory.APP_DIR = Path(tmp)
        memory.DB_PATH = Path(tmp) / 'benchmark.db'
        db = memory.Memory()
        try:
            brain = Brain(cfg, db)
            for assistant, prompt in PROMPTS:
                report['responses'].append(measure_reply(brain, assistant, prompt))
            if args.coding:
                def approve(name):
                    if args.yes:
                        return True
                    return input(f"Run the generated code and tests for '{name}' on this PC? (y/N) ").strip().lower() == 'y'
                report['coding'] = run_coding_suite(cfg, brain, approve)
                report['coding_summary'] = summarise_coding(report['coding'])
        finally:
            db.db.close()
    if args.audio:
        from jarvis.voice import load_whisper
        model = load_whisper(cfg)
        started = time.perf_counter()
        segments, _ = model.transcribe(args.audio, language='en')
        text = ' '.join(segment.text.strip() for segment in segments)
        expected, actual = args.expected.lower().split(), text.lower().split()
        previous = list(range(len(actual) + 1))
        for index, word in enumerate(expected, 1):
            row = [index]
            for column, found in enumerate(actual, 1):
                row.append(min(row[-1] + 1, previous[column] + 1, previous[column - 1] + (word != found)))
            previous = row
        report['speech'] = {'seconds': round(time.perf_counter() - started, 3), 'transcript': text,
                            'word_error_rate': previous[-1] / max(1, len(expected)),
                            'wake_word_detected': any(word in text.lower().split() for word in cfg.get('wake_words', []))}
    folder = config.APP_DIR / 'benchmarks'
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / ('Benchmark ' + str(time.time_ns()) + '.json')
    path.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(path)
    if 'coding_summary' in report:
        print(json.dumps(report['coding_summary']))
    return report


if __name__ == '__main__':
    main()
