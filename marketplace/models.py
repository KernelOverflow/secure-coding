from __future__ import annotations

import uuid
from datetime import datetime, timezone

from flask_login import UserMixin
from sqlalchemy import CheckConstraint, UniqueConstraint

from .extensions import db


def new_uuid() -> str:
    return str(uuid.uuid4())


def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class User(UserMixin, db.Model):
    __tablename__ = "user"

    id = db.Column(db.String(36), primary_key=True, default=new_uuid)
    username = db.Column(db.String(20), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    bio = db.Column(db.String(500), nullable=False, default="")
    role = db.Column(db.String(20), nullable=False, default="user", index=True)
    status = db.Column(db.String(20), nullable=False, default="active", index=True)
    balance_krw = db.Column(db.Integer, nullable=False, default=1_000_000)
    failed_login_count = db.Column(db.Integer, nullable=False, default=0)
    locked_until = db.Column(db.DateTime(timezone=True), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )

    products = db.relationship("Product", back_populates="seller", lazy="dynamic")

    __table_args__ = (
        CheckConstraint("balance_krw >= 0", name="ck_user_balance_nonnegative"),
        CheckConstraint("role IN ('user', 'admin')", name="ck_user_role"),
        CheckConstraint(
            "status IN ('active', 'suspended', 'banned')", name="ck_user_status"
        ),
    )

    @property
    def is_active(self) -> bool:
        return self.status == "active"

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


class Product(db.Model):
    __tablename__ = "product"

    id = db.Column(db.String(36), primary_key=True, default=new_uuid)
    title = db.Column(db.String(100), nullable=False, index=True)
    description = db.Column(db.String(2000), nullable=False)
    price_krw = db.Column(db.Integer, nullable=False)
    image_filename = db.Column(db.String(80), nullable=True)
    seller_id = db.Column(db.String(36), db.ForeignKey("user.id"), nullable=False)
    status = db.Column(db.String(20), nullable=False, default="active", index=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )

    seller = db.relationship("User", back_populates="products")
    conversations = db.relationship("Conversation", back_populates="product", lazy="dynamic")

    __table_args__ = (
        CheckConstraint("price_krw > 0", name="ck_product_price_positive"),
        CheckConstraint(
            "status IN ('active', 'sold', 'hidden', 'deleted')",
            name="ck_product_status",
        ),
    )


class Conversation(db.Model):
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

    __table_args__ = (
        UniqueConstraint(
            "product_id", "buyer_id", "seller_id", name="uq_conversation_participants"
        ),
        CheckConstraint("buyer_id <> seller_id", name="ck_conversation_distinct_users"),
    )


class Message(db.Model):
    __tablename__ = "message"

    id = db.Column(db.String(36), primary_key=True, default=new_uuid)
    conversation_id = db.Column(
        db.String(36), db.ForeignKey("conversation.id"), nullable=False, index=True
    )
    sender_id = db.Column(db.String(36), db.ForeignKey("user.id"), nullable=False)
    content = db.Column(db.String(1000), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now)

    conversation = db.relationship("Conversation", back_populates="messages")
    sender = db.relationship("User")


class Report(db.Model):
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
    __tablename__ = "money_transaction"

    id = db.Column(db.String(36), primary_key=True, default=new_uuid)
    sender_id = db.Column(db.String(36), db.ForeignKey("user.id"), nullable=True)
    receiver_id = db.Column(db.String(36), db.ForeignKey("user.id"), nullable=True)
    amount_krw = db.Column(db.Integer, nullable=False)
    kind = db.Column(db.String(20), nullable=False, index=True)
    idempotency_key = db.Column(db.String(36), unique=True, nullable=False, index=True)
    reference_id = db.Column(db.String(36), nullable=True, index=True)
    note = db.Column(db.String(500), nullable=False, default="")
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now)

    sender = db.relationship("User", foreign_keys=[sender_id])
    receiver = db.relationship("User", foreign_keys=[receiver_id])

    __table_args__ = (
        CheckConstraint("amount_krw > 0", name="ck_transaction_amount_positive"),
        CheckConstraint(
            "kind IN ('transfer', 'purchase', 'adjustment')", name="ck_transaction_kind"
        ),
    )


class Purchase(db.Model):
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

    __table_args__ = (
        CheckConstraint("amount_krw > 0", name="ck_purchase_amount_positive"),
        CheckConstraint("status IN ('completed', 'reversed')", name="ck_purchase_status"),
    )


class AuditLog(db.Model):
    __tablename__ = "audit_log"

    id = db.Column(db.String(36), primary_key=True, default=new_uuid)
    actor_id = db.Column(db.String(36), db.ForeignKey("user.id"), nullable=True)
    action = db.Column(db.String(100), nullable=False, index=True)
    target_type = db.Column(db.String(50), nullable=False)
    target_id = db.Column(db.String(36), nullable=True)
    reason = db.Column(db.String(500), nullable=False, default="")
    ip_address = db.Column(db.String(64), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now)

    actor = db.relationship("User")
