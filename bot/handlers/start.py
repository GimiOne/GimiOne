from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.types import Message

from bot.keyboards.menu import main_menu
from config import Config
from db.models import Database
from services.admin_access import ensure_admin_subscription
from services.xui_client import XUIClient


router = Router()


@router.message(CommandStart())
async def start(message: Message, db: Database, cfg: Config, xui: XUIClient) -> None:
    if message.from_user is None:
        return
    await db.ensure_user(message.from_user.id)
    await ensure_admin_subscription(tg_id=message.from_user.id, db=db, xui=xui, cfg=cfg)

    await message.answer(
        "Привет! Я бот для выдачи VPN-доступа.\n\nВыберите действие:",
        reply_markup=main_menu(),
    )


@router.message(Command("whoami"))
async def whoami(message: Message, db: Database, cfg: Config) -> None:
    if message.from_user is None:
        return
    await db.ensure_user(message.from_user.id)
    is_admin = message.from_user.id in cfg.admin_tg_ids
    sub = await db.get_active_subscription(message.from_user.id)
    await message.answer(
        "Диагностика:\n\n"
        f"- tg_id: {message.from_user.id}\n"
        f"- admin: {is_admin}\n"
        f"- active_subscription: {sub is not None}",
    )

