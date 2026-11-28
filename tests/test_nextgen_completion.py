"""Integration & regression tests for Jarvis 2.0 completion items."""
import base64
import io
import json
import zipfile
from unittest.mock import patch

import pytest

from jarvis import config, geospatial, net
from jarvis.__main__ import App


def _build_minimal_xlsx(rows: list[list[str]]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"></Types>')
        xml_rows = []
        for r_idx, row in enumerate(rows, start=1):
            cells = "".join(
                f'<c r="{chr(65 + c_idx)}{r_idx}" t="inlineStr"><is><t>{val}</t></is></c>'
                for c_idx, val in enumerate(row)
            )
            xml_rows.append(f'<row r="{r_idx}">{cells}</row>')
        sheet_xml = f'<?xml version="1.0"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>{"".join(xml_rows)}</sheetData></worksheet>'
        zf.writestr("xl/worksheets/sheet1.xml", sheet_xml)
    return buf.getvalue()


def test_geospatial_extract_feed_markers_all_formats():
    usgs = json.dumps({"features": [{"geometry": {"coordinates": [-105.0, 40.0, 10.0]}, "properties": {"title": "M3.1 Denver"}}]})
    cnt, markers = geospatial.extract_feed_markers("usgs_earthquakes", usgs)
    assert cnt == 1 and markers[0]["lat"] == 40.0 and markers[0]["lon"] == -105.0

    nasa = json.dumps({"events": [{"title": "Pine Fire", "geometry": [{"coordinates": [-120.5, 38.2]}]}]})
    cnt, markers = geospatial.extract_feed_markers("nasa_eonet_wildfires", nasa)
    assert cnt == 1 and markers[0]["label"] == "Pine Fire"

    opensky = json.dumps({"states": [["abc123", "UAL100 ", "US", 0, 0, -104.67, 39.85]]})
    cnt, markers = geospatial.extract_feed_markers("opensky_public_flights", opensky)
    assert cnt == 1 and markers[0]["label"] == "UAL100"

    noaa = "#STN LAT LON\n41001 34.68 -72.66 1013\n"
    cnt, markers = geospatial.extract_feed_markers("noaa_maritime_buoys", noaa)
    assert cnt == 1 and markers[0]["label"] == "Buoy 41001"


def test_app_geospatial_feed_fail_closed_and_mocked_overlay(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    app = App(dict(config.DEFAULTS, allow_internet_tools=False, lockdown=False, speak_replies=False), use_voice=False)
    try:
        with pytest.raises(net.NetworkBlockedError):
            app.geospatial_operation({"action": "feed", "feed_id": "usgs_earthquakes"})

        app.cfg["allow_internet_tools"] = True
        payload = json.dumps({"features": [{"geometry": {"coordinates": [-105.0, 40.0]}, "properties": {"title": "Quake"}}]})
        with patch.object(net, "read_public_page", return_value=(payload, "application/json")):
            res = app.geospatial_operation({"action": "feed", "feed_id": "usgs_earthquakes"})
        assert res["item_count"] == 1
        assert len(res["markers"]) == 1
        assert res["markers"][0]["lat"] == 40.0
    finally:
        app.memory.db.close()


def test_app_pro_xlsx_variance_and_invalid_b64_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    app = App(dict(config.DEFAULTS, speak_replies=False), use_voice=False)
    try:
        base = _build_minimal_xlsx([["item", "amount"], ["Servers", "100"], ["Storage", "50"]])
        act = _build_minimal_xlsx([["item", "amount"], ["Servers", "125"], ["Storage", "50"]])
        res = app.pro_operation({
            "action": "xlsx_variance",
            "baseline_b64": base64.b64encode(base).decode("ascii"),
            "actual_b64": base64.b64encode(act).decode("ascii"),
            "key_col": "item",
            "value_col": "amount",
        })
        assert res["total_baseline"] == 150.0
        assert res["total_actual"] == 175.0
        assert res["total_delta"] == 25.0

        with pytest.raises(ValueError, match="Invalid base64"):
            app.pro_operation({"action": "xlsx_variance", "baseline_b64": "!!!", "actual_b64": "!!!"})
    finally:
        app.memory.db.close()


def test_app_daily_summary_extracts_from_recent_messages_and_approves(tmp_path, monkeypatch):
    from jarvis import memory as _memory
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(_memory, "DB_PATH", tmp_path / "mem.db")
    app = App(dict(config.DEFAULTS, speak_replies=False), use_voice=False)
    try:
        app.memory.log("user", "I prefer concise engineering summaries.")
        ext = app.daily_summary_operation({"action": "extract"})
        assert len(ext["candidates"]) >= 1
        cand_text = ext["candidates"][0]["text"]
        saved = app.daily_summary_operation({"action": "approve", "text": cand_text})
        assert "concise engineering summaries" in saved["saved"]
    finally:
        app.memory.db.close()
