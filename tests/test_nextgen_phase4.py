"""Phase 4 Next-Generation tests:
- Global Hotkey Manager & Emergency Kill Switch (hotkeys.py)
- Native Desktop Shell loopback guard, capabilities & opt-in start-at-login (native_shell.py)
"""
import pytest

from jarvis import hotkeys, native_shell


def test_hotkey_manager_kill_switch_and_summon():
    events = []
    mgr = hotkeys.GlobalHotkeyManager(
        on_summon=lambda: events.append("summon"),
        on_kill_switch=lambda: events.append("kill"),
    )
    st = mgr.status()
    assert st["bindings"]["summon"] == "Ctrl+Alt+J"
    assert st["bindings"]["kill_switch"] == "Ctrl+Alt+Backspace"
    assert mgr.trigger_summon()["action"] == "summon"
    assert mgr.trigger_kill_switch()["action"] == "kill_switch"
    assert events == ["summon", "kill"]


def test_native_shell_loopback_guard_and_capabilities():
    caps = native_shell.shell_capabilities()
    assert "pywebview_available" in caps
    assert caps["default_mode"] == "browser_hud"

    # Non-loopback URLs MUST be refused by native shell
    with pytest.raises(ValueError, match="loopback"):
        native_shell.launch_native_window("https://evil.example.com")
    with pytest.raises(ValueError, match="loopback"):
        native_shell.launch_native_window("http://localhost:8765")
