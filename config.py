from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv


def _required(name: str) -> str:
    v = os.getenv(name)
    if not v:
        raise RuntimeError(f"Missing required env var: {name}")
    return v


def _get_int(name: str, default: int) -> int:
    v = os.getenv(name)
    if v is None or v == "":
        return default
    return int(v)


@dataclass(frozen=True, slots=True)
class Config:
    bot_token: str
    sqlite_path: str
    admin_tg_ids: frozenset[int]
    log_level: str

    xui_base_url: str
    xui_username: str
    xui_password: str
    xui_inbound_id: int | None
    xui_inbound_remark: str | None

    vpn_public_host: str

    subscription_days: int
    subscription_price_rub: int
    subscription_watch_interval_sec: int

    @staticmethod
    def load() -> "Config":
        load_dotenv()

        admin_raw = os.getenv("ADMIN_TG_IDS", "").strip()
        admin_ids: set[int] = set()
        if admin_raw:
            for part in admin_raw.split(","):
                part = part.strip()
                if not part:
                    continue
                admin_ids.add(int(part))

        inbound_id_raw = os.getenv("XUI_INBOUND_ID", "").strip()
        inbound_id = int(inbound_id_raw) if inbound_id_raw else None
        inbound_remark = os.getenv("XUI_INBOUND_REMARK", "").strip() or None

        return Config(
            bot_token=_required("BOT_TOKEN"),
            sqlite_path=os.getenv("SQLITE_PATH", "./db/bot.sqlite3"),
            admin_tg_ids=frozenset(admin_ids),
            log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
            xui_base_url=os.getenv("XUI_BASE_URL", "http://127.0.0.1:54321").rstrip("/"),
            xui_username=_required("XUI_USERNAME"),
            xui_password=_required("XUI_PASSWORD"),
            xui_inbound_id=inbound_id,
            xui_inbound_remark=inbound_remark,
            vpn_public_host=_required("VPN_PUBLIC_HOST"),
            subscription_days=_get_int("SUBSCRIPTION_DAYS", 30),
            subscription_price_rub=_get_int("SUBSCRIPTION_PRICE_RUB", 199),
            subscription_watch_interval_sec=_get_int("SUBSCRIPTION_WATCH_INTERVAL_SEC", 60),
        )

