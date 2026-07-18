# 시큐어 코딩 과제 보안 체크리스트

- 기준: 제공된 `secure_coding_checklist.csv` 27개 항목 전체와 과제 확장 기능의 추가 위험
- 상태: `통과`, `부분 통과`, `실패`로 기록하며 외부 HTTPS·Docker 실기 검증이 필요한 항목은 부분 통과로 남깁니다.

## 회원가입 및 프로필 관리

| ID | 위험 | 점검 대상 | 제공 체크리스트 원문 설명 | 공격 입력·절차 | 적용 방어 | 예상 결과 | 실제 결과 | 증거 | 상태 | 잔존 위험 |
|---|---|---|---|---|---|---|---|---|---|---|
| SC-01 | XSS·비정상 계정 | 서버측 입력 검증 | 사용자명(username)과 비밀번호(password)에 대해 길이, 허용 문자 집합, 형식 등 서버측 검증 수행. XSS 공격 방지를 위해 입력값 필터링 및 인코딩 적용 여부 확인 | 잘못된 사용자명·약한 비밀번호·스크립트 소개글 입력 | 사용자명 정규식, 비밀번호 정책, 길이 제한, Jinja 자동 이스케이프 | 비정상 입력 거부, 스크립트 미실행 | 약한 비밀번호 400, XSS 인코딩 확인 | `validate_username`, `validate_password`, `test_registration_rejects_weak_password`, `test_profile_output_escapes_xss` | 통과 | 유니코드 동형 문자에 대한 별도 정규화는 미적용 |
| SC-02 | 요청 위조 | CSRF 보호 | 회원가입, 로그인, 프로필 수정 등 모든 폼에 대해 CSRF 토큰 사용 여부를 확인하여 요청 위조 공격 방지 | CSRF 토큰 없이 회원가입 POST | 전역 Flask-WTF CSRFProtect와 모든 상태 변경 폼 토큰 | 400 거부 | 토큰 없는 요청 400 확인 | `test_csrf_rejects_state_change_without_token`, 전체 폼의 `csrf_token` | 통과 | 외부 CDN 장애와 무관하게 폼 CSRF는 동작 |
| SC-03 | 계정 탈취 | 비밀번호 보안 | 비밀번호를 평문으로 저장하지 않고 bcrypt, Argon2 등 강력한 해시 알고리즘과 고유 salt를 적용하여 암호화 저장하는지 확인 | DB의 저장값과 가입 비밀번호 비교 | Argon2id, 라이브러리 기본 개별 salt, 재해시 검사 | 평문과 다른 Argon2id 문자열 | `$argon2id$` 확인 | `security.py`, `test_registration_hashes_password_and_starts_with_one_million` | 통과 | 비밀번호 유출 여부 외부 서비스 검사는 미적용 |
| SC-04 | 세션 탈취 | 세션 쿠키 설정 | 세션 쿠키에 HttpOnly 및 HTTPS 환경에서 Secure 플래그가 적용되어 있는지 확인 | 쿠키 설정 코드와 운영 설정 검토 | HttpOnly, SameSite=Lax, 운영 기본 Secure, 별도 쿠키명 | 스크립트 접근 차단, HTTPS에서만 전송 | 설정 코드 확인 | `create_app` 세션 설정, `.env.example` | 통과 | 로컬 HTTP 시연은 의도적으로 Secure=0 사용 |
| SC-05 | 탈취 세션 장기 사용 | 세션 만료 및 재인증 | 일정 시간 이후 세션 만료 및 민감 작업 시 재인증 로직이 구현되어 있는지 확인 | 오래된 세션, 비밀번호 없는 송금·구매·변경 요청 | 30분 만료, strong 세션 보호, 송금·구매·비밀번호 변경 재인증 | 만료 후 로그인, 민감 작업은 현재 비밀번호 요구 | 코드 및 거래 테스트 확인 | `PERMANENT_SESSION_LIFETIME`, `products.purchase`, `users.transfer`, `auth.change_password` | 통과 | 비밀번호 변경 외 모든 기기의 기존 서명 쿠키를 중앙 폐기하는 서버 세션 저장소는 없음 |
| SC-06 | 무차별 대입 | 실패 로그인 방어 | 로그인 실패 횟수에 따른 계정 잠금 혹은 지연(time-out) 메커니즘 적용 여부 확인 | 같은 계정에 틀린 비밀번호 5회 | 계정별 5회 실패 시 5분 잠금, IP별 10회/분 제한 | 추가 로그인 거부 | `locked_until` 생성 확인 | `test_five_failed_logins_temporarily_lock_account`, `@limiter.limit` | 통과 | 인메모리 IP 제한은 프로세스 재시작 시 초기화 |
| SC-07 | 내부 정보 노출 | 오류 메시지 | 오류 발생 시 내부 정보(스택 트레이스, DB 정보 등)가 노출되지 않도록 처리되어 있는지 확인 | 400·403·404·413·429·500 오류 발생 | 공통 오류 템플릿, 운영 debug=False, 500 롤백 | 일반 메시지만 표시 | 오류 핸들러와 실행 설정 확인 | `register_handlers`, `app.py` | 통과 | 운영 로그 수집 시스템은 별도 구성 필요 |

