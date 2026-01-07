from __future__ import annotations

import uuid
from dataclasses import dataclass

from db.models import Database, Payment


@dataclass(frozen=True, slots=True)
class CreatePaymentResult:
    payment: Payment
    already_existed: bool


class PaymentService:
    async def create_payment(self, *, tg_id: int, amount: int, currency: str) -> CreatePaymentResult:
        raise NotImplementedError

    async def confirm_payment(self, *, payment_id: str, tg_id: int) -> Payment:
        raise NotImplementedError


class MockPaymentService(PaymentService):
    """
    Заглушка оплаты.

    Поведение: создаём payment со статусом 'pending', после нажатия "Оплатил" переводим в 'succeeded'.
    """

    def __init__(self, db: Database) -> None:
        self._db = db

    async def create_payment(self, *, tg_id: int, amount: int, currency: str = "RUB") -> CreatePaymentResult:
        existing = await self._db.get_latest_pending_payment(
            tg_id=tg_id, provider="payment_mock", amount=amount, currency=currency
        )
        if existing is not None:
            return CreatePaymentResult(payment=existing, already_existed=True)

        idempotency_key = uuid.uuid4().hex
        payment = await self._db.create_payment(
            tg_id=tg_id,
            provider="payment_mock",
            amount=amount,
            currency=currency,
            idempotency_key=idempotency_key,
            payload={},
        )
        return CreatePaymentResult(payment=payment, already_existed=False)

    async def confirm_payment(self, *, payment_id: str, tg_id: int) -> Payment:
        payment = await self._db.get_payment(payment_id)
        if payment.tg_id != tg_id:
            raise PermissionError("payment owner mismatch")
        if payment.status == "succeeded":
            return payment
        if payment.status != "pending":
            return payment
        return await self._db.set_payment_status(payment_id, "succeeded")

