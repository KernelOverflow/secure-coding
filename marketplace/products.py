"""상품 검색, 등록, 조회, 수정, 삭제, 구매와 이미지 제공 요청을 처리한다"""

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
from .models import Product, ProductComment
from .security import (
    ValidationError,
    parse_positive_krw,
    save_product_image,
    validate_optional_text,
    validate_text,
    validate_uuid,
    verify_password,
)
from .services import TransactionError, add_audit_log, purchase_product


bp = Blueprint("products", __name__)


def _can_manage(product: Product) -> bool:
    """현재 사용자가 상품 판매자이거나 관리자인지 확인한다"""
    return current_user.is_authenticated and (
        current_user.id == product.seller_id or current_user.is_admin
    )


def _get_visible_product(product_id: str) -> Product:
    """상품 UUID와 공개 권한을 확인해 현재 사용자가 볼 수 있는 상품만 반환한다"""
    product = db.session.get(Product, validate_uuid(product_id, "상품 ID"))
    if not product or product.status == "deleted":
        abort(404)
    if product.status == "hidden" and not _can_manage(product):
        abort(404)
    return product


@bp.get("/dashboard")
def dashboard_redirect():
    """이전 대시보드 주소로 온 요청을 현재 상품 목록으로 연결한다"""
    return redirect(url_for("products.list_products"))


@bp.get("/products")
def list_products():
    """공개 가능한 상품을 키워드, 가격, 판매 상태 조건으로 검색한다"""
    # 숨김과 삭제 상품은 처음부터 쿼리 대상에서 제외해 일반 사용자에게 노출하지 않는다
    query = Product.query.filter(Product.status.in_(["active", "sold"]))
    keyword = (request.args.get("q") or "").strip()[:100]
    if keyword:
        # SQLAlchemy가 값을 매개변수로 바인딩하므로 검색어를 SQL 문자열로 직접 붙이지 않는다
        pattern = f"%{keyword}%"
        query = query.filter(or_(Product.title.ilike(pattern), Product.description.ilike(pattern)))

    # 가격은 서버에서 양의 원화 정수로 변환하며 잘못된 값은 검색 조건에서 제외한다
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
    # 한 요청이 지나치게 많은 행과 이미지를 불러오지 않도록 최대 200개로 제한한다
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
    """상품 등록 폼을 보여 주거나 검증된 상품을 DB에 저장한다"""
    if request.method == "GET":
        return render_template("products/form.html", product=None)
    # 제목, 설명, 가격, 이미지를 모두 서버에서 검사해 변조된 폼 요청도 막는다
    try:
        title = validate_text(request.form.get("title", ""), "상품명", 2, 100)
        description = validate_optional_text(
            request.form.get("description", ""), "설명", 5, 2000
        )
        price = parse_positive_krw(request.form.get("price", ""))
        image_filename = save_product_image(request.files.get("image"))
        # 사진으로 충분히 설명할 수 있지만 사진과 설명이 모두 없는 상품은 받지 않는다
        if not description and not image_filename:
            raise ValidationError("상품 사진이나 설명 중 하나는 입력해 주세요.")
    except ValidationError as exc:
        flash(str(exc), "error")
        return render_template("products/form.html", product=None), 400

    # 검증을 통과한 값만 모델에 담고 로그인 사용자를 판매자로 지정한다
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
    """현재 사용자가 등록한 상품 중 삭제되지 않은 상품만 최신 순으로 보여준다"""
    # 삭제 기록 자체는 감사 로그와 관리자 화면에 남으므로, 본인 목록에서는 더 이상 볼 이유가 없는
    # deleted 상품을 굳이 노출해 클릭 시 404로 이어지는 죽은 링크를 만들지 않는다
    products = (
        Product.query.filter(
            Product.seller_id == current_user.id, Product.status != "deleted"
        )
        .order_by(Product.created_at.desc())
        .all()
    )
    return render_template("products/mine.html", products=products)


@bp.get("/products/<product_id>")
def view_product(product_id: str):
    """공개 가능한 상품 상세를 보여 주고 구매 중복 방지용 키를 새로 만든다"""
    product = _get_visible_product(product_id)
    comments = (
        ProductComment.query.filter_by(product_id=product.id, status="active")
        .order_by(ProductComment.created_at.desc())
        .limit(200)
        .all()
    )
    return render_template(
        "products/detail.html",
        product=product,
        comments=comments,
        purchase_key=str(uuid.uuid4()),
    )


