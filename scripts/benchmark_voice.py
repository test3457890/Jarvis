"""Authentic local neural & compatibility voice benchmark + WAV sample generator.

Generates real Kokoro-82M ONNX neural WAV samples for:
  Jarvis (4 British voices): bm_george, bm_daniel, bm_fable, bm_lewis
  TUKI (4 distinct voices):  bf_emma, bf_isabella, af_bella, af_heart
Plus Windows SAPI5 compatibility baseline samples (clearly labeled separately).
Measures authentic cold/warm synthesis time, TTFA, audio duration, RTF, CPU/RAM/GPU,
and EchoGuard barge-in latency. Never substitutes SAPI audio as neural speech.
"""
import json
import platform
import time
from pathlib import Path

from jarvis import config, speech_engines, telemetry, voice_profile, voice_runtime

JARVIS_SENTENCE = (
    "Good evening, sir. All local neural systems are calibrated, "
    "SQLite memory is synchronized, and your schedule is clear until nine."
)
TUKI_SENTENCE = (
    "TUKI online. Independent verification complete: ONNX checksums matched, "
    "VRAM utilization is nominal, and confidence is high."
)

KOKORO_VOICES = [
    ("jarvis", "bm_george", "kokoro_jarvis_george.wav", JARVIS_SENTENCE),
    ("jarvis", "bm_daniel", "kokoro_jarvis_daniel.wav", JARVIS_SENTENCE),
    ("jarvis", "bm_fable", "kokoro_jarvis_fable.wav", JARVIS_SENTENCE),
    ("jarvis", "bm_lewis", "kokoro_jarvis_lewis.wav", JARVIS_SENTENCE),
    ("tuki", "bf_emma", "kokoro_tuki_emma.wav", TUKI_SENTENCE),
    ("tuki", "bf_isabella", "kokoro_tuki_isabella.wav", TUKI_SENTENCE),
    ("tuki", "af_bella", "kokoro_tuki_bella.wav", TUKI_SENTENCE),
    ("tuki", "af_heart", "kokoro_tuki_heart.wav", TUKI_SENTENCE),
]


def run_benchmark(out_dir: Path | None = None) -> dict:
    cfg = dict(config.DEFAULTS, voice_performance_profile="balanced")
    target_dir = out_dir or Path("docs/measurements/voice-samples")
    target_dir.mkdir(parents=True, exist_ok=True)

    avail = speech_engines.engine_availability(cfg)
    neural_results = []
    sapi_results = []

    # 1. Real Kokoro-82M ONNX neural synthesis (all 8 voices, cold + warm on first voice)
    if avail.get("kokoro_onnx", {}).get("ready"):
        voice_runtime.CLIENT.shutdown()  # ensure genuine cold start for first measurement
        for idx, (assistant, vid, fname, text) in enumerate(KOKORO_VOICES):
            wav_path = target_dir / fname
            first = speech_engines.synthesize_to_wav(
                cfg, text, assistant=assistant, out_path=wav_path,
                voice_override=vid, engine_override="kokoro_onnx", allow_fallback=False,
            )
            warm = first
            if idx == 0:
                warm = speech_engines.synthesize_to_wav(
                    cfg, text, assistant=assistant, out_path=wav_path,
                    voice_override=vid, engine_override="kokoro_onnx", allow_fallback=False,
                )
            neural_results.append({
                "assistant": assistant,
                "engine": first["engine"],
                "voice": first["voice"],
                "cold_seconds": first["total_seconds"] if idx == 0 else None,
                "warm_seconds": warm["total_seconds"],
                "ttfa_seconds": warm.get("ttfa_seconds"),
                "audio_seconds": warm["audio_seconds"],
                "rtf": warm["rtf"],
                "sample_wav": str(wav_path).replace("\\", "/"),
                "sample_bytes": warm["bytes"],
            })

    # 2. Windows SAPI5 compatibility baseline (explicitly labeled as windows_sapi)
    if avail.get("windows_sapi", {}).get("ready"):
        for assistant, text in (("jarvis", JARVIS_SENTENCE), ("tuki", TUKI_SENTENCE)):
            wav_path = target_dir / f"{assistant}_sapi_baseline.wav"
            cold = speech_engines.synthesize_to_wav(
                cfg, text, assistant=assistant, out_path=wav_path,
                engine_override="windows_sapi", allow_fallback=False,
            )
            warm = speech_engines.synthesize_to_wav(
                cfg, text, assistant=assistant, out_path=wav_path,
                engine_override="windows_sapi", allow_fallback=False,
            )
            sapi_results.append({
                "assistant": assistant,
                "engine": "windows_sapi",
                "voice": cold["voice"],
                "cold_seconds": cold["total_seconds"],
                "warm_seconds": warm["total_seconds"],
                "audio_seconds": warm["audio_seconds"],
                "rtf": warm["rtf"],
                "sample_wav": str(wav_path).replace("\\", "/"),
                "sample_bytes": warm["bytes"],
            })

    # 3. EchoGuard spoken barge-in & cancellation latency
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
        "neural_runtime": voice_runtime.CLIENT.health(),
        "os": after["os"],
        "ram_total_gb": after["memory"]["total_gb"],
        "ram_percent_after": after["memory"]["percent"],
        "cpu_percent_after": after["cpu"]["percent"],
        "gpus": after["gpus"],
        "engine_availability": avail,
        "barge_in_detection_ms": interrupt_ms,
        "neural_benchmarks": neural_results,
        "sapi_baseline_benchmarks": sapi_results,
    }
    report_path = Path("docs/measurements/voice-benchmark-windows.json")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


if __name__ == "__main__":
    rep = run_benchmark()
    print("NEURAL_COUNT:", len(rep["neural_benchmarks"]))
    print(json.dumps(rep["neural_benchmarks"], indent=2))
    print("SAPI_BASELINE:", json.dumps(rep["sapi_baseline_benchmarks"], indent=2))
    print("Barge-in ms:", rep["barge_in_detection_ms"])
