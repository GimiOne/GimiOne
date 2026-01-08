from __future__ import annotations

import time

from config import Config
from db.models import Database
from services.xui_client import XUIClient, new_client_uuid


ADMIN_EXPIRES_AT = 4102444800  # 2100-01-01 UTC


async def ensure_admin_subscription(*, tg_id: int, db: Database, xui: XUIClient, cfg: Config) -> None:
    """
    Для админов (cfg.admin_tg_ids) гарантирует наличие активной подписки.
    Идемпотентно: если подписка уже есть — ничего не делает.
    """
    if tg_id not in cfg.admin_tg_ids:
        return

    sub = await db.get_active_subscription(tg_id)
    if sub is not None:
        return

    payment = await db.create_or_get_admin_grant_payment(tg_id=tg_id)
    inbound = await xui.resolve_inbound(inbound_id=cfg.xui_inbound_id, inbound_remark=cfg.xui_inbound_remark)

    client_uuid = new_client_uuid()
    client_email = f"admin{tg_id}-{client_uuid[:8]}"
    starts = int(time.time())

    await xui.add_client(
        inbound_id=inbound.id,
        client_uuid=client_uuid,
        email=client_email,
        expiry_time_ms=ADMIN_EXPIRES_AT * 1000,
    )
    vless_uri = xui.build_vless_reality_uri(
        inbound=inbound,
        vpn_public_host=cfg.vpn_public_host,
        client_uuid=client_uuid,
        label=client_email,
    )
    await db.create_subscription(
        tg_id=tg_id,
        payment_id=payment.id,
        inbound_id=inbound.id,
        client_uuid=client_uuid,
        client_email=client_email,
        vless_uri=vless_uri,
        starts_at=starts,
        expires_at=ADMIN_EXPIRES_AT,
    )

