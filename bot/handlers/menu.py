from __future__ import annotations

import io
from datetime import datetime, timezone
from html import escape

import qrcode
from aiogram import F, Router
from aiogram.types import BufferedInputFile, CallbackQuery

from bot.keyboards.menu import main_menu, payment_mock_keyboard
from config import Config
from db.models import Database, now_ts
from services.payments import PaymentService
from services.xui_client import XUIClient, new_client_uuid


router = Router()


def _fmt_ts(ts: int) -> str:
    dt = datetime.fromtimestamp(ts, tz=timezone.utc)
    return dt.strftime("%Y-%m-%d %H:%M UTC")


def _qr_png_bytes(data: str) -> bytes:
    img = qrcode.make(data)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


@router.callback_query(F.data == "menu")
async def menu(cb: CallbackQuery) -> None:
    if cb.message is None:
        await cb.answer()
        return
    await cb.message.edit_text("Выберите действие:", reply_markup=main_menu())
    await cb.answer()


@router.callback_query(F.data == "buy")
async def buy(cb: CallbackQuery, db: Database, payments: PaymentService, cfg: Config) -> None:
    if cb.from_user is None:
        return
    if cb.message is None:
        await cb.answer()
        return
    await db.ensure_user(cb.from_user.id)

    active = await db.get_active_subscription(cb.from_user.id)
    if active is not None:
        await cb.message.edit_text(
            f"У вас уже есть активная подписка до <b>{_fmt_ts(active.expires_at)}</b>.\n\n"
            "Если нужен ключ — нажмите «Получить ключ».",
            reply_markup=main_menu(),
            parse_mode="HTML",
        )
        await cb.answer()
        return

    res = await payments.create_payment(tg_id=cb.from_user.id, amount=cfg.subscription_price_rub, currency="RUB")
    p = res.payment
    await cb.message.edit_text(
        f"Оплата (mock)\n\n"
        f"- Сумма: <b>{p.amount} {p.currency}</b>\n"
        f"- Статус: <b>{p.status}</b>\n\n"
        "Нажмите кнопку ниже, чтобы имитировать успешную оплату.",
        reply_markup=payment_mock_keyboard(p.id),
        parse_mode="HTML",
    )
    await cb.answer()


@router.callback_query(F.data == "my_sub")
async def my_sub(cb: CallbackQuery, db: Database) -> None:
    if cb.from_user is None:
        return
    if cb.message is None:
        await cb.answer()
        return
    await db.ensure_user(cb.from_user.id)

    sub = await db.get_active_subscription(cb.from_user.id)
    if sub is None:
        latest = await db.get_latest_subscription(cb.from_user.id)
        if latest is None:
            text = "У вас ещё нет подписки."
        else:
            text = (
                "Активной подписки нет.\n"
                f"Последняя: <b>{escape(latest.status)}</b>, до <b>{_fmt_ts(latest.expires_at)}</b>."
            )
        await cb.message.edit_text(text, reply_markup=main_menu(), parse_mode="HTML")
        await cb.answer()
        return

    left = max(0, sub.expires_at - now_ts())
    days = left // 86400
    hours = (left % 86400) // 3600
    await cb.message.edit_text(
        "Подписка активна ✅\n\n"
        f"- До: <b>{_fmt_ts(sub.expires_at)}</b>\n"
        f"- Осталось: <b>{days}d {hours}h</b>\n",
        reply_markup=main_menu(),
        parse_mode="HTML",
    )
    await cb.answer()


@router.callback_query(F.data == "get_key")
async def get_key(cb: CallbackQuery, db: Database) -> None:
    if cb.from_user is None:
        return
    if cb.message is None:
        await cb.answer()
        return
    await db.ensure_user(cb.from_user.id)

    sub = await db.get_active_subscription(cb.from_user.id)
    if sub is None:
        await cb.message.edit_text("Активной подписки нет. Сначала купите подписку.", reply_markup=main_menu())
        await cb.answer()
        return

    qr = _qr_png_bytes(sub.vless_uri)
    await cb.message.answer(
        "Ваш ключ (VLESS Reality):\n\n"
        f"<code>{escape(sub.vless_uri)}</code>",
        parse_mode="HTML",
    )
    await cb.message.answer_photo(BufferedInputFile(qr, filename="vless.png"))
    await cb.answer()


@router.callback_query(F.data.startswith("pay_confirm:"))
async def pay_confirm(cb: CallbackQuery, db: Database, payments: PaymentService, xui: XUIClient, cfg: Config) -> None:
    if cb.from_user is None:
        return
    if cb.message is None:
        await cb.answer()
        return
    await db.ensure_user(cb.from_user.id)

    payment_id = cb.data.split(":", 1)[1]
    payment = await payments.confirm_payment(payment_id=payment_id, tg_id=cb.from_user.id)
    if payment.status != "succeeded":
        await cb.message.edit_text(
            f"Платёж не успешен. Статус: <b>{escape(payment.status)}</b>",
            reply_markup=main_menu(),
            parse_mode="HTML",
        )
        await cb.answer()
        return

    existing_sub = await db.get_subscription_by_payment(payment.id)
    if existing_sub is not None:
        qr = _qr_png_bytes(existing_sub.vless_uri)
        await cb.message.edit_text(
            "Оплата уже обработана ✅\n\n"
            "Ключ:\n\n"
            f"<code>{escape(existing_sub.vless_uri)}</code>",
            reply_markup=main_menu(),
            parse_mode="HTML",
        )
        await cb.message.answer_photo(BufferedInputFile(qr, filename="vless.png"))
        await cb.answer()
        return

    inbound = await xui.resolve_inbound(inbound_id=cfg.xui_inbound_id, inbound_remark=cfg.xui_inbound_remark)
    client_uuid = new_client_uuid()
    client_email = f"tg{cb.from_user.id}-{client_uuid[:8]}"

    starts = now_ts()
    expires = starts + cfg.subscription_days * 86400
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
        tg_id=cb.from_user.id,
        payment_id=payment.id,
        inbound_id=inbound.id,
        client_uuid=client_uuid,
        client_email=client_email,
        vless_uri=vless_uri,
        starts_at=starts,
        expires_at=expires,
    )

    qr = _qr_png_bytes(sub.vless_uri)
    await cb.message.edit_text(
        "Оплата успешна ✅\n\n"
        f"Подписка до: <b>{_fmt_ts(sub.expires_at)}</b>\n\n"
        "Ключ:\n\n"
        f"<code>{escape(sub.vless_uri)}</code>",
        reply_markup=main_menu(),
        parse_mode="HTML",
    )
    await cb.message.answer_photo(BufferedInputFile(qr, filename="vless.png"))
    await cb.answer()

