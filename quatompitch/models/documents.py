"""报送正文与财报附注表领域模型。

这部分是给大模型当原料用的：10-K/10-Q 的业务描述、风险因素、MD&A 正文，
以及从 SEC 渲染文件里抽出的分部/分产品收入表。
"""
from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


class FilingSection(BaseModel):
    """报送正文里的一个章节，如 Item 1A 风险因素。"""

    item: Optional[str] = None      # "1A" / "7"
    title: Optional[str] = None     # "Risk Factors"
    text: str = ""
    char_count: int = 0
    truncated: bool = False         # 是否因超长被截断


class FilingDocument(BaseModel):
    """一份报送的正文抽取结果（10-K / 10-Q / 8-K）。"""

    ticker: str
    form_type: str
    filing_date: str
    report_date: Optional[str] = None
    accession_no: Optional[str] = None
    url: Optional[str] = None
    sections: List[FilingSection] = Field(default_factory=list)

    @property
    def total_chars(self) -> int:
        return sum(s.char_count for s in self.sections)


class StatementTable(BaseModel):
    """从 SEC 渲染文件（R*.htm）抽出的一张附注表。

    典型用途：分产品收入（iPhone/Mac/服务…）、分部与地区收入。

    原始 R 文件是给浏览器看的：分组名（iPhone、Americas…）单独占一行，
    组内再重复一遍「Net sales」。这里已经拍平成规整的二维表——
    `columns` 是期间表头，`rows` 每行首列是自带分组前缀的行标签，
    后面依次是各期数值。这样每一行都能独立读懂，适合喂给大模型。
    """

    ticker: str
    title: str
    # "primary" = 三大报表原文（as-filed）；"note" = 附注明细表（分部收入等）
    category: str = "note"
    units: Optional[str] = None         # 如 "USD ($) $ in Millions"
    period_label: Optional[str] = None  # 如 "12 Months Ended"
    columns: List[str] = Field(default_factory=list)  # 各期表头
    rows: List[List[str]] = Field(default_factory=list)
    source_form: Optional[str] = None   # 10-K / 10-Q
    filing_date: Optional[str] = None
    url: Optional[str] = None

    @property
    def width(self) -> int:
        """列数 = 行标签 + 各期，用于渲染 Markdown 分隔行。"""
        return len(self.columns) + 1