@bp.post("/products/<product_id>/comments")
@login_required
@limiter.limit("10 per minute")
def create_comment(product_id: str):
    """로그인 회원의 검증된 댓글을 상품에 저장한다"""
    product = _get_visible_product(product_id)
    try:
        content = validate_text(request.form.get("content", ""), "댓글", 1, 500)
    except ValidationError as exc:
        flash(str(exc), "error")
        return redirect(url_for("products.view_product", product_id=product.id) + "#comments")

    comment = ProductComment(
        product_id=product.id,
        author_id=current_user.id,
        content=content,
    )
    db.session.add(comment)
    db.session.commit()
    flash("댓글을 등록했습니다.", "success")
    return redirect(url_for("products.view_product", product_id=product.id) + "#comments")


@bp.post("/products/<product_id>/comments/<comment_id>/delete")
@login_required
def delete_comment(product_id: str, comment_id: str):
    """댓글 작성자 또는 관리자가 공개 댓글을 소프트 삭제한다"""
    product = _get_visible_product(product_id)
    comment = db.session.get(
        ProductComment, validate_uuid(comment_id, "댓글 ID")
    )
    if not comment or comment.product_id != product.id or comment.status != "active":
        abort(404)
    if comment.author_id != current_user.id and not current_user.is_admin:
        abort(403)

    comment.status = "deleted"
    add_audit_log(
        "comment.deleted",
        "product_comment",
        comment.id,
        "댓글 삭제",
        actor_id=current_user.id,
    )
    db.session.commit()
    flash("댓글을 삭제했습니다.", "success")
    return redirect(url_for("products.view_product", product_id=product.id) + "#comments")


@bp.route("/products/<product_id>/edit", methods=["GET", "POST"])
@login_required
def edit_product(product_id: str):
    """판매자 또는 관리자가 상품 내용과 새 이미지를 수정한다"""
    product = db.session.get(Product, validate_uuid(product_id, "상품 ID"))
    if not product or product.status == "deleted":
        abort(404)
    # 로그인 여부만으로 부족하므로 객체 소유권까지 확인해 IDOR를 막는다
    if not _can_manage(product):
        abort(403)
    if request.method == "GET":
        return render_template("products/form.html", product=product)

    try:
        product.title = validate_text(request.form.get("title", ""), "상품명", 2, 100)
        description = validate_optional_text(
            request.form.get("description", ""), "설명", 5, 2000
        )
        product.price_krw = parse_positive_krw(request.form.get("price", ""))
        new_image = save_product_image(request.files.get("image"))
        # 새 사진이 없어도 기존 사진이 남아 있다면 빈 설명을 허용한다
        if not description and not (new_image or product.image_filename):
            raise ValidationError("상품 사진이나 설명 중 하나는 입력해 주세요.")
        product.description = description
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


@bp.post("/products/<product_id>/status")
@login_required
def update_status(product_id: str):
    """판매자는 판매 중 상품만 판매 완료로 되돌릴 수 없게 전환하고, 관리자는 양방향으로 전환한다"""
    product = db.session.get(Product, validate_uuid(product_id, "상품 ID"))
    if not product:
        abort(404)
    if not _can_manage(product):
        abort(403)
    new_status = request.form.get("status")
    if new_status not in {"active", "sold"} or product.status not in {"active", "sold"}:
        abort(400)
    # 판매 완료는 원칙적으로 되돌릴 수 없는 상태이지만, 관리자는 돈이 오가지 않는 상태 표시만
    # 바로잡을 수 있어야 하므로 sold -> active 전환은 관리자에게만 허용한다
    if new_status == "active" and product.status == "sold" and not current_user.is_admin:
        abort(403)
    product.status = new_status
    add_audit_log(
        "product.status_changed",
        "product",
        product.id,
        f"상품 상태를 {new_status}로 변경",
        actor_id=current_user.id,
    )
    db.session.commit()
    flash("상품 상태를 변경했습니다.", "success")
    # 내 상품 목록에서 전환한 경우에는 상세 페이지로 이동하지 않고 그 목록으로 돌아간다
    if request.form.get("next") == "mine":
        return redirect(url_for("products.my_products"))
    return redirect(url_for("products.view_product", product_id=product.id))


@bp.post("/products/<product_id>/delete")
@login_required
def delete_product(product_id: str):
    """상품을 실제 삭제하지 않고 deleted 상태로 바꾸어 기록을 보존한다"""
    product = db.session.get(Product, validate_uuid(product_id, "상품 ID"))
    if not product:
        abort(404)
    if not _can_manage(product):
        abort(403)
    # 완료된 거래와 연결된 상품 기록은 판매자가 임의로 숨기지 못하게 한다
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
    """현재 비밀번호를 재확인하고 내부 원화 잔액으로 상품을 구매한다"""
    product_id = validate_uuid(product_id, "상품 ID")
    try:
        # 폼에 포함한 고유 키로 새로고침과 이중 클릭에 의한 중복 결제를 막는다
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
    """공개 권한이 있는 상품의 서버 재인코딩 이미지만 응답한다"""
    # 업로드 폴더에 파일이 있더라도 실제 상품과 연결되지 않으면 직접 내려받을 수 없다
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
