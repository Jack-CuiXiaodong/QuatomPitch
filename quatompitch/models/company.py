"""公司与行情领域模型。"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


class Company(BaseModel):
    ticker: str
    cik: Optional[str] = None
    name: Optional[str] = None
    sector: Optional[str] = None
    industry: Optional[str] = None
    exchange: Optional[str] = None
    country: Optional[str] = None
    website: Optional[str] = None
    employees: Optional[int] = None
    description: Optional[str] = None


class Quote(BaseModel):
    ticker: str
    price: Optional[float] = None
    currency: Optional[str] = None
    market_cap: Optional[float] = None
    shares_outstanding: Optional[float] = None
    day_high: Optional[float] = None
    day_low: Optional[float] = None
    week52_high: Optional[float] = None
    week52_low: Optional[float] = None
    avg_volume: Optional[float] = None
    beta: Optional[float] = None
    dividend_yield: Optional[float] = None
