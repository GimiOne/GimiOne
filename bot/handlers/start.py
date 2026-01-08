from __future__ import annotations

import io
import time
from html import escape

import qrcode
from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import BufferedInputFile, Message

from bot.keyboards.menu import main_menu
from config import Config
from db.models import Database
from services.xui_client import XUIClient, new_client_uuid


router = Router()


def _qr_png_bytes(data: str) -> bytes:
    img = qrcode.make(data)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


@router.message(CommandStart())
async def start(message: Message, db: Database, cfg: Config, xui: XUIClient) -> None:
    if message.from_user is None:
        return
    await db.ensure_user(message.from_user.id)

    # Админский доступ: выдаём бессрочную подписку без оплаты.
    if message.from_user.id in cfg.admin_tg_ids:
        sub = await db.get_active_subscription(message.from_user.id)
        if sub is None:
            payment = await db.create_or_get_admin_grant_payment(tg_id=message.from_user.id)
            inbound = await xui.resolve_inbound(inbound_id=cfg.xui_inbound_id, inbound_remark=cfg.xui_inbound_remark)
            client_uuid = new_client_uuid()
            client_email = f"admin{message.from_user.id}-{client_uuid[:8]}"
            starts = int(time.time())
            expires = 4102444800  # 2100-01-01 UTC
            await xui.add_client(
                inbound_id=inbound.id,
                client_uuid=client_uuid,
                email=client_email,
                expiry_time_ms=expires * 1000,
            )
            vless_uri = xui.build_vless_reality_uri(
                inbound=inbound,
                vpn_public_host=cfg.vpn_public_host,
                client_uuid=client_uuid,
                label=client_email,
            )
            sub = await db.create_subscription(
                tg_id=message.from_user.id,
                payment_id=payment.id,
                inbound_id=inbound.id,
                client_uuid=client_uuid,
                client_email=client_email,
                vless_uri=vless_uri,
                starts_at=starts,
                expires_at=expires,
            )
            qr = _qr_png_bytes(sub.vless_uri)
            await message.answer(
                "✅ Админ-доступ активирован.\n\n"
                f"<code>{escape(sub.vless_uri)}</code>",
                parse_mode="HTML",
            )
            await message.answer_photo(BufferedInputFile(qr, filename="vless.png"))

    await message.answer(
        "Привет! Я бот для выдачи VPN-доступа.\n\nВыберите действие:",
        reply_markup=main_menu(),
    )

