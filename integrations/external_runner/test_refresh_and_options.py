"""Runner gate and the exact options-block patch. No model calls."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import refresh_current  # noqa: E402
from acquire_sentiment import Result  # noqa: E402
from patch_options_block import NEW, OLD, patch_bytes, unified_diff  # noqa: E402


def test_failed_fetch_does_not_start_the_runner(tmp_path, monkeypatch):
    baseline = tmp_path / "sentiment_digest_BABA_2026-11-16.md"
    baseline.write_text("OLD DIGEST", encoding="utf-8")
    ran = tmp_path / "ran.txt"
    runner = tmp_path / "runner.py"
    runner.write_text(f"from pathlib import Path\nPath({str(ran)!r}).write_text('ran')\n", encoding="utf-8")
    run = tmp_path / "acquisitions" / "none"
    run.mkdir(parents=True)

    def failed(*args, **kwargs):
        return Result("BABA", "BABA", "2026-11-16", "2026-11-17T14:00:00+00:00", False, False, "partial_or_failed", "MISSING", run)

    monkeypatch.setattr(refresh_current, "acquire", failed)
    code = refresh_current.main([
        "BABA", "2026-11-16", "--decision-at", "2026-11-17T14:00:00Z",
        "--refresh-current", "--runner", str(runner), "--root", str(tmp_path),
    ])
    assert code == 4
    assert not ran.exists()
    assert baseline.read_text(encoding="utf-8") == "OLD DIGEST"


def test_runner_receives_this_acquisition_and_keeps_prior_outputs(tmp_path, monkeypatch):
    baseline = tmp_path / "sentiment_digest_BABA_2026-11-16.md"
    baseline.write_text("OLD DIGEST", encoding="utf-8")
    report = tmp_path / "BABA_2026-11-16"
    report.mkdir()
    (report / "market_report.md").write_text("PRIOR REPORT", encoding="utf-8")
    log = tmp_path / "logs" / "BABA" / "TradingAgentsStrategy_logs"
    log.mkdir(parents=True)
    (log / "full_states_log_2026-11-16.json").write_text('{"prior": true}', encoding="utf-8")
    run = tmp_path / "acquisitions" / "fresh"
    run.mkdir(parents=True)
    fresh = "fetched: true\nhttps://www.alibabagroup.com/en-US/ir-financial-reports-quarterly-results\nRevenue excerpt\n"
    produced = run / "sentiment_digest_BABA_2026-11-16.md"
    produced.write_text(fresh, encoding="utf-8")
    seen = tmp_path / "seen.txt"
    runner = tmp_path / "runner.py"
    runner.write_text(
        "from pathlib import Path\n"
        f"root = Path({str(tmp_path)!r})\n"
        f"Path({str(seen)!r}).write_text((root / 'sentiment_digest_BABA_2026-11-16.md').read_text())\n"
        "(root / 'BABA_2026-11-16' / 'market_report.md').write_text('NEW RUN')\n",
        encoding="utf-8",
    )

    def ok(*args, **kwargs):
        return Result("BABA", "BABA", "2026-11-16", "2026-11-17T14:00:00+00:00", True, True, "fetched", fresh, run)

    monkeypatch.setattr(refresh_current, "acquire", ok)
    code = refresh_current.main([
        "BABA", "2026-11-16", "--decision-at", "2026-11-17T14:00:00Z",
        "--refresh-current", "--runner", str(runner), "--root", str(tmp_path),
    ])
    assert code == 0
    assert seen.read_text(encoding="utf-8") == fresh
    assert (report / "market_report.md").read_text(encoding="utf-8") == "NEW RUN"
    prior_reports = list((tmp_path / "backups").rglob("market_report.md"))
    prior_logs = list((tmp_path / "backups").rglob("full_states_log_2026-11-16.json"))
    assert any(path.read_text(encoding="utf-8") == "PRIOR REPORT" for path in prior_reports)
    assert any(path.read_text(encoding="utf-8") == '{"prior": true}' for path in prior_logs)
    assert (log / "full_states_log_2026-11-16.json").is_file()


def test_historical_runner_is_refused(tmp_path, monkeypatch):
    ran = tmp_path / "ran.txt"
    runner = tmp_path / "runner.py"
    runner.write_text(f"from pathlib import Path\nPath({str(ran)!r}).write_text('ran')\n", encoding="utf-8")

    def explode(*args, **kwargs):
        raise AssertionError("historical mode fetched")

    monkeypatch.setattr(refresh_current, "acquire", explode)
    code = refresh_current.main([
        "LI", "2026-11-16", "--decision-at", "2026-08-01T00:00:00Z",
        "--mode", "historical", "--runner", str(runner), "--root", str(tmp_path),
    ])
    assert code == 4
    assert not ran.exists()


def test_options_block_drops_pinned_file_and_other_companies(tmp_path):
    source = "PREFIX\n" + OLD + "SUFFIX\n"
    updated = patch_bytes(source.encode())
    assert updated.startswith(b"PREFIX\n")
    assert updated.endswith(b"SUFFIX\n")
    text = updated.decode()
    assert "options_digest_2026-11-13.md" not in text
    assert "HK options unavailable" not in text
    assert "timeout=60" in text
    assert "options_digest.py" in text
    namespace = {"RUN": tmp_path, "TICKER": "BABA", "DATE": "2026-11-16", "pathlib": __import__("pathlib")}
    exec(NEW, namespace)
    pinned = tmp_path / "options_digest_2026-11-13.md"
    pinned.write_text("## BABA pinned\n## LI other\n", encoding="utf-8")
    combined = tmp_path / "options_digest_2026-11-16.md"
    combined.write_text("## NVDA something\n\n## BABA call volume\n\n## O realty\n", encoding="utf-8")
    assert namespace["_load_options_digest"]("BABA", "2026-11-16") == "## BABA call volume\n\n"
    assert "O realty" not in namespace["_load_options_digest"]("LI", "2026-11-16")
    assert namespace["_load_options_digest"]("LI", "2026-11-16").startswith("(no options digest found for LI")
    assert "HK options unavailable" not in namespace["opt_block"]
    diff = unified_diff(source, text, "a/run_ta.py", "b/run_ta.py")
    assert diff.startswith("--- a/run_ta.py\n+++ b/run_ta.py\n@@ ")
    root = tmp_path / "apply"
    root.mkdir()
    (root / "run_ta.py").write_text(source, encoding="utf-8")
    diff_path = tmp_path / "options.diff"
    diff_path.write_text(diff, encoding="utf-8")
    git = subprocess.run(["git", "apply", "--check", str(diff_path)], cwd=root, capture_output=True, text=True)
    assert git.returncode == 0, git.stderr


def test_issuer_listing_is_not_a_pinned_filename():
    source = (HERE / "acquire_sentiment.py").read_text(encoding="utf-8")
    assert "June-results.pdf" not in source
    assert "June%20Quarter%202026%20Results.pdf" not in source
