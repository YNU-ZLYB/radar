"""应用配置。所有项均可用环境变量或 .env 覆盖。"""
from __future__ import annotations
from pydantic import Field

import os
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(BASE_DIR / ".env"), env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Futures Radar"
    host: str = "0.0.0.0"
    port: int = 8000

    database_url: str = f"sqlite:///{DATA_DIR / 'radar.db'}"

    # DeepSeek：留空则使用内置规则引擎（免费模式）
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-chat"
    llm_enabled: bool = True
    llm_max_concurrency: int = 2

    # 采集间隔（秒）
    interval_jin10: int = 60
    interval_eastmoney: int = 60
    interval_sina7x24: int = 120
    interval_quotes: int = 60
    interval_quote_summary: int = 300
    interval_oil: int = 60
    interval_rss: int = 900
    interval_czce: int = 120
    interval_fred: int = 21600
    interval_worker: int = 20
    interval_digest: int = 3600

    request_timeout: int = 15
    user_agent: str = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"

    # 研判参数
    top_n: int = 10
    candidate_confidence: float = 0.5
    quick_model: str = "rule-quick"
    rule_model: str = "rule-engine"

    enable_scheduler: bool = True

    @property
    def llm_available(self) -> bool:
        return bool(self.deepseek_api_key) and self.llm_enabled

    async def probe_llm(self) -> tuple[bool, str]:
        """启动时发一个最小请求验证 Key 真能调用。

        余额不足、Key 无效、网络错误都视为不可用，自动回退规则模式。
        """
        if not self.deepseek_api_key or not self.llm_enabled:
            return False, "未配置或已禁用"
        try:
            import httpx
            async with httpx.AsyncClient(timeout=12) as client:
                resp = await client.post(
                    f"{self.deepseek_base_url.rstrip('/')}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.deepseek_api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": self.deepseek_model,
                        "messages": [{"role": "user", "content": "ping"}],
                        "max_tokens": 2,
                    },
                )
            if resp.status_code == 200:
                return True, "正常"
            try:
                err = resp.json().get("error", {}).get("message", "")
            except Exception:  # noqa: BLE001
                err = resp.text[:120]
            return False, f"HTTP {resp.status_code} · {err}"
        except Exception as exc:  # noqa: BLE001
            return False, f"{type(exc).__name__} · {exc}"


settings = Settings()

# 允许空 key 时从环境读取（pydantic 已处理，显式兜底）
if not settings.deepseek_api_key:
    settings.deepseek_api_key = os.getenv("DEEPSEEK_API_KEY", "")
