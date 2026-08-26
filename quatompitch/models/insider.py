"""内部人交易（SEC Form 4）与 SEC 报送领域模型。"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


class InsiderTrade(BaseModel):
    """一笔内部人交易（高管/董事/大股东的增持或减持）。"""

    ticker: str
    insider_name: Optional[str] = None
    title: Optional[str] = None  # 职务，如 CEO / Director / 10% Owner
    transaction_date: Optional[str] = None  # YYYY-MM-DD
    transaction_code: Optional[str] = None  # P=买入 S=卖出 A=授予 M=行权 等
    acquired_disposed: Optional[str] = None  # A=增持 D=减持
    shares: Optional[float] = None
    price: Optional[float] = None
    value: Optional[float] = None  # shares * price
    shares_owned_after: Optional[float] = None
    is_direct: Optional[bool] = None
    filing_url: Optional[str] = None

    # 衍生品（期权/权证/RSU）交易。有些公司的内部人活动**全部**发生在衍生品表，
    # 只读普通股表会整份漏掉（如 SHOP）。
    is_derivative: bool = False
    security_title: Optional[str] = None      # 如 "Warrants to Purchase..."
    exercise_price: Optional[float] = None    # 行权价/转换价
    underlying_shares: Optional[float] = None # 对应的标的股数

    @property
    def direction(self) -> str:
        """归一化方向标签。"""
        if self.acquired_disposed == "A":
            return "增持"
        if self.acquired_disposed == "D":
            return "减持"
        return self.transaction_code or "未知"


class Filing(BaseModel):
    """一份 SEC 报送索引（10-K / 10-Q / 8-K 等）。"""

    ticker: str
    cik: Optional[str] = None
    form_type: str
    filing_date: str
    report_date: Optional[str] = None
    accession_no: Optional[str] = None
    primary_doc: Optional[str] = None
    url: Optional[str] = None
    description: Optional[str] = None


class NewsItem(BaseModel):
    ticker: str
    title: str
    publisher: Optional[str] = None
    published_at: Optional[str] = None
    url: Optional[str] = None
    summary: Optional[str] = None


class MacroIndicator(BaseModel):
    series_id: str
    label: str
    date: Optional[str] = None
    value: Optional[float] = None
    units: Optional[str] = None
