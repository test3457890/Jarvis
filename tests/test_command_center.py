"""Comprehensive Tests for Jarvis Advanced Command Center Backends (Phases 3-11)."""
import json
import re
import socket
import urllib.error
import urllib.request
import zipfile
import pytest

from jarvis import (
    __main__ as jarvis_main,
    config,
    connectors,
    containers,
    coop_agents,
    geospatial,
    memory,
    office_docs,
    sentinel_ops,
    smarthome,
    uia_control,
    webui,
)


def test_uia_control_blocks_passwords_uac_and_requires_approval():
    blocked, reason = uia_control.is_sensitive_control("Account Password", "Edit", is_password=True)
    assert blocked is True and "password" in reason.lower()

    blocked_uac, _ = uia_control.is_sensitive_control("User Account Control - Allow this app", "Button")
    assert blocked_uac is True

    prev = uia_control.preview_desktop_action("hotkey", value="ctrl+alt+del")
    assert prev["blocked"] is True

    cfg = dict(config.DEFAULTS, lockdown=False)
    with pytest.raises(PermissionError, match="Explicit user approval"):
        uia_control.execute_approved_action(cfg, "click_control", target="Save Button", approved=False)

    with pytest.raises(PermissionError, match="password"):
        uia_control.execute_approved_action(cfg, "type_control", target="Password", approved=True, is_password=True)

    ok = uia_control.execute_approved_action(cfg, "click_control", target="Save Document", approved=True)
    assert ok["ok"] is True

    cfg_lock = dict(config.DEFAULTS, lockdown=True)
    with pytest.raises(PermissionError, match="Lockdown"):
        uia_control.execute_approved_action(cfg_lock, "click_control", target="Save Document", approved=True)

    assert uia_control.cancel_active()["cancelled"] is True


def test_geospatial_global_intelligence_annotations_orbit_and_voice_nav(tmp_path, monkeypatch):
    monkeypatch.setattr(memory, "DB_PATH", tmp_path / "geo.db")
    mem = memory.Memory()
    st = geospatial.workspace_status(config.DEFAULTS, mem)
    assert len(st["feeds"]) >= 6
    for f in st["feeds"]:
        assert f["data_class"] in ("live", "delayed", "estimated", "simulated")
        assert f["attribution"]

    ann = geospatial.add_annotation(mem, "Base Camp", 39.7392, -104.9903, category="sar", notes="Staging point")
    assert ann["data_class"] == "user_annotation"
    assert len(geospatial.list_annotations(mem)) == 1
    geospatial.delete_annotation(mem, ann["id"])
    assert len(geospatial.list_annotations(mem)) == 0

    orbit = geospatial.estimate_orbital_track("ISS", steps=24)
    assert orbit["data_class"] == "estimated" and len(orbit["points"]) == 24

    nav = geospatial.parse_voice_navigation("Jarvis fly to Tokyo")
    assert nav["action"] == "fly_to" and abs(nav["lat"] - 35.6762) < 0.01
    nav_layer = geospatial.parse_voice_navigation("show earthquakes")
    assert nav_layer["action"] == "toggle_layer" and nav_layer["feed"] == "usgs_earthquakes"
    mem.db.close()


def test_smarthome_owner_authorization_dpapi_and_biometric_refusal(tmp_path, monkeypatch):
    monkeypatch.setattr(memory, "DB_PATH", tmp_path / "sh.db")
    mem = memory.Memory()
    cfg = dict(config.DEFAULTS, lockdown=False)

    # Must refuse without explicit owner authorization
    with pytest.raises(PermissionError, match="owner authorization"):
        smarthome.register_device(
            mem, cfg, device_id="cam1", name="Front Porch", kind="rtsp_camera",
            endpoint="rtsp://192.168.1.50:554/stream1", owner_authorized=False,
        )

    # Must refuse credentials embedded in URL
    with pytest.raises(ValueError, match="embed credentials"):
        smarthome.register_device(
            mem, cfg, device_id="cam1", name="Front Porch", kind="rtsp_camera",
            endpoint="rtsp://admin:pass@192.168.1.50:554/stream1", owner_authorized=True,
        )

    dev = smarthome.register_device(
        mem, cfg, device_id="porch_cam", name="Front Porch", kind="onvif_camera",
        endpoint="https://192.168.1.50/onvif", zone="Exterior", owner_authorized=True,
    )
    assert dev["id"] == "porch_cam" and dev["owner_authorized"] is True

    # Recording requires explicit approval
    with pytest.raises(PermissionError, match="Explicit owner approval"):
        smarthome.set_recording(mem, cfg, "porch_cam", True, approved=False)
    rec = smarthome.set_recording(mem, cfg, "porch_cam", True, approved=True)
    assert rec["recording_enabled"] is True

    # Facial identification is strictly prohibited
    with pytest.raises(PermissionError, match="Facial identification"):
        smarthome.record_event(mem, "porch_cam", "alert", "facial_recognition match detected")

    smarthome.remove_device(mem, cfg, "porch_cam")
    assert smarthome.list_devices(mem) == []
    mem.db.close()


