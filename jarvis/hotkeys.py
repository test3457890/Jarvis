"""OS-wide Global Hotkeys and Emergency Kill Switch (Windows Win32 RegisterHotKey).

- Ctrl+Alt+J: Summon / focus Jarvis HUD.
- Ctrl+Alt+Backspace: Emergency Kill Switch — immediately stops active replies,
  cancels pending confirmations, and records a kill_switch_triggered audit event.
Gracefully degrades to inactive on non-Windows or headless environments.
"""
import ctypes
import ctypes.wintypes as wt
import os
import threading

from . import secure

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_NOREPEAT = 0x4000
VK_J = 0x4A
VK_BACK = 0x08
WM_HOTKEY = 0x0312
WM_QUIT = 0x0012

HOTKEY_SUMMON = 1
HOTKEY_KILL_SWITCH = 2


class GlobalHotkeyManager:
    """Thread-safe Windows global hotkey listener with clean shutdown."""

    def __init__(self, *, on_summon=None, on_kill_switch=None):
        self._on_summon = on_summon or (lambda: None)
        self._on_kill_switch = on_kill_switch or (lambda: None)
        self._thread: threading.Thread | None = None
        self._thread_id: int | None = None
        self._running = threading.Event()
        self._registered: list[str] = []

    @property
    def supported(self) -> bool:
        return os.name == "nt"

    def trigger_kill_switch(self) -> dict:
        """Execute the emergency kill switch callback and audit the event."""
        secure.audit("kill_switch_triggered", {"source": "hotkey_manager"})
        self._on_kill_switch()
        return {"ok": True, "action": "kill_switch"}

    def trigger_summon(self) -> dict:
        self._on_summon()
        return {"ok": True, "action": "summon"}

    def start(self) -> bool:
        if not self.supported or self._thread is not None:
            return False
        self._running.set()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="jarvis-hotkeys")
        self._thread.start()
        return True

    def stop(self) -> None:
        self._running.clear()
        if self.supported and self._thread_id:
            try:
                ctypes.windll.user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
            except Exception:
                pass
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
            self._thread_id = None
            self._registered.clear()

    def status(self) -> dict:
        return {
            "supported": self.supported,
            "running": self._running.is_set(),
            "registered": list(self._registered),
            "bindings": {
                "summon": "Ctrl+Alt+J",
                "kill_switch": "Ctrl+Alt+Backspace",
            },
        }

    def _loop(self) -> None:
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        self._thread_id = kernel32.GetCurrentThreadId()
        mods = MOD_CONTROL | MOD_ALT | MOD_NOREPEAT
        if user32.RegisterHotKey(None, HOTKEY_SUMMON, mods, VK_J):
            self._registered.append("Ctrl+Alt+J")
        if user32.RegisterHotKey(None, HOTKEY_KILL_SWITCH, mods, VK_BACK):
            self._registered.append("Ctrl+Alt+Backspace")
        msg = wt.MSG()
        try:
            while self._running.is_set():
                ret = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
                if ret <= 0:
                    break
                if msg.message == WM_HOTKEY:
                    if msg.wParam == HOTKEY_SUMMON:
                        self.trigger_summon()
                    elif msg.wParam == HOTKEY_KILL_SWITCH:
                        self.trigger_kill_switch()
        finally:
            user32.UnregisterHotKey(None, HOTKEY_SUMMON)
            user32.UnregisterHotKey(None, HOTKEY_KILL_SWITCH)
            self._registered.clear()
