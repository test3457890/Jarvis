"""Denylist tests: ensure no skill can modify system/security settings or expose a general shell."""
import inspect
import re

from jarvis import skills

FORBIDDEN_PATTERNS = [
    ("registry", re.compile(r"\b(winreg|reg\.exe|HKLM|HKCU|HKEY_|Set-ItemProperty|New-ItemProperty|Remove-ItemProperty)\b", re.I)),
    ("group_policy", re.compile(r"\b(gpupdate|gpedit|secedit|lgpo)\b", re.I)),
    ("firewall", re.compile(r"\b(advfirewall|New-NetFirewallRule|Set-NetFirewallProfile|netsh\s+firewall)\b", re.I)),
    ("defender", re.compile(r"\b(Set-MpPreference|Add-MpPreference|MpCmdRun|Remove-MpPreference)\b", re.I)),
    ("uac", re.compile(r"\b(EnableLUA|ConsentPromptBehavior\w*)\b", re.I)),
    ("services", re.compile(r"\b(sc\.exe|New-Service|Set-Service|Stop-Service|Start-Service)\b", re.I)),
    ("scheduled_tasks", re.compile(r"\b(schtasks|Register-ScheduledTask|New-ScheduledTask)\b", re.I)),
    ("startup_entries", re.compile(r"(CurrentVersion\\\\Run|CurrentVersion/Run|Shell:Startup)", re.I)),
    ("accounts_permissions", re.compile(r"\b(net\s+user|net\s+localgroup|icacls|cacls|takeown|New-LocalUser|Add-LocalGroupMember)\b", re.I)),
]

FORBIDDEN_SKILL_NAMES = {
    "run_shell", "shell", "powershell", "run_powershell", "exec_command", "cmd", "bash",
    "edit_registry", "set_firewall", "disable_defender", "manage_service", "schedule_task",
}


def test_no_system_or_security_modification_skills():
    for name, meta in skills.SKILLS.items():
        assert name not in FORBIDDEN_SKILL_NAMES, f"Forbidden shell/system skill registered: {name}"
        src = inspect.getsource(meta["fn"])
        text = f"{name}\n{meta['description']}\n{src}"
        for category, pat in FORBIDDEN_PATTERNS:
            assert not pat.search(text), f"Skill '{name}' matched forbidden {category} pattern: {pat.pattern}"


def test_only_run_code_executes_code_and_is_risky():
    assert "run_code" in skills.SKILLS
    assert skills.SKILLS["run_code"]["risky"] is True
