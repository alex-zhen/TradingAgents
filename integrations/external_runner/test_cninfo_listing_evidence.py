"""Official listing evidence is separate from the 公告时间 text gate. No network."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from cninfo_listing_evidence import (  # noqa: E402
    attach_cninfo_listing,
    load_cninfo_listing_evidence,
    main,
)

FIXTURE = HERE / "fixtures" / "synthetic_cninfo_300750.json"
GUARDED = "4dac0876f434b93b666b8663171317f0e3ef89f32ed60ea77a5d00411a4f5f4b"
DECISION = "2026-10-21T10:00:00+08:00"
MARKER = "12,345"


def _base() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _write(tmp_path: Path, payload: dict) -> Path:
    path = tmp_path / "listing.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def _view(path, symbol="300750.SZ", decision=DECISION):
    return load_cninfo_listing_evidence(path, requested_symbol=symbol, decision_at=decision)


def _shown(path, symbol="300750.SZ", decision=DECISION, method="get_fundamentals"):
    return attach_cninfo_listing(
        "VENDOR", method, requested_symbol=symbol, decision_at=decision, path=path,
    )


def test_date_only_listing_admits_the_next_day_and_keeps_the_label():
    view = _view(FIXTURE)
    shown = _shown(FIXTURE)
    assert view.status == "admitted"
    assert "source_label: 公告时间" in shown
    assert "source_label: 公告日期" not in shown
    assert "公告日期" not in shown
    assert "availability: 2026-10-20" in shown
    assert "availability: 2026-08-01" not in shown
    assert "availability: 2026-09-30" not in shown
    assert "availability_precision: date" in shown
    assert MARKER in shown
    assert "latest_discovery_verified: true" not in shown
    assert "latest_discovery_verified: not established by this evidence" in shown
    assert "Latest disclosure discovery is not proven" in shown
    assert _shown(FIXTURE, method="get_stock_data") == "VENDOR"
    assert main(["--file", str(FIXTURE), "--symbol", "300750", "--decision-at", DECISION]) == 0


def test_same_day_midnight_board_period_and_identity_fail_closed(tmp_path):
    same_day = _view(FIXTURE, decision="2026-10-20T18:00:00+08:00")
    assert same_day.status == "withheld"
    assert MARKER not in _shown(FIXTURE, decision="2026-10-20T18:00:00+08:00")
    earlier = _view(FIXTURE, decision="2026-10-19T18:00:00+08:00")
    assert earlier.status == "withheld"
    assert MARKER not in _shown(FIXTURE, decision="2026-10-19T18:00:00+08:00")
    midnight = _base()
    midnight["publication"] = {"value": "2026-10-20T00:00:00+08:00", "raw": "公告时间：2026-10-20 00:00:00"}
    held = _view(_write(tmp_path, midnight), decision="2026-10-20T10:00:00+08:00")
    held_text = _shown(_write(tmp_path, midnight), decision="2026-10-20T10:00:00+08:00")
    assert held.status == "withheld"
    assert "availability_precision: timestamp" not in held_text
    assert MARKER not in held_text
    later = _shown(_write(tmp_path, midnight), decision="2026-10-21T10:00:00+08:00")
    assert "availability_precision: date" in later
    assert "midnight_placeholder: true" in later
    assert MARKER in later
    board = _base()
    board["publication"] = {"value": "2026-10-18", "raw": "公告时间：2026年10月18日"}
    assert _view(_write(tmp_path, board)).status == "rejected"
    assert "board signature" in " ".join(_view(_write(tmp_path, board)).reasons)
    assert MARKER not in _shown(_write(tmp_path, board))
    period = _base()
    period["publication"] = {"value": "2026-09-30", "raw": "公告时间：2026年9月30日"}
    assert "period end" in " ".join(_view(_write(tmp_path, period)).reasons)
    signature = _base()
    signature["publication"] = {"value": "2026-10-20", "raw": "董事会落款：2026年10月18日"}
    assert _view(_write(tmp_path, signature)).status == "rejected"
    naive = _base()
    naive["publication"] = {"value": "2026-10-20T16:30:00", "raw": "公告时间：2026-10-20 16:30:00"}
    assert "no timezone" in " ".join(_view(_write(tmp_path, naive)).reasons)
    assert _view(FIXTURE, decision="").status == "rejected"
    assert "DATE was not used" in " ".join(_view(FIXTURE, decision="").reasons)


def test_precise_official_clock_can_be_used_after_it_on_the_same_day(tmp_path):
    payload = _base()
    payload["publication"] = {"value": "2026-10-20T16:30:00+08:00", "raw": "公告时间：2026-10-20 16:30:00"}
    path = _write(tmp_path, payload)
    before = _shown(path, decision="2026-10-20T16:00:00+08:00")
    after = _shown(path, decision="2026-10-20T16:30:00+08:00")
    assert "status: withheld" in before and MARKER not in before
    assert "availability_precision: timestamp" in after
    assert "availability: 2026-10-20T16:30:00+08:00" in after
    assert MARKER in after
    assert "latest_discovery_verified: true" not in after


def test_wrong_security_pdf_hash_period_id_and_source_are_rejected(tmp_path):
    wrong_symbol = _shown(FIXTURE, symbol="600519.SH")
    assert "status: rejected" in wrong_symbol and MARKER not in wrong_symbol
    pdf = _base()
    pdf["pdf_url"] = "https://static.cninfo.com.cn/finalpage/2026-10-20/OTHER.PDF"
    assert "pdf_url" in " ".join(_view(_write(tmp_path, pdf)).reasons)
    hashed = _base()
    hashed["content_sha256"] = "0" * 64
    assert "content_sha256" in " ".join(_view(_write(tmp_path, hashed)).reasons)
    period = _base()
    period["report_period"] = "2026-06-30"
    assert "report_period" in " ".join(_view(_write(tmp_path, period)).reasons)
    ident = _base()
    ident["announcement_id"] = "SYN-OTHER-0001"
    ident["pdf_url"] = "https://static.cninfo.com.cn/finalpage/2026-08-01/SYN-OTHER-0001.PDF"
    assert "announcement_id" in " ".join(_view(_write(tmp_path, ident)).reasons)
    external = _base()
    external["source"] = "eastmoney"
    assert "source" in " ".join(_view(_write(tmp_path, external)).reasons)
    summary = _base()
    summary["pdf_url"] = "https://xueqiu.com/SYN-CNINFO-300750-20261020"
    assert "pdf_url" in " ".join(_view(_write(tmp_path, summary)).reasons)
    renamed = _base()
    renamed["source_label"] = "公告日期"
    assert _view(_write(tmp_path, renamed)).status == "rejected"
    for payload in (pdf, hashed, period, ident, external, summary, renamed):
        assert MARKER not in _shown(_write(tmp_path, payload))


def _staged():
    from patch_cninfo_listing_hook import patch_bytes
    base = (HERE / "fixtures" / "run_ta_4dac0876.py").read_bytes()
    return base, patch_bytes(base).decode()


def test_patcher_refuses_older_runners_and_keeps_both_existing_gates():
    from patch_cninfo_listing_hook import PatchMismatch, patch_bytes
    for name in ("run_ta_49f0612.py", "run_ta_6d269117.py"):
        try:
            patch_bytes((HERE / "fixtures" / name).read_bytes())
        except PatchMismatch:
            pass
        else:
            raise AssertionError(name)
    base, staged = _staged()
    assert hashlib.sha256(base).hexdigest() == GUARDED
    official = base.decode().split("def _labeled_availability", 1)[1].split("def _official_not_applicable", 1)[0]
    public = base.decode().split("# === PUBLIC EVIDENCE HOOK START", 1)[1].split("# === PUBLIC EVIDENCE HOOK END", 1)[0]
    assert official == staged.split("def _labeled_availability", 1)[1].split("def _official_not_applicable", 1)[0]
    assert public == staged.split("# === PUBLIC EVIDENCE HOOK START", 1)[1].split("# === PUBLIC EVIDENCE HOOK END", 1)[0]
    label_line = staged.split("label =", 1)[1].split("\n", 1)[0]
    assert "公告时间" not in label_line
    assert "公告日期" in label_line


def test_staged_route_uses_listing_evidence_and_keeps_prior_gates(monkeypatch, capsys, tmp_path):
    from preflight_cninfo_listing import main as preflight_main
    base, staged = _staged()
    del base
    start = staged.find("def _norm_listing")
    end = staged.find("_orig = T.route_to_vendor")
    namespace = {}
    exec(staged[start:end], namespace)
    block = namespace["_official_fundamentals_block"]
    notice = """ticker: 300750.SZ
