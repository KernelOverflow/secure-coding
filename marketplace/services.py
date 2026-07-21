"""라우트에서 공통으로 사용하는 잔액 이동, 구매, 신고 조치, 감사 기록을 처리한다"""

from __future__ import annotations

from flask import has_request_context
from sqlalchemy import func, update
from sqlalchemy.exc import IntegrityError

from .extensions import db
from .models import AuditLog, MoneyTransaction, Product, Purchase, Report, User
from .security import client_ip


class TransactionError(ValueError):
    """잔액 부족이나 중복 요청처럼 안전하게 사용자에게 알릴 거래 오류이다"""

    pass


def add_audit_log(
    action: str,
    target_type: str,
    target_id: str | None,
    reason: str,
    actor_id: str | None = None,
) -> AuditLog:
    """주요 작업의 수행자, 대상, 사유와 요청 IP를 감사 로그에 추가한다"""
    # 요청 밖에서 실행되는 CLI 작업은 IP가 없으므로 None으로 기록한다
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
    """조건부 UPDATE 두 개로 송신자 차감과 수신자 증가를 안전하게 수행한다"""
    if sender_id == receiver_id:
        raise TransactionError("자기 자신에게는 송금할 수 없습니다.")

    # 활성 계정이고 현재 잔액이 충분할 때만 DB가 직접 금액을 차감한다
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

    # 받는 계정도 활성 상태일 때만 증가시키며 실패하면 상위 트랜잭션이 전체를 취소한다
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
    """회원 간 송금을 한 번만 처리하고 거래 객체와 신규 처리 여부를 반환한다"""
    # 같은 고유 키가 이미 처리됐다면 잔액을 다시 움직이지 않고 기존 결과를 돌려준다
    existing = MoneyTransaction.query.filter_by(idempotency_key=idempotency_key).first()
    if existing:
        if existing.sender_id != sender_id:
            raise TransactionError("잘못된 중복 요청입니다.")
        return existing, False

    # 잔액 이동, 거래 기록, 감사 로그를 한 번의 commit으로 확정한다
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
        # 동시 요청 중 하나가 고유 키를 먼저 저장했다면 기존 성공 결과로 처리한다
        db.session.rollback()
        existing = MoneyTransaction.query.filter_by(idempotency_key=idempotency_key).first()
        if existing and existing.sender_id == sender_id:
            return existing, False
        raise TransactionError("송금 요청을 안전하게 처리하지 못했습니다.")
    except Exception:
        # 예상하지 못한 오류도 잔액만 바뀐 상태로 남지 않도록 모두 되돌린다
        db.session.rollback()
        raise


def purchase_product(
    buyer_id: str, product_id: str, idempotency_key: str
) -> tuple[Purchase, bool]:
    """상품 선점, 잔액 이동, 거래와 구매 기록을 하나의 원자적 작업으로 처리한다"""
    # 새로고침된 구매 요청이면 기존 거래와 구매자를 확인해 같은 결과를 반환한다
    existing_transaction = MoneyTransaction.query.filter_by(
        idempotency_key=idempotency_key
    ).first()
    if existing_transaction:
        purchase = Purchase.query.filter_by(transaction_id=existing_transaction.id).first()
        if purchase and purchase.buyer_id == buyer_id:
            return purchase, False
        raise TransactionError("잘못된 중복 구매 요청입니다.")

    # 가격은 폼에서 받지 않고 DB 상품 가격을 읽어 클라이언트 가격 변조를 막는다
    product = Product.query.filter_by(id=product_id).first()
    if not product or product.status != "active":
        raise TransactionError("현재 구매할 수 없는 상품입니다.")
    if product.seller_id == buyer_id:
        raise TransactionError("본인이 등록한 상품은 구매할 수 없습니다.")

    try:
        # 판매 중인 행 하나만 sold로 바꾸는 조건부 UPDATE로 동시 구매자 중 한 명만 선점한다
        claimed = db.session.execute(
            update(Product)
            .where(Product.id == product_id, Product.status == "active")
            .values(status="sold")
        )
        if claimed.rowcount != 1:
            raise TransactionError("다른 사용자가 먼저 구매한 상품입니다.")

        # 상품 선점에 성공한 뒤 DB 가격만큼 구매자에서 판매자로 잔액을 이동한다
        _move_balance(buyer_id, product.seller_id, product.price_krw)
        # 일반 거래 원장과 상품 전용 구매 기록을 함께 남겨 조회에 사용한다
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
        # 고유 키나 상품 고유 구매 제약 충돌 시 기존 성공인지 실제 실패인지 다시 확인한다
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
    """서로 다른 신고 세 건이 쌓이면 상품을 숨기거나 일반 사용자를 임시 정지한다"""
    # DB 고유 제약으로 중복 신고가 빠진 pending 신고 개수만 계산한다
    count = (
        db.session.query(func.count(Report.id))
        .filter(
            Report.target_type == target_type,
            Report.target_id == target_id,
            Report.status == "pending",
        )
        .scalar()
    )
    # 임계값 전에는 관리자 검토를 기다리며 대상 상태를 자동 변경하지 않는다
    if count < 3:
        return count

    # 상품은 삭제하지 않고 hidden으로 바꿔 관리자가 복구할 수 있게 한다
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
        # 관리자 계정은 신고 자동화만으로 정지되지 않게 해 관리 기능 잠금을 방지한다
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
