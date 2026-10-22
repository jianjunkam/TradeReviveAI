"""Acceptance tests: AI Trading Diagnosis & Recovery Report (use case UC5 in docs/REQUIREMENTS.md)

Used by: Trader (Account Owner). Analyzes quantitative metrics and mistake tags to generate an actionable, evidence-based diagnostic memo and structured improvement drills.
Placeholders from GigaLab: each fails until it is replaced by a real test in its milestone. Never delete one to make it pass.
"""
import pytest


def test_ac5_1():
    pytest.fail("Not written yet: Given a verified metrics payload containing OVERSIZED_RISK and REVENGE_TRADING tags, when the AI report is triggered, then the generated output returns valid JSON containing primary_weakness, behavioral_analysis, and recovery_drills.")


def test_ac5_2():
    pytest.fail("Not written yet: Given the AI system prompt guardrails, when any report is produced, then the text contains zero ticker recommendations, zero target price forecasts, and includes an explicit financial coaching disclaimer.")


def test_ac5_3():
    pytest.fail("Not written yet: Given a user profile configured in Bahasa Melayu, when the report is requested, then the resulting diagnosis and action drills are returned completely in fluent Bahasa Melayu.")


def test_ac5_4():
    pytest.fail("Not written yet: Given the LLM provider fails or times out, when the user requests a report, then the system returns a graceful error message, does not deduct a user report credit, and allows retrying.")
