import os
import threading
from pathlib import Path

import pytest

from jarvis import filejobs, skills


@pytest.fixture
def folder(isolated_app, tmp_path):
    cfg, db, ctx, _ = isolated_app
    root = tmp_path / "Selected"
    (root / "Inbox").mkdir(parents=True)
    (root / "Inbox" / "photo.jpg").write_bytes(b"jpeg data")
    (root / "Inbox" / "notes.txt").write_text("notes")
    (root / "Inbox" / "song.mp3").write_bytes(b"mp3")
    cfg["file_folders"] = [str(root)]
    ctx.cancelled = threading.Event()
    return cfg, ctx, root


def confirm(ctx):
    pending = ctx.pending
    assert pending, "the change needs confirmation"
    ctx.pending = None
    return skills.run(ctx, pending["name"], pending["args"], confirmed=True)


def test_browse_and_search_stay_inside_selected_folder(folder):
    cfg, _, root = folder
    listing = filejobs.browse(cfg, 0, "Inbox")
    assert [item["name"] for item in listing["items"]] == ["notes.txt", "photo.jpg", "song.mp3"]
    assert "never overwritten" in listing["limits"]
    assert filejobs.search(cfg, 0, "PHOTO")["results"][0]["path"] == "Inbox/photo.jpg"
    for bad in ("../outside", "C:/Windows", "Inbox/../../x", "\\\\server\\share", "Inbox/con", ".Jarvis Recycle"):
        with pytest.raises(ValueError):
            filejobs.browse(cfg, 0, bad)
    with pytest.raises(ValueError):
        filejobs.browse(cfg, 3, "")


def test_code_workspace_is_never_a_file_task_root(folder):
    cfg, _, _ = folder
    cfg["file_folders"] = [cfg["code_dir"], str(Path(cfg["code_dir"]).parent)]
    assert filejobs.folder_roots(cfg) == []


@pytest.mark.skipif(os.name == "nt", reason="symlink creation needs privileges on Windows")
def test_symlinks_are_not_followed(folder, tmp_path):
    cfg, ctx, root = folder
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("secret")
    (root / "escape").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="link"):
        filejobs.browse(cfg, 0, "escape")
    with pytest.raises(ValueError, match="link"):
        filejobs.prepare_folder_task(ctx, 0, "copy", {"paths": ["escape/secret.txt"], "destination": "Inbox"})
    assert {item["type"] for item in filejobs.browse(cfg, 0, "")["items"] if item["name"] == "escape"} == {"link"}
    assert not any(r["path"].startswith("escape/") for r in filejobs.search(cfg, 0, "secret")["results"])


def test_preview_is_exact_and_nothing_changes_before_confirmation(folder):
    cfg, ctx, root = folder
    result = filejobs.prepare_folder_task(ctx, 0, "organize", {"path": "Inbox"})
    assert result["preview"].splitlines() == [
        "1. Create folder Inbox/Documents",
        "2. Move Inbox/notes.txt to Inbox/Documents/notes.txt",
        "3. Create folder Inbox/Images",
        "4. Move Inbox/photo.jpg to Inbox/Images/photo.jpg",
        "5. Create folder Inbox/Audio",
        "6. Move Inbox/song.mp3 to Inbox/Audio/song.mp3",
    ]
    assert result["pending"] and not (root / "Inbox" / "Images").exists()
    assert "Finished 6 steps" in confirm(ctx)
    assert (root / "Inbox" / "Images" / "photo.jpg").read_bytes() == b"jpeg data"
    assert "File task undone" in (skills.run(ctx, "undo_folder_job", {"job_id": result["job_id"]}) and confirm(ctx))
    assert sorted(p.name for p in (root / "Inbox").iterdir()) == ["notes.txt", "photo.jpg", "song.mp3"]


def test_collisions_are_refused_and_never_overwritten(folder):
    cfg, ctx, root = folder
    (root / "Inbox" / "photo copy.jpg").write_text("other")
    with pytest.raises(ValueError, match="already exists"):
        filejobs.prepare_folder_task(ctx, 0, "rename", {"path": "Inbox/photo.jpg", "new_name": "notes.txt"})
    with pytest.raises(ValueError, match="already exists"):
        filejobs.prepare_folder_task(ctx, 0, "mkdir", {"path": "Inbox"})
    with pytest.raises(ValueError, match="does not exist"):
        filejobs.prepare_folder_task(ctx, 0, "copy", {"paths": ["Inbox/notes.txt"], "destination": "Missing"})
    with pytest.raises(ValueError, match="into itself"):
        filejobs.prepare_folder_task(ctx, 0, "move", {"paths": ["Inbox"], "destination": "Inbox"})
    # A destination that appears after the preview blocks the step instead of being replaced.
    result = filejobs.prepare_folder_task(ctx, 0, "rename", {"path": "Inbox/photo.jpg", "new_name": "holiday.jpg"})
    (root / "Inbox" / "holiday.jpg").write_text("someone else's file")
    assert "Step 1 failed" in confirm(ctx)
    assert (root / "Inbox" / "holiday.jpg").read_text() == "someone else's file"
    assert (root / "Inbox" / "photo.jpg").read_bytes() == b"jpeg data"
    assert filejobs._get_folder_job(ctx, result["job_id"])["state"] == "failed"


