"""Authentic local voice benchmark and WAV comparison sample generator.

Measures real cold/warm synthesis time, audio duration, Real-Time Factor (RTF),
CPU/RAM/GPU telemetry, and EchoGuard barge-in interruption latency on identical sentences.
Never fabricates results for uninstalled engines.
"""
import json
import platform
import time
from pathlib import Path

from jarvis import config, speech_engines, telemetry, voice_profile

JARVIS_SENTENCE = (
    "Good evening, sir. All local neural systems are calibrated, "
    "SQLite memory is synchronized, and your schedule is clear until nine."
)
TUKI_SENTENCE = (
    "TUKI online. Independent verification complete: ONNX checksums matched, "
    "VRAM utilization is nominal, and confidence is high."
)


def run_benchmark(out_dir: Path | None = None) -> dict:
    cfg = dict(config.DEFAULTS)
    target_dir = out_dir or Path("docs/measurements/voice-samples")
    target_dir.mkdir(parents=True, exist_ok=True)

    before = telemetry.snapshot(include_processes=False, record_history=False)
    avail = speech_engines.engine_availability(cfg)
    results = []

    for assistant, text in (("jarvis", JARVIS_SENTENCE), ("tuki", TUKI_SENTENCE)):
        wav_path = target_dir / f"{assistant}_sample.wav"
        cold = speech_engines.synthesize_to_wav(cfg, text, assistant=assistant, out_path=wav_path)
        warm = speech_engines.synthesize_to_wav(cfg, text, assistant=assistant, out_path=wav_path)
        results.append({
            "assistant": assistant,
            "engine": cold["engine"],
            "voice": cold["voice"],
            "fallback_used": cold["fallback_used"],
            "cold_seconds": cold["total_seconds"],
            "warm_seconds": warm["total_seconds"],
            "audio_seconds": warm["audio_seconds"],
            "cold_rtf": cold["rtf"],
            "warm_rtf": warm["rtf"],
            "sample_wav": str(wav_path).replace("\\", "/"),
            "sample_bytes": warm["bytes"],
        })

    # Measure EchoGuard spoken barge-in detection latency (100 iterations)
    eg = voice_profile.EchoGuard()
    eg.note_speaking(JARVIS_SENTENCE, duration_s=10.0)
    t0 = time.perf_counter()
    for _ in range(100):
        assert eg.is_barge_in_command("Jarvis stop") is True
        assert eg.is_self_echo("local neural systems are calibrated") is True
    interrupt_ms = round(((time.perf_counter() - t0) / 100.0) * 1000.0, 4)

    after = telemetry.snapshot(include_processes=False, record_history=False)
    report = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "python": platform.python_version(),
        "os": after["os"],
        "ram_total_gb": after["memory"]["total_gb"],
        "ram_percent_after": after["memory"]["percent"],
        "cpu_percent_after": after["cpu"]["percent"],
        "gpus": after["gpus"],
        "engine_availability": avail,
        "barge_in_detection_ms": interrupt_ms,
        "benchmarks": results,
    }
    report_path = Path("docs/measurements/voice-benchmark-windows.json")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


if __name__ == "__main__":
    rep = run_benchmark()
    print(json.dumps(rep["benchmarks"], indent=2))
    print("Barge-in detection ms:", rep["barge_in_detection_ms"])
