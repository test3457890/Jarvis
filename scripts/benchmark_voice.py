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
import tempfile
import threading
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
                "model_file": first.get("model_file", ""),
                "actual_provider": first.get("actual_provider", ""),
                "voice": first["voice"],
                "cold_seconds": first["total_seconds"] if idx == 0 else None,
                "warm_seconds": warm["total_seconds"],
                "ttfa_seconds": warm.get("ttfa_seconds"),
                "audio_seconds": warm["audio_seconds"],
                "rtf": warm["rtf"],
                "sample_wav": str(wav_path).replace("\\", "/"),
                "sample_bytes": warm["bytes"],
            })

    # 1b. Hardware & Precision Matrix (GPU vs CPU x FP32 vs int8) + Streaming TTFA + Active Cancellation
    matrix_results = []
    streaming_result = {}
    cancel_latency_ms = None
    if avail.get("kokoro_onnx", {}).get("ready"):
        mdir = str(speech_engines.model_storage_dir())
        with tempfile.TemporaryDirectory() as td:
            for label, dev, fp32 in (
                ("gpu_fp32", "gpu", True),
                ("gpu_int8", "gpu", False),
                ("cpu_fp32", "cpu", True),
                ("cpu_int8", "cpu", False),
            ):
                try:
                    r1 = voice_runtime.CLIENT.request({
                        "cmd": "synthesize", "engine": "kokoro_onnx", "voice": "bm_george",
                        "text": JARVIS_SENTENCE, "speed": 1.0, "device": dev, "prefer_fp32": fp32,
                        "model_dir": mdir, "out_path": str(Path(td) / f"{label}_cold.wav"),
                    }, timeout=60.0)
                    r2 = voice_runtime.CLIENT.request({
                        "cmd": "synthesize", "engine": "kokoro_onnx", "voice": "bm_george",
                        "text": JARVIS_SENTENCE, "speed": 1.0, "device": dev, "prefer_fp32": fp32,
                        "model_dir": mdir, "out_path": str(Path(td) / f"{label}_warm.wav"),
                    }, timeout=60.0)
                    matrix_results.append({
                        "config": label,
                        "requested_device": dev,
                        "actual_provider": r2["actual_provider"],
                        "model_file": r2["model_file"],
                        "cold_seconds": r1["total_seconds"],
                        "warm_seconds": r2["total_seconds"],
                        "audio_seconds": r2["audio_seconds"],
                        "warm_rtf": r2["rtf"],
                    })
                except Exception as exc:
                    matrix_results.append({"config": label, "error": str(exc)})

            # Streaming TTFA benchmark (3 sentences)
            chunks_log = []
            t_s = time.perf_counter()
            sres = speech_engines.synthesize_stream(
                cfg,
                f"{JARVIS_SENTENCE} {TUKI_SENTENCE}",
                assistant="jarvis",
                out_dir=Path(td) / "stream",
                on_chunk=lambda c: chunks_log.append({
                    "chunk": c["chunk"],
                    "arrived_seconds": round(time.perf_counter() - t_s, 3),
                    "audio_seconds": c["audio_seconds"],
                }),
            )
            streaming_result = {
                "actual_provider": sres["actual_provider"],
                "model_file": sres["model_file"],
                "chunks": chunks_log,
                "ttfa_seconds": sres["ttfa_seconds"],
                "total_seconds": sres["total_seconds"],
                "audio_seconds": sres["audio_seconds"],
                "rtf": sres["rtf"],
            }

            # Real active cancellation latency during neural inference
            long_text = " ".join([JARVIS_SENTENCE] * 6)
            def _bg():
                try:
                    voice_runtime.CLIENT.request({
                        "cmd": "synthesize", "engine": "kokoro_onnx", "voice": "bm_george",
                        "text": long_text, "speed": 1.0, "device": "cpu", "prefer_fp32": False,
                        "model_dir": mdir, "out_path": str(Path(td) / "cancel.wav"),
                    }, timeout=60.0)
                except Exception:
                    pass
            th = threading.Thread(target=_bg, daemon=True)
            th.start()
            time.sleep(0.15)
            tc = time.perf_counter()
            voice_runtime.CLIENT.cancel()
            th.join(timeout=3.0)
            cancel_latency_ms = round((time.perf_counter() - tc) * 1000.0, 2)
            voice_runtime.CLIENT.health(force=True)

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
        "active_cancellation_ms": cancel_latency_ms,
        "hardware_precision_matrix": matrix_results,
        "streaming_benchmark": streaming_result,
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
