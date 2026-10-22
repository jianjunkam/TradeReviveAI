"""Acceptance tests: Rule-Based Behavioral Mistake Detector (use case UC4 in docs/REQUIREMENTS.md)

Used by: Trader (Account Owner). Scans trade history with deterministic heuristics to flag revenge trading, oversized positions, and holding losers.
Placeholders from GigaLab: each fails until it is replaced by a real test in its milestone. Never delete one to make it pass.
"""
import pytest


def test_ac4_1():
    pytest.fail("Not written yet: Given a user closes a losing trade and opens a new trade in the same or correlated symbol within 10 minutes at $1.5\\times$ or greater position size, when the detector runs, then the second trade is tagged with REVENGE_TRADING.")


def test_ac4_2():
    pytest.fail("Not written yet: Given an account with $5,000 balance and a 2% max-risk rule ($100), when a user takes a single trade loss exceeding $250, then the trade is automatically tagged with OVERSIZED_RISK.")


def test_ac4_3():
    pytest.fail("Not written yet: Given an open losing trade held for more than $3\\times$ the user's average winning trade duration while passing predefined stop-loss levels, when closed, then it receives the BAG_HOLDING tag.")


def test_ac4_4():
    pytest.fail("Not written yet: Given a set of 5 trades flagged with REVENGE_TRADING summing to -$450 in net loss, when the mistake breakdown is viewed, then \"Cost of Revenge Trading\" displays -$450.")
