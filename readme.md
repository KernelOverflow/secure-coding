# 파일마켓

- Python 및 Flask로 구현한 소규모 중고거래 플랫폼입니다.
- 강의에서 제공된 `ugonfor/secure-coding` 예제 코드를 기반으로 아래 기능을 구현했습니다.
  1. 회원가입, 로그인, 회원 검색, 프로필 및 비밀번호 변경
  2. 상품 사진, 가격 및 설명 등록, 조회, 수정, 삭제 및 검색
  3. 상품별 구매자와 판매자의 실시간 1:1 채팅
  4. 사용자 및 상품 신고, 중복 신고 방지 및 누적 신고 차단
  5. 서비스 내부 원화 잔액 송금 및 상품 구매
  6. 회원, 상품, 신고, 거래, 채팅 및 감사 로그 관리자 기능
  7. 기존 코드의 보안 취약 구조 개선 및 자동화 테스트 추가

> NOTE : 모든 상품 가격과 거래 금액은 원화로 표시되지만 과제에서 제시한 프로토타입 구현을 목적으로 설계했기에 실제 카드 및 은행 결제 시스템과는 연결되지 않습니다. 신규 회원에게 제공되는 1,000,000원은 서비스 내부 잔액으로써 포인트의 개념으로 사용됩니다.



## 주요 기능

- 회원가입, 로그인, 회원 검색, 소개글 및 비밀번호 변경
- 상품 사진, 가격 및 설명 등록, 조회, 검색, 수정, 삭제
- 상품별 구매자와 판매자의 실시간 1:1 채팅
- 사용자 간 내부 원화 송금과 상품 구매
- 중복 신고 방지, 3인 신고 시 상품 숨김과 회원 임시 정지
- 회원, 상품, 신고, 거래, 채팅 및 감사 로그 관리자 화면
- CSRF, Argon2id, 객체별 권한 검사, 입력 검증, 보안 헤더, 요청 제한



## 프로젝트 구조

```text
marketplace/
  __init__.py       애플리케이션 팩토리와 공통 보안 설정
  models.py         SQLAlchemy 데이터 모델
  auth.py           인증과 프로필
  products.py       상품과 이미지, 구매
  users.py          회원 검색과 송금 내역
  chat.py           상품별 1:1 Socket.IO 채팅
  reports.py        신고와 자동 차단
  admin.py          관리자 기능
  security.py       입력, 비밀번호 및 이미지 보안
  services.py       송금, 구매 및 감사 서비스
templates/          Jinja2 화면
static/             반응형 CSS와 JavaScript
tests/              pytest 자동화 테스트
pyproject.toml      프로젝트 및 의존성 선언
uv.lock             운영 및 개발 의존성 잠금
```



## uv로 실행

