# SuperK Home Assistant Add-on

이 폴더는 SuperK를 Home Assistant add-on으로 실행하기 위한 기본 스캐폴딩입니다.

## 포함 파일
- `config.yaml`: add-on 메타데이터/옵션 정의
- `Dockerfile`: 컨테이너 빌드 설정
- `run.sh`: add-on 시작 스크립트
- `requirements.txt`: Flask 및 런타임 의존성
- `src/web_app.py`: Flask 웹 UI + 내부 워커 서버 + 로그 API
- `addon.json`: 외부 툴 연동용 참고 JSON

## 동작
- 웹 UI: `http://<HA_HOST>:<설정한 외부 포트>` (기본 내부 포트 `5555`)
- 로그 파일: `/data/superk.log`
- 옵션 파일: `/data/options.json`

## 참고
현재 워커는 안정적인 add-on 기동을 위한 기본 루프(heartbeat 로그)로 구성되어 있습니다.
실제 예약 로직 연결 시 `src/web_app.py`의 `InternalServer` 클래스에 기존 SuperK 서비스 호출을 추가하면 됩니다.


## 포트 충돌 해결
- Add-on은 기본적으로 `5555/tcp`를 **고정 호스트 포트에 매핑하지 않습니다**.
- Add-on 옵션의 `port` 값을 변경하면 Flask가 해당 내부 포트로 실행됩니다.
- Home Assistant Add-on 설정의 **Network**에서 `5555/tcp`에 원하는 외부 포트를 지정하세요(예: `5001`).
- 이미 다른 서비스가 `5555`를 사용 중이면 동일 포트로는 시작할 수 없습니다.


## 옵션 연동
- 웹 UI 입력값은 Home Assistant Add-on의 `/data/options.json` 값을 기본값으로 불러옵니다.
- 즉, Add-on 구성(설정)에서 `login`, `telegram`, `search`, `payment` 항목에 값을 넣어두면 UI가 자동으로 채웁니다.
- 민감 정보(`password` 타입)는 Home Assistant에서 시크릿 형태로 관리할 수 있습니다.

## 접속 이슈(about:blank#blocked)
- 기본 포트는 `5555`입니다.
- Add-on Web UI 버튼은 `config.yaml`의 `webui`/`ports` 정의를 기준으로 열립니다(현재 `5555`).
- `port` 옵션을 기본값과 다르게 변경하면 Web UI 버튼 주소와 실제 Flask 포트가 달라져 빈 화면/차단 화면이 보일 수 있습니다.
- 포트를 바꿀 경우에는 수동으로 `http://<HA_IP>:<매핑한 외부포트>`로 접속하거나, add-on의 `webui`/`ports` 정의도 함께 맞춰주세요.
