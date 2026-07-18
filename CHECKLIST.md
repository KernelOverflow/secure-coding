# 요구사항 체크리스트

- 자동 테스트: `uv run --frozen pytest --cov=marketplace --cov-report=term-missing -q`
- 최종 결과: 22개 통과, 코드 커버리지 71%
- 상태 기준: `통과`는 자동 또는 정적 검증 완료, `부분 통과`는 구현되었으나 실제 외부 환경 증거가 필요한 항목입니다.

## 요구사항 추적표

| ID | 기능 및 세부 조건 | 사전 조건 | 테스트 입력·실행 절차 | 예상 결과 | 실제 결과 | 구분 | 상태 | 증거 | 실패·수정·재시험 |
|---|---|---|---|---|---|---|---|---|---|
| RQ-01 | 회원가입·로그인·회원 조회·소개글·비밀번호 변경 | 빈 DB | 신규 계정 가입 후 로그인 및 프로필 접근 | 계정 생성, 초기 잔액 1,000,000원, 해시 비밀번호 저장 | 가입·로그인 및 프로필 화면 정상, Argon2id 확인 | 자동+코드 | 통과 | `test_registration_hashes_password_and_starts_with_one_million`, `auth.py` | 최초 템플릿 경로 오류 수정 후 재시험 통과 |
| RQ-02 | 상품명·가격·사진·설명 등록, 조회, 수정, 삭제 | 로그인 판매자 | 상품 등록 후 목록·상세·수정·삭제 접근 | 본인 상품만 관리, 목록은 상품명 중심, 상세 정보 표시 | 소유권 검사와 상품 화면 구현 | 자동+코드 | 통과 | `test_only_owner_can_edit_product`, `products.py` | 없음 |
| RQ-03 | 상품별 구매자·판매자 실시간 1:1 채팅 | 판매자 상품과 구매자 | 대화 생성 2회, 제3자 URL·Socket 참가 | 방 하나만 생성, 참여자만 접근 | 고유 제약과 HTTP·Socket 권한 검사 통과 | 자동 | 통과 | `test_conversation_is_unique_and_private`, `test_socket_rejects_nonparticipant_and_accepts_participant` | 다중 앱 Socket 테스트 격리 문제 수정 후 통과 |
| RQ-04 | 악성 사용자·상품 신고 및 차단 | 서로 다른 신고자 3명 | 동일 상품·회원에 각 3명 신고 | 상품 숨김, 회원 임시 정지, 중복 신고 거부 | 자동 숨김·정지 및 중복 방지 확인 | 자동 | 통과 | `test_three_distinct_reports_hide_product`, `test_three_distinct_reports_suspend_user`, `test_duplicate_report_is_rejected` | 최초 테스트 로그인 전환 오류 수정 후 통과 |
| RQ-05 | 회원 간 내부 원화 송금과 상품 구매 | 구매자·판매자 각 1,000,000원 | 직접 송금, 상품 구매, 동일 키 재요청 | 원자적 잔액 이동, 음수 금지, 중복 차감 없음 | 잔액·거래·판매 상태 검증 통과 | 자동 | 통과 | `test_direct_transfer_rejects_negative_and_moves_valid_amount`, `test_duplicate_purchase_key_does_not_charge_twice` | 없음 |
| RQ-06 | 상품 키워드·가격·상태 검색 | 상품 1,000개 | 키워드와 가격 범위로 검색 | 정상 결과, 1초 이내 응답 | 1초 미만 assertion 통과 | 자동 | 통과 | `test_search_of_one_thousand_products_completes_under_one_second` | 없음 |
| RQ-07 | 관리자가 회원·상품·신고·채팅·거래·로그 관리 | 관리자 계정 | 관리자 화면 및 상태 변경·거래 정정 접근 | 관리자만 접근, 사유와 감사 기록 필요 | 일반 사용자 403, 정정 거래·로그 생성 | 자동+코드 | 통과 | `test_admin_route_rejects_regular_user`, `test_admin_reversal_records_new_adjustment`, `admin.py` | 없음 |

## 기능 테스트 케이스

