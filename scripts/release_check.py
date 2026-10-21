"""Pre-release gate for Tariff Tracker. Run before every `gh release create`.

    python scripts/release_check.py                 # everything
    python scripts/release_check.py --skip-ha       # no WSL available
    python scripts/release_check.py --live X:/custom_components/tariff_tracker

Checks, in order: repo state, version/tag/changelog agreement, manifest and
translation files, a pyflakes-level lint, the engine tests, and the Home
Assistant tests. The HA tests need pytest-homeassistant-custom-component,
which doesn't install on Windows, so they run in WSL from the venv built by
scripts/setup_wsl_test_env.sh. `--live` additionally compares the files
deployed on a Home Assistant install against the repo.

Exits non-zero if anything FAILs. WARNs are worth reading but don't block.
"""
from __future__ import annotations

import argparse
import filecmp
import json
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
COMPONENT = ROOT / "custom_components" / "tariff_tracker"
WSL_VENV = "~/.venvs/tariff_tracker"

results: list[tuple[str, str, str]] = []


def record(status: str, name: str, detail: str = "") -> None:
    results.append((status, name, detail))
    print(f"[{status:4}] {name}" + (f" - {detail}" if detail else ""), flush=True)


def run(cmd: list[str], cwd: Path = ROOT) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace")


def git(*args: str) -> str:
    return run(["git", *args]).stdout.rstrip()


def version_tuple(v: str) -> tuple[int, ...]:
    return tuple(int(p) for p in v.split("."))


# ---- repo state ----------------------------------------------------------


def check_repo() -> None:
    branch = git("rev-parse", "--abbrev-ref", "HEAD")
    if branch == "main":
        record("PASS", "branch", "main")
    else:
        record("WARN", "branch", f"on '{branch}' - HACS ships from the tag; merge to main first")

    tracked = [l for l in git("status", "--porcelain").splitlines() if not l.startswith("??")]
    if tracked:
        record("FAIL", "working tree", f"{len(tracked)} uncommitted change(s): " + ", ".join(l[3:] for l in tracked[:5]))
    else:
        record("PASS", "working tree", "clean")


# ---- version, tag, changelog ------------------------------------------------


def check_version() -> None:
    manifest = json.loads((COMPONENT / "manifest.json").read_text(encoding="utf-8"))
    version = manifest.get("version", "")
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        record("FAIL", "manifest version", f"'{version}' is not X.Y.Z")
        return

    # Releases are tagged on GitHub by `gh release create`, so the local
    # clone can lag; ask the remote too.
    names = set(git("tag", "-l", "v*").split())
    names |= {line.rsplit("/", 1)[-1] for line in git("ls-remote", "--tags", "origin").splitlines()}
    tags = [t[1:] for t in names if re.fullmatch(r"v\d+\.\d+\.\d+", t)]
    if version in tags:
        record("FAIL", "version tag", f"v{version} already exists - bump manifest.json")
    else:
        latest = max(tags, key=version_tuple) if tags else None
        if latest and version_tuple(version) <= version_tuple(latest):
            record("FAIL", "version tag", f"{version} is not above latest tag v{latest}")
        else:
            record("PASS", "version tag", f"{version} (latest tag v{latest})")

    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    m = re.search(r"^## \[(\d+\.\d+\.\d+)\] - (\d{4}-\d{2}-\d{2})", changelog, re.M)
    if not m:
        record("FAIL", "changelog", "no '## [X.Y.Z] - YYYY-MM-DD' entry found")
        return
    top_version, top_date = m.groups()
    if top_version != version:
        record("FAIL", "changelog", f"top entry is {top_version}, manifest says {version}")
    elif top_date != date.today().isoformat():
        record("WARN", "changelog", f"{version} dated {top_date}, today is {date.today()} - re-date it?")
    else:
        record("PASS", "changelog", f"{version} - {top_date}")

    next_entry = changelog.find("\n## [", m.end())
    section = changelog[m.start():next_entry if next_entry != -1 else None]
    for ref in sorted(set(re.findall(r"\[#(\d+)\]", section))):
        if not re.search(rf"^\[#{ref}\]: ", changelog, re.M):
            record("FAIL", "changelog", f"[#{ref}] used but has no link definition")


