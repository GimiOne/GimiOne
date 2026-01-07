from __future__ import annotations

from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import Message

from bot.keyboards.menu import main_menu
from db.models import Database


router = Router()


@router.message(CommandStart())
async def start(message: Message, db: Database) -> None:
    if message.from_user is None:
        return
    await db.ensure_user(message.from_user.id)
    await message.answer(
        "Привет! Я бот для выдачи VPN-доступа.\n\nВыберите действие:",
        reply_markup=main_menu(),
    )

