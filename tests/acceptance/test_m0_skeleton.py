"""Acceptance tests: M0 · Skeleton (docs/BUILD_PLAN.md, blueprint.json milestones[M0]).

The build pack lists four criteria:

1. The health route returns ok
2. The test command passes
3. .env is in .gitignore
4. blueprint.json is unchanged

Plus the milestone goal — "reads its settings from .env" — which no criterion covers but
which the "Done when" line requires, so it gets a test of its own below.

On criterion 2: the 40 placeholder tests in test_f1..f6 and test_quality.py are
``pytest.fail("Not written yet: ...")`` until their own milestones (M3 for F1-F6, M6 for
the quality targets), so ``pytest -q`` cannot exit 0 at M0. This test runs the real
command and requires that every failure is such a placeholder. Any failure that is not a
placeholder — a real bug, a broken M0 test, a collection error — fails this test. It goes
green by itself once those files are replaced with real tests; nothing here needs editing.
"""

from __future__ import annotations

import fnmatch
import hashlib
import json
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GITIGNORE = ROOT / ".gitignore"
BLUEPRINT = ROOT / "blueprint.json"

# Acceptance files that still hold GigaLab placeholders. Each one fails with
# "Not written yet:" until its own milestone replaces it.
PLACEHOLDER_FILES = frozenset(
    {
        "test_f1_user_authentication_tenant_management.py",
        "test_f2_trade_data_import_ingestion.py",
        "test_f3_quantitative_performance_analytics_engin.py",
        "test_f4_rule_based_behavioral_mistake_detector.py",
        "test_f5_ai_trading_diagnosis_recovery_report.py",
        "test_f6_interactive_performance_dashboard.py",
        "test_quality.py",
    }
)
PLACEHOLDER_PREFIX = "Not written yet:"

# sha256 of blueprint.json as shipped in the confirmed build pack (2026-10-22).
# If the human downloads a new pack, this line is meant to be updated with it.
BLUEPRINT_SHA256 = "629d9f3e2af633f89137d3112ec763d7db1931130bedb519d3ee74d34a636788"


def test_health_route_returns_ok():
    """Criterion 1: the app starts and GET /health answers ok."""
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_test_command_passes(tmp_path):
    """Criterion 2: `pytest -q` passes, apart from future-milestone placeholders."""
    report = tmp_path / "report.xml"
    this_test = f"{Path(__file__).resolve().relative_to(ROOT).as_posix()}::test_test_command_passes"
    command = [
        sys.executable,
        "-m",
        "pytest",
        "-q",
        # Deselect only this test: running it inside itself would recurse forever.
        "--deselect",
        this_test,
        f"--junitxml={report}",
    ]

    completed = subprocess.run(
        command, cwd=ROOT, capture_output=True, text=True, timeout=600
    )
    if not report.is_file():
        raise AssertionError(
            "`pytest -q` produced no report, so it did not run.\n"
            f"exit code: {completed.returncode}\n"
            f"stdout:\n{completed.stdout}\n"
            f"stderr:\n{completed.stderr}"
        )

    collected = 0
    passed = 0
    failures: list[tuple[str, str, str]] = []
    for case in ET.parse(report).getroot().iter("testcase"):
        collected += 1
        node = case.find("failure")
        if node is None:
            node = case.find("error")
        if node is not None:
            failures.append(
                (
                    _report_file_name(case),
                    case.get("name") or "?",
                    (node.get("message") or "").strip(),
                )
            )
        elif case.find("skipped") is None:
            passed += 1

    assert collected > 0, "`pytest -q` collected no tests at all"

    unexpected = [
        f"{file_name}::{name} — {message.splitlines()[0] if message else 'no message'}"
        for file_name, name, message in failures
        if not (_is_placeholder(message) and file_name in PLACEHOLDER_FILES)
    ]
    assert not unexpected, (
        "`pytest -q` failed on something that is not a future-milestone placeholder:\n  "
        + "\n  ".join(unexpected)
        + f"\n\noutput:\n{completed.stdout[-4000:]}"
    )

    if not failures:
        assert completed.returncode == 0, (
            f"no test failed, but `pytest -q` exited {completed.returncode}:\n"
            f"{completed.stdout[-4000:]}"
        )

    # The other M0 tests must have passed in that run (guards against collecting nothing
    # or skipping everything and calling it success).
    assert passed >= 4, (
        f"only {passed} test(s) passed in `pytest -q`; M0 needs at least 4:\n"
        f"{completed.stdout[-4000:]}"
    )


