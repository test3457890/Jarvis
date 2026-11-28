"""Phase 8 Next-Generation tests:
- Mobile companion pairing (disabled by default, single-use code, hashed token, revocation, Lockdown block)
- Geospatial offline geodesy, SAR search-grid generation, and fail-closed public feed guards
"""
import pytest

from jarvis import companion, config, geospatial, memory, net


def test_companion_pairing_disabled_by_default_and_revocation(tmp_path, monkeypatch):
    monkeypatch.setattr(memory, "DB_PATH", tmp_path / "mem.db")
    mem = memory.Memory()
    cfg = dict(config.DEFAULTS)

    # MUST be disabled by default
    assert companion.is_enabled(cfg) is False
    with pytest.raises(PermissionError, match="disabled"):
        companion.create_pairing_code(cfg)

    # Explicit opt-in enables pairing
    cfg["remote_companion_enabled"] = True
    code_info = companion.create_pairing_code(cfg)
    assert len(code_info["code"]) == 6

    paired = companion.complete_pairing(mem, cfg, code=code_info["code"], device_name="Pixel 9", platform="android")
    assert paired["token"]
    assert companion.verify_device_token(mem, cfg, paired["token"])["name"] == "Pixel 9"

    # Pairing code is single-use
    with pytest.raises(PermissionError):
        companion.complete_pairing(mem, cfg, code=code_info["code"], device_name="Replay", platform="android")

    # Lockdown immediately invalidates verification
    cfg["lockdown"] = True
    assert companion.verify_device_token(mem, cfg, paired["token"]) is None
    cfg["lockdown"] = False

    # Revocation permanently blocks device token
    assert companion.revoke_device(mem, paired["device_id"]) is True
    assert companion.verify_device_token(mem, cfg, paired["token"]) is None


def test_geospatial_offline_geodesy_sar_grid_and_fail_closed_feeds():
    # San Francisco to Los Angeles (~559 km)
    dist = geospatial.haversine_km(37.7749, -122.4194, 34.0522, -118.2437)
    assert 550.0 < dist < 570.0
    brg = geospatial.initial_bearing_deg(37.7749, -122.4194, 34.0522, -118.2437)
    assert 130.0 < brg < 150.0

    grid = geospatial.sar_search_grid(39.7392, -104.9903, radius_km=4.0, spacing_km=1.0)
    assert grid["tracks"] >= 4
    assert grid["area_km2"] == 64.0
    assert len(grid["waypoints"]) == grid["tracks"] * 2

    # Public geospatial feeds MUST fail closed when offline
    cfg = dict(config.DEFAULTS)
    with pytest.raises(net.NetworkBlockedError):
        geospatial.fetch_public_feed(cfg, "usgs_earthquakes")
