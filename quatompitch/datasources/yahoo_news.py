"""Yahoo Finance 舆情：优先 yfinance.news，失败则 RSS 兜底。免 API key。"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import feedparser
import yfinance as yf

from ..models import NewsItem
from .base import DataSource

RSS_URL = "https://feeds.finance.yahoo.com/rss/2.0/headline?s={ticker}&region=US&lang=en-US"


def _ts_to_date(ts: Any) -> str | None:
    try:
        return datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
    except (TypeError, ValueError, OSError):
        return None


class YahooNewsSource(DataSource):
    name = "news"

    def __init__(self, limit: int = 12) -> None:
        self.limit = limit

    def fetch(self, ticker: str) -> dict[str, Any]:
        items = self._from_yfinance(ticker)
        if not items:
            items = self._from_rss(ticker)
        return {"news": items[: self.limit]}

    def _from_yfinance(self, ticker: str) -> list[NewsItem]:
        out: list[NewsItem] = []
        try:
            raw = yf.Ticker(ticker).news or []
        except Exception:
            return out
        for n in raw:
            # yfinance 新版把字段放在 content 下，旧版是扁平结构，两者都兼容
            content = n.get("content", n)
            title = content.get("title")
            if not title:
                continue
            provider = content.get("provider", {})
            pub = (
                provider.get("displayName")
                if isinstance(provider, dict)
                else n.get("publisher")
            )
            url = None
            cu = content.get("canonicalUrl") or content.get("clickThroughUrl")
            if isinstance(cu, dict):
                url = cu.get("url")
            url = url or n.get("link")
            pub_date = content.get("pubDate") or _ts_to_date(n.get("providerPublishTime"))
            out.append(
                NewsItem(
                    ticker=ticker.upper(),
                    title=title,
                    publisher=pub,
                    published_at=pub_date,
                    url=url,
                    summary=content.get("summary"),
                )
            )
        return out

    def _from_rss(self, ticker: str) -> list[NewsItem]:
        out: list[NewsItem] = []
        try:
            feed = feedparser.parse(RSS_URL.format(ticker=ticker))
        except Exception:
            return out
        for e in feed.entries:
            out.append(
                NewsItem(
                    ticker=ticker.upper(),
                    title=e.get("title", ""),
                    publisher=e.get("source", {}).get("title") if e.get("source") else "Yahoo Finance",
                    published_at=e.get("published"),
                    url=e.get("link"),
                    summary=e.get("summary"),
                )
            )
        return out
