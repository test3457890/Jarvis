"""Phase 8 & Companion Completion tests:
- Mobile companion pairing: disabled by default, single-use code, failed-attempt rate limiting,
  token expiration TTL, revocation, Lockdown block, notifications & approved T0 remote commands
- Geospatial offline geodesy, SAR search-grid generation, and fail-closed public feed guards
"""
import time
import pytest

from jarvis import companion, config, geospatial, memory, net, skills


def test_companion_pairing_rate_limit_expiration_revocation_and_commands(tmp_path, monkeypatch):
    monkeypatch.setattr(memory, "DB_PATH", tmp_path / "mem.db")
    companion.reset_rate_limiter()
    mem = memory.Memory()
    cfg = dict(config.DEFAULTS)
    ctx = skills.Context(cfg, mem)

    # MUST be disabled by default
    assert companion.is_enabled(cfg) is False
    with pytest.raises(PermissionError, match="disabled"):
        companion.create_pairing_code(cfg)

    # Explicit opt-in enables pairing
    cfg["remote_companion_enabled"] = True
    code_info = companion.create_pairing_code(cfg)
    assert len(code_info["code"]) == 6

    # Failed pairing rate limiting after MAX_PAIR_FAILURES wrong attempts
    for _ in range(companion.MAX_PAIR_FAILURES):
        with pytest.raises(PermissionError):
            companion.complete_pairing(mem, cfg, code="000000", device_name="Attacker", client_id="bad_ip")
    with pytest.raises(PermissionError, match="Too many failed"):
        companion.complete_pairing(mem, cfg, code="000000", device_name="Attacker", client_id="bad_ip")

    # Fresh code pairs cleanly with custom short TTL
    code_info2 = companion.create_pairing_code(cfg)
    paired = companion.complete_pairing(
        mem, cfg, code=code_info2["code"], device_name="Pixel 9", platform="android",
        token_ttl_seconds=120, client_id="good_ip",
    )
    token = paired["token"]
    assert companion.verify_device_token(mem, cfg, token)["name"] == "Pixel 9"

    # Expired token MUST be rejected
    assert companion.verify_device_token(mem, cfg, token, now=time.time() + 300) is None

    # Approved T0 command succeeds; risky/unapproved command is blocked
    res = companion.execute_approved_command(mem, ctx, token=token, tool="get_time_date")
    assert res["ok"] is True and res["output"]
    with pytest.raises(PermissionError, match="allowlist"):
        companion.execute_approved_command(mem, ctx, token=token, tool="power", args={"action": "shutdown"})

    # Notification queue redacts secrets
    note = companion.push_notification("Alert", "Key sk-1234567890abcdef12345678 blocked", level="warn")
    assert "sk-1234567890" not in note["body"]
    assert companion.recent_notifications(5)[0]["id"] == note["id"]

    # Lockdown immediately invalidates verification
    cfg["lockdown"] = True
    assert companion.verify_device_token(mem, cfg, token) is None
    cfg["lockdown"] = False

    # Revocation permanently blocks device token
    assert companion.revoke_device(mem, paired["device_id"]) is True
    assert companion.verify_device_token(mem, cfg, token) is None


def test_geospatial_offline_geodesy_sar_grid_and_fail_closed_feeds():
    dist = geospatial.haversine_km(37.7749, -122.4194, 34.0522, -118.2437)
    assert 550.0 < dist < 570.0
    brg = geospatial.initial_bearing_deg(37.7749, -122.4194, 34.0522, -118.2437)
    assert 130.0 < brg < 150.0

    grid = geospatial.sar_search_grid(39.7392, -104.9903, radius_km=4.0, spacing_km=1.0)
    assert grid["tracks"] >= 4
    assert grid["area_km2"] == 64.0
    assert len(grid["waypoints"]) == grid["tracks"] * 2

    cfg = dict(config.DEFAULTS)
    with pytest.raises(net.NetworkBlockedError):
        geospatial.fetch_public_feed(cfg, "usgs_earthquakes")
