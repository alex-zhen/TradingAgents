# Hotfix for the live runner

Do not install `research_ingest.py` as `run_ta.py`. That selector rejects plain
markdown, returns None, and only accepts five hardcoded symbols.

The live script starts:

```python
import sys, os, json, re, pathlib
sys.path.insert(0, '/workspace/tradingagents')
import tradingagents.agents.tools as T
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.graph.trading_graph import TradingAgentsGraph
TICKER = sys.argv[1]; DATE = sys.argv[2] if len(sys.argv)>2 else '2026-11-13'
```

Replace only the pinned digest block. `run_ta_hotfix.diff` is that replacement.
`sent_path.exists()` stays. `sent_path` stays a path. The route hook, options
block, xueqiu wrap, and `propagate(TICKER, DATE)` stay.

```python
sent_path=RUN/f'sentiment_digest_{TICKER}_{DATE}.md'
sent=sent_path.read_text() if sent_path.exists() else (
    f'MISSING sentiment_digest_{TICKER}_{DATE}.md in {RUN}. '
    'No older file was substituted. This run did not fetch a replacement.'
)
sent_block=sent
```

There is no glob and no symbol whitelist. `0700`, `BABA`, `LI`, `NVDA`,
`0981`, `601169`, and `601398` use the same filename pattern. The markdown is
copied into the `get_news` tool result as written, including its URLs and
dates. A manifest at `{TICKER}_{DATE}/digest_manifest.json` records path,
sha256, mtime, and date. `fetched` is false.

If the live file has more options or xueqiu code than the verbatim excerpt,
paste this block in place. Do not overwrite that extra code with the test
wrapper.

This does not fetch. See `PRODUCER.md` for the command the parent runs first.
If `sentiment_digest_{TICKER}_{DATE}.md` is absent, the run stays MISSING.