## 상품 등록 및 관리

| ID | 위험 | 점검 대상 | 제공 체크리스트 원문 설명 | 공격 입력·절차 | 적용 방어 | 예상 결과 | 실제 결과 | 증거 | 상태 | 잔존 위험 |
|---|---|---|---|---|---|---|---|---|---|---|
| SC-08 | 비정상 상품 데이터 | 폼 입력 검증 | 상품 제목, 설명, 가격 등의 입력 필드에 대해 서버측 검증 및 필수 항목 체크 여부 확인. 가격은 숫자 형식 및 범위 검증 적용 | 빈 제목, 음수·문자·범위 초과 가격 | 제목 2~100자, 설명 5~2000자, 가격 1~10억 원 정수 | 400 또는 오류 메시지 | 음수 송금·가격 위변조 관련 검증 통과 | `validate_text`, `parse_positive_krw`, `products.py` | 통과 | 통화는 KRW 정수만 지원 |
| SC-09 | 저장형 XSS | XSS 방어 | 사용자 입력(상품 설명 등)에 대해 HTML 태그 및 스크립트 코드 이스케이프 또는 필터링 적용 여부 확인 | `<script>`가 포함된 사용자 입력 출력 | Jinja2 자동 이스케이프, JS는 `textContent` 사용 | 태그 미실행 | 프로필 XSS 테스트로 동일 출력 경로 검증 | `base.html`, `chat.js`, `test_profile_output_escapes_xss` | 통과 | Markdown·HTML 입력 기능은 제공하지 않음 |
| SC-10 | 비인가 상품 변경 | 인증된 사용자만 등록 | 상품 등록, 수정, 삭제 기능이 로그인한 사용자에게만 허용되도록 접근 제어가 구현되어 있는지 확인 | 비로그인 상태에서 등록·수정·삭제 URL 접근 | Flask-Login `login_required` | 로그인 화면으로 이동 | 데코레이터 정적 확인 | `products.py` | 통과 | 없음 |
| SC-11 | IDOR | 소유자 확인 | 상품 수정 및 삭제 시, 요청한 사용자가 해당 상품의 소유자인지 검증하는 로직이 구현되어 있는지 확인 | 구매자가 판매자 상품 수정 URL 접근 | `_can_manage`에서 판매자 ID 또는 관리자 역할 검사 | 403 | 403 확인 | `test_only_owner_can_edit_product` | 통과 | 관리자는 업무상 모든 상품 관리 가능 |
| SC-12 | DB 불일치 | 데이터 무결성 | 데이터베이스에 저장되기 전 모든 필수 항목 및 형식이 올바른지 검증하는 로직이 있는지 확인 | 필수값 누락·0원·잘못된 상태 저장 | 서버 검증, NOT NULL, CHECK, FK, UNIQUE 제약 | 저장 거부·트랜잭션 롤백 | 모델 제약과 테스트 DB 생성 확인 | `models.py`, 22개 pytest | 통과 | 스키마 마이그레이션 도구는 소규모 과제 범위에서 미적용 |

## 실시간 채팅 및 메시징

