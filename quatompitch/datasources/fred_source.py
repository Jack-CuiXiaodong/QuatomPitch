"""FRED 宏观数据源（可选）：需免费 API key，未配置则自动跳过。"""
from __future__ import annotations

from typing import Any

from ..config import settings
from ..models import MacroIndicator
from .base import DataSource

# 默认关注的宏观指标
DEFAULT_SERIES = {
    "DGS10": ("10 年期美债收益率", "%"),
    "DFF": ("联邦基金利率", "%"),
    "CPIAUCSL": ("CPI 消费者物价指数", "Index"),
    "UNRATE": ("失业率", "%"),
    "T10Y2Y": ("10Y-2Y 期限利差", "%"),
    "VIXCLS": ("VIX 波动率指数", "Index"),
}


class FredSource(DataSource):
    name = "fred"

    def __init__(self, series: dict[str, tuple[str, str]] | None = None) -> None:
        self.series = series or DEFAULT_SERIES

    def fetch(self, ticker: str) -> dict[str, Any]:
        if not settings.fred_enabled:
            return {"macro": [], "skipped": "未配置 FRED_API_KEY，跳过宏观模块"}

        from fredapi import Fred  # 延迟导入，未启用时不依赖

        fred = Fred(api_key=settings.fred_api_key)
        out: list[MacroIndicator] = []
        for sid, (label, units) in self.series.items():
            try:
                s = fred.get_series(sid)
                s = s.dropna()
                if s.empty:
                    continue
                out.append(
                    MacroIndicator(
                        series_id=sid,
                        label=label,
                        date=s.index[-1].strftime("%Y-%m-%d"),
                        value=float(s.iloc[-1]),
                        units=units,
                    )
                )
            except Exception:
                continue
        return {"macro": out}
