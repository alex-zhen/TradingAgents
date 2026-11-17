"""Point-in-time selection of research files already on disk.

This module does not fetch filings, news, prices, or sentiment, and it does not
call a producer. It chooses the latest file that was published and captured by
an explicit cutoff, records provenance, and writes an immutable run directory.

Share listings are not interchangeable: BABA (ADS) is not 9988 (ordinary),
LI (ADS) is not 2015 (ordinary), and 0700 is the Hong Kong ordinary listing.
"""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

NEWS_STALE_AFTER = timedelta(days=7)
KINDS = ("financial_extract", "news", "sentiment", "official_ir", "hkex_summary")
FINANCIAL_KINDS = ("financial_extract", "official_ir", "hkex_summary")
_SKIP_NAMES = {
    "producer_status.json",
    "input_manifest.json",
    "full_state.json",
    "final_state.json",
}
_SESSION = {
    "US": {"tz": ZoneInfo("America/New_York"), "close_hour": 16, "close_minute": 0},
    "HK": {"tz": ZoneInfo("Asia/Hong_Kong"), "close_hour": 16, "close_minute": 0},
}


@dataclass(frozen=True)
class Instrument:
    canonical: str
    market: str
    company: str
    listing_unit: str
    quote_currency: str
    ordinary_per_listing: int
    aliases: tuple[str, ...]

    @property
    def unit_note(self) -> str:
        if self.listing_unit == "ADS":
            return (
                f"{self.canonical} is an ADS listing: 1 ADS = {self.ordinary_per_listing} "
                "ordinary shares. Do not use ordinary-share per-share figures as ADS figures."
            )
        sister = {"alibaba": "BABA is 1 ADS = 8 ordinary shares", "li_auto": "LI is 1 ADS = 2 ordinary shares"}.get(self.company)
        extra = f" Sister listing: {sister}." if sister else ""
        return (
            f"{self.canonical} is an ordinary-share listing quoted in {self.quote_currency}. "
            f"Do not use ADS per-share figures as ordinary-share figures.{extra}"
        )


def _hk(code: str) -> str:
    return f"{int(code):04d}.HK"


_INSTRUMENTS = (
    Instrument("BABA", "US", "alibaba", "ADS", "USD", 8, ("BABA",)),
    Instrument(
        "9988.HK", "HK", "alibaba", "ordinary", "HKD", 1,
        ("9988", "09988", "9988.HK", "09988.HK"),
    ),
    Instrument("LI", "US", "li_auto", "ADS", "USD", 2, ("LI",)),
    Instrument(
        "2015.HK", "HK", "li_auto", "ordinary", "HKD", 1,
        ("2015", "02015", "2015.HK", "02015.HK"),
    ),
    Instrument(
        "0700.HK", "HK", "tencent", "ordinary", "HKD", 1,
        ("0700", "700", "00700", "0700.HK", "700.HK", "00700.HK"),
    ),
)
_BY_ALIAS = {alias.upper(): inst for inst in _INSTRUMENTS for alias in inst.aliases}


def resolve_instrument(symbol: str, market: str | None = None) -> Instrument:
    """Resolve a listing alias. ADS and ordinary lines of one company stay distinct."""
    key = symbol.strip().upper().replace(" ", "")
    inst = _BY_ALIAS.get(key)
    if inst is None and key.endswith(".HK"):
        number = key[:-3]
        if number.isdigit():
            inst = _BY_ALIAS.get(_hk(number))
    if inst is None:
        known = ", ".join(sorted(_BY_ALIAS))
        raise ValueError(f"unknown listing {symbol!r}; known aliases: {known}")
    if market is not None and market.upper() != inst.market:
        raise ValueError(
            f"{symbol} is the {inst.market} {inst.listing_unit} listing {inst.canonical}, "
            f"not a {market} listing"
        )
    return inst


def market_for(symbol: str) -> str:
    return resolve_instrument(symbol).market


def parse_decision_at(value: str | datetime) -> datetime:
    """Parse an explicit timezone-aware cutoff. Naive timestamps are rejected."""
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value).strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        raise ValueError("decision timestamp must include a timezone offset")
    return parsed.astimezone(UTC)