| ID | 위험 | 점검 대상 | 제공 체크리스트 원문 설명 | 공격 입력·절차 | 적용 방어 | 예상 결과 | 실제 결과 | 증거 | 상태 | 잔존 위험 |
|---|---|---|---|---|---|---|---|---|---|---|
| SC-13 | XSS·대용량 메시지 | 메시지 내용 검증 | 채팅 메시지에 대해 길이 제한, 허용 문자 집합, XSS 이스케이프 처리 여부 등 서버측 검증 수행 여부 확인 | 빈 메시지, 1000자 초과, HTML 메시지 | 서버 1~1000자 검사, 브라우저 `textContent` | 비정상 메시지 거부, HTML 미실행 | 정상 메시지 Socket 테스트 통과, 코드 검토 | `send_private_message_event`, `chat.js` | 통과 | 메시지 금칙어·첨부파일 기능은 없음 |
| SC-14 | Socket 계정 위조 | 사용자 인증 | Socket 연결 시 사용자가 인증된 상태인지 확인하는 로직(예: 로그인 상태 확인)이 적용되어 있는지 확인 | 비로그인 또는 정지 계정 Socket 연결 | Flask-Login 세션으로 connect 검사, 클라이언트 사용자 ID 미사용 | 연결 거부 | 참여자 Socket 연결 확인 | `socket_connect`, Socket 테스트 | 통과 | 분산 Socket 환경에서는 공유 세션 저장소 필요 |
| SC-15 | 이벤트 변조·IDOR | 메시지 검증 | 클라이언트에서 수신한 메시지 데이터의 형식 및 내용에 대해 서버측 검증 로직이 존재하는지 확인 | 타 대화방 ID·변조된 자료형·잘못된 CSRF 토큰 | UUID·문자열·CSRF·대화 참여자 검증 | `chat_error`, 저장 안 됨 | 제3자 HTTP·Socket 접근 거부 확인 | `test_conversation_is_unique_and_private`, `test_socket_rejects_nonparticipant_and_accepts_participant` | 통과 | 관리자에게는 명시적 열람 권한이 있음 |
| SC-16 | 채팅 도배 | Rate Limiting | 동일 사용자가 단기간에 과도한 메시지를 보내지 않도록 제한하는 기능(스팸 방지)이 구현되어 있는지 확인 | 10초 안에 11개 이상 메시지 전송 | 사용자별 10초당 10개 인메모리 슬라이딩 윈도 | 초과 메시지 오류 | 로직·잠금 코드 정적 검증 | `_socket_rate_allowed` | 통과 | 프로세스 재시작·다중 서버 간 카운터 공유 안 됨 |
| SC-17 | 도청·변조 | 연결 암호화 | 운영 환경에서 WSS(SSL/TLS 암호화된 웹소켓)를 사용하여 데이터 전송의 기밀성이 보장되는지 확인 | ngrok HTTPS/WSS 외부 접속 | Secure 쿠키, ProxyFix 선택 설정, README ngrok HTTPS 절차 | WSS 연결 | 구현·설정 완료, 현재 ngrok 미설치로 실기 미실행 | README 외부 시연 절차 | 부분 통과 | 제출 전 실제 모바일 WSS 증거 필요 |

## 안전 거래 및 신고