# ---- manifest, hacs, translations ------------------------------------------------


def check_manifest() -> None:
    try:
        manifest = json.loads((COMPONENT / "manifest.json").read_text(encoding="utf-8"))
        json.loads((ROOT / "hacs.json").read_text(encoding="utf-8"))
    except json.JSONDecodeError as err:
        record("FAIL", "manifest/hacs json", str(err))
        return

    keys = list(manifest)
    # hassfest: domain, name, then the rest alphabetically.
    expected = ["domain", "name"] + sorted(k for k in keys if k not in ("domain", "name"))
    if keys != expected:
        record("FAIL", "manifest key order", f"hassfest wants {expected}")
    else:
        record("PASS", "manifest key order")

    missing = [k for k in ("codeowners", "config_flow", "documentation", "iot_class", "issue_tracker", "version") if k not in manifest]
    if missing:
        record("FAIL", "manifest keys", "missing " + ", ".join(missing))

    if not (COMPONENT / "brand").is_dir():
        record("FAIL", "brand icon", "custom_components/tariff_tracker/brand missing - HACS brands check")


def check_translations() -> None:
    try:
        strings = json.loads((COMPONENT / "strings.json").read_text(encoding="utf-8"))
        en = json.loads((COMPONENT / "translations" / "en.json").read_text(encoding="utf-8"))
    except json.JSONDecodeError as err:
        record("FAIL", "translations json", str(err))
        return
    if strings != en:
        record("FAIL", "translations", "strings.json and translations/en.json differ")
        return

    problems = []
    options_src = (COMPONENT / "options_flow.py").read_text(encoding="utf-8")
    config_src = (COMPONENT / "config_flow.py").read_text(encoding="utf-8")

    for key in re.findall(r'translation_key="(\w+)"', options_src + config_src):
        if key not in strings.get("selector", {}):
            problems.append(f"selector '{key}' has no strings")

    for section, src in (("options", options_src), ("config", config_src)):
        steps = strings.get(section, {}).get("step", {})
        for step in set(re.findall(r'step_id="(\w+)"', src)):
            if step not in steps:
                problems.append(f"{section} step '{step}' has no strings")

    menu = re.search(r"menu_options=\[(.*?)\]", options_src, re.S)
    if menu:
        labels = strings["options"]["step"]["init"].get("menu_options", {})
        for option in re.findall(r'"(\w+)"', menu.group(1)):
            if option not in labels:
                problems.append(f"menu option '{option}' has no label")

    if problems:
        record("FAIL", "translations", "; ".join(problems))
    else:
        record("PASS", "translations", "strings.json == en.json, selectors/steps/menu covered")


# ---- code ------------------------------------------------------------------


def wsl_available() -> bool:
    try:
        return run(["wsl", "-e", "true"]).returncode == 0
    except FileNotFoundError:
        return False


def wsl_path(path: Path) -> str:
    return run(["wsl", "-e", "wslpath", "-a", str(path).replace("\\", "/")]).stdout.strip()


def wsl(command: str) -> subprocess.CompletedProcess:
    return run(["wsl", "-e", "bash", "-lc", f"cd '{wsl_path(ROOT)}' && {command}"])


def check_compile() -> None:
    proc = run([sys.executable, "-m", "py_compile", *map(str, COMPONENT.glob("*.py"))])
    if proc.returncode:
        record("FAIL", "py_compile", proc.stderr.strip())
    else:
        record("PASS", "py_compile")


