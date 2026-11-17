"""Sanitized fixture of the external defect.

This is not the parent's run_ta.py. That file was not in the workspace. The
marker below is the hardcoded digest the running wrapper was described as using
for every symbol and every analysis date.
"""

from pathlib import Path

RUNS = Path("/workspace/tradingagents-runs")
CONFIG = RUNS / "config.json"

RESEARCH_DIGEST = Path("/workspace/tradingagents-runs/digests/BABA_2026-11-15.md")


def load_research(symbol, as_of):
    del symbol, as_of
    return RESEARCH_DIGEST.read_text(encoding="utf-8")