def last_completed_session(
    market: str,
    decision_at: datetime,
    holidays: Iterable[date] | None = None,
) -> date:
    """The market's last session that had already closed at ``decision_at``.

    A timestamp before the close, or on a weekend or supplied holiday, walks
    back. The close itself counts as completed. This date is the price as-of;
    it is not the news cutoff.
    """
    spec = _SESSION[market]
    closed = frozenset(holidays or ())
    local = decision_at.astimezone(spec["tz"])
    day = local.date()
    close = local.replace(
        hour=spec["close_hour"], minute=spec["close_minute"], second=0, microsecond=0,
    )

    def trades(day: date) -> bool:
        return day.weekday() < 5 and day not in closed

    if not trades(day) or local < close:
        day -= timedelta(days=1)
        while not trades(day):
            day -= timedelta(days=1)
    return day


def graph_trade_date(market: str, decision_at: datetime) -> str:
    """Calendar date the framework should clamp vendor tools to.

    This is the decision's date in the listing's market, including a session
    that has not closed yet. It is intentionally not ``last_completed_session``:
    news after the prior close and before the decision must remain reachable.
    """
    return decision_at.astimezone(_SESSION[market]["tz"]).date().isoformat()


@dataclass(frozen=True)
class Record:
    symbol: str
    market: str
    kind: str
    statement_scope: str
    unit: str
    currency: str
    period_end: str | None
    published_at: datetime
    available_at: datetime
    captured_at: datetime
    source_url: str
    provenance: str
    body: str
    generated: bool
    original_urls: tuple[str, ...]
    company: str | None
    path: str
    sha256: str

    def identity(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "sha256": self.sha256,
            "source_url": self.source_url,
            "currency": self.currency,
            "unit": self.unit,
            "statement_scope": self.statement_scope,
            "period_end": self.period_end,
            "published_at": _iso(self.published_at),
            "available_at": _iso(self.available_at),
            "captured_at": _iso(self.captured_at),
            "provenance": self.provenance,
            "generated": self.generated,
            "original_urls": list(self.original_urls),
            "company": self.company,
            "symbol": self.symbol,
            "kind": self.kind,
        }


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


def _parse_stamp(value: Any, field: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} is required")
    return parse_decision_at(value)


