"""SEC 响应磁盘缓存。

一次完整采集要下约 6 MB（companyfacts 3.8 MB + 10-K 正文 1.5 MB + 若干 R 文件），
反复分析同一只股票会把这些原样重下一遍——既慢，对 SEC 也不礼貌。

两类地址的时效性完全不同，分开处理：

- **`/Archives/` 下的报送文件是不可变的**：一份 10-K 交上去就永远是那个内容，
  accession 号唯一确定一份文档。这类**永久缓存**，命中即用。
- **submissions / companyfacts 会随新报送变化**：按 TTL 缓存（默认当天有效）。

只缓存成功响应。失败不写缓存，也不由缓存吞掉——保持 fail-loud。
"""
from __future__ import annotations

import hashlib
import os
import tempfile
import time
from pathlib import Path
from typing import Optional

from ..config import settings

# 报送归档地址内容不可变，无需过期
_IMMUTABLE_MARKER = "/Archives/"


def _is_immutable(url: str) -> bool:
    return _IMMUTABLE_MARKER in url


class ResponseCache:
    """按 URL 哈希缓存文本响应到磁盘。"""

    def __init__(
        self,
        root: Optional[Path] = None,
        ttl_hours: Optional[float] = None,
        enabled: Optional[bool] = None,
    ) -> None:
        self.root = Path(root) if root else settings.cache_dir
        self.ttl_seconds = (
            (ttl_hours if ttl_hours is not None else settings.cache_ttl_hours) * 3600
        )
        self.enabled = settings.cache_enabled if enabled is None else enabled
        # 由 CLI 的 --refresh 置位：忽略已有缓存，但仍然写入新结果
        self.refresh = False

    def _path(self, url: str) -> Path:
        h = hashlib.sha256(url.encode("utf-8")).hexdigest()
        # 打散到两级子目录，避免单目录堆几万个文件
        return self.root / h[:2] / f"{h}.txt"

    def get(self, url: str) -> Optional[str]:
        if not self.enabled or self.refresh:
            return None
        p = self._path(url)
        try:
            if not p.is_file():
                return None
            if not _is_immutable(url):
                age = time.time() - p.stat().st_mtime
                if age > self.ttl_seconds:
                    return None
            return p.read_text(encoding="utf-8")
        except OSError:
            # 缓存本身出问题绝不能影响采集，当作未命中
            return None

    def put(self, url: str, text: str) -> None:
        if not self.enabled:
            return
        p = self._path(url)
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            # 先写临时文件再原子改名：多个数据源并发时可能写同一个键，
            # 半截文件被另一个线程读到会比没有缓存更糟。
            fd, tmp = tempfile.mkstemp(dir=str(p.parent), suffix=".part")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    f.write(text)
                os.replace(tmp, p)
            except BaseException:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
                raise
        except OSError:
            pass  # 写不进缓存不算错误

    def stats(self) -> tuple[int, int]:
        """返回 (文件数, 总字节数)，用于 CLI 展示。"""
        count = size = 0
        if self.root.is_dir():
            for p in self.root.rglob("*.txt"):
                try:
                    size += p.stat().st_size
                    count += 1
                except OSError:
                    pass
        return count, size

    def clear(self) -> int:
        """清空缓存，返回删除的文件数。"""
        removed = 0
        if self.root.is_dir():
            for p in self.root.rglob("*.txt"):
                try:
                    p.unlink()
                    removed += 1
                except OSError:
                    pass
        return removed


# 进程级共享实例：SecClient 每次采集都会新建，但缓存要跨实例复用
CACHE = ResponseCache()
