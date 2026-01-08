from __future__ import annotations

from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware

from config import Config
from db.models import Database
from services.payments import PaymentService
from services.xui_client import XUIClient


class DepsMiddleware(BaseMiddleware):
    """
    Надёжная прокидка зависимостей в aiogram DI для всех апдейтов.

    Это защищает от случаев, когда данные из Dispatcher не попадают в handler kwargs
    (или их сложнее отлаживать в проде).
    """

    def __init__(self, *, cfg: Config, db: Database, xui: XUIClient, payments: PaymentService) -> None:
        self._cfg = cfg
        self._db = db
        self._xui = xui
        self._payments = payments

    async def __call__(
        self,
        handler: Callable[[Any, dict[str, Any]], Awaitable[Any]],
        event: Any,
        data: dict[str, Any],
    ) -> Any:
        data.setdefault("cfg", self._cfg)
        data.setdefault("db", self._db)
        data.setdefault("xui", self._xui)
        data.setdefault("payments", self._payments)
        return await handler(event, data)

