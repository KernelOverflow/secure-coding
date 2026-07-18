import uuid

from marketplace.extensions import db
from marketplace.models import MoneyTransaction, Product, Purchase, User

from .conftest import TEST_PASSWORD, login_as


def test_only_owner_can_edit_product(client, users, product):
    login_as(client, users["buyer"])
    assert client.get(f"/products/{product}/edit").status_code == 403


def test_purchase_moves_balance_and_marks_product_sold(client, app, users, product):
    login_as(client, users["buyer"])
    key = str(uuid.uuid4())
    response = client.post(
        f"/products/{product}/purchase",
        data={"idempotency_key": key, "current_password": TEST_PASSWORD},
    )
    assert response.status_code == 302
    with app.app_context():
        buyer = db.session.get(User, users["buyer"])
        seller = db.session.get(User, users["seller"])
        item = db.session.get(Product, product)
        assert buyer.balance_krw == 700_000
        assert seller.balance_krw == 1_300_000
        assert item.status == "sold"
        assert Purchase.query.filter_by(product_id=product).count() == 1
        assert MoneyTransaction.query.filter_by(idempotency_key=key).count() == 1


def test_duplicate_purchase_key_does_not_charge_twice(client, app, users, product):
    login_as(client, users["buyer"])
    key = str(uuid.uuid4())
    data = {"idempotency_key": key, "current_password": TEST_PASSWORD}
    client.post(f"/products/{product}/purchase", data=data)
    client.post(f"/products/{product}/purchase", data=data)
    with app.app_context():
        buyer = db.session.get(User, users["buyer"])
        assert buyer.balance_krw == 700_000
        assert MoneyTransaction.query.filter_by(idempotency_key=key).count() == 1


def test_direct_transfer_rejects_negative_and_moves_valid_amount(client, app, users):
    login_as(client, users["buyer"])
    invalid = client.post(
        f"/users/{users['seller']}/transfer",
        data={
            "amount": "-1",
            "idempotency_key": str(uuid.uuid4()),
            "current_password": TEST_PASSWORD,
        },
    )
    assert invalid.status_code == 302
    client.post(
        f"/users/{users['seller']}/transfer",
        data={
            "amount": "50000",
            "idempotency_key": str(uuid.uuid4()),
            "current_password": TEST_PASSWORD,
            "note": "거래 대금",
        },
    )
    with app.app_context():
        assert db.session.get(User, users["buyer"]).balance_krw == 950_000
        assert db.session.get(User, users["seller"]).balance_krw == 1_050_000


def test_server_uses_database_price_not_submitted_price(client, app, users, product):
    login_as(client, users["buyer"])
    client.post(
        f"/products/{product}/purchase",
        data={
            "idempotency_key": str(uuid.uuid4()),
            "current_password": TEST_PASSWORD,
            "price": "1",
        },
    )
    with app.app_context():
        assert db.session.get(User, users["buyer"]).balance_krw == 700_000
