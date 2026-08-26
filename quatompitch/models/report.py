"""报告聚合对象：一次分析产出的全部数据集合。"""
from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field

from .company import Company, Quote
from .financials import FinancialPeriod, Valuation
from .insider import Filing, InsiderTrade, MacroIndicator, NewsItem


class ResearchReport(BaseModel):
    ticker: str
    generated_at: str

    company: Optional[Company] = None
    quote: Optional[Quote] = None
    valuation: Optional[Valuation] = None

    annual_financials: List[FinancialPeriod] = Field(default_factory=list)
    quarterly_financials: List[FinancialPeriod] = Field(default_factory=list)

    insider_trades: List[InsiderTrade] = Field(default_factory=list)
    filings: List[Filing] = Field(default_factory=list)
    news: List[NewsItem] = Field(default_factory=list)
    macro: List[MacroIndicator] = Field(default_factory=list)

    # 采集过程中的告警（某数据源失败时记录，写入报告脚注）
    warnings: List[str] = Field(default_factory=list)
