"""报告聚合对象：一次分析产出的全部数据集合。"""
from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field

from .company import Company, Quote
from .financials import FinancialPeriod, Valuation
from .documents import FilingDocument, StatementTable
from .insider import Filing, InsiderTrade, MacroIndicator, NewsItem


class ResearchReport(BaseModel):
    ticker: str
    generated_at: str

    company: Optional[Company] = None
    quote: Optional[Quote] = None
    valuation: Optional[Valuation] = None

    annual_financials: List[FinancialPeriod] = Field(default_factory=list)
    quarterly_financials: List[FinancialPeriod] = Field(default_factory=list)

    # SEC XBRL 官方财务数据（与 yfinance 并列，可交叉验证）
    xbrl_annual: List[FinancialPeriod] = Field(default_factory=list)
    xbrl_quarterly: List[FinancialPeriod] = Field(default_factory=list)

    insider_trades: List[InsiderTrade] = Field(default_factory=list)
    filings: List[Filing] = Field(default_factory=list)

    # 报送正文抽取（10-K / 10-Q / 8-K）与财报附注表（分部、分产品收入）
    filing_documents: List[FilingDocument] = Field(default_factory=list)
    statement_tables: List[StatementTable] = Field(default_factory=list)

    news: List[NewsItem] = Field(default_factory=list)
    macro: List[MacroIndicator] = Field(default_factory=list)

    # 采集过程中的告警（某数据源失败时记录，写入报告脚注）
    warnings: List[str] = Field(default_factory=list)
