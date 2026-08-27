"""数据自洽性校验结果。

存在的理由：错数比缺数危险。缺一格是「—」，一眼看得见；而一个映射错误
（例如把只含管理费用的标签当成合并销管费）会输出一个格式完好、量级合理的
数字，人和大模型都没有线索知道它错了。

会计恒等式是确定性的：毛利必须等于营收减营业成本，总资产必须等于负债加权益。
把这些等式在报告里当场验一遍，映射错误就会自己暴露，而不是等下游发现。
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel

# 状态取值
OK = "一致"
DIFF = "差异"
SKIP = "无法校验"


class ConsistencyCheck(BaseModel):
    """一条校验记录。"""

    name: str                      # 校验项，如「毛利 = 营收 − 营业成本」
    period: str                    # 报告期
    scope: str                     # 校验范围：XBRL 内部 / XBRL vs yfinance
    expected_label: str            # 左侧（按等式推出的值）说明
    expected: Optional[float] = None
    actual_label: str              # 右侧（申报值）说明
    actual: Optional[float] = None
    diff: Optional[float] = None   # 申报值 − 推算值
    diff_pct: Optional[float] = None  # 差额占营收比（%），用于判断严重程度
    status: str = SKIP
    note: Optional[str] = None

    @property
    def failed(self) -> bool:
        return self.status == DIFF
