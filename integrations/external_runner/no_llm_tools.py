"""Stdlib stand-in for the three tool functions the synthetic suite calls.

The acceptance archive copies this file to tradingagents/agents/tools.py.
Those functions forward to route_to_vendor. They do not import LangChain
and they do not read the checkout.
"""

def route_to_vendor(method, *args, **kwargs):
    raise RuntimeError("route_to_vendor was not replaced")


def _stock(symbol, start_date, end_date, trade_date=""):
    return route_to_vendor("get_stock_data", symbol, start_date, end_date)


def _news(ticker, start_date, end_date, trade_date=""):
    return route_to_vendor("get_news", ticker, start_date, end_date)


def _fundamentals(ticker, curr_date, trade_date=""):
    return route_to_vendor("get_fundamentals", ticker, curr_date)


class _Tool:
    def __init__(self, func):
        self.func = func


get_stock_data = _Tool(_stock)
get_news = _Tool(_news)
get_fundamentals = _Tool(_fundamentals)
