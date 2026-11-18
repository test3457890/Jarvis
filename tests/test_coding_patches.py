import json
from pathlib import Path

import pytest

from jarvis import coder, skills
from jarvis.brain import Brain


@pytest.fixture
def project(isolated_app, monkeypatch):
    cfg, db, ctx, _ = isolated_app
    cfg["mode"] = "coding"
    root = Path(cfg["code_dir"]) / "budget"
    (root / "tests").mkdir(parents=True)
    (root / "budget.py").write_text("def total(values):\n    return sum(values) / len(values)\n\n\ndef label():\n    return 'Budget'\n")
    (root / "helpers.py").write_text("RATE = 1\n")
    (root / "tests" / "test_budget.py").write_text("from budget import total\n\ndef test_empty():\n    assert total([]) == 0\n")
    brain = Brain(cfg, db)
    replies, requests = [], []

    def raw_chat(messages, model):
        requests.append(json.loads(messages[1]["content"]))
        return replies.pop(0)

    monkeypatch.setattr(brain, "raw_chat", raw_chat)
    return cfg, brain, root, replies, requests


PATCH = """FILE: budget/budget.py
<<<<<<< SEARCH
    return sum(values) / len(values)
=======
    if not values:
        return 0
    return sum(values) / len(values)
>>>>>>> REPLACE
"""


def test_focused_patch_changes_only_the_matched_lines(project):
    cfg, brain, root, replies, requests = project
    replies.append(PATCH)
    preview = brain.ask("/fix budget/budget.py | handle empty input")
    assert "Preview only" in preview and "+    if not values:" in preview
    assert "Python syntax OK" in preview
    assert "budget/tests/test_budget.py" in requests[0]["project"]["files"] or "tests/test_budget.py" in requests[0]["project"]["files"]
    assert "pytest" in requests[0]["project"]["test_command"] or "unittest" in requests[0]["project"]["test_command"]
    assert "Updated budget.py" in brain.ask("/apply")
    text = (root / "budget.py").read_text()
    assert "if not values" in text and "return 'Budget'" in text
    assert (root / "budget.py.bak").exists()


def test_multi_file_preview_applies_together_and_undoes_together(project):
    cfg, brain, root, replies, _ = project
    replies.append(PATCH + "FILE: budget/helpers.py\n<<<<<<< SEARCH\nRATE = 1\n=======\nRATE = 2\n>>>>>>> REPLACE\n"
                   + "FILE: budget/constants.py\n<<<<<<< SEARCH\n=======\nLIMIT = 10\n>>>>>>> REPLACE\n")
    preview = brain.ask("/fix budget/budget.py, budget/helpers.py | use the new rate")
    assert "budget/budget.py, budget/helpers.py, budget/constants.py" in preview
    assert "+RATE = 2" in preview and "+LIMIT = 10" in preview and "/dev/null" in preview
    assert not (root / "constants.py").exists()
    brain.ask("/apply")
    assert (root / "helpers.py").read_text() == "RATE = 2\n" and (root / "constants.py").read_text() == "LIMIT = 10\n"
    assert "Restored" in brain.ask("/undo")
    assert (root / "helpers.py").read_text() == "RATE = 1\n" and not (root / "constants.py").exists()
    assert "if not values" not in (root / "budget.py").read_text()


@pytest.mark.parametrize("reply, message", [
    ("FILE: budget/budget.py\n<<<<<<< SEARCH\nnot in the file\n=======\nx\n>>>>>>> REPLACE\n", "was not found"),
    ("FILE: budget/budget.py\n<<<<<<< SEARCH\n\n=======\n# gap\n>>>>>>> REPLACE\n", "places"),
    ("FILE: budget/budget.py\n<<<<<<< SEARCH\ndef label():\n=======\ndef label(:\n>>>>>>> REPLACE\n", "did not compile"),
    ("FILE: budget/helpers.py\n<<<<<<< SEARCH\nRATE = 1\n=======\nRATE = 3\n>>>>>>> REPLACE\n", "was not selected"),
    ("FILE: ../outside.py\n<<<<<<< SEARCH\n=======\nx = 1\n>>>>>>> REPLACE\n", "relative path"),
])
def test_bad_patches_change_nothing(project, reply, message):
    cfg, brain, root, replies, _ = project
    before = {path: path.read_bytes() for path in root.rglob("*") if path.is_file()}
    replies.extend([reply, reply])
    assert message in brain.ask("/fix budget/budget.py | change it")
    assert {path: path.read_bytes() for path in root.rglob("*") if path.is_file()} == before
    assert brain.ctx.code_proposal is None


