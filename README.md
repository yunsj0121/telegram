# Noche Telegram Relay

`@aetherjapanresearch`의 새 게시물을 `@noche_economic` 방송 채널로 자동 복사하는 사용자 계정 기반 릴레이입니다.

원본 채널에는 봇을 추가할 필요가 없습니다. 사용자 계정이 원본 채널에 가입해 새 게시물을 수신하고, 원본 작성자 표시를 제거해 대상 채널에 게시합니다.

## 지원 기능

- 텍스트, 사진, 동영상, 파일 전달
- 여러 이미지·동영상 앨범 형태 유지
- 원본 채널 작성자 표시 제거
- SQLite 기반 중복 게시 방지
- 텍스트·캡션 수정 동기화
- 텔레그램 전송 제한 자동 대기

텔레그램 Bot API는 채널에서 삭제된 일반 게시물 이벤트를 제공하지 않으므로 원본 삭제는 자동 동기화하지 않습니다. 미디어 파일 자체를 교체하는 편집도 자동 반영 대상이 아닙니다.

## 보안 주의사항

`API_HASH`와 `TELEGRAM_SESSION`은 비밀번호와 같습니다. 채팅, GitHub, README, `.env.example`에 실제 값을 올리지 마세요. 가능하면 개인 대화가 없는 자동화 전용 텔레그램 계정을 사용하세요.

## 1. 준비

1. 자동화에 사용할 텔레그램 계정으로 `@aetherjapanresearch`에 가입합니다.
2. 같은 계정이 `@noche_economic` 채널에 게시할 수 있어야 합니다. 채널 소유자가 아니라면 관리자로 추가합니다.
3. [my.telegram.org](https://my.telegram.org)의 `API development tools`에서 `API_ID`와 `API_HASH`를 발급합니다.
4. Python 3.11 이상을 설치합니다.

## 2. 설치

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

## 3. 사용자 세션 생성

터미널에서 비밀값을 환경변수로 입력합니다.

```bash
export API_ID='발급받은 숫자'
export API_HASH='발급받은 해시'
PYTHONPATH=src python -m noche_relay.session_tool
```

전화번호, 텔레그램으로 받은 인증번호, 2단계 인증 비밀번호를 차례대로 입력하면 `TELEGRAM_SESSION` 문자열이 출력됩니다. 이 값은 외부에 공개하지 말고 배포 서버의 비밀변수로만 저장합니다.

## 4. 실행

`.env.example`을 참고해 실제 비밀변수를 설정한 후 실행합니다.

```bash
PYTHONPATH=src python -m noche_relay
```

정상 연결되면 로그에 다음과 비슷하게 표시됩니다.

```text
Relay ready: account=... source=aetherjapanresearch target=noche_economic
```

이후 원본 채널에 새 테스트 게시물을 올려 대상 채널로 복사되는지 확인합니다. 프로그램을 처음 실행하기 전의 과거 게시물은 자동으로 복사하지 않습니다.

## 5. Docker 실행

`.env` 파일을 만든 후 다음 명령을 실행합니다.

```bash
docker compose up -d --build
docker compose logs -f relay
```

Docker 볼륨에 메시지 대응표를 보관하므로 컨테이너를 다시 시작해도 중복 게시와 수정 동기화 상태가 유지됩니다.

## 테스트

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
```
