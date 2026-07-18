from __future__ import annotations

from flask import has_request_context
from sqlalchemy import func, update
from sqlalchemy.exc import IntegrityError

from .extensions import db
from .models import AuditLog, MoneyTransaction, Product, Purchase, Report, User
from .security import client_ip


class TransactionError(ValueError):
    pass


def add_audit_log(
    action: str,
    target_type: str,
    target_id: str | None,
    reason: str,
    actor_id: str | None = None,
) -> AuditLog:
    log = AuditLog(
        actor_id=actor_id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        reason=reason,
        ip_address=client_ip() if has_request_context() else None,
    )
    db.session.add(log)
    return log


def _move_balance(sender_id: str, receiver_id: str, amount_krw: int) -> None:
    if sender_id == receiver_id:
        raise TransactionError("자기 자신에게는 송금할 수 없습니다.")

    debit = db.session.execute(
        update(User)
        .where(
            User.id == sender_id,
            User.status == "active",
            User.balance_krw >= amount_krw,
        )
        .values(balance_krw=User.balance_krw - amount_krw)
    )
    if debit.rowcount != 1:
        raise TransactionError("잔액이 부족하거나 송금할 수 없는 계정입니다.")

    credit = db.session.execute(
        update(User)
        .where(User.id == receiver_id, User.status == "active")
        .values(balance_krw=User.balance_krw + amount_krw)
    )
    if credit.rowcount != 1:
        raise TransactionError("받는 사용자가 없거나 현재 송금받을 수 없습니다.")


def transfer_funds(
    sender_id: str,
    receiver_id: str,
    amount_krw: int,
    idempotency_key: str,
    note: str = "회원 간 송금",
) -> tuple[MoneyTransaction, bool]:
    existing = MoneyTransaction.query.filter_by(idempotency_key=idempotency_key).first()
    if existing:
        if existing.sender_id != sender_id:
            raise TransactionError("잘못된 중복 요청입니다.")
        return existing, False

    try:
        _move_balance(sender_id, receiver_id, amount_krw)
        transaction = MoneyTransaction(
            sender_id=sender_id,
            receiver_id=receiver_id,
            amount_krw=amount_krw,
            kind="transfer",
            idempotency_key=idempotency_key,
            note=note,
        )
        db.session.add(transaction)
        db.session.flush()
        add_audit_log(
            "transfer.completed", "transaction", transaction.id, note, actor_id=sender_id
        )
        db.session.commit()
        return transaction, True
    except IntegrityError:
        db.session.rollback()
        existing = MoneyTransaction.query.filter_by(idempotency_key=idempotency_key).first()
        if existing and existing.sender_id == sender_id:
            return existing, False
        raise TransactionError("송금 요청을 안전하게 처리하지 못했습니다.")
    except Exception:
        db.session.rollback()
        raise


def purchase_product(
    buyer_id: str, product_id: str, idempotency_key: str
) -> tuple[Purchase, bool]:
    existing_transaction = MoneyTransaction.query.filter_by(
        idempotency_key=idempotency_key
    ).first()
    if existing_transaction:
        purchase = Purchase.query.filter_by(transaction_id=existing_transaction.id).first()
        if purchase and purchase.buyer_id == buyer_id:
            return purchase, False
        raise TransactionError("잘못된 중복 구매 요청입니다.")

    product = Product.query.filter_by(id=product_id).first()
    if not product or product.status != "active":
        raise TransactionError("현재 구매할 수 없는 상품입니다.")
    if product.seller_id == buyer_id:
        raise TransactionError("본인이 등록한 상품은 구매할 수 없습니다.")

    try:
        claimed = db.session.execute(
            update(Product)
            .where(Product.id == product_id, Product.status == "active")
            .values(status="sold")
        )
        if claimed.rowcount != 1:
            raise TransactionError("다른 사용자가 먼저 구매한 상품입니다.")

        _move_balance(buyer_id, product.seller_id, product.price_krw)
        transaction = MoneyTransaction(
            sender_id=buyer_id,
            receiver_id=product.seller_id,
            amount_krw=product.price_krw,
            kind="purchase",
            idempotency_key=idempotency_key,
            reference_id=product.id,
            note=f"상품 구매: {product.title}",
        )
        db.session.add(transaction)
        db.session.flush()
        purchase = Purchase(
            product_id=product.id,
            buyer_id=buyer_id,
            seller_id=product.seller_id,
            transaction_id=transaction.id,
            amount_krw=product.price_krw,
        )
        db.session.add(purchase)
        add_audit_log(
            "purchase.completed",
            "product",
            product.id,
            "내부 원화 잔액으로 상품 구매",
            actor_id=buyer_id,
        )
        db.session.commit()
        return purchase, True
    except IntegrityError:
        db.session.rollback()
        existing_transaction = MoneyTransaction.query.filter_by(
            idempotency_key=idempotency_key
        ).first()
        if existing_transaction:
            purchase = Purchase.query.filter_by(transaction_id=existing_transaction.id).first()
            if purchase and purchase.buyer_id == buyer_id:
                return purchase, False
        raise TransactionError("상품 구매 요청이 중복되었거나 이미 판매되었습니다.")
    except Exception:
        db.session.rollback()
        raise


def apply_report_threshold(target_type: str, target_id: str) -> int:
    count = (
        db.session.query(func.count(Report.id))
        .filter(
            Report.target_type == target_type,
            Report.target_id == target_id,
            Report.status == "pending",
        )
        .scalar()
    )
    if count < 3:
        return count

    if target_type == "product":
        product = Product.query.filter_by(id=target_id).first()
        if product and product.status == "active":
            product.status = "hidden"
            add_audit_log(
                "report.auto_hide",
                "product",
                target_id,
                "서로 다른 사용자 3명 이상의 신고",
            )
    else:
        user = User.query.filter_by(id=target_id).first()
        if user and user.role != "admin" and user.status == "active":
            user.status = "suspended"
            add_audit_log(
                "report.auto_suspend",
                "user",
                target_id,
                "서로 다른 사용자 3명 이상의 신고",
            )
    return count


def reverse_transaction(
    original: MoneyTransaction, admin_id: str, reason: str, idempotency_key: str
) -> MoneyTransaction:
    if not original.sender_id or not original.receiver_id:
        raise TransactionError("정정할 수 없는 거래입니다.")
    if MoneyTransaction.query.filter_by(reference_id=original.id, kind="adjustment").first():
        raise TransactionError("이미 정정된 거래입니다.")

    try:
        _move_balance(original.receiver_id, original.sender_id, original.amount_krw)
        correction = MoneyTransaction(
            sender_id=original.receiver_id,
            receiver_id=original.sender_id,
            amount_krw=original.amount_krw,
            kind="adjustment",
            idempotency_key=idempotency_key,
            reference_id=original.id,
            note=f"관리자 정정: {reason}",
        )
        db.session.add(correction)
        purchase = Purchase.query.filter_by(transaction_id=original.id).first()
        if purchase:
            purchase.status = "reversed"
        add_audit_log(
            "transaction.reversed",
            "transaction",
            original.id,
            reason,
            actor_id=admin_id,
        )
        db.session.commit()
        return correction
    except Exception:
        db.session.rollback()
        raise
