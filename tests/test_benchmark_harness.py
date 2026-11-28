"""Checks the benchmark harness itself with stubbed models. These are not benchmark results."""
import json

from jarvis.brain import Brain
from scripts import benchmark

GOOD = ("FILE: empty-average/stats.py\n<<<<<<< SEARCH\n    return sum(values) / len(values)\n=======\n"
        "    if not values:\n        return 0\n    return sum(values) / len(values)\n>>>>>>> REPLACE\n")
WRONG = "FILE: title-case/names.py\n<<<<<<< SEARCH\n    return name\n=======\n    return name.strip()\n>>>>>>> REPLACE\n"


def stub_brain(cfg, db, replies):
    brain = Brain(cfg, db)
    brain.raw_chat = lambda messages, model: replies.pop(0)
    return brain


def test_coding_suite_scores_and_asks_before_running_code(isolated_app):
    cfg, db, _, _ = isolated_app
    replies = [GOOD, WRONG, "no edits here", "still no edits"]
    asked = []
    results = benchmark.run_coding_suite(cfg, stub_brain(cfg, db, replies),
                                         lambda name: asked.append(name) or name != "title-case")
    summary = benchmark.summarise_coding(results)
    assert asked == ["empty-average", "title-case"]
    assert [r.get("tests") for r in results[:2]] == ["passed", "not run (not approved)"], results
    assert results[2]["valid_proposal"] is False
    assert summary == {"tasks": 3, "valid_proposals": 2, "tests_run": 1, "tests_passed": 1}


def test_reply_measurement_records_first_sentence(isolated_app):
    cfg, db, _, _ = isolated_app
    brain = Brain(cfg, db)

    def chat(messages, use_tools):
        brain.on_stream("Hello")
        brain.on_stream("Hello there. More")
        return {"content": "Hello there. More text."}

    brain._chat = chat
    row = benchmark.measure_reply(brain, "jarvis", "hi")
    assert row["first_sentence_seconds"] is not None and row["elapsed_seconds"] >= row["first_sentence_seconds"]
    assert "jarvis_peak_mib" in row["memory"] or row["memory"] == {"available": False}
    json.dumps(row)
