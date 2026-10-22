"""Quality targets (docs/QUALITY.md), for milestone M6

A real test, or a test that runs a scripted check (an audit, a load test, a Lighthouse run).
Placeholders from GigaLab: each fails until it is replaced by a real test in its milestone. Never delete one to make it pass.
"""
import pytest


def test_security_validate():
    pytest.fail("Not written yet: Security: Every input is validated on the server")


def test_security_secrets():
    pytest.fail("Not written yet: Security: Secrets live only in environment variables, never in code, logs or the browser")


def test_security_https():
    pytest.fail("Not written yet: Security: HTTPS only, secure cookies and CSRF protection")


def test_security_ratelimit():
    pytest.fail("Not written yet: Security: Rate limits on sign-in and on every public route")


def test_security_deps():
    pytest.fail("Not written yet: Security: A dependency audit runs on every build (pip-audit or npm audit)")


def test_security_owasp():
    pytest.fail("Not written yet: Security: Reviewed against the OWASP Top 10 before launch")


def test_security_injection():
    pytest.fail("Not written yet: Security: Prompt-injection tests: text from customers never changes the rules")


def test_reliability_errors():
    pytest.fail("Not written yet: Reliability: Every error gives a clear message, and nothing is left half-saved")


def test_reliability_timeouts():
    pytest.fail("Not written yet: Reliability: Calls to outside services time out and retry with back-off")


def test_reliability_backups():
    pytest.fail("Not written yet: Reliability: Daily backups, restored once to prove they work")


def test_reliability_idempotent():
    pytest.fail("Not written yet: Reliability: Payments and actions are idempotent: a retry never runs them twice")


def test_reliability_gate():
    pytest.fail("Not written yet: Reliability: The AI release gate passes before every release")


def test_performance_page():
    pytest.fail("Not written yet: Performance: p95 page load under 2 seconds on a phone over 4G")


def test_performance_api():
    pytest.fail("Not written yet: Performance: p95 API response under 500 ms, not counting AI calls")


def test_performance_indexes():
    pytest.fail("Not written yet: Performance: A database index for every list and search")


def test_performance_ai():
    pytest.fail("Not written yet: Performance: An AI reply starts within 5 seconds, streamed or with progress shown")
