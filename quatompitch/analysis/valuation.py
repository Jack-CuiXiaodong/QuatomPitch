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
        # ROE 用**平均**股东权益：净利润是期间数、权益是时点数，直接除期末权益
        # 会在权益快速增长的公司上系统性压低 ROE（DUOL 2025 权益从 8.2 亿涨到
        # 13.5 亿，期末口径算出来比平均口径低约 7 个百分点）。拿不到上一期时
        # 退回期末口径。
        prior = annual[1] if len(annual) > 1 else None
        if latest.total_equity and prior and prior.total_equity:
            avg_equity = (latest.total_equity + prior.total_equity) / 2
        else:
            avg_equity = latest.total_equity
        roe = _safe_div(latest.net_income, avg_equity)

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

    fy = f"FY{latest.fiscal_date[:4]}" if latest else "最近财年"
    bases: dict[str, str] = {}

    def pick(self_computed, fallback_key: str, key: str, self_desc: str,
             fallback_desc: str = "TTM · yfinance 现成值", fallback_transform=None):
        """自算优先、yfinance 兜底，并记录该指标实际用的口径。

        fallback_transform 用于单位换算：yfinance 的比率型字段（如
        returnOnEquity）是小数，报告里统一按百分数展示。
        """
        if self_computed is not None:
            bases[key] = self_desc
            return self_computed
        v = info_metrics.get(fallback_key)
        if v is None:
            return None
        bases[key] = fallback_desc
        return fallback_transform(v) if fallback_transform else v

    roe_pct = roe * 100 if roe is not None else None
    equity_desc = "平均股东权益" if (latest and len(annual) > 1) else "期末股东权益"

    val = Valuation(
        ticker=ticker.upper(),
        as_of_date=date.today().isoformat(),
        pe_trailing=info_metrics.get("trailingPE"),
        pe_forward=info_metrics.get("forwardPE"),
        roe=pick(roe_pct, "returnOnEquity", "roe",
                 f"{fy} 自算：净利润 ÷ {equity_desc}", fallback_transform=pct),
        ev_ebitda=pick(ev_ebitda, "enterpriseToEbitda", "ev_ebitda",
                       f"EV ÷ {fy} EBITDA（GAAP 口径，非公司披露的 Adjusted EBITDA）"),
        pb=pick(pb, "priceToBook", "pb", f"现价 ÷ {fy} 每股净资产"),
        ps=pick(ps, "priceToSalesTrailing12Months", "ps", f"市值 ÷ {fy} 营收"),
        peg=info_metrics.get("pegRatio"),
        gross_margin=pct(info_metrics.get("grossMargins")),
        net_margin=pct(info_metrics.get("profitMargins")),
        debt_to_equity=info_metrics.get("debtToEquity"),
        current_ratio=info_metrics.get("currentRatio"),
        enterprise_value=enterprise_value,
    )
    # 其余指标一律来自 yfinance 现成字段，口径固定
    bases.setdefault("pe_trailing", "TTM · yfinance 现成值")
    bases.setdefault("pe_forward", "分析师预期 · yfinance")
    bases.setdefault("peg", "TTM · yfinance 现成值")
    bases.setdefault("gross_margin", "TTM · yfinance 现成值")
    bases.setdefault("net_margin", "TTM · yfinance 现成值")
    bases.setdefault("current_ratio", "最近季度 · yfinance")
    bases.setdefault(
        "debt_to_equity", "最近季度 · yfinance（原始值为百分数，此处按百分比显示）"
    )
    bases.setdefault(
        "enterprise_value",
        "yfinance 现成值" if info_metrics.get("enterpriseValue") is not None
        else f"自算：市值 + {fy} 总债务 − {fy} 现金",
    )
    val.bases = bases
    return val
