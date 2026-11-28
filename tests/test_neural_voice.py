"""Neural Voice Studio & Unified Speech Engine Tests (feature/jarvis-neural-voice)."""
import hashlib
import json
import os
import re
import socket
import urllib.error
import urllib.request
import pytest

from jarvis import __main__ as jarvis_main, config, memory, speech_engines, webui


def test_engines_licenses_profiles_and_hardware_recommendation():
    assert set(speech_engines.ENGINES) == {"kokoro_onnx", "kokoro", "qwen3_tts", "chatterbox", "piper", "windows_sapi"}
    assert "GPL-3.0" in speech_engines.ENGINES["piper"]["code_license"]
    assert speech_engines.ENGINES["kokoro_onnx"]["code_license"] == "MIT"
    assert speech_engines.ENGINES["qwen3_tts"]["code_license"] == "Apache-2.0"

    assert set(speech_engines.VOICE_PERFORMANCE_PROFILES) == {"cinematic", "balanced", "performance", "compatibility"}
    rec_gpu = speech_engines.recommend_voice_profile({"memory": {"total_gb": 32.0}, "gpus": [{"vram_total_gb": 16.0}]})
    assert rec_gpu["profile"] == "cinematic" and rec_gpu["device"] == "gpu"
    rec_low = speech_engines.recommend_voice_profile({"memory": {"total_gb": 8.0}, "gpus": []})
    assert rec_low["profile"] == "performance" and rec_low["device"] == "cpu"


def test_pronunciation_dictionary_and_sha256_integrity(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    out = speech_engines.apply_pronunciation("TUKI checked SQLite and VRAM via ONNX.", {"Jarvis": "Jaa-vis"})
    assert "Too-key" in out and "Sequel-light" in out and "V-RAM" in out and "On-ix" in out

    # Model storage stays strictly inside APP_DIR/voice-models (outside repo)
    sdir = speech_engines.model_storage_dir()
    assert sdir == tmp_path / "voice-models"
    sample = sdir / "test.onnx"
    payload = b"onnx-model-bytes"
    sample.write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()
    assert speech_engines.verify_file_sha256(sample, digest) is True
    assert speech_engines.verify_file_sha256(sample, "0" * 64) is False
    with pytest.raises(ValueError):
        speech_engines.verify_file_sha256(sample, "not-a-sha256")


def test_graceful_fallback_and_live_sapi_wav_synthesis(tmp_path):
    cfg = dict(config.DEFAULTS, voice_performance_profile="cinematic", jarvis_speech_engine="qwen3_tts")
    resolved = speech_engines.resolve_engine(cfg, "jarvis")
    if os.name == "nt":
        assert resolved["selected"] in ("kokoro_onnx", "windows_sapi")
        assert resolved["fallback_used"] is True
        wav = tmp_path / "jarvis_sapi_test.wav"
        res = speech_engines.synthesize_to_wav(
            cfg, "Good evening, sir. TUKI is online.", assistant="jarvis",
            out_path=wav, engine_override="windows_sapi",
        )
        assert res["ok"] is True and res["engine"] == "windows_sapi"
        assert wav.is_file() and res["bytes"] > 44
        assert res["audio_seconds"] > 0 and res["rtf"] is not None
        assert "Too-key" in res["spoken_text"]


def test_real_kokoro_onnx_inference_and_speaker_worker_integration(tmp_path):
    from jarvis import voice as voice_mod, voice_runtime
    avail = speech_engines.engine_availability(config.DEFAULTS)
    if not avail.get("kokoro_onnx", {}).get("ready"):
        pytest.skip("Isolated Python 3.12 Kokoro ONNX runtime/pack not installed on this runner")

    cfg = dict(config.DEFAULTS, voice_performance_profile="balanced", jarvis_speech_engine="kokoro_onnx", jarvis_neural_voice="bm_george")
    wav = tmp_path / "kokoro_live.wav"
    res = speech_engines.synthesize_to_wav(cfg, "Good evening, sir.", assistant="jarvis", out_path=wav, allow_fallback=False)
    assert res["ok"] is True
    assert res["engine"] == "kokoro_onnx"
    assert res["voice"] == "bm_george"
    assert wav.is_file() and res["bytes"] > 10000
    assert res["audio_seconds"] > 0.5

    # Verify Speaker.describe() reports actual neural engine & voice
    sp = voice_mod.Speaker(cfg)
    assert "kokoro_onnx" in sp.describe("jarvis")
    assert "bm_george" in sp.describe("jarvis")

    # Verify inference failure triggers controlled fallback to windows_sapi
    bad_cfg = dict(cfg, jarvis_speech_engine="qwen3_tts")
    fb = speech_engines.synthesize_to_wav(bad_cfg, "Fallback check.", assistant="jarvis", out_path=tmp_path / "fb.wav", engine_override="qwen3_tts", allow_fallback=True)
    assert fb["engine"] == "windows_sapi" and fb["fallback_used"] is True
    voice_runtime.CLIENT.shutdown()


def test_voice_studio_http_api_auth_save_reset_and_lockdown(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(memory, "DB_PATH", tmp_path / "mem.db")
    cfg = dict(config.DEFAULTS, notes_dir=str(tmp_path / "notes"))
    (tmp_path / "notes").mkdir(exist_ok=True)
    config.save(cfg)

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]

    app = jarvis_main.App(cfg, use_voice=False)
    server = webui.serve(app, port)
    base = f"http://127.0.0.1:{port}"
    try:
        # Unauthenticated GET must fail with 403
        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(base + "/api/voice-studio", timeout=5)
        assert exc.value.code == 403

        html = urllib.request.urlopen(base + "/", timeout=5).read().decode("utf-8")
        key = re.search(r"\bKEY\s*=\s*['\"]([^'\"]+)['\"]", html).group(1)
        hdrs = {"X-Jarvis-Key": key, "Origin": base, "Content-Type": "application/json"}

        req = urllib.request.Request(base + "/api/voice-studio", headers=hdrs)
        st = json.loads(urllib.request.urlopen(req, timeout=5).read())
        assert st["profile"] == "balanced"
        assert "kokoro_onnx" in st["engines"]

        # Save Voice Studio settings
        req = urllib.request.Request(
            base + "/api/voice-studio",
            data=json.dumps({
                "action": "save", "profile": "cinematic", "compute_device": "gpu",
                "jarvis_neural_voice": "bm_daniel", "tuki_neural_voice": "bf_isabella",
                "pronunciations": {"Jarvis": "Jar-vis"},
            }).encode(),
            headers=hdrs, method="POST",
        )
        saved = json.loads(urllib.request.urlopen(req, timeout=5).read())
        assert saved["profile"] == "cinematic"
        assert saved["jarvis"]["voice"] == "bm_daniel"
        assert saved["tuki"]["voice"] == "bf_isabella"

        # Lockdown blocks mutations
        app.cfg["lockdown"] = True
        req = urllib.request.Request(
            base + "/api/voice-studio",
            data=json.dumps({"action": "reset"}).encode(),
            headers=hdrs, method="POST",
        )
        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(req, timeout=5)
        assert exc.value.code == 400
    finally:
        server.shutdown()
        server.server_close()
