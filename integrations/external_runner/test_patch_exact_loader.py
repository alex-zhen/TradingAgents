"""Standalone checks for patch_exact_loader.py. No package fixtures."""

from __future__ import annotations

import hashlib
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from patch_exact_loader import NEW, OLD, patch_bytes, unified_diff  # noqa: E402, I001

PREFIX = (
    "import sys, os, json, re, pathlib\n"
    "sys.path.insert(0, '/workspace/tradingagents')\n"
    "import tradingagents.agents.tools as T\n"
    "TICKER = sys.argv[1]; DATE = sys.argv[2] if len(sys.argv)>2 else '2026-11-13'\n"
    "RUN = pathlib.Path('/workspace/tradingagents-runs')\n"
)
SUFFIX = (
    "# existing options/xueqiu hooks and cfg remain unchanged\n"
    "sent_block = f\"\\n\\nEXTRA CONTEXT\\n{sent}\\n\"\n"
    "_orig = T.route_to_vendor\n"
    "def patched(method, *a, **k):\n"
    "    out = _orig(method, *a, **k)\n"
    "    if method == 'get_news':\n"
    "        out = f'{out}{sent_block}'\n"
    "    elif method == 'get_stock_data':\n"
    "        out = f'{out}{opt_block}'\n"
    "    return out\n"
    "T.route_to_vendor = patched\n"
)
CODES = (
    "0700", "BABA", "LI", "NVDA", "0981", "601169", "601398",
    "9988", "2015", "3690", "1810", "9618", "1211", "9888",
    "9992", "600519", "601318", "300750", "002594", "AAPL",
    "TSM", "AMD", "2318", "0883", "0388", "0941", "9868", "1024",
)


def _source() -> bytes:
    return (PREFIX + OLD + SUFFIX).encode()


def _run_loader(root: Path, ticker: str, date: str) -> tuple[object, str]:
    namespace = {"RUN": root, "TICKER": ticker, "DATE": date}
    exec(NEW, namespace)
    return namespace["sent_path"], namespace["sent"]


def test_one_block_keeps_every_other_byte():
    updated = patch_bytes(_source())
    assert updated.startswith(PREFIX.encode())
    assert updated.endswith(SUFFIX.encode())
    assert updated[len(PREFIX.encode()):-len(SUFFIX.encode())] == NEW.encode()
    assert b"sent_block = sent\n" not in updated
    assert b"research_ingest" not in updated
    assert OLD.encode() not in updated


def test_cli_writes_a_separate_file_and_rejects_a_mismatch(tmp_path=None):
    own = tempfile.TemporaryDirectory() if tmp_path is None else None
    root = Path(tmp_path) if tmp_path is not None else Path(own.name)
    try:
        source = root / "run_ta.py"
        source.write_bytes(_source())
        output = root / "out" / "run_ta.patched.py"
        proc = subprocess.run(
            [sys.executable, str(HERE / "patch_exact_loader.py"), str(source), "--output", str(output)],
            capture_output=True, text=True,
        )
        assert proc.returncode == 0, proc.stderr
        assert source.read_bytes() == _source()
        assert output.read_bytes() == patch_bytes(_source())
        assert output.resolve() != source.resolve()

        broken = root / "broken.py"
        broken.write_bytes(_source().replace(b"2026-11-15.md", b"2026-11-15.MD", 1))
        refused = root / "refused.py"
        bad = subprocess.run(
            [sys.executable, str(HERE / "patch_exact_loader.py"), str(broken), "--output", str(refused)],
            capture_output=True, text=True,
        )
        assert bad.returncode == 2
        assert not refused.exists()
        assert broken.read_bytes().count(OLD.encode()) == 0

        twice = root / "twice.py"
        twice.write_bytes(_source() + b"\n" + OLD.encode())
        twice_out = root / "twice.patched.py"
        dup = subprocess.run(
            [sys.executable, str(HERE / "patch_exact_loader.py"), str(twice), "--output", str(twice_out)],
            capture_output=True, text=True,
        )
        assert dup.returncode == 2
        assert not twice_out.exists()
        assert twice.read_bytes() == _source() + b"\n" + OLD.encode()
    finally:
        if own is not None:
            own.cleanup()


