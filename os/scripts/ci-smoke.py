#!/usr/bin/env python3
"""Headless checks for Huginn OS's apps and shell (GitHub Actions, or by hand): every app and the shell open in
their demo mode with no screen (QT_QPA_PLATFORM=offscreen), draw a picture of themselves, and say nothing about
broken QML or Python. The theme generator runs, and the settings portal says what it would tell apps.

    python3 scripts/ci-smoke.py [app …]      pictures go to $SMOKE_OUT (default /tmp/huginn-smoke)
"""
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = Path(os.environ.get("SMOKE_OUT", "/tmp/huginn-smoke"))
APPS = """archives authenticator backup books calculator calendar camera characters clips clock code contacts disks documents
easel feeds files fonts games help installer machines mail maps messages money monitor music notes passwords phone photos
podcasts print privacy recorder reminders scan screenshot settings sharing sheets shortcuts slides store tempo translate
video weather welcome writer""".split()
PROBLEM = re.compile(r"\.qml:\d+|(qml|QML).*(Error|error)|Traceback|ReferenceError|TypeError|is not a type|Cannot assign|No module")


def run(name: str, cmd: list, picture: Path) -> bool:
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", HOME=str(OUT / "home"), XDG_RUNTIME_DIR=str(OUT / "run"))
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=120, env=env, cwd=cmd[1].rsplit("/", 1)[0])
        out, code = p.stdout + p.stderr, p.returncode
    except subprocess.TimeoutExpired:
        out, code = "timed out", -1
    bad = [line for line in out.splitlines() if PROBLEM.search(line) and "DeprecationWarning" not in line]
    good = code == 0 and picture.exists() and picture.stat().st_size > 2000 and not bad
    print(f"{'ok  ' if good else 'FAIL'} {name:14} exit {code}{'' if picture.exists() else ', no picture'}", flush=True)
    for line in (bad or ([] if good else out.splitlines()[-8:]))[:8]:
        print("       ", line[:240], flush=True)
    return good


def main() -> int:
    for d in ("home", "run", "shots"):
        (OUT / d).mkdir(parents=True, exist_ok=True)
    os.chmod(OUT / "run", 0o700)
    results = []
    gen = subprocess.run([sys.executable, str(ROOT / "tokens/gen_theme.py"), str(ROOT / "tokens/tokens.json"), str(OUT / "theme")],
                         capture_output=True, text=True)
    print(f"{'ok  ' if gen.returncode == 0 else 'FAIL'} {'theme':14} {gen.stdout.strip().splitlines()[-1] if gen.stdout.strip() else gen.stderr[-300:]}")
    results.append(gen.returncode == 0)
    portal = subprocess.run([sys.executable, str(ROOT / "apps/huginn_portal_settings.py"), "--print"], capture_output=True, text=True,
                            env=dict(os.environ, HOME=str(OUT / "home")))
    told = "org.freedesktop.appearance color-scheme" in portal.stdout
    print(f"{'ok  ' if told else 'FAIL'} {'settings':14} {'the portal answers' if told else portal.stderr[-300:]}")
    results.append(told)
    shot = OUT / "shots" / "shell.png"
    results.append(run("shell", [sys.executable, str(ROOT / "shell/huginn_shell.py"), "--preview", "--shot", str(shot)], shot))
    for key in sys.argv[1:] or APPS:
        shot = OUT / "shots" / f"{key}.png"
        results.append(run(key, [sys.executable, str(ROOT / "apps/huginn_app.py"), key, "--demo", "--shot", str(shot)], shot))
    print(f"\n{sum(results)} of {len(results)} fine")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