def test_sentinel_ops_fim_secrets_eve_alerts_firewall_and_evidence(tmp_path, monkeypatch):
    monkeypatch.setattr(memory, "DB_PATH", tmp_path / "sec.db")
    mem = memory.Memory()
    target = tmp_path / "important.txt"
    target.write_text("original-safe-content", encoding="utf-8")

    base = sentinel_ops.fim_baseline(mem, [target])
    assert base["recorded"] == 1
    assert sentinel_ops.fim_verify(mem)["ok"] is True

    # Modify file -> FIM must detect tamper
    target.write_text("tampered-content", encoding="utf-8")
    ver = sentinel_ops.fim_verify(mem)
    assert ver["ok"] is False and len(ver["modified"]) == 1

    # Secret scanner detects test token patterns
    (tmp_path / "leak.py").write_text("TOKEN = 'ghp_1234567890abcdefghijklmnop'\n", encoding="utf-8")
    scan = sentinel_ops.scan_secrets(tmp_path)
    assert scan["finding_count"] == 1 and scan["findings"][0]["kind"] == "github_pat"

    # Suricata EVE JSON parser
    eve = tmp_path / "eve.json"
    eve.write_text(json.dumps({"event_type": "alert", "timestamp": "2026-11-28T12:00:00Z", "src_ip": "198.51.100.5", "dest_port": 22, "alert": {"signature": "ET SCAN SSH", "severity": 2}}) + "\n", encoding="utf-8")
    parsed = sentinel_ops.parse_ids_eve_alerts(eve)
    assert parsed["alert_count"] == 1 and parsed["alerts"][0]["dest_port"] == 22

    # Firewall rule preview only
    fw = sentinel_ops.preview_defensive_firewall_rule("BlockScanner", "198.51.100.5")
    assert fw["dry_run"] is True and "New-NetFirewallRule" in fw["command_preview"]

    # Evidence pack export
    ev = sentinel_ops.export_incident_evidence(mem, out_dir=tmp_path / "ev", title="ssh_scan")
    assert ev["ok"] is True and len(ev["sha256"]) == 64
    mem.db.close()


def test_containers_hardened_policy_blocks_docker_sock_and_escapes(tmp_path):
    work = tmp_path / "proj"
    work.mkdir()
    args = containers.build_hardened_run_args(
        "python:3.12-slim", ["python", "-V"],
        workspace_mount=work, allowed_root=tmp_path,
    )
    assert "--read-only" in args
    assert "--cap-drop=ALL" in args
    assert "--user" in args and "65534:65534" in args
    assert "--network" in args and "none" in args

    with pytest.raises(PermissionError, match="docker.sock"):
        containers.validate_mount_path("/var/run/docker.sock", tmp_path)
    with pytest.raises(PermissionError, match="approved workspace root"):
        containers.validate_mount_path(tmp_path.parent, work)


