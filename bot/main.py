from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher

from bot.handlers import menu as menu_handlers
from bot.handlers import start as start_handlers
from config import Config
from db.models import Database, now_ts
from services.payments import MockPaymentService
from services.xui_client import XUIClient


log = logging.getLogger("vpn-bot")


async def subscription_watcher(*, db: Database, xui: XUIClient, interval_sec: int) -> None:
    while True:
        try:
            expired = await db.list_expired_active_subscriptions(at_ts=now_ts())
            for sub in expired:
                try:
                    await xui.delete_client(inbound_id=sub.inbound_id, client_uuid=sub.client_uuid)
                except Exception as e:
                    log.warning("Failed to delete client in x-ui: sub=%s err=%r", sub.id, e)
                await db.mark_subscription_expired(sub.id)
        except Exception as e:
            log.exception("subscription_watcher iteration failed: %r", e)
        await asyncio.sleep(interval_sec)


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    cfg = Config.load()

    db = Database(cfg.sqlite_path)
    await db.connect()

    xui = XUIClient(base_url=cfg.xui_base_url, username=cfg.xui_username, password=cfg.xui_password)
    payments = MockPaymentService(db)

    bot = Bot(token=cfg.bot_token)
    dp = Dispatcher()

    dp["cfg"] = cfg
    dp["db"] = db
    dp["xui"] = xui
    dp["payments"] = payments

    dp.include_router(start_handlers.router)
    dp.include_router(menu_handlers.router)

    watcher_task = asyncio.create_task(
        subscription_watcher(db=db, xui=xui, interval_sec=cfg.subscription_watch_interval_sec)
    )
    try:
        await dp.start_polling(bot)
    finally:
        watcher_task.cancel()
        await xui.aclose()
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())

