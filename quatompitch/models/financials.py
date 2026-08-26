"""财务数据领域模型。"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


class FinancialPeriod(BaseModel):
    """单期财务快照（年度或季度）。"""

    period_type: str  # "FY" 年度 / "FQ" 季度
    fiscal_date: str  # 财报截止日 YYYY-MM-DD
    currency: Optional[str] = "USD"

    # 利润表
    revenue: Optional[float] = None
    gross_profit: Optional[float] = None
    operating_income: Optional[float] = None
    ebitda: Optional[float] = None
    net_income: Optional[float] = None
    eps_basic: Optional[float] = None
    eps_diluted: Optional[float] = None

    # 资产负债表
    total_assets: Optional[float] = None
    total_liabilities: Optional[float] = None
    total_equity: Optional[float] = None
    total_debt: Optional[float] = None
    cash_and_equivalents: Optional[float] = None
    shares_outstanding: Optional[float] = None

    # 现金流量表
    operating_cash_flow: Optional[float] = None
    capital_expenditure: Optional[float] = None
    free_cash_flow: Optional[float] = None

    source: Optional[str] = None  # yfinance / sec


class Valuation(BaseModel):
    """估值指标（作为数据写入报告，不做筛选打分）。"""

    ticker: str
    as_of_date: str
    pe_trailing: Optional[float] = None
    pe_forward: Optional[float] = None
    roe: Optional[float] = None
    ev_ebitda: Optional[float] = None
    pb: Optional[float] = None
    ps: Optional[float] = None
    peg: Optional[float] = None
    gross_margin: Optional[float] = None
    net_margin: Optional[float] = None
    debt_to_equity: Optional[float] = None
    current_ratio: Optional[float] = None
    enterprise_value: Optional[float] = None