def test_env_is_gitignored():
    """Criterion 3: .env is ignored by git, .env.example is not."""
    assert GITIGNORE.is_file(), ".gitignore is missing"
    lines = GITIGNORE.read_text(encoding="utf-8").splitlines()

    assert _gitignore_ignores(".env", lines) is True, ".env is not ignored"
    assert _gitignore_ignores(".env.local", lines) is True, ".env.local is not ignored"
    assert (
        _gitignore_ignores(".env.example", lines) is False
    ), ".env.example must stay committable, it holds no secret"

    # Cross-check against git itself once the repository exists.
    git = shutil.which("git")
    if git and (ROOT / ".git").exists():
        ignored = subprocess.run(
            [git, "check-ignore", "-q", ".env"], cwd=ROOT, capture_output=True
        )
        assert ignored.returncode == 0, "git does not treat .env as ignored"
        kept = subprocess.run(
            [git, "check-ignore", "-q", ".env.example"], cwd=ROOT, capture_output=True
        )
        assert kept.returncode != 0, "git ignores .env.example, which must be committed"


def test_blueprint_json_unchanged():
    """Criterion 4: blueprint.json is byte-for-byte the confirmed pack, and still says so."""
    raw = BLUEPRINT.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    assert digest == BLUEPRINT_SHA256, (
        "blueprint.json has changed since the pack was downloaded "
        f"(expected {BLUEPRINT_SHA256}, got {digest}). "
        "Only the human changes the blueprint, in GigaLab."
    )

    blueprint = json.loads(raw.decode("utf-8"))
    assert blueprint["status"] == "confirmed"

    stack = blueprint["stack"]
    assert stack["confirmed"] is True
    assert stack["backend"]["value"] == "fastapi"
    assert stack["database"]["value"] == "postgres"
    assert stack["frontend"]["value"] == "html"
    # The app must answer to the commands the pack promises.
    assert stack["commands"] == {
        "install": "pip install -r requirements.txt",
        "test": "pytest -q",
        "run": "uvicorn app.main:app --reload",
    }


def test_settings_are_read_from_env_file(tmp_path, monkeypatch):
    """The M0 goal: settings come from .env, and a secret never shows up in a repr."""
    from app.config import Settings

    env_file = tmp_path / "settings.env"
    env_file.write_text(
        "APP_SECRET=secret-from-the-file\n"
        "DATABASE_URL=postgresql://trader:pw@localhost:5432/traderevive_ai\n",
        encoding="utf-8",
    )
    for name in ("APP_SECRET", "DATABASE_URL"):
        monkeypatch.delenv(name, raising=False)

    settings = Settings(_env_file=str(env_file))

    assert settings.app_secret.get_secret_value() == "secret-from-the-file"
    assert settings.database_url == "postgresql://trader:pw@localhost:5432/traderevive_ai"

    # AGENTS.md: never write a key in a log. A repr is what ends up in a log line.
    assert "secret-from-the-file" not in repr(settings)
    assert "secret-from-the-file" not in str(settings)

    # And by default the app looks for ".env" in the project root.
    assert Settings.model_config["env_file"] == ".env"


def _report_file_name(case: ET.Element) -> str:
    """The acceptance file a junit testcase came from.

    pytest's junit report carries no ``file`` attribute here, only a dotted
    ``classname`` such as ``tests.acceptance.test_quality``.
    """
    classname = case.get("classname") or ""
    if classname:
        return f"{classname.rsplit('.', 1)[-1]}.py"
    return Path(case.get("file") or "").name


def _is_placeholder(message: str) -> bool:
    """True for the pack's not-yet-written placeholders, however pytest labels them."""
    return message.removeprefix("Failed: ").startswith(PLACEHOLDER_PREFIX)


def _gitignore_ignores(name: str, lines: list[str]) -> bool | None:
    """Whether a root-level file is ignored, last matching pattern winning, as git does."""
    decision: bool | None = None
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        negated = line.startswith("!")
        pattern = line[1:] if negated else line
        if pattern.startswith("/"):
            pattern = pattern[1:]
        pattern = pattern.rstrip("/")
        if "/" in pattern:
            continue  # not a root-level file pattern
        if fnmatch.fnmatch(name, pattern):
            decision = not negated
    return decision
