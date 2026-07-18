from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy.exc import IntegrityError

from .extensions import db, limiter
from .models import Product, Report, User
from .security import ValidationError, validate_text, validate_uuid
from .services import add_audit_log, apply_report_threshold


bp = Blueprint("reports", __name__, url_prefix="/reports")


def _target_exists(target_type: str, target_id: str):
    if target_type == "user":
        return db.session.get(User, target_id)
    if target_type == "product":
        return db.session.get(Product, target_id)
    return None


@bp.route("/new", methods=["GET", "POST"])
@login_required
@limiter.limit("10 per hour", methods=["POST"])
def create_report():
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

    report = Report(
        reporter_id=current_user.id,
        target_type=target_type,
        target_id=target_id,
        reason=reason,
    )
    db.session.add(report)
    try:
        db.session.flush()
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
    reports = (
        Report.query.filter_by(reporter_id=current_user.id)
        .order_by(Report.created_at.desc())
        .all()
    )
    return render_template("reports/list.html", reports=reports)
