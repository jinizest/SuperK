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
- 웹 UI: `http://<HA_HOST>:5000`
- 로그 파일: `/data/superk.log`
- 옵션 파일: `/data/options.json`

## 참고
현재 워커는 안정적인 add-on 기동을 위한 기본 루프(heartbeat 로그)로 구성되어 있습니다.
실제 예약 로직 연결 시 `src/web_app.py`의 `InternalServer` 클래스에 기존 SuperK 서비스 호출을 추가하면 됩니다.
