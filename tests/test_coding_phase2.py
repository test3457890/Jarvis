import json
import os
import subprocess
from pathlib import Path

import pytest

from jarvis import coder, skills
from jarvis.brain import Brain


@pytest.fixture
def project(isolated_app, monkeypatch):
    cfg, db, _, _ = isolated_app
    cfg["mode"] = "coding"
    root = Path(cfg["code_dir"]) / "shop"
    (root / "tests").mkdir(parents=True)
    (root / "cart.py").write_text("from pricing import discount\n\n\ndef total(items):\n    return sum(items) - discount(items)\n")
    (root / "pricing.py").write_text("def discount(items):\n    return 0\n")
    (root / "checkout.py").write_text("import cart\n\n\ndef pay(items):\n    return cart.total(items)\n")
    (root / "tests" / "test_cart.py").write_text("from cart import total\n\ndef test_total():\n    assert total([1, 2]) == 3\n")
    (root / "unrelated.py").write_text("VALUE = 1\n")
    (root / "shipping.md").write_text("Shipping is free over 50.\n")
    brain = Brain(cfg, db)
    replies, requests = [], []

    def raw_chat(messages, model):
        requests.append(json.loads(messages[1]["content"]))
        return replies.pop(0)

    monkeypatch.setattr(brain, "raw_chat", raw_chat)
    return cfg, db, brain, root, replies, requests


PATCH = ("FILE: shop/cart.py\n<<<<<<< SEARCH\n    return sum(items) - discount(items)\n=======\n"
         "    if not items:\n        return 0\n    return sum(items) - discount(items)\n>>>>>>> REPLACE\n")


def test_relevant_files_are_selected_and_shown(project):
    cfg, _, brain, root, replies, requests = project
    replies.append(PATCH)
    reply = brain.ask("/fix shop/cart.py | handle empty carts using the shipping rules")
    sent = set(requests[0]["references"])
    assert {"shop/pricing.py", "shop/tests/test_cart.py", "shop/checkout.py"} <= sent | {"shop/shipping.md"}
    assert "shop/unrelated.py" not in sent
    assert len(sent) <= 3
    assert "Read-only context sent to the model:" in reply


def test_context_stays_inside_the_budget(project, monkeypatch):
    cfg, _, brain, root, replies, requests = project
    (root / "pricing.py").write_text("def discount(items):\n    return 0\n" + "# padding\n" * 2000)
    replies.append(PATCH)
    brain.ask("/fix shop/cart.py | handle empty carts")
    assert "shop/pricing.py" not in requests[0].get("references", {})
    total = sum(len(text) for text in requests[0].get("references", {}).values()) + len(requests[0]["source"])
    assert total <= coder._MAX_SOURCE_CHARS
    cfg["auto_context"] = False
    replies.append(PATCH)
    brain.ask("/fix shop/cart.py | handle empty carts")
    assert "references" not in requests[1]


def test_oversized_project_scan_is_bounded(project, monkeypatch):
    cfg, _, brain, root, replies, requests = project
    monkeypatch.setattr(coder, "_MAX_SCAN", 5)
    for number in range(20):
        (root / f"extra_{number}.py").write_text("x = 1\n")
    replies.append(PATCH)
    assert "Preview only" in brain.ask("/fix shop/cart.py | handle empty carts")
    assert requests[0]["project"]["files_truncated"] is True


@pytest.mark.skipif(os.name == "nt", reason="symlink creation needs privileges on Windows")
def test_links_are_refused(project, tmp_path):
    cfg, _, brain, root, replies, _ = project
    outside = tmp_path / "secret.py"
    outside.write_text("TOKEN = 'x'\n")
    (root / "linked.py").symlink_to(outside)
    (root / "alias.py").symlink_to(root / "cart.py")
    assert "link" in brain.ask("/fix shop/linked.py | change it")
    assert "link" in brain.ask("/fix shop/alias.py | change it")
    assert "shop/linked.py" not in coder.project_files(root)[0]
    assert outside.read_text() == "TOKEN = 'x'\n" and not replies


