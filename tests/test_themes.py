import re
from pathlib import Path

import pytest

from jarvis import config

UI = (Path(__file__).parents[1] / "jarvis" / "ui.html").read_text(encoding="utf-8")


def _hex(value):
    value = value.strip().lstrip("#")
    if len(value) == 3:
        value = "".join(c * 2 for c in value)
    return tuple(int(value[i:i + 2], 16) / 255 for i in (0, 2, 4))


def _luminance(rgb):
    channel = lambda c: c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = map(channel, rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a, b):
    light, dark = sorted((_luminance(_hex(a)), _luminance(_hex(b))), reverse=True)
    return (light + 0.05) / (dark + 0.05)


def theme_vars(theme):
    found = {}
    root = re.search(r":root \{(.*?)\}", UI, re.S)[1]
    found.update(re.findall(r"--(\w+):(#[0-9a-fA-F]{3,6})", root))
    if theme != "hud":
        base = re.search(r"body\[data-theme=simple\], body\[data-theme=light\].*?\{(.*?)\}", UI, re.S)[1]
        found.update(re.findall(r"--(\w+):(#[0-9a-fA-F]{3,6})", base))
        own = re.search(rf"body\[data-theme={theme}\] \{{(.*?)\}}", UI, re.S)
        if own:
            found.update(re.findall(r"--(\w+):(#[0-9a-fA-F]{3,6})", own[1]))
    return found


@pytest.mark.parametrize("theme", config.THEMES)
def test_every_theme_has_readable_text(theme):
    colours = theme_vars(theme)
    assert f'<option value="{theme}">' in UI
    backgrounds = [colours["bg"]] + ([colours["panel"]] if "panel" in colours else [])
    for background in backgrounds:
        for name in ("text", "dim", "cyan2", "warn"):
            ratio = contrast(colours[name], background)
            minimum = 7 if theme == "contrast" and name == "text" else 4.5
            assert ratio >= minimum, f"{theme} {name} on {background}: {ratio:.2f}"


def test_theme_preference_is_saved(isolated_app):
    cfg, _, _, _ = isolated_app
    cfg["theme"] = "paper"
    config.save(cfg)
    assert config.load()["theme"] == "paper"
    cfg["theme"] = "neon"
    config.save(cfg)
    assert config.load()["theme"] == "hud"


def test_hud_does_not_replace_browser_dialogs():
    # A global function named confirm made every "Are you sure?" prompt answer yes silently.
    for name in ("confirm", "alert", "prompt", "open", "close", "print", "stop", "find"):
        assert not re.search(rf"^\s*(?:async\s+)?function\s+{name}\s*\(", UI, re.M), name
        assert not re.search(rf"^(?:const|let|var)\s+{name}\s*=", UI, re.M), name