def _http_url(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.startswith(("http://", "https://")):
        raise ValueError(f"{field} must be an http(s) URL")
    return value


def _under(root: Path, path: Path) -> Path:
    resolved = path.resolve()
    if not resolved.is_relative_to(root.resolve()):
        raise ValueError(f"{path} escapes {root}")
    return resolved


def load_record(path: Path, corpus: Path) -> Record:
    """Load one metadata-bearing extract. The file bytes are the hash input."""
    resolved = _under(corpus, path)
    raw = resolved.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    text = raw.decode("utf-8")
    if resolved.suffix == ".json":
        data = json.loads(text)
        if not isinstance(data, dict):
            raise ValueError("record JSON must be an object")
        body = str(data.get("body") or "")
    elif resolved.suffix == ".md":
        if not text.startswith("<!-- research-record\n"):
            raise ValueError("markdown record is missing a research-record header")
        end = text.find("\n-->\n")
        if end < 0:
            raise ValueError("markdown record header is not closed")
        data = json.loads(text[len("<!-- research-record\n"):end])
        body = text[end + len("\n-->\n"):]
    else:
        raise ValueError("record must be .json or .md")
    kind = data.get("kind")
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {KINDS}")
    scope = data.get("statement_scope") or ("group" if data.get("unit") == "group" else "per_share")
    if scope not in {"group", "per_share", "item"}:
        raise ValueError("statement_scope must be group, per_share, or item")
    period = data.get("period_end")
    if period is not None:
        period = datetime.strptime(str(period), "%Y-%m-%d").date().isoformat()
    urls = tuple(_http_url(u, "original_urls") for u in data.get("original_urls") or [])
    return Record(
        symbol=str(data["symbol"]),
        market=str(data.get("market") or "").upper(),
        kind=kind,
        statement_scope=scope,
        unit=str(data["unit"]),
        currency=str(data["currency"]),
        period_end=period,
        published_at=_parse_stamp(data.get("published_at"), "published_at"),
        available_at=_parse_stamp(data.get("available_at"), "available_at"),
        captured_at=_parse_stamp(data.get("captured_at"), "captured_at"),
        source_url=_http_url(data.get("source_url"), "source_url"),
        provenance=str(data.get("provenance") or ""),
        body=body,
        generated=bool(data.get("generated")),
        original_urls=urls,
        company=data.get("company"),
        path=str(resolved),
        sha256=digest,
    )


def scan_corpus(corpus: Path) -> tuple[list[Record], list[dict[str, str]]]:
    records: list[Record] = []
    issues: list[dict[str, str]] = []
    root = corpus.resolve()
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.name in _SKIP_NAMES or path.suffix not in {".json", ".md"}:
            continue
        if any(part == "runs" or part.endswith(".partial") for part in path.relative_to(root).parts):
            continue
        try:
            records.append(load_record(path, root))
        except (OSError, UnicodeError, ValueError, json.JSONDecodeError, KeyError) as exc:
            issues.append({"path": str(path), "reason": f"{type(exc).__name__}: {exc}"})
    return records, issues


def _matches(record: Record, inst: Instrument) -> str | None:
    """Return a rejection reason when the record is for a different listing or unit."""
    if record.statement_scope == "group" or record.unit == "group":
        if record.company != inst.company or record.unit != "group":
            return "different_company_or_unit"
        return None
    try:
        other = resolve_instrument(record.symbol, record.market or None)
    except ValueError:
        return "unknown_listing"
    if other.canonical != inst.canonical:
        return "different_listing"
    if record.kind in FINANCIAL_KINDS and record.unit != inst.listing_unit:
        return "unit_mismatch"
    if record.market and record.market != inst.market:
        return "market_mismatch"
    return None


def _timing_rejection(record: Record, cutoff: datetime, market: str) -> str | None:
    if record.published_at > cutoff:
        return "published_after_cutoff"
    if record.available_at > cutoff:
        return "available_after_cutoff"
    if record.captured_at > cutoff:
        return "captured_after_cutoff"
    if record.period_end:
        cutoff_day = cutoff.astimezone(_SESSION[market]["tz"]).date().isoformat()
        if record.period_end > cutoff_day:
            return "period_after_cutoff"
        if record.period_end > record.published_at.astimezone(UTC).date().isoformat():
            return "period_after_publication"
    return None


@dataclass
class Category:
    kind: str
    status: str
    selected: Record | None
    warnings: list[str]
    rejected: list[dict[str, str]]
    newer_unavailable: list[dict[str, Any]]
    older_eligible: list[dict[str, Any]]


def select_records(
    records: list[Record],
    inst: Instrument,
    cutoff: datetime,
    *,
    news_stale_after: timedelta = NEWS_STALE_AFTER,
) -> list[Category]:
    categories = []
    for kind in KINDS:
        pool = [r for r in records if r.kind == kind]
        eligible: list[Record] = []
        rejected: list[dict[str, str]] = []
        for record in pool:
            listing = _matches(record, inst)
            if listing is not None:
                rejected.append({**_brief(record), "reason": listing})
                continue
            timing = _timing_rejection(record, cutoff, inst.market)
            if timing is not None:
                rejected.append({**_brief(record), "reason": timing})
                continue
            eligible.append(record)
        eligible.sort(key=_rank)
        selected = eligible[-1] if eligible else None
        newer = [
            item for item in rejected
            if item["reason"] in {
                "published_after_cutoff", "available_after_cutoff",
                "captured_after_cutoff", "period_after_cutoff",
            }
        ]
        warnings: list[str] = []
        if selected is None:
            status = "missing"
            warnings.append("no_eligible")
        else:
            status = "selected"
            if kind in {"news", "sentiment"} and cutoff - selected.published_at > news_stale_after:
                status = "selected_stale"
                warnings.append("stale_news" if kind == "news" else "stale_sentiment")
            if selected.generated:
                warnings.append("generated_summary_not_official")
                if not selected.original_urls:
                    warnings.append("missing_original_urls")
            if selected.statement_scope == "group":
                warnings.append("cross_listing_group_statement")
        if newer and (selected is None or any(_is_newer(item, selected) for item in newer)):
            warnings.append("newer_unavailable")
        if any("BABA_2026-11-15" in Path(item["path"]).name and item["reason"] != "selected"
               for item in rejected):
            warnings.append("fixed_digest_name_not_used")
        categories.append(Category(
            kind=kind,
            status=status,
            selected=selected,
            warnings=warnings,
            rejected=sorted(rejected, key=lambda item: item["path"]),
            newer_unavailable=newer,
            older_eligible=[_brief(r) for r in eligible[:-1]],
        ))
    return categories


def _rank(record: Record) -> tuple:
    return (record.published_at, record.period_end or "", record.available_at, record.path)


def _brief(record: Record) -> dict[str, Any]:
    return record.identity()


def _is_newer(rejected: dict[str, Any], selected: Record) -> bool:
    published = parse_decision_at(rejected["published_at"])
    return published > selected.published_at or (
        rejected.get("period_end") or ""
    ) > (selected.period_end or "")


def render_analyst_text(
    inst: Instrument,
    *,
    mode: str,
    decision_at: datetime,
    price_as_of: date,
    categories: list[Category],
    manifest_sha256: str,
) -> str:
    trade_date = graph_trade_date(inst.market, decision_at)
    lines = [
        "[[research-input]]",
        "Selection only. No filing, news, sentiment, or price feed was fetched for this bundle.",
        f"manifest_sha256: {manifest_sha256}",
        f"requested listing: {inst.canonical} market {inst.market} unit {inst.listing_unit}",
        inst.unit_note,
        f"mode: {mode}",
        f"decision_at: {_iso(decision_at)}",
        f"news_and_filing_cutoff: {_iso(decision_at)}",
        f"price_last_completed_session: {price_as_of.isoformat()}",
        f"framework_trade_date: {trade_date}",
        "News and filings are eligible through decision_at. Do not drop an item solely because",
        "price_last_completed_session is an earlier session.",
        "A generated summary is not an official source. Use source_url and original_urls.",
        "If a vendor withholds present-day fundamentals, the official_ir and hkex_summary",
        "sections below are still part of this analyst input.",
    ]
    for category in categories:
        lines.append(f"## {category.kind}")
        lines.append(f"status: {category.status}")
        for warning in category.warnings:
            lines.append(f"warning: {warning}")
        if category.newer_unavailable:
            lines.append(
                "newer_unavailable: a later file exists but was not published, captured, "
                "or otherwise available by the cutoff"
            )
        if category.selected is None:
            lines.append("MISSING: no eligible file. A fixed filename was not substituted.")
            continue
        record = category.selected
        lines.append(f"source_url: {record.source_url}")
        lines.append(f"currency: {record.currency}")
        lines.append(f"unit: {record.unit}")
        lines.append(f"period_end: {record.period_end or ''}")
        lines.append(f"published_at: {_iso(record.published_at)}")
        lines.append(f"available_at: {_iso(record.available_at)}")
        lines.append(f"captured_at: {_iso(record.captured_at)}")
        lines.append(f"provenance: {record.provenance}")
        lines.append(f"sha256: {record.sha256}")
        if record.generated:
            lines.append("generated_summary: true")
            lines.append("This text is a generated summary, not an official source.")
            lines.append("original_urls: " + ", ".join(record.original_urls))
        else:
            lines.append("generated_summary: false")
            lines.append(
                "This file is an extract. The official source is source_url, not this file."
            )
        if "BABA_2026-11-15" in Path(record.path).name:
            lines.append("selected_by: metadata, not by this filename")
        lines.append(record.body.rstrip())
    return "\n".join(lines).rstrip() + "\n"


def _producer_status(corpus: Path) -> dict[str, Any] | None:
    path = corpus / "producer_status.json"
    if not path.is_file():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("producer_status.json must be an object")
    return data


def _config_note(config_path: Path | None) -> dict[str, Any]:
    if config_path is None or not config_path.is_file():
        return {"config_path": str(config_path or ""), "config_present": False}
    raw = config_path.read_bytes()
    note: dict[str, Any] = {
        "config_path": str(config_path),
        "config_present": True,
        "config_sha256": hashlib.sha256(raw).hexdigest(),
    }
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        note["config_allowlist"] = {}
        return note
    allow = {}
    if isinstance(data, dict):
        for key in ("analysts", "output_language", "results_dir", "data_vendors"):
            if key in data:
                allow[key] = data[key]
    note["config_allowlist"] = allow
    return note


@dataclass(frozen=True)
class PreparedRun:
    symbol: str
    canonical: str
    market: str
    mode: str
    decision_at: datetime
    price_as_of: date
    graph_trade_date: str
    analyst_text: str
    manifest: dict[str, Any]
    run_dir: Path

    @property
    def marker(self) -> str:
        return self.analyst_text


def prepare_run(
    *,
    symbol: str,
    market: str | None,
    decision_at: str | datetime,
    mode: str,
    corpus: str | Path,
    runs_dir: str | Path,
    config_path: str | Path | None = None,
    holidays: Iterable[date] | None = None,
    news_stale_after: timedelta = NEWS_STALE_AFTER,
) -> PreparedRun:
    """Select eligible files and write a new run directory. Sources are only read."""
    if mode not in {"current", "historical"}:
        raise ValueError("mode must be current or historical")
    inst = resolve_instrument(symbol, market)
    cutoff = parse_decision_at(decision_at)
    corpus_path = Path(corpus)
    if not corpus_path.is_dir():
        raise FileNotFoundError(
            f"research corpus {corpus_path} does not exist; the producer must write it"
        )
    records, issues = scan_corpus(corpus_path)
    before = _tree_hashes(corpus_path)
    categories = select_records(records, inst, cutoff, news_stale_after=news_stale_after)
    price_as_of = last_completed_session(inst.market, cutoff, holidays)
    producer = _producer_status(corpus_path)
    missing = [c.kind for c in categories if c.status == "missing"]
    prerequisite = {
        "fetches_latest": False,
        "producer_invoked": False,
        "producer_last_success_at": None if producer is None else producer.get("last_success_at"),
        "missing_categories": missing,
        "detail": (
            "This run only selects files already in the corpus. It does not call "
            "options_digest.py, xueqiu_digest.py, ta_batch.py, or any filing or news "
            "source. If the latest official extract is absent, generating it is a "
            "producer prerequisite, not something this selection can do."
        ),
    }
    warnings = sorted({w for c in categories for w in c.warnings})
    if producer is None:
        warnings.append("producer_status_unknown")
    else:
        last = producer.get("last_success_at")
        if last and parse_decision_at(last) < cutoff:
            warnings.append("producer_not_run_for_decision")
    manifest_body = {
        "symbol": symbol,
        "canonical": inst.canonical,
        "market": inst.market,
        "company": inst.company,
        "listing_unit": inst.listing_unit,
        "quote_currency": inst.quote_currency,
        "ordinary_per_listing": inst.ordinary_per_listing,
        "mode": mode,
        "decision_at": _iso(cutoff),
        "timezone_comparison": "UTC",
        "price_as_of": price_as_of.isoformat(),
        "news_cutoff": _iso(cutoff),
        "financial_cutoff": _iso(cutoff),
        "framework_trade_date": graph_trade_date(inst.market, cutoff),
        "selection_rule": (
            "latest eligible by published_at, period_end, available_at, path; "
            "filename is not a key; capture age does not reject a published financial period"
        ),
        "financial_stale_policy": "publication and availability; capture age is not a rejection",
        "news_stale_policy": f"warn when the newest eligible item is older than {news_stale_after}",
        "categories": [_category_json(c) for c in categories],
        "unreadable": issues,
        "warnings": warnings,
        "freshness_prerequisite": prerequisite,
        "config": _config_note(None if config_path is None else Path(config_path)),
    }
    encoded = json.dumps(manifest_body, sort_keys=True, ensure_ascii=False).encode()
    manifest_body["manifest_sha256"] = hashlib.sha256(encoded).hexdigest()
    analyst_text = render_analyst_text(
        inst, mode=mode, decision_at=cutoff, price_as_of=price_as_of,
        categories=categories, manifest_sha256=manifest_body["manifest_sha256"],
    )
    run_dir = _write_run(Path(runs_dir), inst, cutoff, manifest_body, analyst_text, categories)
    after = _tree_hashes(corpus_path)
    if after != before:
        raise RuntimeError("corpus changed while selecting; sources must stay untouched")
    return PreparedRun(
        symbol=symbol,
        canonical=inst.canonical,
        market=inst.market,
        mode=mode,
        decision_at=cutoff,
        price_as_of=price_as_of,
        graph_trade_date=graph_trade_date(inst.market, cutoff),
        analyst_text=analyst_text,
        manifest=manifest_body,
        run_dir=run_dir,
    )


def _category_json(category: Category) -> dict[str, Any]:
    return {
        "kind": category.kind,
        "status": category.status,
        "warnings": list(category.warnings),
        "selected": None if category.selected is None else category.selected.identity(),
        "rejected": category.rejected,
        "newer_unavailable": category.newer_unavailable,
        "older_eligible": category.older_eligible,
    }


def _tree_hashes(root: Path) -> dict[str, str]:
    hashes = {}
    for path in sorted(root.rglob("*")):
        if path.is_file():
            hashes[str(path.resolve())] = hashlib.sha256(path.read_bytes()).hexdigest()
    return hashes


def _exclusive_write(path: Path, data: bytes) -> None:
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    try:
        os.write(fd, data)
    finally:
        os.close(fd)


def _write_run(
    runs_root: Path,
    inst: Instrument,
    cutoff: datetime,
    manifest: dict[str, Any],
    analyst_text: str,
    categories: list[Category],
) -> Path:
    runs_root.mkdir(parents=True, exist_ok=True)
    stamp = cutoff.astimezone(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    partial = runs_root / f"{inst.canonical}_{stamp}_{uuid.uuid4().hex[:8]}.partial"
    partial.mkdir(exist_ok=False)
    inputs = partial / "inputs"
    inputs.mkdir()
    copied: set[str] = set()
    for category in categories:
        record = category.selected
        if record is None or record.sha256 in copied:
            continue
        copied.add(record.sha256)
        name = f"{record.sha256[:12]}_{Path(record.path).name}"
        _exclusive_write(inputs / name, Path(record.path).read_bytes())
    _exclusive_write(
        partial / "input_manifest.json",
        json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False).encode(),
    )
    state = analyst_input_state(inst.canonical, graph_trade_date(inst.market, cutoff), analyst_text)
    _exclusive_write(
        partial / "full_state.json",
        json.dumps(state, indent=2, ensure_ascii=False).encode(),
    )
    final = partial.with_name(partial.name.removesuffix(".partial"))
    return partial.rename(final)


def analyst_input_state(canonical: str, trade_date: str, analyst_text: str) -> dict[str, Any]:
    """Initial graph state whose messages are what each analyst is given."""
    return {
        "company_of_interest": canonical,
        "trade_date": trade_date,
        "asset_type": "stock",
        "instrument_context": "",
        "messages": [
            {"type": "human", "content": canonical},
            {"type": "human", "content": analyst_text},
        ],
    }


def inject_research_messages(state: dict[str, Any], analyst_text: str) -> dict[str, Any]:
    """Append the bundle to the message list the analysts already receive."""
    updated = dict(state)
    messages = list(state.get("messages") or [])
    messages.append(("human", analyst_text))
    updated["messages"] = messages
    return updated


def install_research_state(graph: Any, analyst_text: str):
    """Wrap ``create_run_state`` so propagate() carries the bundle in messages."""
    original = graph.create_run_state

    def wrapped(*args, **kwargs):
        return inject_research_messages(original(*args, **kwargs), analyst_text)

    graph.create_run_state = wrapped
    return original


def retained_runs(runs_dir: Path) -> list[Path]:
    """Completed run directories, oldest name first. Nothing here deletes them."""
    if not runs_dir.is_dir():
        return []
    return sorted(
        path for path in runs_dir.iterdir()
        if path.is_dir() and not path.name.endswith(".partial")
    )
