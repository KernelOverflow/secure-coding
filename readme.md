# 파일마켓

- Python 및 Flask로 구현한 소규모 중고거래 플랫폼입니다.
- 강의에서 제공된 `ugonfor/secure-coding` 예제 코드를 기반으로 아래 기능을 구현했습니다.
  1. 닉네임, 아이디, 비밀번호 기반 회원가입과 로그인, 회원 검색, 프로필 사진 및 소개글 변경
  2. 상품 사진, 가격 및 설명 등록, 조회, 수정, 삭제 및 검색
  3. 상품별 구매자와 판매자의 실시간 1:1 채팅
  4. 사용자 및 상품 신고, 중복 신고 방지 및 누적 신고 차단
  5. 서비스 내부 원화 잔액 송금 및 상품 구매
  6. 회원, 프로필 콘텐츠, 상품, 댓글, 신고, 구매, 거래, 채팅 메시지 및 감사 로그 관리자 기능
  7. 기존 코드의 보안 취약 구조 개선 및 자동화 테스트 추가

> NOTE : 모든 상품 가격과 거래 금액은 원화로 표시되지만 과제에서 제시한 프로토타입 구현을 목적으로 설계했기에 실제 카드 및 은행 결제 시스템과는 연결되지 않습니다. 신규 회원에게 제공되는 1,000,000원은 서비스 내부 잔액으로써 포인트의 개념으로 사용됩니다.



## 주요 기능

- 닉네임, 아이디, 비밀번호 기반 회원가입과 로그인, 아이디 기억과 로그인 상태 유지
- 닉네임 기반 회원 검색, 소개글 및 비밀번호 변경
- 상품 사진, 가격 및 설명 등록, 조회, 검색, 수정, 삭제
- 상품 상세 댓글 작성과 본인 댓글 삭제
- 상품별 구매자와 판매자의 실시간 1:1 채팅
- 사용자 간 내부 원화 송금과 상품 구매
- 중복 신고 방지, 3인 신고 시 상품 숨김과 회원 임시 정지
- 회원 상태와 프로필 콘텐츠, 상품, 댓글, 신고, 구매, 거래, 대화·메시지 및 감사 로그 관리자 화면
- 관리자 전체 목록 검색과 50개 단위 페이지 이동, 조치 사유와 감사 기록
- CSRF, Argon2id, 객체별 권한 검사, 입력 검증, 보안 헤더, 요청 제한



### 계정 표시 정책

- 회원가입 화면은 닉네임, 아이디, 비밀번호 순서로 입력합니다.
- 아이디는 영문 소문자, 숫자, 밑줄 4~20자로 제한하며 로그인에만 사용합니다.
- 닉네임은 한글, 영문, 숫자, 밑줄, 공백 2~20자로 제한하며 일반 사용자 화면에는 닉네임만 표시합니다.
- 닉네임은 NFKC 정규화와 대소문자 통일 결과를 기준으로 중복을 방지하고 관리자 및 서비스 사칭 표현을 거부합니다.
- 비밀번호는 영문, 숫자, 특수문자를 모두 포함한 8~128자로 받고 Argon2id로 해시합니다.
- 아이디는 일반 회원, 상품, 채팅, 신고 및 거래 화면에 노출하지 않으며 관리자만 계정 식별 목적으로 확인할 수 있습니다.



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
templates/          Jinja2 화면과 공통 상단 바·페이지 헤더·상품 카드·표 컴포넌트
static/             반응형 CSS와 JavaScript
tests/              pytest 자동화 테스트
pyproject.toml      프로젝트 및 의존성 선언
uv.lock             운영 및 개발 의존성 잠금
```

- 코드 리뷰를 위해 대부분의 파일에 주석을 달아뒀습니다.



## 실행 방법

- 해당 프로젝트는 Docker Compose로 실행 또는 uv로 직접 실행 둘 중 하나의 방법으로 실행할 수 있습니다.
- 또한 ngrok을 통해 외부 접속을 시현해볼 수 있습니다.



### Docker Compose로 실행 (권장)

- Docker Compose는 Python과 라이브러리를 호스트에 따로 설치하지 않아도 동일한 환경으로 실행할 수 있어 가장 권장하는 방법입니다.

- Docker Desktop 또는 Docker Engine과 Compose 플러그인을 설치한 뒤 다음 명령을 실행합니다.

```bash
git clone https://github.com/KernelOverflow/secure-coding.git
cd secure-coding
docker compose up --build -d
```

이미지를 빌드하고 컨테이너를 백그라운드에서 실행합니다. 브라우저에서 `http://127.0.0.1:5000`으로 접속합니다. 컨테이너는 비루트 `market` 사용자로 실행하며 DB, 업로드 이미지와 자동 생성 비밀키는 `market_instance` 볼륨에 보관합니다.

