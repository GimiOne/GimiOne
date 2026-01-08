from __future__ import annotations

import asyncio
import logging
import os

from aiogram import Bot, Dispatcher

from bot.handlers import menu as menu_handlers
from bot.handlers import start as start_handlers
from bot.middlewares.deps import DepsMiddleware
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
    cfg = Config.load()
    logging.basicConfig(level=getattr(logging, cfg.log_level, logging.INFO))
    log.info("Starting bot")
    log.info("CWD=%s", os.getcwd())
    log.info(".env present=%s", os.path.exists(".env"))
    log.info("sqlite_path=%s", cfg.sqlite_path)
    log.info("admin_tg_ids=%s", sorted(cfg.admin_tg_ids))
    log.info("xui_base_url=%s inbound_id=%s inbound_remark=%s", cfg.xui_base_url, cfg.xui_inbound_id, cfg.xui_inbound_remark)

    db = Database(cfg.sqlite_path)
    await db.connect()

    xui = XUIClient(base_url=cfg.xui_base_url, username=cfg.xui_username, password=cfg.xui_password)
    payments = MockPaymentService(db)

    bot = Bot(token=cfg.bot_token)
    me = await bot.get_me()
    log.info("Bot username=@%s id=%s", me.username, me.id)
    # Важно для polling: если раньше был webhook, команды могут "молчать".
    await bot.delete_webhook(drop_pending_updates=True)
    dp = Dispatcher()

    # Прокидываем зависимости в DI через middleware (надежнее, чем только dp["..."]).
    dp.update.outer_middleware(DepsMiddleware(cfg=cfg, db=db, xui=xui, payments=payments))

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