def test_mismatched_patch_gets_one_model_repair_without_writing(project):
    _, brain, root, replies, requests = project
    replies.extend([
        "FILE: budget/budget.py\n<<<<<<< SEARCH\n    return mean(values)\n=======\n    return 0\n>>>>>>> REPLACE\n",
        PATCH,
    ])
    preview = brain.ask("/fix budget/budget.py | handle empty input")
    assert "Preview only" in preview and "+    if not values:" in preview
    assert len(requests) == 2
    assert "if not values" not in (root / "budget.py").read_text()


def test_too_many_selected_files_are_rejected_instead_of_ignored(project):
    _, brain, _, replies, requests = project
    names = ", ".join(f"budget/file{i}.py" for i in range(7))
    assert "between 1 and 6" in brain.ask(f"/fix {names} | make a change")
    assert not requests and not replies


def test_failed_write_rolls_back_earlier_files(project, monkeypatch):
    cfg, brain, root, replies, _ = project
    replies.append(PATCH + "FILE: budget/helpers.py\n<<<<<<< SEARCH\nRATE = 1\n=======\nRATE = 2\n>>>>>>> REPLACE\n")
    brain.ask("/fix budget/budget.py, budget/helpers.py | change both")
    real = coder._replace_file

    def failing(path, content):
        if path.name == "helpers.py":
            raise PermissionError("locked by another program")
        return real(path, content)

    monkeypatch.setattr(coder, "_replace_file", failing)
    assert "locked" in brain.ask("/apply")
    monkeypatch.setattr(coder, "_replace_file", real)
    assert "if not values" not in (root / "budget.py").read_text()
    assert (root / "helpers.py").read_text() == "RATE = 1\n"


def test_json_is_validated_without_running_anything(project):
    cfg, brain, root, replies, _ = project
    (root / "settings.json").write_text('{"rate": 1}\n')
    replies.append('FILE: budget/settings.json\n<<<<<<< SEARCH\n{"rate": 1}\n=======\n{"rate": 2,}\n>>>>>>> REPLACE\n')
    assert "JSON" in brain.ask("/fix budget/settings.json | update the rate")
    assert (root / "settings.json").read_text() == '{"rate": 1}\n'


def test_project_tests_need_approval_and_feed_errors_back(project, monkeypatch):
    cfg, brain, root, replies, requests = project
    calls = []
    monkeypatch.setattr(coder, "_run_in_job", lambda command, cwd, timeout: (calls.append((command, cwd)) or
                                                                            (1, "FAILED test_empty - ZeroDivisionError", "")))
    reply = brain.ask("/test budget/budget.py")
    assert "run the project tests in" in reply and not calls
    assert brain.ctx.pending["name"] == "run_project_tests"
    result = brain.confirm_pending(True)
    assert "Tests failed" in result and "ZeroDivisionError" in result and calls[0][1] == root
    replies.append(PATCH)
    assert "Preview only" in brain.ask("/fix-tests budget/budget.py | empty list")
    assert "ZeroDivisionError" in requests[-1]["task"]


def test_generated_code_never_runs_without_approval(project):
    cfg, brain, _, _, _ = project
    assert skills.SKILLS["run_project_tests"]["risky"] and skills.SKILLS["run_code"]["risky"]
    cfg["lockdown"] = True
    assert "Lockdown" in brain.ask("/test budget/budget.py")


def test_whole_file_reply_is_still_accepted(project):
    cfg, brain, root, replies, _ = project
    replies.append("```python\nRATE = 5\n```")
    assert "+RATE = 5" in brain.ask("/fix budget/helpers.py | change the rate")
