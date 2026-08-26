"""读写封装：把领域模型持久化到 SQLite，并提供当日缓存判断。"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from ..models import (
    Company,
    Filing,
    FinancialPeriod,
    InsiderTrade,
    ResearchReport,
    Valuation,
)
from .db import session_scope
from .schema import (
    CompanyRow,
    FilingRow,
    FinancialRow,
    InsiderTradeRow,
    ReportRow,
    ValuationRow,
)


def _upsert(session, model, values: dict, index_elements: list[str]):
    """SQLite UPSERT：冲突则更新非主键字段。"""
    stmt = sqlite_insert(model).values(**values)
    update_cols = {
        c.name: stmt.excluded[c.name]
        for c in model.__table__.columns
        if c.name not in index_elements and not c.primary_key
    }
    stmt = stmt.on_conflict_do_update(
        index_elements=index_elements, set_=update_cols
    )
    session.execute(stmt)


def save_company(company: Company) -> None:
    with session_scope() as s:
        _upsert(
            s,
            CompanyRow,
            {
                "ticker": company.ticker,
                "cik": company.cik,
                "name": company.name,
                "sector": company.sector,
                "industry": company.industry,
                "exchange": company.exchange,
                "country": company.country,
                "website": company.website,
                "employees": company.employees,
                "description": company.description,
                "updated_at": datetime.utcnow(),
            },
            ["ticker"],
        )


def save_financials(ticker: str, periods: list[FinancialPeriod]) -> None:
    with session_scope() as s:
        for p in periods:
            data = p.model_dump()
            data["ticker"] = ticker
            _upsert(s, FinancialRow, data, ["ticker", "period_type", "fiscal_date"])


def save_valuation(val: Valuation) -> None:
    with session_scope() as s:
        _upsert(
            s,
            ValuationRow,
            {
                "ticker": val.ticker,
                "as_of_date": val.as_of_date,
                "pe_trailing": val.pe_trailing,
                "pe_forward": val.pe_forward,
                "roe": val.roe,
                "ev_ebitda": val.ev_ebitda,
                "pb": val.pb,
                "ps": val.ps,
                "peg": val.peg,
                "enterprise_value": val.enterprise_value,
            },
            ["ticker", "as_of_date"],
        )


def save_insider_trades(ticker: str, trades: list[InsiderTrade]) -> None:
    with session_scope() as s:
        for t in trades:
            _upsert(
                s,
                InsiderTradeRow,
                {
                    "ticker": ticker,
                    "insider_name": t.insider_name,
                    "title": t.title,
                    "transaction_date": t.transaction_date,
                    "transaction_code": t.transaction_code,
                    "acquired_disposed": t.acquired_disposed,
                    "shares": t.shares,
                    "price": t.price,
                    "value": t.value,
                    "shares_owned_after": t.shares_owned_after,
                    "is_direct": t.is_direct,
                    "filing_url": t.filing_url,
                },
                ["ticker", "insider_name", "transaction_date",
                 "transaction_code", "shares", "price"],
            )


def save_filings(ticker: str, filings: list[Filing]) -> None:
    with session_scope() as s:
        for f in filings:
            _upsert(
                s,
                FilingRow,
                {
                    "ticker": ticker,
                    "cik": f.cik,
                    "form_type": f.form_type,
                    "filing_date": f.filing_date,
                    "report_date": f.report_date,
                    "accession_no": f.accession_no,
                    "primary_doc": f.primary_doc,
                    "url": f.url,
                    "description": f.description,
                },
                ["ticker", "accession_no"],
            )


def record_report(report: ResearchReport, path: str, summary: str) -> None:
    with session_scope() as s:
        s.add(
            ReportRow(
                ticker=report.ticker,
                generated_at=report.generated_at,
                path=path,
                summary=summary,
            )
        )


def list_reports(ticker: str | None = None, limit: int = 20) -> list[dict]:
    with session_scope() as s:
        stmt = select(ReportRow).order_by(ReportRow.id.desc()).limit(limit)
        if ticker:
            stmt = (
                select(ReportRow)
                .where(ReportRow.ticker == ticker.upper())
                .order_by(ReportRow.id.desc())
                .limit(limit)
            )
        rows = s.execute(stmt).scalars().all()
        return [
            {
                "ticker": r.ticker,
                "generated_at": r.generated_at,
                "path": r.path,
                "summary": r.summary,
            }
            for r in rows
        ]