먼저 [uv 공식 설치 안내](https://docs.astral.sh/uv/getting-started/installation/)에 따라 uv를 설치합니다. Linux, WSL 및 macOS에서는 다음 명령으로 설치할 수 있습니다.

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Windows에서는 PowerShell에서 다음 명령을 사용합니다.

```powershell
winget install --id=astral-sh.uv -e
```

설치 후 운영체제와 관계없이 프로젝트 루트에서 같은 uv 명령을 사용합니다.

```bash
git clone <본인의-public-github-repository-url>
cd secure-coding
uv sync --frozen
uv run --frozen python app.py
```

uv가 Python 3.12와 `.venv`를 준비하고 `uv.lock`에 고정된 운영 및 개발 의존성을 설치합니다. 브라우저에서 `http://127.0.0.1:5000`으로 접속합니다.

관리자 계정은 기본 계정이나 하드코딩된 비밀번호 없이 직접 생성합니다.

```bash
uv run --frozen flask --app app create-admin
```



## Docker Compose로 실행

```bash
docker compose up --build
docker compose exec web uv run --no-sync flask --app app create-admin
```

`http://127.0.0.1:5000`으로 접속합니다. 컨테이너는 비루트 `market` 사용자로 실행하며 DB, 업로드 및 자동 생성 비밀키는 `market_instance` 볼륨에 보관합니다.

종료할 때 데이터 볼륨을 보존하려면 다음 명령만 사용합니다.

```bash
docker compose down
```



## 외부 기기에서 시연

ngrok 설치와 계정 인증을 완료한 뒤 애플리케이션을 실행하고 별도 터미널에서 다음 명령을 실행합니다.

```bash
ngrok http 5000
```

운영에 가까운 HTTPS/WSS 설정으로 확인할 때는 프록시 신뢰 범위를 ngrok 한 단계로 제한하고 보안 쿠키를 활성화합니다.

```bash
FLASK_ENV=production COOKIE_SECURE=1 TRUST_PROXY=1 uv run --frozen python app.py
```

ngrok이 제공한 HTTPS 주소를 데스크톱과 모바일에서 각각 열어 서로 다른 계정으로 1:1 채팅을 확인합니다. `TRUST_PROXY=1`은 신뢰할 수 있는 단일 역방향 프록시 뒤에서만 사용합니다.



## 환경변수

| 변수 | 기본값 | 설명 |
|---|---:|---|
| `SECRET_KEY` | 자동 생성 | 32자 이상 비밀키. 미설정 시 `instance/.secret_key`에 권한 `600`으로 생성 |
| `DATABASE_URL` | `instance/market.db` | SQLAlchemy DB 주소 |
| `FLASK_ENV` | `development` | `production`이면 보안 쿠키 기본 활성화 |
| `COOKIE_SECURE` | 환경에 따라 결정 | HTTPS에서 `1`, 로컬 HTTP에서 `0` |
| `TRUST_PROXY` | `0` | 신뢰하는 역방향 프록시가 한 단계 있을 때만 `1` |
| `HOST` | `127.0.0.1` | 개발 서버 바인딩 주소 |
| `PORT` | `5000` | 개발 서버 포트 |

`.env.example`에는 변수 이름만 있으며 실제 비밀키와 `.env`는 Git에 포함하지 않습니다.



## 테스트와 보안 검사

```bash
uv lock --check
uv run --frozen pytest --cov=marketplace --cov-report=term-missing
uv run --frozen ruff check .
uv run --frozen bandit -r marketplace app.py -q
uv run --frozen pip-audit
git diff --check
```

검증 당시 결과는 다음과 같습니다.

- pytest: 22개 통과
- 코드 커버리지: 71%
- uv 잠금 파일: 최신 상태
- Ruff: 통과
- Bandit: 발견 사항 없음
- pip-audit: 발견된 취약 의존성을 수정 버전으로 올린 뒤 알려진 취약점 없음



## 보안 설계 요약

- 비밀번호는 Argon2id로 해시하고 로그인 5회 실패 시 5분 동안 잠급니다.
- 모든 상태 변경 폼과 Socket.IO 메시지에 CSRF 검증을 적용합니다.
- 송금 및 구매 금액은 서버 DB 값을 기준으로 계산하고 중복 요청 키와 DB 트랜잭션으로 이중 처리를 방지합니다.
- 이미지의 실제 형식, 크기 및 해상도를 검사하고 UUID 파일명으로 다시 인코딩합니다.
- 상품, 채팅 및 관리자 기능은 로그인뿐 아니라 소유권, 대화 참여자 및 역할을 확인합니다.
- 신고, 거래 및 관리자 조치는 감사 로그 또는 별도 거래 내역으로 기록합니다.

자세한 구현, 테스트 및 잔존 위험은 `REPORT.md`, `CHECKLIST.md`, `SECURITY_CHECKLIST.md`에서 확인할 수 있습니다.



## 알려진 제한 사항

- 실제 금융 결제와 계좌 정산을 제공하지 않습니다.
- SQLite와 단일 Gunicorn 프로세스를 기준으로 설계했습니다. 다중 서버 운영 시 PostgreSQL, Redis 기반 요청 제한 및 Socket.IO 메시지 큐가 필요합니다.
- Socket.IO 브라우저 클라이언트는 CSP로 허용한 고정 버전 CDN을 사용하므로 완전한 오프라인 채팅에는 로컬 정적 파일로의 교체가 필요합니다.
- 공개 GitHub URL, 제출자 정보, 외부 모바일 및 ngrok 증거는 제출 전에 본인 환경에서 채워야 합니다.
