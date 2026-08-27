"""数据源内部局部失败的收集。

三件事在报告里长得一模一样，含义却天差地别：

1. **公司确实没披露** —— 数据不存在，`—` 是正确答案。
2. **本工具没归类到** —— 数据在报送原文里，只是映射没覆盖到。
3. **这次采集失败了** —— 网络或格式故障，换个时间重跑可能就有了。

第三种最危险，因为静默返回空列表会让它**伪装成第一种**。Form 4 内部人交易
长期恒为 0 就是这么藏住的：请求拿回来的是 HTML 不是 XML，`ET.fromstring`
抛 ParseError 被就地吞掉、返回空列表，于是看起来就像「这家公司没有内部人交易」。

约定：
- 空列表 / None 只允许表示「数据确实不存在」。
- 基础设施故障（网络、超时、格式不对）**必须被记录**，最终写进报告告警。
- 局部失败（某一份报送取不到）不应中断整体采集，但要留痕。
- 整体失败（主索引都取不到）直接抛异常，由 pipeline 统一兜住。
"""
from __future__ import annotations

from typing import Optional


class IssueLog:
    """收集单个数据源采集过程中的局部失败。"""

    def __init__(self, source: str) -> None:
        self.source = source
        self._items: list[str] = []

    def record(self, what: str, err: BaseException | str) -> None:
        """记一次局部失败。`what` 说明是哪一步，`err` 是原因。"""
        detail = err if isinstance(err, str) else f"{type(err).__name__}: {err}"
        self._items.append(f"{what}（{detail}）")

    def __bool__(self) -> bool:
        return bool(self._items)

    def __len__(self) -> int:
        return len(self._items)

    def as_warning(self, limit: int = 4) -> Optional[str]:
        """汇总成一句告警；没有失败时返回 None。

        同类失败往往批量出现（例如限流时一连串报送都取不到），全列出来会淹没
        报告，所以只展示前几条、其余折叠计数。
        """
        if not self._items:
            return None
        shown = self._items[:limit]
        text = "；".join(shown)
        rest = len(self._items) - len(shown)
        if rest > 0:
            text += f"；另有 {rest} 处同类失败"
        return f"{self.source} 采集不完整：{text}"