관리자 기능을 사용할 때만 다음 명령으로 관리자 계정을 생성합니다. 기본 관리자 계정이나 하드코딩된 비밀번호는 제공하지 않습니다.

```bash
docker compose exec web uv run --no-sync flask --app app create-admin
```

실행 상태와 로그는 다음 명령으로 확인합니다.

```bash
docker compose ps
docker compose logs -f web
```

종료할 때 데이터 볼륨을 보존하려면 다음 명령을 사용합니다.

```bash
docker compose down
```



### uv로 직접 실행

- Docker를 사용하지 않거나 코드를 수정하면서 개발 서버의 자동 재시작 기능을 사용하려면 uv로 직접 실행합니다.

- 먼저 [uv 공식 설치 안내](https://docs.astral.sh/uv/getting-started/installation/)에 따라 uv를 설치합니다. Linux, WSL 및 macOS에서는 다음 명령으로 설치할 수 있습니다.

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Windows에서는 PowerShell에서 다음 명령을 사용합니다.

```powershell
winget install --id=astral-sh.uv -e
```

설치 후 다음 명령을 실행합니다.

```bash
git clone https://github.com/KernelOverflow/secure-coding.git
cd secure-coding
uv sync --frozen
uv run --frozen python app.py
```

uv가 Python 3.12와 `.venv`를 준비하고 `uv.lock`에 고정된 운영 및 개발 의존성을 설치합니다. 브라우저에서 `http://127.0.0.1:5000`으로 접속합니다.

기본 `FLASK_ENV=development`에서는 Python 코드 변경 시 서버를 자동 재시작하고 Jinja 템플릿을 다시 읽으며 CSS와 JavaScript 캐시를 해제합니다. 운영 환경에서는 `FLASK_ENV=production`으로 실행해 디버그, 리로더와 템플릿 자동 갱신 기능을 모두 끕니다. 두 값 외의 환경 이름은 안전을 위해 거부합니다.

host와 port를 계속 사용할 값으로 지정하려면 `.env.example`을 `.env`로 복사한 뒤 다음 항목을 수정합니다. `.env`는 자동으로 불러오며 Git에는 포함하지 않습니다.

```dotenv
HOST=127.0.0.1
PORT=8000
```

한 번만 다른 주소로 실행할 때는 명령행 옵션을 사용합니다. 명령행 옵션, 환경변수 또는 `.env`, 기본값 순으로 우선 적용됩니다.

```bash
uv run --frozen python app.py --host 127.0.0.1 --port 8000
```

`0.0.0.0`으로 바인딩하면 같은 네트워크의 다른 기기에서도 접근할 수 있으므로, 방화벽과 신뢰할 수 있는 네트워크를 확인한 경우에만 사용합니다.

관리자 기능을 사용할 때만 새 터미널에서 다음 명령으로 관리자 계정을 생성합니다.

```bash
uv run --frozen flask --app app create-admin
```



### ngrok으로 외부 기기에서 시연 (선택)

- ngrok은 파일마켓을 실행하는 세 번째 방법이 아니라 이미 실행 중인 로컬 서버를 외부 기기에서 접속할 수 있게 임시 HTTPS 주소로 연결하는 보조 도구입니다.
- 로컬 실행만 필요하다면 이 과정은 생략합니다.

ngrok은 Docker 컨테이너 안이 아니라 파일마켓을 실행하는 호스트 컴퓨터에 설치하고 실행합니다. Docker Compose는 컨테이너의 5000번 포트를 호스트의 5000번 포트로 연결하고, uv 직접 실행도 호스트의 5000번 포트를 사용하므로 두 실행 방법 모두 같은 ngrok 명령을 사용합니다.

Docker Compose 또는 uv 중 한 가지 방법으로 파일마켓을 먼저 실행한 뒤 호스트 컴퓨터의 별도 터미널에서 다음 명령을 실행합니다.

```bash
ngrok http 5000
```

ngrok이 제공한 HTTPS 주소를 데스크톱과 모바일에서 각각 열어 서로 다른 계정으로 1:1 채팅과 반응형 화면을 확인할 수 있습니다. 파일마켓의 호스트 포트를 8000번처럼 변경했다면 ngrok 명령도 `ngrok http 8000`으로 맞춰야 합니다. 의도하지 않은 외부 노출을 막기 위해 ngrok은 자동으로 실행하지 않으며 시연을 마치면 `Ctrl+C`로 종료합니다. 임시 주소는 필요한 사람에게만 공유하고 실제 개인정보나 비밀번호를 입력하지 않습니다.



## 환경변수

| 변수 | 기본값 | 설명 |
|---|---:|---|
| `SECRET_KEY` | 자동 생성 | 32자 이상 비밀키. 미설정 시 `instance/.secret_key`에 권한 `600`으로 생성 |
| `DATABASE_URL` | `instance/market.db` | SQLAlchemy DB 주소 |
| `FLASK_ENV` | `development` | 개발 시 디버그·리로더·템플릿 자동 갱신과 정적 파일 캐시 해제, 운영 시 모두 비활성화하고 보안 쿠키 기본 활성화 |
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

- pytest: 68개 통과
- 코드 커버리지: 79%
- uv 잠금 파일: 최신 상태
- Ruff: 통과
- Bandit: 발견 사항 없음
- pip-audit: 발견된 취약 의존성을 수정 버전으로 올린 뒤 알려진 취약점 없음



## 보안 설계 요약

- 비밀번호는 Argon2id로 해시하고 로그인 5회 실패 시 5분 동안 잠급니다.
- 로그인 아이디와 공개 닉네임을 분리하고, 일반 사용자 화면에는 닉네임만 표시합니다.
- 모든 상태 변경 폼과 Socket.IO 메시지에 CSRF 검증을 적용합니다.
- 송금 및 구매 금액은 서버 DB 값을 기준으로 계산하고 중복 요청 키와 DB 트랜잭션으로 이중 처리를 방지합니다.
- 이미지의 실제 형식, 크기 및 해상도를 검사하고 UUID 파일명으로 다시 인코딩합니다.
- 상품, 채팅 및 관리자 기능은 로그인뿐 아니라 소유권, 대화 참여자 및 역할을 확인합니다.
- 신고, 거래 및 관리자 조치는 감사 로그 또는 별도 거래 내역으로 기록합니다.
- 댓글과 채팅 메시지의 관리자 조치는 원문을 보존하고 사용자 화면의 공개 상태만 변경합니다.



## 알려진 제한 사항

- 실제 금융 결제와 계좌 정산을 제공하지 않습니다.
- SQLite와 단일 Gunicorn 프로세스를 기준으로 설계했습니다. 다중 서버 운영 시 PostgreSQL, Redis 기반 요청 제한 및 Socket.IO 메시지 큐가 필요합니다.
- Socket.IO 브라우저 클라이언트는 CSP로 허용한 고정 버전 CDN을 사용하므로 완전한 오프라인 채팅에는 로컬 정적 파일로의 교체가 필요합니다.
- 공개 GitHub URL, 제출자 정보, 외부 모바일 및 ngrok 증거는 제출 전에 본인 환경에서 채워야 합니다.
