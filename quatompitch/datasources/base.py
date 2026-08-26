"""数据源抽象基类：所有数据源实现统一接口，pipeline 只依赖该接口。"""
from __future__ import annotations

import abc
from typing import Any


class DataSource(abc.ABC):
    """一个数据源适配器。"""

    name: str = "base"

    @abc.abstractmethod
    def fetch(self, ticker: str) -> dict[str, Any]:
        """采集指定 ticker 的数据，返回字典（键含义由各源自定义）。

        实现方应自行容错：网络失败时抛出异常，由 pipeline 捕获并记入 warnings，
        不应让单个源的失败影响整份报告。
        """
        raise NotImplementedError
