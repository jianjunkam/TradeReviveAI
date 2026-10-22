"""Acceptance tests: Interactive Performance Dashboard (use case UC6 in docs/REQUIREMENTS.md)

Used by: Trader (Account Owner). Displays equity curves, P&L calendar heatmaps, drawdown charts, and mistake breakdowns across mobile and desktop.
Placeholders from GigaLab: each fails until it is replaced by a real test in its milestone. Never delete one to make it pass.
"""
import pytest


def test_ac6_1():
    pytest.fail("Not written yet: Given an active user with closed trade records, when navigating to /dashboard, then the Net P&L card, Win Rate card, and Equity Curve render within 1.5 seconds.")


def test_ac6_2():
    pytest.fail("Not written yet: Given a mobile screen viewport of 375px width, when the dashboard loads, then all metric cards stack vertically without horizontal overflow or clipped text.")


def test_ac6_3():
    pytest.fail("Not written yet: Given a user clicks on the \"Revenge Trading\" tag filter on the dashboard, when the chart updates, then data points corresponding to revenge trades are highlighted visually with red marker flags.")


def test_ac6_4():
    pytest.fail("Not written yet: Given a month with zero logged trades, when the calendar heatmap is displayed, then all day cells render in a neutral grey state without layout breakage.")
