import pytest

from jarvis import secure
from jarvis.assistants import route
from jarvis.brain import Brain, OllamaError


def test_auto_and_manual_routing():
    assert route("Jarvis, please proofread this. It mentions a Python script.")[0] == "jarvis"
    assert route("Solve this equation")[0] == "tuki"
    assert route("Find my files")[0] == "tuki"
    assert route("Tuki, check that") == ("tuki", "check that")
    assert route("Jarvis: solve this equation") == ("jarvis", "solve this equation")
    assert route("Write code", preference="jarvis")[0] == "jarvis"
    assert route("Tell me about Tuki") == ("jarvis", "Tell me about Tuki")
    assert route("Fix this", mode="coding")[0] == "tuki"
    assert route("Solve this equation", mode="talk")[0] == "jarvis"


def test_profiles_choose_different_models_and_share_context(isolated_app, monkeypatch):
    cfg, db, _, _ = isolated_app
    brain = Brain(cfg, db)
    payloads = []

    def post(path, payload, timeout=300):
        if path == "/api/chat":
            payloads.append(payload)
            return {"message": {"content": "Example answer"}}
        return {"embeddings": [[]]}

    monkeypatch.setattr(brain, "_post", post)
    brain.ask("Please proofread my sentence")
    brain.ask("Tuki, solve the equation")
    assert [obj["model"] for obj in payloads] == [cfg["everyday_model"], cfg["model"]]
    assert payloads[0]["think"] is False and payloads[1]["think"] is True
    assert any(m["content"] == "Example answer" for m in payloads[1]["messages"][:-1])


def test_missing_everyday_model_falls_back_and_reports_it(isolated_app, monkeypatch):
    cfg, db, _, _ = isolated_app
    brain = Brain(cfg, db)

    def post(path, payload):
        if payload["model"] == cfg["everyday_model"]:
            raise OllamaError("model not found")
        return {"message": {"content": "Fallback answer"}}

    monkeypatch.setattr(brain, "_post", post)
    assert brain.ask("Hello there") == "Fallback answer"
    assert brain.assistant == "jarvis"
    assert brain.model_used == cfg["model"]


def test_fact_check_reuses_confirmed_sources_without_tools(isolated_app, monkeypatch):
    cfg, db, _, _ = isolated_app
    cfg.update(allow_internet_tools=True, allow_web_search=True)
    monkeypatch.setattr(secure, "has_secret", lambda name: name == "brave_search_key")
    monkeypatch.setattr("jarvis.online._request", lambda *a: {"web": {"results": [
        {"title": "Evidence", "url": "https://example.org/", "description": "A supporting snippet"}
    ]}})
    brain = Brain(cfg, db)
    brain.history = [{"role": "assistant", "content": "The previous claim"}]

    def post(path, payload):
        if "tools" in payload:
            assert {t["function"]["name"] for t in payload["tools"]} <= {
                "web_search", "search_library", "calculate", "read_source", "check_sources"
            }
            return {"message": {"tool_calls": [
                {"function": {"name": "web_search", "arguments": {"query": "public question"}}}
            ]}}
        assert "The previous claim" in payload["messages"][-1]["content"]
        assert "A supporting snippet" in payload["messages"][-1]["content"]
        return {"message": {"content": "The snippet is inconclusive."}}

    monkeypatch.setattr(brain, "_post", post)
    assert "confirm search" in brain.ask("Tuki, fact-check that")
    result = brain.ask("confirm search")
    assert "The snippet is inconclusive." in result
    assert "https://example.org/" in result


def test_tuki_answers_name_questions_without_a_model(isolated_app, monkeypatch):
    cfg, db, _, _ = isolated_app
    brain = Brain(cfg, db)
    monkeypatch.setattr(brain, "_chat", lambda *args: pytest.fail("name lookup used the model"))
    for question in ("What does TUKI stand for?", "What does each letter in TUKI stand for?",
                     "Tuki, what does your name stand for?"):
        assert brain.ask(question) == "TUKI stands for Technical Utility for Knowledge and Insight."
        assert brain.assistant == "tuki"


def test_tuki_calculator_and_file_search_work_offline(isolated_app, monkeypatch):
    cfg, db, _, app_dir = isolated_app
    cfg["search_folders"] = [str(app_dir)]
    (app_dir / "budget draft.txt").write_text("sample", encoding="utf-8")
    brain = Brain(cfg, db)
    monkeypatch.setattr(brain, "_chat", lambda *args: pytest.fail("offline commands used the model"))

    assert brain.ask("/calc (12.5*3)/4 + 2^8").endswith("265.375")
    assert brain.assistant == "tuki"
    assert brain.ask("Tuki: /calc 2^70").endswith("1180591620717411303424")
    assert "only finite real results" in brain.ask("/calc (-1)^0.5")
    assert "calculator limit" in brain.ask("/calc (2^1000)^1000")
    assert "budget draft.txt" in brain.ask("/files budget")
    assert brain.assistant == "tuki"
    assert brain.ask("/files other") == "No files found."
