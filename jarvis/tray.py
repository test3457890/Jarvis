"""Zero-dependency Windows System Tray integration via Win32 Shell_NotifyIconW.

Provides a lightweight notification-area icon on Windows with Open HUD, Lockdown,
Emergency Stop, and Quit callbacks. Gracefully degrades to inactive on Linux/macOS.
"""
import ctypes
import ctypes.wintypes as wt
import os
import threading

from . import secure

NIM_ADD = 0x00000000
NIM_DELETE = 0x00000002
NIF_MESSAGE = 0x00000001
NIF_ICON = 0x00000002
NIF_TIP = 0x00000004
WM_USER = 0x0400
WM_TRAY = WM_USER + 20
WM_QUIT = 0x0012
IDI_APPLICATION = 32512


class _NOTIFYICONDATAW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wt.DWORD),
        ("hWnd", wt.HWND),
        ("uID", wt.UINT),
        ("uFlags", wt.UINT),
        ("uCallbackMessage", wt.UINT),
        ("hIcon", wt.HICON),
        ("szTip", wt.WCHAR * 128),
    ]


class SystemTrayIcon:
    """Thread-safe Windows system tray controller with clean shutdown."""

    def __init__(self, *, tooltip: str = "J.A.R.V.I.S. Local Assistant", on_open=None, on_stop=None, on_quit=None):
        self.tooltip = str(tooltip or "J.A.R.V.I.S.")[:120]
        self._on_open = on_open or (lambda: None)
        self._on_stop = on_stop or (lambda: None)
        self._on_quit = on_quit or (lambda: None)
        self._running = threading.Event()
        self._thread: threading.Thread | None = None
        self._hwnd = None

    @property
    def supported(self) -> bool:
        return os.name == "nt"

    def status(self) -> dict:
        return {
            "supported": self.supported,
            "running": self._running.is_set(),
            "tooltip": self.tooltip,
            "actions": ["open_hud", "emergency_stop", "quit"],
        }

    def trigger_action(self, action: str) -> dict:
        act = str(action or "").strip().lower()
        if act == "open_hud":
            self._on_open()
        elif act == "emergency_stop":
            secure.audit("tray_emergency_stop", {"source": "tray"})
            self._on_stop()
        elif act == "quit":
            self._on_quit()
        else:
            raise ValueError(f"Unknown tray action '{action}'.")
        return {"ok": True, "action": act}

    def start(self) -> bool:
        if not self.supported or self._thread is not None:
            return False
        self._running.set()
        self._thread = threading.Thread(target=self._run, daemon=True, name="jarvis-tray")
        self._thread.start()
        return True

    def stop(self) -> None:
        self._running.clear()
        if self.supported and self._hwnd:
            try:
                nid = _NOTIFYICONDATAW()
                nid.cbSize = ctypes.sizeof(_NOTIFYICONDATAW)
                nid.hWnd = self._hwnd
                nid.uID = 1
                ctypes.windll.shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(nid))
                ctypes.windll.user32.PostMessageW(self._hwnd, WM_QUIT, 0, 0)
            except Exception:
                pass
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
            self._hwnd = None

    def _run(self) -> None:
        try:
            user32 = ctypes.windll.user32
            shell32 = ctypes.windll.shell32
            hwnd = user32.CreateWindowExW(0, "STATIC", "JarvisTray", 0, 0, 0, 0, 0, None, None, None, None)
            if not hwnd:
                self._running.clear()
                return
            self._hwnd = hwnd
            nid = _NOTIFYICONDATAW()
            nid.cbSize = ctypes.sizeof(_NOTIFYICONDATAW)
            nid.hWnd = hwnd
            nid.uID = 1
            nid.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP
            nid.uCallbackMessage = WM_TRAY
            nid.hIcon = user32.LoadIconW(None, IDI_APPLICATION)
            nid.szTip = self.tooltip
            shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(nid))
            msg = wt.MSG()
            while self._running.is_set() and user32.GetMessageW(ctypes.byref(msg), hwnd, 0, 0) > 0:
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
        except Exception:
            pass
        finally:
            self._running.clear()
