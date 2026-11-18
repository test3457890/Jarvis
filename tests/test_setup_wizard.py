import json

import pytest

from jarvis import config, setupwizard


@pytest.fixture
def wizard(isolated_app, monkeypatch, tmp_path):
    cfg, db, ctx, app_dir = isolated_app
    monkeypatch.setattr(setupwizard, "installed_ollama", lambda cfg: {"qwen3:4b": 2_600_000_000})
    monkeypatch.setattr(setupwizard, "whisper_cached", lambda name: False)
    monkeypatch.setattr(setupwizard, "ollama_models_dir", lambda: tmp_path)
    monkeypatch.setattr(setupwizard, "hf_cache_dir", lambda: tmp_path)
    return cfg, app_dir


def test_existing_config_is_marked_complete_and_new_install_is_not(isolated_app):
    cfg, _, _, app_dir = isolated_app
    assert config.load()["setup_complete"] is False
    config.CONFIG_PATH.write_text(json.dumps({"honorific": "Brett", "model": "custom:1b"}))
    loaded = config.load()
    assert loaded["setup_complete"] is True
    assert loaded["honorific"] == "Brett" and loaded["model"] == "custom:1b"


def test_unreadable_config_is_kept_not_overwritten(isolated_app):
    config.CONFIG_PATH.write_text("{ not json")
    config.load()
    copies = list(config.APP_DIR.glob("config.unreadable-*.json"))
    assert copies and copies[0].read_text() == "{ not json"


def test_plan_reports_sizes_installed_models_and_budget(wizard):
    cfg, _ = wizard
    plan = setupwizard.plan(cfg, {"profile": "low-memory", "budget_gb": 2})
    names = {item["name"]: item for item in plan["items"]}
    assert set(names) == {"qwen3:4b", "qwen2.5-coder:1.5b", "base.en"}
    assert names["qwen3:4b"]["installed"] and names["qwen3:4b"]["bytes"] == 2_600_000_000
    assert plan["needed_bytes"] == names["qwen2.5-coder:1.5b"]["bytes"] + names["base.en"]["bytes"]
    assert plan["over_budget"] and "budget" in plan["warnings"][0]
    assert "hard per-app limit" in plan["shared_cache_note"]
    standard = setupwizard.plan(cfg, {"profile": "standard", "voice": False, "budget_gb": 50,
                                      "optional_models": ["gemma3:4b"]})
    assert not standard["over_budget"] and "gemma3:4b" in {i["name"] for i in standard["items"]}
    with pytest.raises(ValueError):
        setupwizard.plan(cfg, {"profile": "huge"})
    with pytest.raises(ValueError):
        setupwizard.plan(cfg, {"optional_models": ["anything:70b"]})


def test_start_refuses_over_budget_without_explicit_acceptance(wizard):
    cfg, _ = wizard
    with pytest.raises(ValueError, match="budget"):
        setupwizard.start(cfg, {"profile": "standard", "budget_gb": 1})
    assert setupwizard.load_state()["steps"] == []


def test_failed_download_resumes_and_preserves_settings(wizard, tmp_path):
    cfg, _ = wizard
    cfg["honorific"] = "Brett"
    cfg["user_name"] = "Brett T"
    config.save(cfg)
    docs = tmp_path / "docs"
    docs.mkdir()
    pulls = []

    def flaky(cfg, name, progress):
        pulls.append(name)
        progress(10, 100)
        if name == "qwen2.5-coder:1.5b" and pulls.count(name) == 1:
            raise RuntimeError("connection dropped")

    whisper = []
    setupwizard.start(cfg, {"profile": "low-memory", "document_folders": [str(docs)]},
                      pull=flaky, fetch_whisper=whisper.append).join()
    state = setupwizard.load_state()
    assert "Resume" in state["error"] and not state["running"]
    assert [s["status"] for s in state["steps"]] == ["done", "failed", "pending"]
    saved = json.loads(config.CONFIG_PATH.read_text())
    assert saved["honorific"] == "Brett" and saved["user_name"] == "Brett T"
    assert saved["performance_profile"] == "low-memory" and saved["document_folders"] == [str(docs.resolve())]
    assert not saved["setup_complete"]

    setupwizard.start(cfg, {"profile": "low-memory"}, pull=flaky, fetch_whisper=whisper.append).join()
    state = setupwizard.load_state()
    assert [s["status"] for s in state["steps"]] == ["done", "done", "done"]
    assert pulls == ["qwen2.5-coder:1.5b", "qwen2.5-coder:1.5b"]  # qwen3:4b was already installed
    assert whisper == ["base.en"]
    assert json.loads(config.CONFIG_PATH.read_text())["setup_complete"] is True


def test_file_folders_must_be_separate_from_code_workspace(wizard, tmp_path):
    cfg, _ = wizard
    with pytest.raises(ValueError, match="separate"):
        setupwizard.apply_choices(cfg, {"file_folders": [cfg["code_dir"]]})
    outside = tmp_path / "Photos"
    outside.mkdir()
    updated = setupwizard.apply_choices(cfg, {"file_folders": [str(outside)], "online_tools": False})
    assert updated["file_folders"] == [str(outside.resolve())]


def test_wizard_finish_without_downloads(wizard):
    cfg, _ = wizard
    result = setupwizard.finish_without_downloads(cfg, {"profile": "standard", "voice": False})
    assert result["first_run"] is False and cfg["voice_enabled"] is False