def check_lint(use_wsl: bool) -> None:
    # F = pyflakes (undefined names, unused imports), E9 = syntax errors.
    # An undefined name is exactly what crashed every plan's setup in v0.3.0.
    cmd = "ruff check --select F,E9 --no-cache --output-format concise custom_components tests scripts"
    if use_wsl:
        proc = wsl(f"{WSL_VENV}/bin/{cmd}")
    else:
        proc = run([sys.executable, "-m", *cmd.split()])
        if "No module named ruff" in proc.stderr:
            record("WARN", "lint", "ruff not installed here; run with WSL or `pip install ruff`")
            return
    if proc.returncode:
        record("FAIL", "lint", "\n         " + "\n         ".join(proc.stdout.strip().splitlines()))
    else:
        record("PASS", "lint", "ruff F,E9 clean")


def summarise_pytest(proc: subprocess.CompletedProcess) -> str:
    lines = [l for l in proc.stdout.splitlines() if re.search(r"\d+ (passed|failed|error)", l)]
    return lines[-1].strip("= ") if lines else proc.stdout.strip()[-300:]


def check_engine_tests() -> None:
    proc = run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--ignore=tests/ha"])
    status = "PASS" if proc.returncode == 0 else "FAIL"
    record(status, "engine tests (local)", summarise_pytest(proc))
    if status == "FAIL":
        print(proc.stdout[-3000:])


def check_ha_tests() -> None:
    proc = wsl(f"{WSL_VENV}/bin/python -m pytest -q -p no:cacheprovider --show-capture=no tests")
    if "No such file" in proc.stderr or "No such file" in proc.stdout[:200]:
        record("FAIL", "HA tests (WSL)", f"no venv at {WSL_VENV} - run scripts/setup_wsl_test_env.sh in WSL")
        return
    status = "PASS" if proc.returncode == 0 else "FAIL"
    record(status, "HA tests (WSL)", summarise_pytest(proc))
    if status == "FAIL":
        failures = [l for l in proc.stdout.splitlines() if l.startswith(("FAILED", "ERROR", "E "))]
        print("\n".join(failures[:40]))


def check_live(live: Path) -> None:
    if not live.is_dir():
        record("FAIL", "live install", f"{live} not reachable")
        return
    files = [p.relative_to(COMPONENT) for p in COMPONENT.rglob("*") if p.is_file() and "__pycache__" not in p.parts]
    def same(f: Path) -> bool:
        # Line endings only: a checkout on Windows rewrites them.
        if not (live / f).is_file():
            return False
        if filecmp.cmp(COMPONENT / f, live / f, shallow=False):
            return True
        ours = (COMPONENT / f).read_bytes().replace(b"\r\n", b"\n")
        theirs = (live / f).read_bytes().replace(b"\r\n", b"\n")
        return ours == theirs

    differ = [str(f) for f in files if not same(f)]
    if differ:
        record("WARN", "live install", f"{len(differ)} file(s) differ from repo: " + ", ".join(differ[:6]))
    else:
        record("PASS", "live install", f"matches repo ({len(files)} files)")


# ---- main ------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--skip-ha", action="store_true", help="skip the WSL Home Assistant tests (WARN instead of running)")
    parser.add_argument("--live", type=Path, help="deployed custom_components/tariff_tracker to compare against the repo")
    args = parser.parse_args()

    check_repo()
    check_version()
    check_manifest()
    check_translations()
    check_compile()

    use_wsl = not args.skip_ha and wsl_available()
    check_lint(use_wsl)
    check_engine_tests()
    if args.skip_ha:
        record("WARN", "HA tests (WSL)", "skipped by --skip-ha - runtime.py, flows and sensors untested")
    elif not use_wsl:
        record("FAIL", "HA tests (WSL)", "WSL not available; pass --skip-ha to release without them")
    else:
        check_ha_tests()

    if args.live:
        check_live(args.live)

    fails = sum(1 for s, _, _ in results if s == "FAIL")
    warns = sum(1 for s, _, _ in results if s == "WARN")
    print()
    if fails:
        print(f"NOT READY: {fails} failure(s), {warns} warning(s).")
        return 1
    print(f"READY to release ({warns} warning(s)).")
    print("Not covered here: hassfest and HACS validation run in GitHub Actions on push to main.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