def test_missing_file_is_explicit_for_any_code(tmp_path=None):
    own = tempfile.TemporaryDirectory() if tmp_path is None else None
    root = Path(tmp_path) if tmp_path is not None else Path(own.name)
    try:
        assert len(CODES) == 28
        for ticker in CODES:
            old = root / f"sentiment_digest_{ticker}_2026-11-15.md"
            old.write_text(f"OLD {ticker} https://example.invalid/{ticker}/old\n", encoding="utf-8")
            path, sent = _run_loader(root, ticker, "2026-11-16")
            assert isinstance(path, Path)
            assert path.name == f"sentiment_digest_{ticker}_2026-11-16.md"
            assert path.exists() is False
            assert sent.startswith(f'MISSING sentiment_digest_{ticker}_2026-11-16.md in {root}.')
            assert "No older file was substituted" in sent
            assert "did not fetch" in sent
            assert f"OLD {ticker}" not in sent
            assert old.read_text(encoding="utf-8").startswith("OLD ")
    finally:
        if own is not None:
            own.cleanup()


def test_dated_operator_summary_is_read_verbatim(tmp_path=None):
    own = tempfile.TemporaryDirectory() if tmp_path is None else None
    root = Path(tmp_path) if tmp_path is not None else Path(own.name)
    try:
        body = (
            "Operator summary compiled 2026-11-17.\n"
            "Declared cutoff: 2026-11-17T09:00:00-05:00.\n"
            "Official URL: https://example.invalid/baba/filing\n"
        )
        path = root / "sentiment_digest_BABA_2026-11-16.md"
        path.write_text(body, encoding="utf-8")
        found, sent = _run_loader(root, "BABA", "2026-11-16")
        assert found == path
        assert found.exists()
        assert sent == body
        evidence = {
            "path": str(found),
            "sha256": hashlib.sha256(body.encode()).hexdigest(),
            "fetched": False,
        }
        assert evidence["fetched"] is False
        assert evidence["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
        assert b"digest_manifest" not in patch_bytes(_source())
    finally:
        if own is not None:
            own.cleanup()


def test_generated_diff_applies():
    before = PREFIX + OLD + SUFFIX
    after = PREFIX + NEW + SUFFIX
    diff = unified_diff(before, after, "a/run_ta.py", "b/run_ta.py")
    assert diff == (HERE / "sentiment_loader_hotfix.diff").read_text(encoding="utf-8")
    assert diff.startswith("--- a/run_ta.py\n+++ b/run_ta.py\n@@ ")
    assert "\n+sent_block = sent\n" not in diff
    assert "\n+sent_block=sent\n" not in diff
    own = tempfile.TemporaryDirectory()
    try:
        root = Path(own.name)
        (root / "run_ta.py").write_text(before, encoding="utf-8")
        diff_path = root / "hotfix.diff"
        diff_path.write_text(diff, encoding="utf-8")
        git = subprocess.run(["git", "apply", "--check", str(diff_path)], cwd=root, capture_output=True, text=True)
        assert git.returncode == 0, git.stderr
        pat = subprocess.run(["patch", "--dry-run", "-p1", "--forward", "-i", str(diff_path)], cwd=root, capture_output=True, text=True)
        assert pat.returncode == 0, pat.stderr
        subprocess.run(["git", "apply", str(diff_path)], cwd=root, check=True)
        assert (root / "run_ta.py").read_text(encoding="utf-8") == after
    finally:
        own.cleanup()


if __name__ == "__main__":
    test_one_block_keeps_every_other_byte()
    test_cli_writes_a_separate_file_and_rejects_a_mismatch()
    test_missing_file_is_explicit_for_any_code()
    test_dated_operator_summary_is_read_verbatim()
    test_generated_diff_applies()
    print("ok")