| ID | 기능 및 세부 조건 | 사전 조건 | 테스트 입력·실행 절차 | 예상 결과 | 실제 결과 | 구분 | 상태 | 증거 | 실패·수정·재시험 |
|---|---|---|---|---|---|---|---|---|---|
| F-01 | 약한 비밀번호 거부 | 비로그인 | `password`로 가입 | 400 및 가입 거부 | 400 확인 | 자동 | 통과 | `test_registration_rejects_weak_password` | 없음 |
| F-02 | 로그인 연속 실패 잠금 | 정상 계정 | 틀린 비밀번호 5회 | 5분 잠금 시각 저장 | `locked_until` 생성 확인 | 자동 | 통과 | `test_five_failed_logins_temporarily_lock_account` | 없음 |
| F-03 | 상품 소유권 | 구매자 로그인 | 다른 판매자의 수정 URL 직접 접근 | 403 | 403 확인 | 자동 | 통과 | `test_only_owner_can_edit_product` | 없음 |
| F-04 | 이미지 위장 파일 거부 | 판매자 로그인 | 텍스트 바이트를 `.jpg`로 업로드 | 400 및 상품 미생성 | 400 확인 | 자동 | 통과 | `test_disguised_image_upload_is_rejected` | 없음 |
| F-05 | 정상 이미지 재인코딩 | 판매자 로그인 | 메타데이터 포함 JPEG와 경로형 파일명 업로드 | UUID 파일명, JPEG 재저장 | 원본 이름·경로 미사용 확인 | 자동 | 통과 | `test_valid_image_is_reencoded_with_random_filename` | 없음 |
| F-06 | 상품 구매 잔액 이동 | 구매자 1,000,000원, 상품 300,000원 | 현재 비밀번호로 구매 | 구매자 700,000원, 판매자 1,300,000원, 판매 완료 | 모든 값 일치 | 자동 | 통과 | `test_purchase_moves_balance_and_marks_product_sold` | 없음 |
| F-07 | 서버 가격 신뢰 | 상품 DB 가격 300,000원 | 클라이언트가 `price=1` 추가 전송 | DB 가격 300,000원 차감 | 구매자 700,000원 확인 | 자동 | 통과 | `test_server_uses_database_price_not_submitted_price` | 없음 |
| F-08 | 구매 경쟁 처리 | 구매자 두 명 | 같은 상품을 순차적으로 구매 요청 | 한 명만 성공, 구매 거래 하나 | 거래 1건과 `sold` 확인 | 자동 | 통과 | `test_only_one_buyer_can_claim_product` | 동시 DB 갱신은 조건부 UPDATE로 보호 |
| F-09 | 중복 구매 방지 | 정상 구매 요청 | 같은 멱등키로 2회 요청 | 한 번만 차감 | 거래 1건 확인 | 자동 | 통과 | `test_duplicate_purchase_key_does_not_charge_twice` | 없음 |
| F-10 | 음수 송금 거부 | 로그인 사용자 | `-1`원 송금 후 정상 50,000원 송금 | 음수 거부, 정상 송금만 반영 | 잔액 950,000/1,050,000원 | 자동 | 통과 | `test_direct_transfer_rejects_negative_and_moves_valid_amount` | 없음 |
| F-11 | 관리자 거래 정정 | 완료된 50,000원 송금 | 관리자가 사유와 새 키로 정정 | 원본 보존, 반대 방향 정정 거래 | 잔액 복구 및 `adjustment` 1건 | 자동 | 통과 | `test_admin_reversal_records_new_adjustment` | 없음 |
| F-12 | 신고 중복 방지 | 신고자·상품 | 같은 사용자가 같은 상품 2회 신고 | 신고 1건만 유지 | 고유 제약 확인 | 자동 | 통과 | `test_duplicate_report_is_rejected` | 없음 |
| F-13 | 채팅방 IDOR 방어 | 구매자·판매자·제3자 | 제3자가 대화 URL 직접 접근 | 403 | 403 확인 | 자동 | 통과 | `test_conversation_is_unique_and_private` | 없음 |
| F-14 | Socket 참여자 검증 | 1:1 대화방 | 참여자 메시지, 제3자 참가 | 참여자는 수신, 제3자는 오류 | 두 경로 확인 | 자동 | 통과 | `test_socket_rejects_nonparticipant_and_accepts_participant` | 테스트 앱 생명주기 수정 후 안정화 |
| F-15 | XSS 출력 인코딩 | 소개글에 `<script>` 저장 | 다른 사용자가 프로필 조회 | 태그가 실행되지 않고 이스케이프 | 원문 태그 미출력, `&lt;script&gt;` 확인 | 자동 | 통과 | `test_profile_output_escapes_xss` | 없음 |
| F-16 | 반응형 화면 | 애플리케이션 실행 | 520px·820px CSS 구간 검토 | 메뉴·검색·상품·채팅 레이아웃 재배치 | 미디어 쿼리 정적 확인 | 정적 | 통과 | `static/css/style.css` | 실제 기기 스크린샷은 제출 전 추가 필요 |
| F-17 | uv 잠금 환경 신규 설치 실행 | uv 설치 환경 | `.venv`가 없는 상태에서 `uv sync --frozen` | Python 3.12 환경과 잠긴 의존성 설치 | 잠금 파일 기준 환경 생성 및 전체 테스트 실행 | 자동+수동 | 통과 | `pyproject.toml`, `uv.lock`, `uv lock --check` | Miniconda와 requirements 구성을 uv 단일 기준으로 교체 후 재시험 통과 |
| F-18 | Docker Compose 신규 실행 | Docker Desktop WSL 통합 | `docker compose up --build` | 비루트 컨테이너 기동 및 healthcheck 정상 | 현재 WSL 통합 비활성으로 미실행 | 수동 | 부분 통과 | `Dockerfile`, `compose.yaml`, `docker version` 오류 기록 | WSL Integration 활성화 후 재시험 필요 |
| F-19 | 외부 모바일·WSS 채팅 | ngrok 설치, 모바일 기기 | 서로 다른 계정으로 HTTPS 주소 접속 | 양방향 1:1 채팅과 WSS 연결 | ngrok 미설치로 미실행 | 수동 | 부분 통과 | README 외부 시연 절차 | 제출 전 실제 화면·주소 증거 추가 필요 |
| F-20 | 공개 저장소 신규 복제 | 본인 Public GitHub URL | 빈 디렉터리에 clone 후 README만 따라 실행 | 추가 설명 없이 실행 | 공개 저장소가 아직 없어 미실행 | 수동 | 부분 통과 | README 설치 절차 | 본인 저장소 생성·push 후 최종 검증 필요 |

