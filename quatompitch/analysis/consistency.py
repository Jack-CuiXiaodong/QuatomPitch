"""会计恒等式与跨源一致性校验。

只做确定性的算术核对，不做任何主观判断：等式两边算出来对不上就如实报差额，
至于差额意味着什么，交给下游大模型结合报表原文去解释。

这一层的价值在于**让映射错误自己暴露**。例如把只含管理费用的标签当成合并
销管费，营业利润的残差会一下子跳到营收的 20% 以上，而单看那个数字完全正常。
"""
from __future__ import annotations

from typing import Optional

from ..models import FinancialPeriod
from ..models.quality import DIFF, OK, SKIP, ConsistencyCheck

# 相对容差：会计报表是精确值，差异超过营收的这个比例就认为不是舍入误差
_TOL_PCT = 0.5
# 营业利润残差超过营收的这个比例，基本可以断定漏了某个大额费用科目
_RESIDUAL_ALERT_PCT = 3.0


def _pct_of(value: Optional[float], base: Optional[float]) -> Optional[float]:
    if value is None or not base:
        return None
    return abs(value) / abs(base) * 100


def _check(
    name: str, period: str, scope: str,
    expected_label: str, expected: Optional[float],
    actual_label: str, actual: Optional[float],
    base: Optional[float], tol_pct: float = _TOL_PCT,
    note: Optional[str] = None,
) -> ConsistencyCheck:
    """构造一条校验：expected 是按等式推算的值，actual 是申报值。"""
    c = ConsistencyCheck(
        name=name, period=period, scope=scope,
        expected_label=expected_label, expected=expected,
        actual_label=actual_label, actual=actual, note=note,
    )
    if expected is None or actual is None:
        c.status = SKIP
        c.note = c.note or "缺少必要科目"
        return c
    c.diff = actual - expected
    c.diff_pct = _pct_of(c.diff, base)
    if c.diff_pct is None:
        # 没有营收做基数时退回按绝对值比较两边量级
        ref = max(abs(expected), abs(actual), 1.0)
        c.diff_pct = abs(c.diff) / ref * 100
    c.status = OK if c.diff_pct <= tol_pct else DIFF
    return c


def _opex_sum(p: FinancialPeriod) -> Optional[float]:
    """已归类的营业费用合计。

    销管费有两种申报法：合并报 SG&A，或拆成销售营销 + 管理费用。两者互斥，
    这里取实际有值的那一种，避免重复计入。
    """
    parts = [p.rnd_expense]
    if p.sga_expense is not None:
        parts.append(p.sga_expense)
    else:
        parts.extend([p.selling_marketing_expense, p.general_admin_expense])
    known = [x for x in parts if x is not None]
    return sum(known) if known else None


def _check_period(p: FinancialPeriod) -> list[ConsistencyCheck]:
    """对单期做会计恒等式校验。"""
    out: list[ConsistencyCheck] = []
    scope = "XBRL 内部"
    rev = p.revenue

    # 毛利 = 营收 − 营业成本
    expected = (
        rev - p.cost_of_revenue
        if rev is not None and p.cost_of_revenue is not None else None
    )
    out.append(_check(
        "毛利 = 营收 − 营业成本", p.fiscal_date, scope,
        "营收 − 营业成本", expected, "申报毛利", p.gross_profit, rev,
    ))

    # 净利润 = 税前利润 − 所得税
    expected = (
        p.pretax_income - p.income_tax_expense
        if p.pretax_income is not None and p.income_tax_expense is not None else None
    )
    out.append(_check(
        "净利润 = 税前利润 − 所得税", p.fiscal_date, scope,
        "税前利润 − 所得税", expected, "申报净利润", p.net_income, rev,
    ))

    # 总资产 = 总负债 + 股东权益
    expected = (
        p.total_liabilities + p.total_equity
        if p.total_liabilities is not None and p.total_equity is not None else None
    )
    out.append(_check(
        "总资产 = 总负债 + 股东权益", p.fiscal_date, scope,
        "总负债 + 股东权益", expected, "申报总资产", p.total_assets,
        p.total_assets,
        note="差额通常来自少数股东权益：若权益标签取的是不含少数股东的口径，两边就对不上",
    ))

    # 营业利润残差：毛利 − 已归类费用 − 申报营业利润
    # 残差本身不一定是错——摊销、重组、减值等科目未被归类很正常；
    # 但残差一旦大到营收的百分之几，多半是漏了某个大额费用标签。
    opex = _opex_sum(p)
    if p.gross_profit is not None and opex is not None and p.operating_income is not None:
        residual = p.gross_profit - opex - p.operating_income
        c = ConsistencyCheck(
            name="营业利润残差 = 毛利 − 已归类营业费用 − 申报营业利润",
            period=p.fiscal_date, scope=scope,
            expected_label="毛利 − 已归类费用", expected=p.gross_profit - opex,
            actual_label="申报营业利润", actual=p.operating_income,
            diff=-residual, diff_pct=_pct_of(residual, rev),
        )
        if c.diff_pct is None:
            c.status = SKIP
        elif c.diff_pct > _RESIDUAL_ALERT_PCT:
            c.status = DIFF
            c.note = ("残差过大，很可能有大额营业费用科目未被采集到"
                      "（可对照本报告「三大报表原文」一节的利润表逐行核对）")
        else:
            c.status = OK
            c.note = "残差属正常范围，一般是摊销/重组等未单独归类的科目"
        out.append(c)

    return out


def _cross_source(
    xbrl: list[FinancialPeriod], yf: list[FinancialPeriod]
) -> list[ConsistencyCheck]:
    """同一报告期下 XBRL 与 yfinance 的关键科目对照。"""
    by_date = {p.fiscal_date: p for p in yf}
    fields = [
        ("营收", "revenue"),
        ("净利润", "net_income"),
        ("总资产", "total_assets"),
        ("股东权益", "total_equity"),
        ("经营现金流", "operating_cash_flow"),
    ]
    out: list[ConsistencyCheck] = []
    for xp in xbrl:
        yp = by_date.get(xp.fiscal_date)
        if yp is None:
            continue
        for label, attr in fields:
            a, b = getattr(xp, attr), getattr(yp, attr)
            if a is None or b is None:
                continue
            out.append(_check(
                f"{label}：XBRL vs yfinance", xp.fiscal_date, "跨源比对",
                "SEC XBRL", a, "yfinance", b, xp.revenue or a,
                note="以 SEC 为准；差异多因 yfinance 的科目归类口径不同",
            ))
    return out


def run_checks(
    xbrl_annual: list[FinancialPeriod],
    yf_annual: list[FinancialPeriod] | None = None,
    max_periods: int = 3,
) -> list[ConsistencyCheck]:
    """跑全部校验。只校验最近几期——越老的期次参考价值越低，且会撑大报告。"""
    periods = (xbrl_annual or [])[:max_periods]
    checks: list[ConsistencyCheck] = []
    for p in periods:
        checks.extend(_check_period(p))
    checks.extend(_cross_source(periods, yf_annual or []))
    return checks
