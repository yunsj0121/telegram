# Noche Telegram Relay

`@aetherjapanresearch`의 새 게시물을 `@noche_economic` 방송 채널로 자동 복사하는 사용자 계정 기반 릴레이입니다.

원본 채널에는 봇을 추가할 필요가 없습니다. 사용자 계정이 원본 채널에 가입해 게시물을 읽고, 원본 작성자 표시를 제거한 복사본을 대상 채널에 게시합니다.

## 지원 기능

- 텍스트, 사진, 동영상, 파일 복사
- 여러 이미지·동영상의 앨범 형태 유지
- 원본 채널 작성자 표시 제거
- Supabase 또는 SQLite 기반 중복 게시 방지
- 최근 게시물의 텍스트·캡션 수정 동기화
- 실행이 한 번 누락돼도 다음 실행에서 놓친 게시물 처리
- 텔레그램 전송 제한 자동 대기

원본에서 삭제된 게시물과 미디어 파일 자체를 교체한 편집은 자동으로 동기화하지 않습니다.

## 실행 방식

### 예약 실행 방식: 권장

cron-job.org가 5분마다 GitHub Actions를 호출합니다. 작업은 마지막 처리 이후의 게시물을 확인하고 복사한 뒤 종료합니다. 처리 위치는 Supabase에 저장되므로 일시적으로 실행이 누락돼도 다음 실행에서 이어집니다.

GitHub 자체 예약 실행도 매시간 17분에 비상 백업으로 실행됩니다.

### 상시 연결 방식

Docker 또는 VM에서 프로세스를 계속 실행하면 새 게시물을 거의 실시간으로 복사합니다. 이 방식은 SQLite와 Docker 볼륨을 사용합니다.

## 보안 주의사항

`API_HASH`, `TELEGRAM_SESSION`, `SUPABASE_SECRET_KEY`, GitHub 토큰은 비밀번호와 같습니다. 채팅, 코드, README, 이슈 또는 공개 로그에 입력하지 마세요. 모든 실제 값은 GitHub Actions Secrets 또는 서버의 비밀 환경변수로만 저장합니다.

## 1. 텔레그램 준비

1. 자동화에 사용할 계정으로 `@aetherjapanresearch`에 가입합니다.
2. 같은 계정이 `@noche_economic` 채널에 게시할 수 있어야 합니다.
3. [my.telegram.org](https://my.telegram.org)의 `API development tools`에서 `API_ID`와 `API_HASH`를 발급합니다.
4. 아래 도구로 사용자 계정의 StringSession을 한 번 생성합니다.

```bash
export API_ID='발급받은 숫자'
export API_HASH='발급받은 해시'
PYTHONPATH=src python -m noche_relay.session_tool
```

출력된 `TELEGRAM_SESSION`은 외부에 공개하지 않습니다.

## 2. Supabase 테이블 만들기

Supabase 프로젝트의 `SQL Editor`에서 다음 파일의 내용을 실행합니다.

```text
supabase/migrations/20261001121500_telegram_relay_state.sql
```

생성되는 테이블은 다음 두 개입니다.

- `telegram_relay_cursors`: 마지막으로 처리한 원본 메시지 번호
- `telegram_relay_message_map`: 원본과 대상 메시지 대응표 및 수정 시각

두 테이블은 RLS가 활성화되고 `anon`, `authenticated` 역할의 접근 권한이 제거됩니다. 서버용 Secret key만 접근합니다.

## 3. GitHub Actions Secrets 등록

저장소에서 `Settings → Secrets and variables → Actions → New repository secret`으로 이동해 다음 다섯 값을 등록합니다.

| Secret 이름 | 값 |
|---|---|
| `TELEGRAM_API_ID` | my.telegram.org에서 발급한 숫자 |
| `TELEGRAM_API_HASH` | my.telegram.org에서 발급한 해시 |
| `TELEGRAM_SESSION` | StringSession 생성 결과 |
| `SUPABASE_URL` | Supabase Project URL |
| `SUPABASE_SECRET_KEY` | Supabase `sb_secret_...` Secret key |

같은 화면의 `Variables` 탭에서 `RELAY_ENABLED`를 만들고 값으로 `true`를 등록합니다. 이 변수가 없으면 예약 작업은 안전하게 건너뛰므로 설정을 마치기 전 실패 로그가 쌓이지 않습니다.

첫 실행은 `Actions → Telegram relay → Run workflow`에서 수동으로 실행합니다. 첫 실행은 현재 최신 게시물 번호만 기준점으로 저장하며 과거 게시물을 복사하지 않습니다. 그다음 원본 채널에 테스트 게시물을 올리고 다시 실행해 복사 여부를 확인합니다.

## 4. cron-job.org를 5분 간격으로 연결

### GitHub 전용 토큰 만들기

GitHub에서 fine-grained personal access token을 새로 만듭니다.

- Repository access: `Only select repositories → telegram`
- Repository permissions: `Actions → Read and write`
- 만료일을 설정하고 만료 전에 교체

토큰은 cron-job.org의 요청 헤더에만 저장하고 코드나 GitHub Secrets에 중복 저장하지 않습니다.

### cron-job.org 작업 설정

- URL: `https://api.github.com/repos/yunsj0121/telegram/actions/workflows/telegram-relay.yml/dispatches`
- 요청 방식: `POST`
- 실행 주기: 매 5분
- 요청 본문:

```json
{"ref":"main"}
```

- 요청 헤더:

```text
Accept: application/vnd.github+json
Authorization: Bearer 발급한_FINE_GRAINED_TOKEN
X-GitHub-Api-Version: 2022-11-28
Content-Type: application/json
```

정상 요청은 GitHub API에서 HTTP `204 No Content`를 반환합니다. 실제 복사 결과는 GitHub 저장소의 `Actions → Telegram relay` 실행 기록에서 확인합니다.

GitHub Actions는 같은 작업이 겹치지 않도록 `concurrency`가 설정되어 있습니다. 외부 5분 호출과 매시간 백업 실행이 겹쳐도 한 번씩 순서대로 처리하며, Supabase 대응표로 중복 게시를 방지합니다.

## 5. Docker·VM에서 상시 실행

예약 실행 대신 거의 실시간 복사를 원하면 `.env.example`을 복사해 실제 값을 채웁니다.

```text
RUN_MODE=continuous
STATE_BACKEND=sqlite
```

그다음 실행합니다.

```bash
docker compose up -d --build
docker compose logs -f relay
```

Docker 볼륨에 상태를 보관하므로 컨테이너를 다시 시작해도 중복 게시와 수정 동기화 상태가 유지됩니다.

## 로컬 테스트

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
PYTHONPATH=src python -m unittest discover -s tests -v
```