| ID | 위험 | 점검 대상 | 제공 체크리스트 원문 설명 | 공격 입력·절차 | 적용 방어 | 예상 결과 | 실제 결과 | 증거 | 상태 | 잔존 위험 |
|---|---|---|---|---|---|---|---|---|---|---|
| SC-18 | 신고 데이터 변조·XSS | 폼 입력 검증 | 신고 대상(target_id) 및 신고 사유(reason)에 대해 서버측 입력 검증, 길이 제한, XSS 방어 적용 여부 확인 | 잘못된 UUID·대상 유형·짧은 사유·HTML | 대상 유형 allowlist, UUID, 실존 대상, 사유 10~1000자, 자동 이스케이프 | 잘못된 신고 거부 | 정상·중복·임계값 테스트 통과 | `reports.py`, 신고 테스트 3개 | 통과 | 신고 본문의 의미적 진위는 관리자 판단 필요 |
| SC-19 | 익명 신고 남용 | 인증된 사용자 접근 | 신고 기능은 반드시 로그인한 사용자만 접근 가능하도록 제어되어 있는지 확인 | 비로그인 신고 URL 접근 | `login_required` | 로그인 요구 | 데코레이터 확인 | `create_report` | 통과 | 없음 |
| SC-20 | 신고 부인·조작 | 데이터 무결성 및 로그 관리 | 신고 접수 시 올바른 형식의 데이터가 저장되고, 신고 활동이 감사 로그로 기록되는지 확인 | 신고 생성 후 DB·감사 로그 확인 | Report 제약, `report.created`, 자동 숨김·정지 로그 | 신고와 감사 기록 동시 커밋 | 코드와 임계값 테스트 통과 | `models.Report`, `apply_report_threshold` | 통과 | 감사 로그 외부 위변조 방지 저장소는 없음 |
| SC-21 | 신고 기능 악용 | 신고 남용 방지 | 동일 사용자의 반복 신고 제한, 신고 건수 제한 및 관리자 검토 프로세스 등 신고 기능 남용 방지 로직이 구현되어 있는지 확인 | 한 사용자의 반복 신고, 1시간 10회 초과 | DB 고유 제약, 10회/시간 제한, 관리자 처리·복구 | 중복 거부, 검토 상태 전환 | 중복 1건 유지, 3인 임계값 확인 | `test_duplicate_report_is_rejected`, 관리자 신고 화면 | 통과 | 공모한 3명이 정상 사용자를 임시 정지시킬 수 있어 관리자 복구 필요 |

## 전체 시스템

| ID | 위험 | 점검 대상 | 제공 체크리스트 원문 설명 | 공격 입력·절차 | 적용 방어 | 예상 결과 | 실제 결과 | 증거 | 상태 | 잔존 위험 |
|---|---|---|---|---|---|---|---|---|---|---|
| SC-22 | SQL 삽입 | ORM 및 파라미터 바인딩 | SQLAlchemy ORM 및 파라미터 바인딩을 통해 SQL 인젝션 공격에 대한 방어가 제대로 이루어지고 있는지 확인 | 검색어·사용자명에 SQL 메타문자 입력 | SQLAlchemy ORM, 표현식과 바인딩 값만 사용 | 쿼리 구조 미변경 | 전체 코드 검색에서 문자열 결합 SQL 없음 | `marketplace/*.py`, Ruff·Bandit 통과 | 통과 | 검색 `%`·`_`는 와일드카드로 동작하지만 데이터 노출 범위는 공개 상품으로 제한 |
| SC-23 | DB 파일 탈취 | 데이터베이스 권한 | 데이터베이스 사용자 권한이 최소 권한 원칙에 따라 설정되어 민감 데이터 접근이 제한되어 있는지 확인 | 컨테이너 사용자와 SQLite 파일 권한 검토 | SQLite 파일·비밀키·이미지 600, instance Git 제외, Docker 비루트 사용자 | 앱 사용자만 파일 쓰기 | 코드·Dockerfile 정적 확인, Docker 실기 미실행 | `security.py`, `.gitignore`, `Dockerfile` | 부분 통과 | SQLite는 DB 사용자 권한 모델이 없어 OS 파일 권한에 의존 |
| SC-24 | 클릭재킹·MIME 스니핑·XSS | 보안 헤더 설정 | Content-Security-Policy, X-Frame-Options, X-Content-Type-Options 등의 보안 헤더가 적용되어 있는지 확인 | GET 응답 헤더 확인 | CSP, DENY, nosniff, Referrer, Permissions Policy | 모든 응답에 헤더 존재 | 자동 테스트 통과 | `test_security_headers_are_set` | 통과 | Socket.IO CDN 도메인을 script-src에 허용 |
| SC-25 | 평문 전송 | HTTPS 적용 | 운영 환경에서 HTTPS를 사용하여 데이터 전송 시 기밀성 및 무결성이 보장되는지 확인 | ngrok 또는 역방향 프록시 HTTPS 접속 | Secure 쿠키, HSTS, ProxyFix, WSS 허용 | HTTPS/WSS 사용 | 코드·절차 완료, 외부 실기 미실행 | `add_security_headers`, README | 부분 통과 | 앱 자체 TLS 종료는 제공하지 않고 신뢰 프록시에 의존 |
| SC-26 | 오류 정보·로그 유출 | 에러 및 예외 처리 | 예외 처리 시 민감 정보가 사용자에게 노출되지 않고, 에러 로그에 민감 정보 기록 방지 로직이 구현되어 있는지 확인 | 500·검증 오류, 비밀번호·메시지 로그 검색 | 일반 오류 템플릿, 롤백, 감사 로그에 비밀번호·메시지 미저장 | 민감정보 미노출 | 코드 검색 및 핸들러 확인 | `register_handlers`, `AuditLog` 모델 | 통과 | 중앙 로그 마스킹·보존 정책은 운영 인프라 범위 |
| SC-27 | 알려진 취약 패키지 | 라이브러리 및 의존성 관리 | 사용 중인 Flask, SQLAlchemy, Flask-SocketIO 등 라이브러리의 최신 보안 패치 및 업데이트가 적용되어 있는지 정기적으로 점검 | `uv run --frozen pip-audit` 실행 | 직접 및 간접 의존성을 `uv.lock`에 고정하고 Flask 3.1.3·Pillow 12.3.0·pytest 9.0.3으로 갱신 | 알려진 취약점 0건 | 최초 16건 발견 후 최종 0건 | `pyproject.toml`, `uv.lock`, pip-audit 결과 | 통과 | 공개 후 정기 재검사 필요 |

