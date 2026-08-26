"""估值指标计算：优先用财报自算，缺失则回退 yfinance 现成指标。

注意：本模块只把指标作为"数据"算出来写进报告，不做任何低估值筛选/打分。
"""
from __future__ import annotations

from datetime import date
from typing import Optional

from ..models import FinancialPeriod, Quote, Valuation


def _safe_div(a: Optional[float], b: Optional[float]) -> Optional[float]:
    if a is None or b is None or b == 0:
        return None
    return a / b


def compute_valuation(
    ticker: str,
    quote: Optional[Quote],
    annual: list[FinancialPeriod],
    info_metrics: dict | None = None,
) -> Valuation:
    info_metrics = info_metrics or {}
    latest: Optional[FinancialPeriod] = annual[0] if annual else None

    price = quote.price if quote else None
    market_cap = quote.market_cap if quote else None

    # --- 自算指标 ---
    roe = None
    ev_ebitda = None
    ps = None
    pb = None
    enterprise_value = info_metrics.get("enterpriseValue")

    if latest:
        roe = _safe_div(latest.net_income, latest.total_equity)

        if enterprise_value is None and market_cap is not None:
            debt = latest.total_debt or 0.0
            cash = latest.cash_and_equivalents or 0.0
            enterprise_value = market_cap + debt - cash
        ev_ebitda = _safe_div(enterprise_value, latest.ebitda)

        ps = _safe_div(market_cap, latest.revenue)

        if latest.total_equity and latest.shares_outstanding:
            book_per_share = _safe_div(latest.total_equity, latest.shares_outstanding)
            pb = _safe_div(price, book_per_share)

    # --- 回退 yfinance 现成指标 ---
    def pct(v):
        return v * 100 if v is not None else None

    val = Valuation(
        ticker=ticker.upper(),
        as_of_date=date.today().isoformat(),
        pe_trailing=info_metrics.get("trailingPE"),
        pe_forward=info_metrics.get("forwardPE"),
        roe=(roe * 100 if roe is not None else pct(info_metrics.get("returnOnEquity"))),
        ev_ebitda=(ev_ebitda if ev_ebitda is not None else info_metrics.get("enterpriseToEbitda")),
        pb=(pb if pb is not None else info_metrics.get("priceToBook")),
        ps=(ps if ps is not None else info_metrics.get("priceToSalesTrailing12Months")),
        peg=info_metrics.get("pegRatio"),
        gross_margin=pct(info_metrics.get("grossMargins")),
        net_margin=pct(info_metrics.get("profitMargins")),
        debt_to_equity=info_metrics.get("debtToEquity"),
        current_ratio=info_metrics.get("currentRatio"),
        enterprise_value=enterprise_value,
    )
    return val
