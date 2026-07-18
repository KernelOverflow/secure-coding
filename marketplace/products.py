import uuid

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    send_from_directory,
    url_for,
)
from flask_login import current_user, login_required
from sqlalchemy import or_

from .extensions import db, limiter
from .models import Product
from .security import (
    ValidationError,
    parse_positive_krw,
    save_product_image,
    validate_text,
    validate_uuid,
    verify_password,
)
from .services import TransactionError, add_audit_log, purchase_product


bp = Blueprint("products", __name__)


def _can_manage(product: Product) -> bool:
    return current_user.is_authenticated and (
        current_user.id == product.seller_id or current_user.is_admin
    )


@bp.get("/dashboard")
def dashboard_redirect():
    return redirect(url_for("products.list_products"))


@bp.get("/products")
def list_products():
    query = Product.query.filter(Product.status.in_(["active", "sold"]))
    keyword = (request.args.get("q") or "").strip()[:100]
    if keyword:
        pattern = f"%{keyword}%"
        query = query.filter(or_(Product.title.ilike(pattern), Product.description.ilike(pattern)))

    try:
        minimum = parse_positive_krw(request.args.get("min_price")) if request.args.get("min_price") else None
        maximum = parse_positive_krw(request.args.get("max_price")) if request.args.get("max_price") else None
    except ValidationError as exc:
        flash(str(exc), "error")
        minimum = maximum = None
    if minimum is not None:
        query = query.filter(Product.price_krw >= minimum)
    if maximum is not None:
        query = query.filter(Product.price_krw <= maximum)

    status = request.args.get("status")
    if status in {"active", "sold"}:
        query = query.filter(Product.status == status)
    products = query.order_by(Product.created_at.desc()).limit(200).all()
    return render_template(
        "products/list.html",
        products=products,
        keyword=keyword,
        minimum=minimum,
        maximum=maximum,
        selected_status=status or "",
    )


@bp.route("/products/new", methods=["GET", "POST"])
@login_required
@limiter.limit("20 per hour", methods=["POST"])
def create_product():
    if request.method == "GET":
        return render_template("products/form.html", product=None)
    try:
        title = validate_text(request.form.get("title", ""), "상품명", 2, 100)
        description = validate_text(request.form.get("description", ""), "설명", 5, 2000)
        price = parse_positive_krw(request.form.get("price", ""))
        image_filename = save_product_image(request.files.get("image"))
    except ValidationError as exc:
        flash(str(exc), "error")
        return render_template("products/form.html", product=None), 400

    product = Product(
        title=title,
        description=description,
        price_krw=price,
        image_filename=image_filename,
        seller_id=current_user.id,
    )
    db.session.add(product)
    db.session.flush()
    add_audit_log(
        "product.created", "product", product.id, "상품 등록", actor_id=current_user.id
    )
    db.session.commit()
    flash("상품을 등록했습니다.", "success")
    return redirect(url_for("products.view_product", product_id=product.id))


@bp.get("/products/mine")
@login_required
def my_products():
    products = (
        Product.query.filter_by(seller_id=current_user.id)
        .order_by(Product.created_at.desc())
        .all()
    )
    return render_template("products/mine.html", products=products)


@bp.get("/products/<product_id>")
def view_product(product_id: str):
    product_id = validate_uuid(product_id, "상품 ID")
    product = db.session.get(Product, product_id)
    if not product or product.status == "deleted":
        abort(404)
    if product.status == "hidden" and not _can_manage(product):
        abort(404)
    return render_template(
        "products/detail.html",
        product=product,
        purchase_key=str(uuid.uuid4()),
    )


@bp.route("/products/<product_id>/edit", methods=["GET", "POST"])
@login_required
def edit_product(product_id: str):
    product = db.session.get(Product, validate_uuid(product_id, "상품 ID"))
    if not product or product.status == "deleted":
        abort(404)
    if not _can_manage(product):
        abort(403)
    if request.method == "GET":
        return render_template("products/form.html", product=product)

    try:
        product.title = validate_text(request.form.get("title", ""), "상품명", 2, 100)
        product.description = validate_text(
            request.form.get("description", ""), "설명", 5, 2000
        )
        product.price_krw = parse_positive_krw(request.form.get("price", ""))
        new_image = save_product_image(request.files.get("image"))
        if new_image:
            product.image_filename = new_image
    except ValidationError as exc:
        flash(str(exc), "error")
        return render_template("products/form.html", product=product), 400
    add_audit_log(
        "product.updated", "product", product.id, "상품 수정", actor_id=current_user.id
    )
    db.session.commit()
    flash("상품을 수정했습니다.", "success")
    return redirect(url_for("products.view_product", product_id=product.id))


@bp.post("/products/<product_id>/delete")
@login_required
def delete_product(product_id: str):
    product = db.session.get(Product, validate_uuid(product_id, "상품 ID"))
    if not product:
        abort(404)
    if not _can_manage(product):
        abort(403)
    if product.status == "sold":
        flash("판매가 완료된 상품은 삭제할 수 없습니다.", "error")
        return redirect(url_for("products.view_product", product_id=product.id))
    product.status = "deleted"
    add_audit_log(
        "product.deleted", "product", product.id, "상품 삭제", actor_id=current_user.id
    )
    db.session.commit()
    flash("상품을 삭제했습니다.", "success")
    return redirect(url_for("products.my_products"))


@bp.post("/products/<product_id>/purchase")
@login_required
@limiter.limit("10 per minute")
def purchase(product_id: str):
    product_id = validate_uuid(product_id, "상품 ID")
    try:
        idempotency_key = validate_uuid(
            request.form.get("idempotency_key", ""), "요청 식별자"
        )
        password = request.form.get("current_password") or ""
        if not verify_password(current_user.password_hash, password):
            raise TransactionError("현재 비밀번호가 올바르지 않습니다.")
        _purchase, created = purchase_product(current_user.id, product_id, idempotency_key)
    except (ValidationError, TransactionError) as exc:
        flash(str(exc), "error")
        return redirect(url_for("products.view_product", product_id=product_id))
    flash("구매가 완료되었습니다." if created else "이미 처리된 구매 요청입니다.", "success")
    return redirect(url_for("users.transactions"))


@bp.get("/uploads/<filename>")
def uploaded_image(filename: str):
    product = Product.query.filter_by(image_filename=filename).first()
    if not product or product.status == "deleted":
        abort(404)
    if product.status == "hidden" and not _can_manage(product):
        abort(404)
    return send_from_directory(
        current_app.config["UPLOAD_FOLDER"],
        filename,
        max_age=3600,
    )
