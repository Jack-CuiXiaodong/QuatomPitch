"""关键数据速览。

报告动辄 5～15 万 token，模型需要一个锚点。这里把最常用的十几个数字抽出来放在
开头——但它**只是索引，不是结论**：每个数字在正文都有出处、口径和更完整的上下文。

严格限制在算术范围内：同比、利润率这类由本期数据直接算出的值。不做评价、不做
筛选、不做预测——那些是下游模型的事。

数据一律优先取 SEC XBRL；XBRL 整片缺失时退回 yfinance，并在报告里标明来源。
"""
from __future__ import annotations

from typing import Optional

from ..models import FinancialPeriod, ResearchReport
from ..models.quality import DIFF


def _yoy(cur: Optional[float], prev: Optional[float]) -> Optional[float]:
    """同比增速（%）。

    基数为零或为负时增速没有意义（由亏转盈算出来的百分数会严重误导），
    这种情况返回 None，报告里渲染成 `—`。
    """
    if cur is None or prev is None or prev <= 0:
        return None
    return (cur - prev) / prev * 100


def _ratio_pct(part: Optional[float], whole: Optional[float]) -> Optional[float]:
    if part is None or not whole:
        return None
    return part / whole * 100


def _prior_same_quarter(
    quarters: list[FinancialPeriod], latest: FinancialPeriod
) -> Optional[FinancialPeriod]:
    """找去年同一财季。按财季标签匹配，而不是简单往前数四个——
    季度序列可能有缺失，数位置会对错期。"""
    if not latest.fiscal_period:
        return None
    for p in quarters:
        if p is latest:
            continue
        if p.fiscal_period == latest.fiscal_period and p.fiscal_date < latest.fiscal_date:
            return p
    return None


def build_overview(report: ResearchReport) -> dict:
    """从已组装好的报告里提炼速览。返回普通 dict，模板直接取用。"""
    annual = report.xbrl_annual or report.annual_financials
    quarterly = report.xbrl_quarterly or report.quarterly_financials
    source = "SEC XBRL" if report.xbrl_annual else (
        "yfinance" if report.annual_financials else None
    )

    fy = annual[0] if annual else None
    fy_prev = annual[1] if len(annual) > 1 else None
    fq = quarterly[0] if quarterly else None
    fq_prev = _prior_same_quarter(quarterly, fq) if fq else None

    # 内部人交易只统计普通股：衍生品与普通股是同一事件的两条腿，相加会重复计数
    common = [t for t in report.insider_trades if not t.is_derivative]
    buys = [t for t in common if t.acquired_disposed == "A"]
    sells = [t for t in common if t.acquired_disposed == "D"]
    # 只有 P 才是真正的公开市场买入（A 授予 / M 行权 / F 扣税都不是主动买）
    open_market_buys = [t for t in common if t.transaction_code == "P"]

    def _latest_filing(form: str) -> Optional[str]:
        for f in report.filings:
            if f.form_type == form:
                return f.filing_date
        return None

    checks = report.consistency
    return {
        "source": source,
        # --- 最新财年 ---
        "fy": fy,
        "fy_revenue_yoy": _yoy(fy.revenue, fy_prev.revenue) if fy and fy_prev else None,
        "fy_net_income_yoy": (
            _yoy(fy.net_income, fy_prev.net_income) if fy and fy_prev else None
        ),
        "fy_gross_margin": _ratio_pct(fy.gross_profit, fy.revenue) if fy else None,
        "fy_operating_margin": _ratio_pct(fy.operating_income, fy.revenue) if fy else None,
        "fy_net_margin": _ratio_pct(fy.net_income, fy.revenue) if fy else None,
        # --- 最新财季 ---
        "fq": fq,
        "fq_prev": fq_prev,
        "fq_revenue_yoy": _yoy(fq.revenue, fq_prev.revenue) if fq and fq_prev else None,
        "fq_net_income_yoy": (
            _yoy(fq.net_income, fq_prev.net_income) if fq and fq_prev else None
        ),
        # --- 报送时点 ---
        "latest_10k": _latest_filing("10-K"),
        "latest_10q": _latest_filing("10-Q"),
        "latest_8k": _latest_filing("8-K"),
        # --- 内部人（仅普通股）---
        "insider_buys": len(buys),
        "insider_sells": len(sells),
        "insider_open_market_buys": len(open_market_buys),
        "insider_net_shares": (
            sum(t.shares or 0 for t in buys) - sum(t.shares or 0 for t in sells)
        ) if common else None,
        # --- 数据完整性 ---
        "checks_total": len(checks),
        "checks_failed": sum(1 for c in checks if c.status == DIFF),
        "primary_statements": len(report.primary_statements),
        "filing_text_chars": sum(d.total_chars for d in report.filing_documents),
        "blocking_warnings": len(report.blocking_warnings),
    }