def test_coop_agents_bounded_recursion_dependencies_and_automations(tmp_path, monkeypatch):
    monkeypatch.setattr(memory, "DB_PATH", tmp_path / "coop.db")
    mem = memory.Memory()
    cfg = dict(config.DEFAULTS, lockdown=False)

    # Prevent unbounded recursion
    with pytest.raises(PermissionError, match="recursive"):
        coop_agents.create_plan(mem, "Deep", "Loop", [{"id": "s1", "title": "x", "agent": "tuki_research"}], depth=10)

    plan = coop_agents.create_plan(mem, "Audit Release", "Verify security & code", [
        {"id": "s1", "title": "Research CVEs", "agent": "tuki_research"},
        {"id": "s2", "title": "Apply Fix", "agent": "tuki_coding", "depends_on": ["s1"], "requires_approval": True},
    ])
    # Dependency enforcement
    with pytest.raises(RuntimeError, match="blocked until dependency"):
        coop_agents.advance_step(mem, plan["id"], "s2")

    p1 = coop_agents.advance_step(mem, plan["id"], "s1", outcome="No critical CVEs", verify=True)
    assert p1["steps"][0]["verified"] is True

    # Approval gate on s2
    p2 = coop_agents.advance_step(mem, plan["id"], "s2")
    assert p2["status"] == "awaiting_approval"
    p3 = coop_agents.advance_step(mem, plan["id"], "s2", outcome="Applied cleanly", approve=True, verify=True)
    assert p3["status"] == "completed"

    auto = coop_agents.save_automation(
        mem, cfg, name="High CPU Alert", trigger_type="metric_threshold",
        trigger_spec="cpu > 90%", action_spec="Notify user", enabled=True,
    )
    assert auto["enabled"] is True and len(coop_agents.list_automations(mem)) == 1
    mem.db.close()


def test_office_docs_docx_pptx_citations_and_knowledge_graph(tmp_path, monkeypatch):
    monkeypatch.setattr(memory, "DB_PATH", tmp_path / "off.db")
    cfg = dict(config.DEFAULTS, notes_dir=str(tmp_path))
    mem = memory.Memory()

    docx_res = office_docs.generate_docx(cfg, "brief.docx", "Jarvis Brief", ["Paragraph one.", "Paragraph two."])
    assert docx_res["ok"] is True and docx_res["bytes"] > 200
    assert "Paragraph one." in office_docs.read_docx_text(docx_res["path"])

    pptx_res = office_docs.generate_pptx(cfg, "deck.pptx", [{"title": "Overview", "body": "All systems nominal."}])
    assert pptx_res["ok"] is True and pptx_res["slides"] == 1
    with zipfile.ZipFile(pptx_res["path"], "r") as zf:
        assert "ppt/slides/slide1.xml" in zf.namelist()

    c = office_docs.add_citation(mem, "jarvis2026", "Jarvis Team", "2026", "Local-First AI Command Centers", venue="LocalConf")
    assert "@article{jarvis2026" in c["bibtex"]
    assert len(office_docs.list_citations(mem)) == 1

    office_docs.add_knowledge_edge(mem, "Kokoro-82M", "uses_provider", "CUDAExecutionProvider")
    edges = office_docs.query_knowledge_graph(mem, "Kokoro")
    assert len(edges) == 1 and edges[0]["object"] == "CUDAExecutionProvider"
    mem.db.close()


def test_connector_catalogue_and_command_center_http_endpoints(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(memory, "DB_PATH", tmp_path / "mem.db")
    cfg = dict(config.DEFAULTS, notes_dir=str(tmp_path / "notes"))
    (tmp_path / "notes").mkdir(exist_ok=True)
    config.save(cfg)

    matches = connectors.search_catalogue("gods-eye")
    assert len(matches) == 1 and matches[0]["auto_install"] is False
    prev = connectors.preview_catalogue_install("gods-eye-view-mcp")
    assert prev["requires_explicit_approval"] is True

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]

    app = jarvis_main.App(cfg, use_voice=False)
    server = webui.serve(app, port)
    base = f"http://127.0.0.1:{port}"
    try:
        html = urllib.request.urlopen(base + "/", timeout=5).read().decode("utf-8")
        key = re.search(r"\bKEY\s*=\s*['\"]([^'\"]+)['\"]", html).group(1)
        hdrs = {"X-Jarvis-Key": key, "Origin": base, "Content-Type": "application/json"}

        for ep in ("/api/uia", "/api/smarthome", "/api/sentinel-ops", "/api/containers", "/api/coop-agents", "/api/office", "/api/catalogue", "/api/tools/catalogue"):
            with pytest.raises(urllib.error.HTTPError) as exc:
                urllib.request.urlopen(base + ep, timeout=5)
            assert exc.value.code == 403
            req = urllib.request.Request(base + ep, headers=hdrs)
            data = json.loads(urllib.request.urlopen(req, timeout=10).read())
            assert isinstance(data, dict)
    finally:
        server.shutdown()
        server.server_close()
