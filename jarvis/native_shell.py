"""Optional Native Desktop Shell (pywebview), Compact Floating Mode & Opt-In Start-at-Login.

Preserves Jarvis's default browser HUD while enabling:
- Native desktop window (WebView2 on Windows, WKWebView on macOS) when pywebview is installed.
- Compact always-on-top floating assistant window mode.
- Strictly opt-in Windows HKCU Run start-at-login (disabled by default, never touches HKLM).
"""
import importlib.util
import os
import sys
from pathlib import Path

from . import secure

RUN_KEY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_VALUE_NAME = "JarvisAssistant"


def pywebview_available() -> bool:
    return importlib.util.find_spec("webview") is not None


def shell_capabilities() -> dict:
    return {
        "os": os.name,
        "pywebview_available": pywebview_available(),
        "global_hotkeys_supported": os.name == "nt",
        "start_at_login_supported": os.name == "nt",
        "start_at_login_enabled": start_at_login_status() if os.name == "nt" else False,
        "default_mode": "browser_hud",
    }


def start_at_login_status() -> bool:
    if os.name != "nt":
        return False
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY_PATH, 0, winreg.KEY_READ) as key:
            val, _ = winreg.QueryValueEx(key, RUN_VALUE_NAME)
            return bool(val)
    except OSError:
        return False


def set_start_at_login(enabled: bool, *, python_exe: str | None = None) -> dict:
    """Enable or disable opt-in HKCU start-at-login for the current user."""
    if os.name != "nt":
        raise ValueError("Start-at-login registry integration is Windows-only.")
    import winreg
    exe = Path(python_exe or sys.executable)
    if exe.name.lower() == "python.exe" and exe.with_name("pythonw.exe").exists():
        exe = exe.with_name("pythonw.exe")
    cmd = f'"{exe}" -m jarvis'
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY_PATH, 0, winreg.KEY_SET_VALUE) as key:
        if enabled:
            winreg.SetValueEx(key, RUN_VALUE_NAME, 0, winreg.REG_SZ, cmd)
        else:
            try:
                winreg.DeleteValue(key, RUN_VALUE_NAME)
            except FileNotFoundError:
                pass
    secure.audit("start_at_login_changed", {"enabled": bool(enabled)})
    return {"enabled": bool(enabled), "command": cmd if enabled else ""}


def launch_native_window(url: str, *, floating: bool = False, title: str = "J.A.R.V.I.S.") -> bool:
    """Open the loopback HUD inside a native WebView window if pywebview is installed.

    Returns True if a native window was started, or False if callers should fall back to browser.
    """
    if not url.startswith("http://127.0.0.1:"):
        raise ValueError("Native shell only loads numeric loopback HUD URLs.")
    if not pywebview_available():
        return False
    import webview
    width, height = (420, 620) if floating else (1360, 860)
    webview.create_window(
        title,
        url,
        width=width,
        height=height,
        on_top=bool(floating),
        resizable=True,
    )
    webview.start()
    return True