@pytest.mark.parametrize("reply", [
    "",
    "FILE: shop/cart.py\n<<<<<<< SEARCH\n    return sum(items)\n=======\n",
    "FILE: shop/cart.py\n<<<<<<< SEARCH\ndef total(items):\n=======\ndef total(items, tax):\n>>>>>>> REPLACE\n"
    "<<<<<<< SEARCH\ndef total(items):\n=======\ndef total(items, fee):\n>>>>>>> REPLACE\n",
])
def test_malformed_and_conflicting_output_saves_nothing(project, reply):
    cfg, _, brain, root, replies, _ = project
    before = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
    replies.extend([reply, reply])  # the original answer and the single repair attempt
    result = brain.ask("/fix shop/cart.py | add a tax argument")
    assert "Nothing was saved" in result or "did not return" in result
    assert {p: p.read_bytes() for p in root.rglob("*") if p.is_file()} == before
    assert brain.ctx.code_proposal is None


def test_undo_survives_a_restart(project):
    cfg, db, brain, root, replies, _ = project
    original = (root / "cart.py").read_text()
    replies.append(PATCH)
    brain.ask("/fix shop/cart.py | handle empty carts")
    brain.ask("/apply")
    restarted = Brain(cfg, db)
    assert "Restored" in restarted.ask("/undo")
    assert (root / "cart.py").read_text() == original
    assert "no applied edit" in restarted.ask("/undo")


def test_undo_after_restart_refuses_a_changed_file(project):
    cfg, db, brain, root, replies, _ = project
    replies.append(PATCH)
    brain.ask("/fix shop/cart.py | handle empty carts")
    brain.ask("/apply")
    (root / "cart.py").write_text("# edited by hand\n")
    assert "changed since" in Brain(cfg, db).ask("/undo")
    assert (root / "cart.py").read_text() == "# edited by hand\n"


def test_test_timeout_is_reported_without_a_result(project, monkeypatch):
    cfg, _, brain, root, _, _ = project

    def slow(command, cwd, timeout):
        raise subprocess.TimeoutExpired(command, timeout)

    monkeypatch.setattr(coder, "_run_in_job", slow)
    brain.ask("/test shop/cart.py")
    result = brain.confirm_pending(True)
    assert "120 seconds" in result and "No result" in result


def test_build_needs_approval_and_compiles_without_running(project):
    cfg, _, brain, root, _, _ = project
    (root / "side_effect.py").write_text("open('ran.txt', 'w').write('ran')\n")
    preview = brain.ask("/build shop/cart.py")
    assert "compileall" in preview and brain.ctx.pending["name"] == "run_project_build"
    assert not list(root.rglob("*.pyc"))
    result = brain.confirm_pending(True)
    assert result.startswith("Build passed"), result
    assert list(root.rglob("*.pyc")) and not (root / "ran.txt").exists()
    (root / "broken.py").write_text("def broken(:\n")
    brain.ask("/build shop/cart.py")
    assert "Build failed" in brain.confirm_pending(True)


def test_failure_output_files_are_added_as_context(project, monkeypatch):
    cfg, _, brain, root, replies, requests = project
    output = (f'Traceback (most recent call last):\n  File "{root / "checkout.py"}", line 5, in pay\n'
              "ZeroDivisionError: division by zero\nFAILED tests/test_cart.py::test_total")
    monkeypatch.setattr(coder, "_run_in_job", lambda command, cwd, timeout: (1, output, ""))
    brain.ask("/test shop/cart.py")
    brain.confirm_pending(True)
    replies.append(PATCH)
    brain.ask("/fix-tests shop/cart.py | fix the failure")
    assert "shop/checkout.py" in requests[0]["references"]
    assert "shop/tests/test_cart.py" in requests[0]["references"]
    assert "ZeroDivisionError" in requests[0]["task"]


def test_build_and_test_commands_are_risky_and_manual():
    for name in ("run_project_build", "run_project_tests", "run_code"):
        assert skills.SKILLS[name]["risky"]
    assert skills.SKILLS["run_project_build"]["manual"] and skills.SKILLS["run_project_tests"]["manual"]


def test_low_memory_profile_keeps_coding_requests_small(project):
    from jarvis import config
    cfg, _, brain, root, replies, requests = project
    cfg.update(config.PERFORMANCE_PROFILES["low-memory"])
    assert coder.source_budget(cfg) == 4096
    replies.append(PATCH)
    assert "Preview only" in brain.ask("/fix shop/cart.py | handle empty carts")
    sent = len(requests[0]["source"]) + sum(len(t) for t in requests[0].get("references", {}).values())
    assert sent <= 4096
    (root / "big.py").write_text("x = 1\n" * 1000)
    assert "4096-character coding context" in brain.ask("/fix shop/big.py | rename x")
