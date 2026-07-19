"""사용자와 상품 신고를 접수하고 중복 신고 및 자동 조치 기준을 처리한다"""

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy.exc import IntegrityError

from .extensions import db, limiter
from .models import Product, Report, User
from .security import ValidationError, validate_text, validate_uuid
from .services import add_audit_log, apply_report_threshold


bp = Blueprint("reports", __name__, url_prefix="/reports")


def _target_exists(target_type: str, target_id: str):
    """신고 유형에 맞는 실제 사용자 또는 상품을 조회한다"""
    if target_type == "user":
        return db.session.get(User, target_id)
    if target_type == "product":
        return db.session.get(Product, target_id)
    return None


@bp.route("/new", methods=["GET", "POST"])
@login_required
@limiter.limit("10 per hour", methods=["POST"])
def create_report():
    """신고 대상과 사유를 검증하고 한 사용자당 한 번만 신고를 저장한다"""
    # GET과 POST 어디에서 오더라도 대상 유형과 UUID를 먼저 검증한다
    target_type = request.values.get("target_type", "")
    raw_target_id = request.values.get("target_id", "")
    try:
        if target_type not in {"user", "product"}:
            raise ValidationError("신고 대상 유형이 올바르지 않습니다.")
        target_id = validate_uuid(raw_target_id, "신고 대상 ID")
    except ValidationError as exc:
        flash(str(exc), "error")
        return redirect(url_for("products.list_products"))

    target = _target_exists(target_type, target_id)
    if not target:
        abort(404)
    # 자기 자신이나 자기 상품을 신고해 임계값을 조작하지 못하게 한다
    if target_type == "user" and target_id == current_user.id:
        flash("자기 자신은 신고할 수 없습니다.", "error")
        return redirect(url_for("users.view_user", user_id=target_id))
    if target_type == "product" and target.seller_id == current_user.id:
        flash("자신의 상품은 신고할 수 없습니다.", "error")
        return redirect(url_for("products.view_product", product_id=target_id))

    if request.method == "GET":
        return render_template(
            "reports/form.html", target_type=target_type, target_id=target_id, target=target
        )
    try:
        reason = validate_text(request.form.get("reason", ""), "신고 사유", 10, 1000)
    except ValidationError as exc:
        flash(str(exc), "error")
        return render_template(
            "reports/form.html", target_type=target_type, target_id=target_id, target=target
        ), 400

    # DB 고유 제약도 함께 사용해 동시에 같은 신고를 보내도 하나만 저장되게 한다
    report = Report(
        reporter_id=current_user.id,
        target_type=target_type,
        target_id=target_id,
        reason=reason,
    )
    db.session.add(report)
    try:
        db.session.flush()
        # 신고를 먼저 flush한 뒤 현재 누적 수를 계산해야 이번 신고까지 포함된다
        count = apply_report_threshold(target_type, target_id)
        add_audit_log(
            "report.created",
            target_type,
            target_id,
            "사용자 신고 접수",
            actor_id=current_user.id,
        )
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        flash("동일한 대상은 한 번만 신고할 수 있습니다.", "error")
        return redirect(url_for("reports.my_reports"))

    if count >= 3:
        flash("신고가 접수되어 대상이 관리자 검토 상태로 전환되었습니다.", "success")
    else:
        flash("신고가 접수되었습니다.", "success")
    return redirect(url_for("reports.my_reports"))


@bp.get("")
@login_required
def my_reports():
    """현재 사용자가 제출한 신고와 처리 상태를 최신 순으로 보여준다"""
    reports = (
        Report.query.filter_by(reporter_id=current_user.id)
        .order_by(Report.created_at.desc())
        .all()
    )
    return render_template("reports/list.html", reports=reports)