def test_changed_source_blocks_the_task(folder):
    cfg, ctx, root = folder
    filejobs.prepare_folder_task(ctx, 0, "copy", {"paths": ["Inbox/notes.txt"], "destination": ""})
    (root / "Inbox" / "notes.txt").write_text("edited after preview")
    assert "changed" in confirm(ctx)
    assert not (root / "notes.txt").exists()


def test_delete_goes_to_recoverable_folder_and_undo_restores(folder):
    cfg, ctx, root = folder
    result = filejobs.prepare_folder_task(ctx, 0, "delete", {"paths": ["Inbox/notes.txt", "Inbox/photo.jpg"]})
    assert "Move to Jarvis Recycle" in result["preview"]
    confirm(ctx)
    assert not (root / "Inbox" / "notes.txt").exists()
    trashed = list((root / filejobs.TRASH).rglob("notes.txt"))
    assert trashed and trashed[0].read_text() == "notes"
    assert all(item["name"] != filejobs.TRASH for item in filejobs.browse(cfg, 0, "")["items"])
    skills.run(ctx, "undo_folder_job", {"job_id": result["job_id"]})
    assert confirm(ctx) == "File task undone."
    assert (root / "Inbox" / "notes.txt").read_text() == "notes"
    assert not list((root / filejobs.TRASH).rglob("*.txt"))


def test_undo_is_blocked_when_a_result_changed(folder):
    cfg, ctx, root = folder
    result = filejobs.prepare_folder_task(ctx, 0, "copy", {"paths": ["Inbox/notes.txt"], "destination": ""})
    confirm(ctx)
    (root / "notes.txt").write_text("edited copy")
    skills.run(ctx, "undo_folder_job", {"job_id": result["job_id"]})
    assert "blocked" in confirm(ctx)
    assert (root / "notes.txt").read_text() == "edited copy"


def test_permission_failure_is_reported_and_finished_steps_can_be_undone(folder, monkeypatch):
    cfg, ctx, root = folder
    result = filejobs.prepare_folder_task(ctx, 0, "move", {"paths": ["Inbox/notes.txt", "Inbox/song.mp3"],
                                                           "destination": ""})
    real = filejobs._move
    calls = []

    def flaky(src, dst):
        calls.append(src.name)
        if src.name == "song.mp3":
            raise PermissionError("Access is denied")
        return real(src, dst)

    monkeypatch.setattr(filejobs, "_move", flaky)
    message = confirm(ctx)
    assert "Step 2 failed: Access is denied" in message and "1 steps finished" in message
    monkeypatch.setattr(filejobs, "_move", real)
    skills.run(ctx, "undo_folder_job", {"job_id": result["job_id"]})
    assert confirm(ctx) == "File task undone."
    assert (root / "Inbox" / "notes.txt").exists() and not (root / "notes.txt").exists()


def test_interrupted_task_resumes_from_the_journal(folder, monkeypatch):
    cfg, ctx, root = folder
    result = filejobs.prepare_folder_task(ctx, 0, "move", {"paths": ["Inbox/notes.txt", "Inbox/photo.jpg"],
                                                           "destination": ""})
    job_id = result["job_id"]
    real = filejobs._move

    def crash_after_publish(src, dst):
        real(src, dst)
        if src.name == "photo.jpg":
            raise KeyboardInterrupt("power cut after the file was moved")

    monkeypatch.setattr(filejobs, "_move", crash_after_publish)
    with pytest.raises(KeyboardInterrupt):
        confirm(ctx)
    monkeypatch.setattr(filejobs, "_move", real)
    job = filejobs._get_folder_job(ctx, job_id)
    assert [step["state"] for step in job["steps"]] == ["done", "running"]
    skills.run(ctx, "execute_folder_job", {"job_id": job_id})
    assert "Finished 2 steps" in confirm(ctx)
    assert (root / "photo.jpg").read_bytes() == b"jpeg data" and not (root / "Inbox" / "photo.jpg").exists()


def test_stop_between_steps_leaves_a_resumable_task(folder):
    cfg, ctx, root = folder
    result = filejobs.prepare_folder_task(ctx, 0, "copy", {"paths": ["Inbox/notes.txt"], "destination": ""})
    pending = ctx.pending
    ctx.cancelled.set()
    assert "Stopped after 0 steps" in filejobs.execute_folder_job(ctx, result["job_id"])
    ctx.cancelled.clear()
    assert filejobs._get_folder_job(ctx, result["job_id"])["state"] == "interrupted"
    assert "Finished 1 steps" in skills.run(ctx, pending["name"], pending["args"], confirmed=True)


def test_limits_and_unavailable_modes(folder, monkeypatch):
    cfg, ctx, root = folder
    monkeypatch.setattr(filejobs, "MAX_STEPS", 2)
    with pytest.raises(ValueError, match="limit is 2"):
        filejobs.prepare_folder_task(ctx, 0, "organize", {"path": "Inbox"})
    cfg["lockdown"] = True
    with pytest.raises(ValueError, match="Lockdown"):
        filejobs.prepare_folder_task(ctx, 0, "mkdir", {"path": "New"})


def test_existing_workspace_copy_commands_still_work(isolated_app):
    cfg, _, ctx, _ = isolated_app
    (Path(cfg["code_dir"]) / "a.txt").write_text("a")
    assert "NOT DONE YET" in filejobs.prepare(ctx, "copy", "a.txt", "b.txt")
