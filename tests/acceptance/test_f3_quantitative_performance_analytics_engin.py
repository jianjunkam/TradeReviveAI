"""Acceptance tests: Quantitative Performance Analytics Engine (use case UC3 in docs/REQUIREMENTS.md)

Used by: Trader (Account Owner). Calculates deterministic metrics: Net P&L, Win Rate, Profit Factor, Risk-to-Reward (R:R), Max Drawdown, and fee drag.
Placeholders from GigaLab: each fails until it is replaced by a real test in its milestone. Never delete one to make it pass.
"""
import pytest


def test_ac3_1():
    pytest.fail("Not written yet: Given a dataset of 10 closed trades containing 6 wins and 4 losses, when the metrics engine runs, then the reported Win Rate must equal exactly 60.0%.")


def test_ac3_2():
    pytest.fail("Not written yet: Given gross profits of $1,500 and gross losses of $500, when the engine calculates the Profit Factor, then the value must evaluate to exactly 3.00.")


def test_ac3_3():
    pytest.fail("Not written yet: Given a trading history where Gross Loss equals 0, when Profit Factor is calculated, then the system returns Infinity or N/A without throwing a zero-division runtime exception.")


def test_ac3_4():
    pytest.fail("Not written yet: Given an initial balance of $10,000 that drops to a trough of $7,500 before rising to $11,000, when Max Drawdown is calculated, then it records exactly 25.0%.")