## 자동 검증 이력

| 실행 | 결과 | 조치 |
|---|---|---|
| 최초 전체 pytest | 14개 중 1개 통과, 13개 실패 | 패키지 템플릿 경로와 테스트 로그인 방식을 수정 |
| 2차 pytest | 14개 중 11개 통과, 3개 실패 | 테스트 사용자 전환 시 기존 세션을 종료하도록 수정 |
| 3차 pytest | 14개 중 13개 통과, Socket 테스트 1개 간헐 실패 | 전역 Socket.IO 확장을 한 번만 초기화하도록 앱 fixture를 세션 범위로 변경 |
| 4차 pytest | 14개 모두 통과 | 보안·성능 테스트 8개 추가 |
| 최종 pytest | 22개 모두 통과, 커버리지 71% | 최종 회귀 테스트 통과 |

## 제출 전 남은 수동 확인

1. Docker Desktop의 WSL Integration을 켠 뒤 Compose 빌드·관리자 생성·로그인을 확인합니다.
2. ngrok HTTPS 주소로 데스크톱과 모바일의 서로 다른 계정 간 1:1 채팅을 확인합니다.
3. 본인 Public GitHub 저장소에 올린 뒤 새 디렉터리에서 다시 복제해 `uv sync --frozen`과 README 절차를 검증합니다.
4. 위 결과의 화면 캡처와 실제 GitHub URL을 보고서에 추가합니다.