decision_at: 2026-11-19T10:00:00+08:00
公告时间：2026年10月15日
http://static.cninfo.com.cn/finalpage/2026-10-15/123.pdf
## Financial report
Revenue 100,000
"""
    shown = block(notice, "2026-11-19T10:00:00+08:00")
    assert "100,000" not in shown and "MISSING:" in shown
    assert "latest_discovery_verified: true" not in shown
    digest = (HERE / "fixtures" / "xiaomi_1810_operator_2026-11-18.md").read_text(encoding="utf-8")
    assert "108,921.6" not in block(digest, "2026-08-18T12:00:00+08:00")
    nxt = block(digest, "2026-08-19T12:00:00+08:00")
    assert "108,921.6" in nxt and "publication_dateline: August 18, 2026" in nxt
    assert "availability: 2026-06-30" not in nxt
    tencent = (HERE / "fixtures" / "tencent_operator_2026-11-18.md").read_text(encoding="utf-8")
    assert "207,336" not in block(tencent, "2026-11-18T16:00:00+08:00")
    assert "207,336" in block(tencent, "2026-11-18T19:34:57+08:00")
    hook_end = staged.find("# === CNINFO LISTING HOOK END")
    monkeypatch.setenv("TRADINGAGENTS_CNINFO_LISTING_DIR", str(HERE))
    monkeypatch.setenv("TRADINGAGENTS_CNINFO_LISTING", str(FIXTURE))
    monkeypatch.delenv("TRADINGAGENTS_DECISION_AT", raising=False)
    sent = (
        "ticker: 300750.SZ\nprice_session_date: 2026-10-20\n"
        f"decision_at: {DECISION}\n公告时间：2026年10月20日\n"
        "## Financial report\nRevenue 100,000\n"
    )
    route_ns = {
        "sys": sys,
        "T": type("T", (), {"route_to_vendor": staticmethod(lambda *a, **k: "VENDOR")})(),
        "TICKER": "300750.SZ",
        "DATE": "2026-10-20",
        "sent": sent,
        "sent_block": "",
        "opt_block": "",
    }
    exec(staged[start:hook_end] + "\n", route_ns)
    fundamentals = route_ns["T"].route_to_vendor("get_fundamentals", "300750.SZ")
    assert MARKER in fundamentals
    assert "100,000" not in fundamentals
    assert "source_label: 公告时间" in fundamentals
    assert "status: admitted" in fundamentals
    prices = route_ns["T"].route_to_vendor("get_stock_data", "300750.SZ")
    assert MARKER not in prices
    route_ns["sent"] = "ticker: 300750.SZ\nprice_session_date: 2026-10-21\n公告时间：2026年10月20日\n"
    route_ns["DATE"] = "2026-10-21"
    route_ns["T"].route_to_vendor = staticmethod(lambda *a, **k: "VENDOR")
    exec(staged[start:hook_end] + "\n", route_ns)
    missing = route_ns["T"].route_to_vendor("get_fundamentals", "300750.SZ")
    assert "status: rejected" in missing and MARKER not in missing
    assert "DATE was not used" in missing
    staged_path = tmp_path / "run_ta.py.staged"
    staged_path.write_text(staged, encoding="utf-8")
    code = preflight_main([
        "--runner", str(staged_path), "--file", str(FIXTURE), "--symbol", "300750.SZ",
        "--session-date", "2026-10-20", "--decision-at", DECISION,
    ])
    printed = capsys.readouterr().out
    assert code == 0
    assert "status: admitted" in printed.split("=== get_stock_data ===", 1)[0]
    assert MARKER in printed and "100,000" not in printed
