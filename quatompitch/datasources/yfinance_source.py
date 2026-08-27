"""yfinance 数据源：公司信息、实时行情、三大报表。免 API key。"""
from __future__ import annotations

from typing import Any, Optional

import pandas as pd
import yfinance as yf

from ..models import Company, FinancialPeriod, Quote
from .base import DataSource
from .issues import IssueLog


def _num(v: Any) -> Optional[float]:
    """安全转 float：NaN / None / 非数值 → None。"""
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if pd.isna(f):
        return None
    return f


def _row(df: Optional[pd.DataFrame], col, *labels: str) -> Optional[float]:
    """从财报 DataFrame 中按多个候选行名取某一列（某一期）的值。"""
    if df is None or df.empty or col not in df.columns:
        return None
    for label in labels:
        if label in df.index:
            return _num(df.loc[label, col])
    return None


def _periods_from_statements(
    income: Optional[pd.DataFrame],
    balance: Optional[pd.DataFrame],
    cashflow: Optional[pd.DataFrame],
    period_type: str,
) -> list[FinancialPeriod]:
    """把三张报表按报告期（列）对齐，组装成 FinancialPeriod 列表。"""
    if income is None or income.empty:
        return []

    periods: list[FinancialPeriod] = []
    for col in income.columns:
        try:
            fiscal_date = pd.Timestamp(col).strftime("%Y-%m-%d")
        except Exception:
            fiscal_date = str(col)

        p = FinancialPeriod(
            period_type=period_type,
            fiscal_date=fiscal_date,
            source="yfinance",
            revenue=_row(income, col, "Total Revenue", "Revenue"),
            gross_profit=_row(income, col, "Gross Profit"),
            operating_income=_row(income, col, "Operating Income", "Operating Income Loss"),
            ebitda=_row(income, col, "EBITDA", "Normalized EBITDA"),
            net_income=_row(income, col, "Net Income", "Net Income Common Stockholders"),
            eps_basic=_row(income, col, "Basic EPS"),
            eps_diluted=_row(income, col, "Diluted EPS"),
            total_assets=_row(balance, col, "Total Assets"),
            total_liabilities=_row(
                balance, col, "Total Liabilities Net Minority Interest",
                "Total Liabilities",
            ),
            total_equity=_row(
                balance, col, "Stockholders Equity", "Total Equity Gross Minority Interest",
                "Common Stock Equity",
            ),
            total_debt=_row(balance, col, "Total Debt"),
            cash_and_equivalents=_row(
                balance, col, "Cash And Cash Equivalents",
                "Cash Cash Equivalents And Short Term Investments",
            ),
            shares_outstanding=_row(
                balance, col, "Ordinary Shares Number", "Share Issued",
            ),
            operating_cash_flow=_row(cashflow, col, "Operating Cash Flow", "Cash Flow From Continuing Operating Activities"),
            capital_expenditure=_row(cashflow, col, "Capital Expenditure"),
            free_cash_flow=_row(cashflow, col, "Free Cash Flow"),
        )
        periods.append(p)
    return periods


class YFinanceSource(DataSource):
    name = "yfinance"

    def fetch(self, ticker: str) -> dict[str, Any]:
        t = yf.Ticker(ticker)
        issues = IssueLog("yfinance 行情与财报")
        info = {}
        try:
            info = t.info or {}
        except Exception as e:
            # info 挂掉意味着公司信息、行情、以及全部现成估值指标都没了，
            # 静默返回空字典会让报告看起来像「这家公司没有行情」。
            issues.record("公司信息与行情（info）获取失败", e)

        company = Company(
            ticker=ticker.upper(),
            name=info.get("longName") or info.get("shortName"),
            sector=info.get("sector"),
            industry=info.get("industry"),
            exchange=info.get("exchange") or info.get("fullExchangeName"),
            country=info.get("country"),
            website=info.get("website"),
            employees=info.get("fullTimeEmployees"),
            description=info.get("longBusinessSummary"),
        )

        quote = Quote(
            ticker=ticker.upper(),
            price=_num(info.get("currentPrice") or info.get("regularMarketPrice")),
            currency=info.get("currency"),
            market_cap=_num(info.get("marketCap")),
            shares_outstanding=_num(info.get("sharesOutstanding")),
            day_high=_num(info.get("dayHigh")),
            day_low=_num(info.get("dayLow")),
            week52_high=_num(info.get("fiftyTwoWeekHigh")),
            week52_low=_num(info.get("fiftyTwoWeekLow")),
            avg_volume=_num(info.get("averageVolume")),
            beta=_num(info.get("beta")),
            dividend_yield=_num(info.get("dividendYield")),
        )

        # 三大报表（年度 + 季度）。yfinance 是抓取式接口，偶发整片返回空，
        # 每张表单独记录失败，避免「抓取失败」和「公司没披露」混为一谈。
        annual = _periods_from_statements(
            _safe(lambda: t.income_stmt, issues, "年度利润表"),
            _safe(lambda: t.balance_sheet, issues, "年度资产负债表"),
            _safe(lambda: t.cashflow, issues, "年度现金流量表"),
            "FY",
        )
        quarterly = _periods_from_statements(
            _safe(lambda: t.quarterly_income_stmt, issues, "季度利润表"),
            _safe(lambda: t.quarterly_balance_sheet, issues, "季度资产负债表"),
            _safe(lambda: t.quarterly_cashflow, issues, "季度现金流量表"),
            "FQ",
        )

        # yfinance 提供的部分现成指标（作为兜底/交叉验证）
        info_metrics = {
            "trailingPE": _num(info.get("trailingPE")),
            "forwardPE": _num(info.get("forwardPE")),
            "priceToBook": _num(info.get("priceToBook")),
            "priceToSalesTrailing12Months": _num(info.get("priceToSalesTrailing12Months")),
            "enterpriseToEbitda": _num(info.get("enterpriseToEbitda")),
            "returnOnEquity": _num(info.get("returnOnEquity")),
            "pegRatio": _num(info.get("trailingPegRatio") or info.get("pegRatio")),
            "enterpriseValue": _num(info.get("enterpriseValue")),
            "grossMargins": _num(info.get("grossMargins")),
            "profitMargins": _num(info.get("profitMargins")),
            "debtToEquity": _num(info.get("debtToEquity")),
            "currentRatio": _num(info.get("currentRatio")),
        }

        out: dict[str, Any] = {
            "company": company,
            "quote": quote,
            "annual_financials": annual,
            "quarterly_financials": quarterly,
            "info_metrics": info_metrics,
        }
        if issues:
            out["warning"] = issues.as_warning()
        return out


def _safe(fn, issues: IssueLog, what: str):
    """调用可能抛异常的 yfinance 属性访问。

    失败返回 None，但**必须留痕**：拿不到报表和公司没有报表是两回事。
    """
    try:
        return fn()
    except Exception as e:
        issues.record(f"{what}获取失败", e)
        return None
