"""공통 상단 바가 모든 화면에서 로그인 상태에 맞게 한 번만 렌더링되는지 검증한다"""

from marketplace.extensions import db
from marketplace.models import Conversation

from .conftest import login_as


def test_guest_pages_share_guest_topbar(client):
    """비로그인 공개 화면들이 상품 목록, 로그인, 회원가입 메뉴를 같은 구조로 쓰는지 확인한다"""
    for path in ("/", "/products", "/login", "/register"):
        page = client.get(path).get_data(as_text=True)
        assert page.count('<header class="site-header">') == 1
        assert '>상품 목록</a>' in page
        assert '>로그인</a>' in page
        assert '>회원가입</a>' in page
        assert '>내 상품</a>' not in page
        assert '>로그아웃</button>' not in page
        assert "<title>파일마켓</title>" in page
        assert page.count('<dialog class="confirm-dialog" data-confirm-dialog') == 1
        assert '/static/js/confirm-dialog.js' in page


def test_member_pages_share_authenticated_topbar(client, users):
    """일반 회원 화면들이 회원 전용 메뉴를 공유하고 관리자 메뉴는 노출하지 않는지 확인한다"""
    login_as(client, users["buyer"])
    for path in ("/products", "/profile", "/products/mine", "/conversations"):
        page = client.get(path).get_data(as_text=True)
        assert page.count('<header class="site-header">') == 1
        assert '>내 상품</a>' in page
        assert '>회원 찾기</a>' in page
        assert '>1:1 채팅</a>' in page
        assert '>로그아웃</button>' in page
        assert '>관리자</a>' not in page
        assert "<title>파일마켓</title>" in page


def test_admin_pages_share_topbar_with_admin_link(client, users):
    """관리자 화면에서도 같은 상단 바를 사용하고 관리자 링크가 추가되는지 확인한다"""
    login_as(client, users["admin"])
    for path in ("/products", "/admin", "/admin/comments"):
        page = client.get(path).get_data(as_text=True)
        assert page.count('<header class="site-header">') == 1
        assert '>상품 목록</a>' in page
        assert '>관리자</a>' in page
        assert '>로그아웃</button>' in page
        assert "<title>파일마켓</title>" in page


def test_product_and_member_pages_share_page_header_component(client, users):
    """상품 목록, 내 상품과 회원 찾기가 공통 페이지 헤더의 선택 설명과 작업 영역을 쓰는지 확인한다"""
    public_products = client.get("/products").get_data(as_text=True)
    assert public_products.count('<div class="page-head">') == 1
    assert "Marketplace" in public_products
    assert "상품 찾기" in public_products
    assert "상품명을 눌러 상세 정보와 판매자를 확인하세요." in public_products
    assert "상품 등록" not in public_products

    login_as(client, users["seller"])
    my_products = client.get("/products/mine").get_data(as_text=True)
    members = client.get("/users").get_data(as_text=True)
    assert my_products.count('<div class="page-head">') == 1
    assert "My products" in my_products
    assert "내 상품 관리" in my_products
    assert '>상품 등록</a>' in my_products
    assert members.count('<div class="page-head">') == 1
    assert "Members" in members
    assert "회원 찾기" in members
    assert "닉네임 또는 소개글로 검색해 송금할 회원을 찾습니다." in members


def test_product_lists_share_card_component(client, app, users, product):
    """공개 목록, 내 상품과 대화 목록이 같은 상품 카드에 화면별 작업만 추가하는지 확인한다"""
    public_page = client.get("/products").get_data(as_text=True)
    assert public_page.count("data-product-card") == 1
    assert "테스트 노트북" in public_page
    assert "300,000원" in public_page
    assert '>수정</a>' not in public_page

    login_as(client, users["seller"])
    my_page = client.get("/products/mine").get_data(as_text=True)
    assert my_page.count("data-product-card") == 1
    assert "테스트 노트북" in my_page
    assert '>수정</a>' in my_page
    assert 'data-confirm-message="이 상품을 정말 삭제하시겠습니까?"' in my_page

    with app.app_context():
        db.session.add(
            Conversation(
                product_id=product,
                buyer_id=users["buyer"],
                seller_id=users["seller"],
            )
        )
        db.session.commit()
    login_as(client, users["buyer"])
    conversations = client.get("/conversations").get_data(as_text=True)
    assert conversations.count("data-product-card") == 1
    assert "테스트 노트북" in conversations
    assert "300,000원" in conversations
    assert '>수정</a>' not in conversations


def test_history_pages_share_data_table_component(client, users):
    """거래와 신고 내역이 같은 표 구조에서 각 열 제목과 빈 상태 문구를 출력하는지 확인한다"""
    login_as(client, users["buyer"])
    transactions = client.get("/users/transactions/history").get_data(as_text=True)
    reports = client.get("/reports").get_data(as_text=True)

    assert transactions.count('<div class="table-wrap">') == 1
    for header in ("시각", "구분", "보낸 사용자", "받은 사용자", "금액", "메모"):
        assert f"<th>{header}</th>" in transactions
    assert '<td colspan="6">거래 내역이 없습니다.</td>' in transactions

    assert reports.count('<div class="table-wrap">') == 1
    for header in ("접수 시각", "대상 유형", "대상 ID", "사유", "상태"):
        assert f"<th>{header}</th>" in reports
    assert '<td colspan="5">신고 내역이 없습니다.</td>' in reports
