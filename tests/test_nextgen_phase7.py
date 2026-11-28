"""Phase 7 Next-Generation tests:
- CSV reconciliation & variance report (pro_workspace.py)
- Document revision unified diff
- Requirements / UAT evidence tracker & Case management
- Private local finance budget summary strictly gated by domains.check_domain_access('finance')
"""
import pytest

from jarvis import config, memory, pro_workspace


def test_csv_variance_and_doc_revision_diff():
    base = "item,amount\nHosting,100\nStorage,50\nLegacy,25\n"
    actual = "item,amount\nHosting,120\nStorage,50\nGPU,200\n"
    rep = pro_workspace.compare_csv_tables(base, actual, key_col="item", value_col="amount")
    assert rep["total_baseline"] == 175.0
    assert rep["total_actual"] == 370.0
    assert rep["total_delta"] == 195.0
    assert rep["added_count"] == 1
    assert rep["removed_count"] == 1
    assert "# Variance Report" in rep["markdown_report"]

    diff = pro_workspace.compare_revisions("line 1\nline 2\n", "line 1\nline 2 revised\nline 3\n")
    assert diff["changed"] is True
    assert diff["lines_added"] == 2
    assert diff["lines_removed"] == 1
    assert "+line 3" in diff["unified_diff"]


def test_uat_tracker_cases_and_fail_closed_finance_domain(tmp_path, monkeypatch):
    monkeypatch.setattr(memory, "DB_PATH", tmp_path / "mem.db")
    mem = memory.Memory()

    u = pro_workspace.uat_add(mem, req_id="REQ-01", title="Loopback auth", status="passed", evidence="Verified 403 without key")
    assert u["status"] == "passed"
    pro_workspace.uat_update(mem, u["id"], status="passed", evidence="Confirmed in Chrome")
    assert len(pro_workspace.uat_list(mem)) == 1

    c = pro_workspace.case_create(mem, title="Vendor audit", category="compliance", note="Token sk-1234567890abcdef12345678")
    assert "sk-1234567890" not in c["notes"][0]["text"]
    assert len(pro_workspace.case_list(mem)) == 1

    # Finance domain MUST fail closed by default
    cfg = dict(config.DEFAULTS)
    txns = [{"category": "Salary", "amount": 5000}, {"category": "Rent", "amount": -1800}]
    with pytest.raises(PermissionError, match="disabled by default"):
        pro_workspace.finance_budget_summary(cfg, txns)

    # Explicitly enabling finance domain unlocks read-only local summary
    cfg["domain_permissions"] = {"finance": True}
    fin = pro_workspace.finance_budget_summary(cfg, txns)
    assert fin["total_income"] == 5000.0
    assert fin["total_expenses"] == 1800.0
    assert fin["net_cashflow"] == 3200.0

    # Lockdown blocks even when finance domain is enabled
    cfg["lockdown"] = True
    with pytest.raises(PermissionError, match="Lockdown"):
        pro_workspace.finance_budget_summary(cfg, txns)