## 확장 보안 항목

| ID | 위험 | 점검 대상 | 공격 입력·절차 | 적용 방어 | 예상 결과 | 실제 결과 | 증거 | 상태 | 잔존 위험 |
|---|---|---|---|---|---|---|---|---|---|
| SC-28 | 수평·수직 권한 상승 | 객체별 접근 통제·RBAC | 일반 사용자가 관리자 URL, 타인 상품·대화 접근 | `login_required`, 소유자·참여자·admin 역할 검사 | 403 | 자동 테스트 통과 | 관리자·상품·채팅 권한 테스트 | 통과 | 관리자 계정 탈취 시 영향이 크므로 MFA가 향후 필요 |
| SC-29 | 웹셸·경로 조작·이미지 폭탄 | 이미지 업로드 | 텍스트를 jpg로 위장, `../../` 파일명, 과대 해상도 | Pillow 실제 형식 검사, 6MB·5000px·25MP 제한, 재인코딩, UUID | 거부 또는 안전한 파일 생성 | 위장 거부·정상 재인코딩 확인 | 이미지 테스트 2개 | 통과 | 악성 이미지에 대한 별도 백신 샌드박스는 없음 |
| SC-30 | 이중 지불·음수 잔액 | 송금 원자성과 중복 방지 | 동일 키 재전송, 잔액 부족, 구매 경쟁 | 조건부 UPDATE, DB 트랜잭션, UNIQUE 멱등키, CHECK 잔액 | 한 번만 처리, 음수 불가 | 관련 테스트 통과 | 거래 테스트 6개 | 통과 | SQLite 단일 노드 범위이며 다중 DB 분산 거래는 미지원 |
| SC-31 | 가격 변조 | 결제 금액 | 클라이언트가 `price=1` 전송 | 상품 가격은 DB에서 다시 조회 | 300,000원 차감 | 구매자 700,000원 확인 | `test_server_uses_database_price_not_submitted_price` | 통과 | 실제 금융 결제는 범위 밖 |
| SC-32 | 거래 기록 조작 | 거래 내역 정정 | 관리자가 완료 거래를 수정·삭제하려 시도 | 수정·삭제 라우트 없음, 반대 방향 adjustment만 생성 | 원본 보존 | 정정 거래와 잔액 복구 확인 | `test_admin_reversal_records_new_adjustment` | 통과 | DB 파일 직접 접근 권한 보유자는 변경 가능하므로 운영 백업·서명 필요 |
| SC-33 | 세션 고정·잔존 | 로그인·로그아웃 | 기존 세션으로 로그인, 로그아웃 후 재접근 | 로그인 시 session.clear, strong 보호, 로그아웃 session.clear | 기존 상태 제거 | 코드 검토 | `auth.login`, `auth.logout` | 통과 | 서버측 전체 세션 목록·원격 로그아웃은 없음 |
| SC-34 | 비밀키 유출 | 설정·Git | 하드코딩 키·`.env`·DB·업로드 검색 | 환경변수 또는 권한 600 자동 키, `.gitignore`, `.dockerignore` | 저장소에 비밀 없음 | 패턴 검색 결과 없음 | `security.load_or_create_secret`, ignore 파일 | 통과 | 이미 공개된 Git 이력 검사와 본인 저장소 push 전 최종 확인 필요 |
| SC-35 | 관리자 행위 부인 | 감사 로그 | 회원·상품·신고·거래 조치 수행 | 수행자·대상·사유·시각·IP 저장, 사유 필수 | 행위 추적 가능 | 코드 검토와 정정 테스트 확인 | `AuditLog`, `admin.py` | 통과 | 외부 WORM 로그 저장소는 없음 |
| SC-36 | 컨테이너 탈출 영향 확대 | Docker 권한 | 컨테이너 사용자·보안 옵션 확인 | 비루트 `market`, `no-new-privileges`, 최소 slim 이미지 | root 권한 없이 실행 | 정적 확인, WSL 통합 문제로 런타임 미검증 | `Dockerfile`, `compose.yaml` | 부분 통과 | 이미지 빌드 후 `id` 명령으로 실제 UID 확인 필요 |
| SC-37 | 신고 공모·오탐 | 관리자 복구 | 3명이 정상 대상을 신고 | 임시 숨김·정지 후 관리자 복구, 사유·로그 | 영구 삭제 없이 복구 가능 | 관리 화면 구현 | `admin.update_user_status`, `admin.update_product_status` | 통과 | 자동 임계값 자체의 평판 가중치는 없음 |
| SC-38 | 소프트웨어 공급망 | 정적·의존성 분석 | `uv lock --check`, Ruff, Bandit, pip-audit 실행 | `uv.lock` 기반 개발 의존성 고정과 반복 가능한 `uv run` 명령 | 잠금 불일치, 오류, 고위험 취약점 0건 | 잠금 파일 최신, Ruff·Bandit 통과, audit 0건 | 실행 결과와 README 명령 | 통과 | CDN JavaScript에 SRI가 없어 CDN 침해 위험이 잔존 |
| SC-39 | 캐시를 통한 개인정보 노출 | HTML 응답 캐시 | 인증 페이지 응답 저장 | 모든 HTML에 `Cache-Control: no-store` | 브라우저·프록시 캐시 방지 | 헤더 자동 테스트 확인 | `test_security_headers_are_set` | 통과 | 정적 이미지에는 1시간 캐시 허용 |
| SC-40 | 프록시 헤더 위조 | 원본 IP·HTTPS 판정 | 직접 접속자가 X-Forwarded 헤더 전송 | 기본 TRUST_PROXY=0, 신뢰 프록시 한 단계일 때만 ProxyFix | 기본 환경에서 위조 헤더 무시 | 설정 코드 확인 | `.env.example`, `create_app`, README 경고 | 통과 | 잘못된 운영 설정으로 TRUST_PROXY를 켜면 위조 위험 |

## 보안 검사 실행 결과

```text
pytest:     22 passed, coverage 71%
ruff:       All checks passed
bandit:     Medium 0 / High 0
pip-audit:  No known vulnerabilities found
diff check: 공백 오류 없음
```

## 제출 전 필수 재점검

- Docker WSL Integration을 켜고 비루트 UID, healthcheck, SQLite 파일 권한을 확인합니다.
- ngrok HTTPS 주소에서 Secure 쿠키, HSTS, WSS 채팅을 브라우저 개발자 도구로 확인합니다.
- Public GitHub에 push하기 전 비밀키·DB·업로드·개인정보가 Git 이력에 없는지 다시 검사합니다.
- Socket.IO CDN 파일을 저장소에 포함하거나 SRI 해시를 추가하면 SC-38 잔존 위험을 줄일 수 있습니다.
