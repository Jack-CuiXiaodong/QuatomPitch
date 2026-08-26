"""全局配置：从环境变量 / .env 读取。"""
from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# 项目根目录（config.py 在 quatompitch/ 下，向上一级即为项目根）
ROOT_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="",
        extra="ignore",
    )

    # SEC EDGAR 强制要求 User-Agent，格式 "AppName email@example.com"
    sec_user_agent: str = "QuatomPitch admin@example.com"

    # FRED 免费 API key（可选，留空则跳过宏观模块）
    fred_api_key: str = ""

    # 数据库与报告输出
    quatompitch_db_path: str = "data/quatompitch.db"
    quatompitch_report_dir: str = "reports"

    # 网络
    http_timeout: float = 20.0
    sec_rate_limit_per_sec: float = 8.0  # SEC 上限约 10 req/s，留余量

    # 报送正文抽取：单个章节保留的最大字符数（风险因素动辄十几万字）。
    # 设为 0 表示不截断，整篇写进报告。
    sec_section_max_chars: int = 40000

    @property
    def db_path(self) -> Path:
        p = Path(self.quatompitch_db_path)
        return p if p.is_absolute() else ROOT_DIR / p

    @property
    def report_dir(self) -> Path:
        p = Path(self.quatompitch_report_dir)
        return p if p.is_absolute() else ROOT_DIR / p

    @property
    def fred_enabled(self) -> bool:
        return bool(self.fred_api_key.strip())


settings = Settings()
