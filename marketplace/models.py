"""회원, 상품, 채팅, 신고, 거래, 감사 기록의 데이터베이스 구조를 정의한다"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from flask_login import UserMixin
from sqlalchemy import CheckConstraint, UniqueConstraint

from .extensions import db


def new_uuid() -> str:
    """외부에서 순서를 추측하기 어려운 UUID 문자열을 새 기본키로 만든다"""
    return str(uuid.uuid4())


def utc_now() -> datetime:
    """서버 지역과 관계없이 비교하기 쉬운 UTC 현재 시각을 반환한다"""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class User(UserMixin, db.Model):
    """로그인 아이디, 공개 닉네임, 권한, 상태, 내부 원화 잔액을 보관한다"""

    __tablename__ = "user"

    # UUID를 사용해 사용자 수와 가입 순서를 URL에서 쉽게 추측하지 못하게 한다
    id = db.Column(db.String(36), primary_key=True, default=new_uuid)
    # 아이디는 로그인에만 쓰고 닉네임은 다른 사용자에게 보여 주는 이름으로 분리한다
    login_id = db.Column(db.String(20), nullable=False, index=True)
    login_id_normalized = db.Column(db.String(20), unique=True, nullable=False, index=True)
    nickname = db.Column(db.String(20), nullable=False, index=True)
    nickname_normalized = db.Column(db.String(20), unique=True, nullable=False, index=True)
    # 비밀번호 원문 대신 Argon2id 결과만 저장한다
    password_hash = db.Column(db.String(255), nullable=False)
    bio = db.Column(db.String(500), nullable=False, default="")
    # UUID 파일명만 저장해 원본 파일명과 서버 경로가 공개되지 않게 한다
    profile_image_filename = db.Column(db.String(80), nullable=True)
    role = db.Column(db.String(20), nullable=False, default="user", index=True)
    status = db.Column(db.String(20), nullable=False, default="active", index=True)
    # 원화는 소수점 오차가 생기지 않도록 정수로 저장한다
    balance_krw = db.Column(db.Integer, nullable=False, default=1_000_000)
    # 연속 로그인 실패 횟수와 잠금 해제 시각으로 무차별 대입을 늦춘다
    failed_login_count = db.Column(db.Integer, nullable=False, default=0)
    locked_until = db.Column(db.DateTime(timezone=True), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )

    # 판매자가 등록한 상품을 필요할 때 쿼리할 수 있게 관계를 연결한다
    products = db.relationship("Product", back_populates="seller", lazy="dynamic")
    product_comments = db.relationship(
        "ProductComment", back_populates="author", lazy="dynamic"
    )

    # DB를 직접 수정하더라도 음수 잔액이나 알 수 없는 역할과 상태는 저장할 수 없다
    __table_args__ = (
        CheckConstraint("balance_krw >= 0", name="ck_user_balance_nonnegative"),
        CheckConstraint("role IN ('user', 'admin')", name="ck_user_role"),
        CheckConstraint(
            "status IN ('active', 'suspended', 'banned')", name="ck_user_status"
        ),
    )

    @property
    def is_active(self) -> bool:
        """Flask-Login이 현재 계정을 로그인 가능한 활성 계정인지 판단할 때 사용한다"""
        return self.status == "active"

    @property
    def is_admin(self) -> bool:
        """현재 사용자가 관리자 전용 기능을 사용할 수 있는지 알려준다"""
        return self.role == "admin"


class Product(db.Model):
    """판매자가 등록한 상품 정보와 판매·숨김·삭제 상태를 저장한다"""

    __tablename__ = "product"

    id = db.Column(db.String(36), primary_key=True, default=new_uuid)
    title = db.Column(db.String(100), nullable=False, index=True)
    description = db.Column(db.String(2000), nullable=False)
    price_krw = db.Column(db.Integer, nullable=False)
    image_filename = db.Column(db.String(80), nullable=True)
    # seller_id는 반드시 실제 user 행을 가리키도록 외래키로 연결한다
    seller_id = db.Column(db.String(36), db.ForeignKey("user.id"), nullable=False)
    status = db.Column(db.String(20), nullable=False, default="active", index=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )

    # 관계 속성을 이용하면 별도 SQL 없이 product.seller와 대화 목록에 접근할 수 있다
    seller = db.relationship("User", back_populates="products")
    conversations = db.relationship("Conversation", back_populates="product", lazy="dynamic")
    comments = db.relationship(
        "ProductComment",
        back_populates="product",
        cascade="all, delete-orphan",
        lazy="dynamic",
    )

    __table_args__ = (
        CheckConstraint("price_krw > 0", name="ck_product_price_positive"),
        CheckConstraint(
            "status IN ('active', 'sold', 'hidden', 'deleted')",
            name="ck_product_status",
        ),
    )


class ProductComment(db.Model):
    """상품 상세 화면에 회원이 남긴 공개 댓글과 삭제 상태를 보관한다"""

    __tablename__ = "product_comment"

    id = db.Column(db.String(36), primary_key=True, default=new_uuid)
    product_id = db.Column(
        db.String(36), db.ForeignKey("product.id"), nullable=False, index=True
    )
    author_id = db.Column(
        db.String(36), db.ForeignKey("user.id"), nullable=False, index=True
    )
    content = db.Column(db.String(500), nullable=False)
    status = db.Column(db.String(20), nullable=False, default="active", index=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now)

    product = db.relationship("Product", back_populates="comments")
    author = db.relationship("User", back_populates="product_comments")

    __table_args__ = (
        CheckConstraint("length(content) BETWEEN 1 AND 500", name="ck_comment_length"),
        CheckConstraint(
            "status IN ('active', 'deleted')", name="ck_product_comment_status"
        ),
    )


class Conversation(db.Model):
    """특정 상품의 구매자와 판매자 사이에 하나만 존재하는 1:1 대화방이다"""

    __tablename__ = "conversation"

    id = db.Column(db.String(36), primary_key=True, default=new_uuid)
    product_id = db.Column(db.String(36), db.ForeignKey("product.id"), nullable=False)
    buyer_id = db.Column(db.String(36), db.ForeignKey("user.id"), nullable=False)
    seller_id = db.Column(db.String(36), db.ForeignKey("user.id"), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now)

    product = db.relationship("Product", back_populates="conversations")
    buyer = db.relationship("User", foreign_keys=[buyer_id])
    seller = db.relationship("User", foreign_keys=[seller_id])
    messages = db.relationship(
        "Message", back_populates="conversation", cascade="all, delete-orphan", lazy="dynamic"
    )

    # 같은 세 사람이 중복 대화방을 만들지 못하게 하고 구매자와 판매자가 같지 않게 한다
    __table_args__ = (
        UniqueConstraint(
            "product_id", "buyer_id", "seller_id", name="uq_conversation_participants"
        ),
        CheckConstraint("buyer_id <> seller_id", name="ck_conversation_distinct_users"),
    )


class Message(db.Model):
    """1:1 대화방에서 누가 어떤 내용을 언제 보냈는지와 공개 상태를 저장한다"""

    __tablename__ = "message"

    id = db.Column(db.String(36), primary_key=True, default=new_uuid)
    conversation_id = db.Column(
        db.String(36), db.ForeignKey("conversation.id"), nullable=False, index=True
    )
    sender_id = db.Column(db.String(36), db.ForeignKey("user.id"), nullable=False)
    content = db.Column(db.String(1000), nullable=False)
    status = db.Column(db.String(20), nullable=False, default="active", index=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now)

    conversation = db.relationship("Conversation", back_populates="messages")
    sender = db.relationship("User")

    __table_args__ = (
        CheckConstraint("status IN ('active', 'deleted')", name="ck_message_status"),
    )


class Report(db.Model):
    """사용자 또는 상품 신고와 관리자의 처리 결과를 저장한다"""

    __tablename__ = "report"

    id = db.Column(db.String(36), primary_key=True, default=new_uuid)
    reporter_id = db.Column(db.String(36), db.ForeignKey("user.id"), nullable=False)
    target_type = db.Column(db.String(20), nullable=False, index=True)
    target_id = db.Column(db.String(36), nullable=False, index=True)
    reason = db.Column(db.String(1000), nullable=False)
    status = db.Column(db.String(20), nullable=False, default="pending", index=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now)
    resolved_at = db.Column(db.DateTime(timezone=True), nullable=True)
    resolved_by_id = db.Column(db.String(36), db.ForeignKey("user.id"), nullable=True)

    reporter = db.relationship("User", foreign_keys=[reporter_id])
    resolved_by = db.relationship("User", foreign_keys=[resolved_by_id])

    # 같은 사용자가 동일 대상을 반복 신고해 자동 차단 수를 부풀리지 못하게 한다
    __table_args__ = (
        UniqueConstraint(
            "reporter_id", "target_type", "target_id", name="uq_report_once"
        ),
        CheckConstraint("target_type IN ('user', 'product')", name="ck_report_target_type"),
        CheckConstraint(
            "status IN ('pending', 'resolved', 'dismissed')", name="ck_report_status"
        ),
    )


class MoneyTransaction(db.Model):
    """회원 송금과 상품 구매로 발생한 잔액 이동을 삭제 없이 기록한다"""

    __tablename__ = "money_transaction"

    id = db.Column(db.String(36), primary_key=True, default=new_uuid)
    sender_id = db.Column(db.String(36), db.ForeignKey("user.id"), nullable=True)
    receiver_id = db.Column(db.String(36), db.ForeignKey("user.id"), nullable=True)
    amount_krw = db.Column(db.Integer, nullable=False)
    kind = db.Column(db.String(20), nullable=False, index=True)
    # 요청마다 고유 키를 저장해 새로고침이나 중복 클릭으로 두 번 처리되는 일을 막는다
    idempotency_key = db.Column(db.String(36), unique=True, nullable=False, index=True)
    reference_id = db.Column(db.String(36), nullable=True, index=True)
    note = db.Column(db.String(500), nullable=False, default="")
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now)

    sender = db.relationship("User", foreign_keys=[sender_id])
    receiver = db.relationship("User", foreign_keys=[receiver_id])

    __table_args__ = (
        CheckConstraint("amount_krw > 0", name="ck_transaction_amount_positive"),
        CheckConstraint(
            "kind IN ('transfer', 'purchase')", name="ck_transaction_kind"
        ),
    )


class Purchase(db.Model):
    """상품 구매자, 판매자, 금액과 연결된 원화 거래를 하나의 구매 기록으로 묶는다"""

    __tablename__ = "purchase"

    id = db.Column(db.String(36), primary_key=True, default=new_uuid)
    product_id = db.Column(
        db.String(36), db.ForeignKey("product.id"), nullable=False, unique=True
    )
    buyer_id = db.Column(db.String(36), db.ForeignKey("user.id"), nullable=False)
    seller_id = db.Column(db.String(36), db.ForeignKey("user.id"), nullable=False)
    transaction_id = db.Column(
        db.String(36), db.ForeignKey("money_transaction.id"), nullable=False, unique=True
    )
    amount_krw = db.Column(db.Integer, nullable=False)
    status = db.Column(db.String(20), nullable=False, default="completed")
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now)

    product = db.relationship("Product")
    buyer = db.relationship("User", foreign_keys=[buyer_id])
    seller = db.relationship("User", foreign_keys=[seller_id])
    transaction = db.relationship("MoneyTransaction")

    # 한 상품은 한 번만 구매되고 한 거래도 한 구매에만 연결되도록 제한한다
    __table_args__ = (
        CheckConstraint("amount_krw > 0", name="ck_purchase_amount_positive"),
        CheckConstraint("status = 'completed'", name="ck_purchase_status"),
    )


class AuditLog(db.Model):
    """로그인, 신고, 거래, 관리자 조치처럼 추적이 필요한 작업을 기록한다"""

    __tablename__ = "audit_log"

    id = db.Column(db.String(36), primary_key=True, default=new_uuid)
    actor_id = db.Column(db.String(36), db.ForeignKey("user.id"), nullable=True)
    action = db.Column(db.String(100), nullable=False, index=True)
    target_type = db.Column(db.String(50), nullable=False)
    target_id = db.Column(db.String(36), nullable=True)
    reason = db.Column(db.String(500), nullable=False, default="")
    ip_address = db.Column(db.String(64), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now)

    # actor를 통해 작업을 수행한 사용자의 닉네임과 관리자 아이디를 조회할 수 있다
    actor = db.relationship("User")
