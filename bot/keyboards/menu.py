from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def main_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Купить подписку", callback_data="buy")],
            [InlineKeyboardButton(text="Моя подписка", callback_data="my_sub")],
            [InlineKeyboardButton(text="Получить ключ", callback_data="get_key")],
        ]
    )


def payment_mock_keyboard(payment_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Оплатил (mock)", callback_data=f"pay_confirm:{payment_id}")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="menu")],
        ]
    )

