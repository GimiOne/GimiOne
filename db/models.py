from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass
from typing import Any

import aiosqlite


def now_ts() -> int:
    return int(time.time())


def gen_id() -> str:
    return uuid.uuid4().hex


@dataclass(frozen=True, slots=True)
class Payment:
    id: str
    tg_id: int
    provider: str
    amount: int
    currency: str
    status: str
    idempotency_key: str
    created_at: int
    updated_at: int
    payload: dict[str, Any]


@dataclass(frozen=True, slots=True)
class Subscription:
    id: str
    tg_id: int
    payment_id: str
    inbound_id: int
    client_uuid: str
    client_email: str
    vless_uri: str
    status: str
    created_at: int
    starts_at: int
    expires_at: int
    revoked_at: int | None


class Database:
    def __init__(self, path: str) -> None:
        self._path = path
        self._conn: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        self._conn = await aiosqlite.connect(self._path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA journal_mode=WAL;")
        await self._conn.execute("PRAGMA foreign_keys=ON;")
        await self._conn.commit()
        await self.init_schema()

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    @property
    def conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("DB not connected")
        return self._conn

    async def init_schema(self) -> None:
        await self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                tg_id INTEGER PRIMARY KEY,
                created_at INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS payments (
                id TEXT PRIMARY KEY,
                tg_id INTEGER NOT NULL,
                provider TEXT NOT NULL,
                amount INTEGER NOT NULL,
                currency TEXT NOT NULL,
                status TEXT NOT NULL,
                idempotency_key TEXT NOT NULL UNIQUE,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL,
                payload_json TEXT NOT NULL DEFAULT '{}',
                FOREIGN KEY (tg_id) REFERENCES users(tg_id)
            );
            CREATE INDEX IF NOT EXISTS idx_payments_tg_id ON payments(tg_id);
            CREATE INDEX IF NOT EXISTS idx_payments_status ON payments(status);

            CREATE TABLE IF NOT EXISTS subscriptions (
                id TEXT PRIMARY KEY,
                tg_id INTEGER NOT NULL,
                payment_id TEXT NOT NULL UNIQUE,
                inbound_id INTEGER NOT NULL,
                client_uuid TEXT NOT NULL,
                client_email TEXT NOT NULL,
                vless_uri TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                starts_at INTEGER NOT NULL,
                expires_at INTEGER NOT NULL,
                revoked_at INTEGER,
                FOREIGN KEY (tg_id) REFERENCES users(tg_id),
                FOREIGN KEY (payment_id) REFERENCES payments(id)
            );
            CREATE INDEX IF NOT EXISTS idx_subs_tg_id ON subscriptions(tg_id);
            CREATE INDEX IF NOT EXISTS idx_subs_status_expires ON subscriptions(status, expires_at);
            """
        )
        await self.conn.commit()

    async def ensure_user(self, tg_id: int) -> None:
        await self.conn.execute(
            "INSERT OR IGNORE INTO users (tg_id, created_at) VALUES (?, ?)",
            (tg_id, now_ts()),
        )
        await self.conn.commit()

    async def create_payment(
        self,
        *,
        tg_id: int,
        provider: str,
        amount: int,
        currency: str,
        idempotency_key: str,
        payload: dict[str, Any] | None = None,
    ) -> Payment:
        p_id = gen_id()
        ts = now_ts()
        payload = payload or {}

        await self.conn.execute(
            """
            INSERT INTO payments
                (id, tg_id, provider, amount, currency, status, idempotency_key, created_at, updated_at, payload_json)
            VALUES
                (?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?)
            """,
            (p_id, tg_id, provider, amount, currency, idempotency_key, ts, ts, json.dumps(payload)),
        )
        await self.conn.commit()
        return await self.get_payment(p_id)

    async def get_payment(self, payment_id: str) -> Payment:
        cur = await self.conn.execute("SELECT * FROM payments WHERE id = ?", (payment_id,))
        row = await cur.fetchone()
        if row is None:
            raise KeyError(f"payment not found: {payment_id}")
        return Payment(
            id=row["id"],
            tg_id=row["tg_id"],
            provider=row["provider"],
            amount=row["amount"],
            currency=row["currency"],
            status=row["status"],
            idempotency_key=row["idempotency_key"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            payload=json.loads(row["payload_json"] or "{}"),
        )

    async def get_payment_by_idempotency(self, idempotency_key: str) -> Payment | None:
        cur = await self.conn.execute("SELECT id FROM payments WHERE idempotency_key = ?", (idempotency_key,))
        row = await cur.fetchone()
        return await self.get_payment(row["id"]) if row else None

    async def set_payment_status(self, payment_id: str, status: str) -> Payment:
        ts = now_ts()
        await self.conn.execute(
            "UPDATE payments SET status = ?, updated_at = ? WHERE id = ?",
            (status, ts, payment_id),
        )
        await self.conn.commit()
        return await self.get_payment(payment_id)

    async def get_latest_pending_payment(
        self, *, tg_id: int, provider: str, amount: int, currency: str
    ) -> Payment | None:
        cur = await self.conn.execute(
            """
            SELECT id FROM payments
            WHERE tg_id = ? AND provider = ? AND amount = ? AND currency = ? AND status = 'pending'
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (tg_id, provider, amount, currency),
        )
        row = await cur.fetchone()
        return await self.get_payment(row["id"]) if row else None

    async def get_active_subscription(self, tg_id: int, *, at_ts: int | None = None) -> Subscription | None:
        at_ts = at_ts or now_ts()
        cur = await self.conn.execute(
            """
            SELECT * FROM subscriptions
            WHERE tg_id = ? AND status = 'active' AND expires_at > ?
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (tg_id, at_ts),
        )
        row = await cur.fetchone()
        return self._row_to_subscription(row) if row else None

    async def get_latest_subscription(self, tg_id: int) -> Subscription | None:
        cur = await self.conn.execute(
            """
            SELECT * FROM subscriptions
            WHERE tg_id = ?
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (tg_id,),
        )
        row = await cur.fetchone()
        return self._row_to_subscription(row) if row else None

    async def get_subscription_by_payment(self, payment_id: str) -> Subscription | None:
        cur = await self.conn.execute("SELECT * FROM subscriptions WHERE payment_id = ?", (payment_id,))
        row = await cur.fetchone()
        return self._row_to_subscription(row) if row else None

    async def create_subscription(
        self,
        *,
        tg_id: int,
        payment_id: str,
        inbound_id: int,
        client_uuid: str,
        client_email: str,
        vless_uri: str,
        starts_at: int,
        expires_at: int,
    ) -> Subscription:
        s_id = gen_id()
        created = now_ts()
        await self.conn.execute(
            """
            INSERT INTO subscriptions
                (id, tg_id, payment_id, inbound_id, client_uuid, client_email, vless_uri,
                 status, created_at, starts_at, expires_at, revoked_at)
            VALUES
                (?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, ?, NULL)
            """,
            (
                s_id,
                tg_id,
                payment_id,
                inbound_id,
                client_uuid,
                client_email,
                vless_uri,
                created,
                starts_at,
                expires_at,
            ),
        )
        await self.conn.commit()
        cur = await self.conn.execute("SELECT * FROM subscriptions WHERE id = ?", (s_id,))
        row = await cur.fetchone()
        return self._row_to_subscription(row)

    async def list_expired_active_subscriptions(self, *, at_ts: int | None = None) -> list[Subscription]:
        at_ts = at_ts or now_ts()
        cur = await self.conn.execute(
            """
            SELECT * FROM subscriptions
            WHERE status = 'active' AND expires_at <= ?
            ORDER BY expires_at ASC
            """,
            (at_ts,),
        )
        rows = await cur.fetchall()
        return [self._row_to_subscription(r) for r in rows]

    async def mark_subscription_expired(self, sub_id: str) -> None:
        ts = now_ts()
        await self.conn.execute(
            "UPDATE subscriptions SET status = 'expired', revoked_at = ? WHERE id = ?",
            (ts, sub_id),
        )
        await self.conn.commit()

    @staticmethod
    def _row_to_subscription(row: aiosqlite.Row) -> Subscription:
        return Subscription(
            id=row["id"],
            tg_id=row["tg_id"],
            payment_id=row["payment_id"],
            inbound_id=row["inbound_id"],
            client_uuid=row["client_uuid"],
            client_email=row["client_email"],
            vless_uri=row["vless_uri"],
            status=row["status"],
            created_at=row["created_at"],
            starts_at=row["starts_at"],
            expires_at=row["expires_at"],
            revoked_at=row["revoked_at"],
        )

