import json
import logging
import os
import threading
import time
from datetime import datetime

from flask import Flask, jsonify, redirect, render_template, request, url_for


DATA_DIR = "/data"
LOG_FILE_PATH = os.path.join(DATA_DIR, "superk.log")
OPTIONS_FILE_PATH = os.path.join(DATA_DIR, "options.json")

app = Flask(__name__)


class InternalServer:
    """간단한 내부 워커 서버.

    Home Assistant add-on 환경에서는 이 워커가 지속 실행되며 로그를 남긴다.
    필요 시 기존 SuperK 예약 로직으로 교체할 수 있도록 분리했다.
    """

    def __init__(self) -> None:
        self._running = threading.Event()
        self._thread: threading.Thread | None = None
        self._status = "idle"
        self._last_message = "대기 중"
        self._active_payload: dict = {}

    def start(self, payload: dict | None = None) -> None:
        if self._thread and self._thread.is_alive():
            return

        self._active_payload = payload or {}
        self._running.set()
        self._status = "running"
        self._last_message = "서버 시작"
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        logging.info("Internal server started")

    def stop(self) -> None:
        self._running.clear()
        self._status = "stopped"
        self._last_message = "서버 중지"
        self._active_payload = {}
        logging.info("Internal server stopping")

    def _run_loop(self) -> None:
        while self._running.is_set():
            self._last_message = f"동작 중: {datetime.now().isoformat(timespec='seconds')}"
            logging.info("Internal server heartbeat")
            time.sleep(5)

    def status(self) -> dict:
        return {
            "status": self._status,
            "last_message": self._last_message,
            "thread_alive": bool(self._thread and self._thread.is_alive()),
            "active_payload": self._active_payload,
        }


def build_mock_trains(payload: dict) -> list[dict]:
    """검색 조건을 바탕으로 UI 표시용 모의 열차 데이터를 생성한다."""
    departure = payload.get("departure") or "서울"
    arrival = payload.get("arrival") or "부산"
    start_time = payload.get("departure_time") or "0700"
    date = payload.get("departure_date") or datetime.now().strftime("%Y%m%d")

    base = [
        ("015", start_time, "+02:48", "예약 가능"),
        ("021", "0815", "+03:04", "매진 임박"),
        ("033", "0930", "+03:11", "예약 가능"),
    ]
    trains: list[dict] = []
    for train_no, dep, duration, status in base:
        h = int(dep[:2])
        m = int(dep[2:])
        extra_h, extra_m = map(int, duration.replace("+", "").split(":"))
        arr_h = (h + extra_h + ((m + extra_m) // 60)) % 24
        arr_m = (m + extra_m) % 60
        trains.append(
            {
                "train_no": train_no,
                "route": f"{departure} → {arrival}",
                "date": date,
                "depart_at": f"{h:02d}:{m:02d}",
                "arrive_at": f"{arr_h:02d}:{arr_m:02d}",
                "status": status,
            }
        )
    return trains


worker = InternalServer()


def configure_logging() -> None:
    os.makedirs(DATA_DIR, exist_ok=True)

    level_name = os.getenv("SUPERK_LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)

    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")

    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    root.addHandler(stream_handler)

    file_handler = logging.FileHandler(LOG_FILE_PATH)
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    logging.info("Logging initialized")


def load_options() -> dict:
    if os.path.exists(OPTIONS_FILE_PATH):
        try:
            with open(OPTIONS_FILE_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as exc:
            logging.warning("Failed to read options.json: %s", exc)
    return {}


def _to_bool(value: object, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def build_form_values(options: dict) -> dict:
    """Home Assistant add-on 옵션을 UI 초기값으로 변환한다."""
    login = options.get("login", {}) if isinstance(options.get("login"), dict) else {}
    telegram = (
        options.get("telegram", {}) if isinstance(options.get("telegram"), dict) else {}
    )
    search = options.get("search", {}) if isinstance(options.get("search"), dict) else {}
    payment = options.get("payment", {}) if isinstance(options.get("payment"), dict) else {}

    return {
        "rail_type": options.get("rail_type", "ktx"),
        "user_id": login.get("user_id", options.get("user_id", "")),
        "user_pw": login.get("user_pw", options.get("user_pw", "")),
        "save_login": _to_bool(login.get("save_login", options.get("save_login", False))),
        "telegram_token": telegram.get("telegram_token", options.get("telegram_token", "")),
        "telegram_chat_id": telegram.get(
            "telegram_chat_id", options.get("telegram_chat_id", "")
        ),
        "save_telegram": _to_bool(
            telegram.get("save_telegram", options.get("save_telegram", False))
        ),
        "departure": search.get("departure", options.get("departure", "서울")),
        "arrival": search.get("arrival", options.get("arrival", "부산")),
        "departure_date": search.get(
            "departure_date", options.get("departure_date", datetime.now().strftime("%Y%m%d"))
        ),
        "departure_time": search.get("departure_time", options.get("departure_time", "0700")),
        "adult": search.get("adult", options.get("adult", 1)),
        "child": search.get("child", options.get("child", 0)),
        "path_index": search.get("path_index", options.get("path_index", 0)),
        "card_number": payment.get("card_number", options.get("card_number", "")),
        "card_password_2": payment.get(
            "card_password_2", options.get("card_password_2", "")
        ),
        "is_corporate_card": _to_bool(
            payment.get("is_corporate_card", options.get("is_corporate_card", False))
        ),
        "birth_date": payment.get("birth_date", options.get("birth_date", "")),
        "card_expire": payment.get("card_expire", options.get("card_expire", "")),
        "save_payment": _to_bool(
            payment.get("save_payment", options.get("save_payment", False))
        ),
    }


@app.route("/")
def index():
    options = load_options()
    return render_template(
        "index.html",
        status=worker.status(),
        options=options,
        form_values=build_form_values(options),
        log_file=LOG_FILE_PATH,
    )


@app.post("/start")
def start_server():
    worker.start({"source": "legacy_form"})
    return redirect(url_for("index"))


@app.post("/stop")
def stop_server():
    worker.stop()
    return redirect(url_for("index"))


@app.post("/api/search")
def api_search_trains():
    payload = request.get_json(silent=True) or {}
    trains = build_mock_trains(payload)
    logging.info(
        "Train search requested: type=%s, %s->%s, date=%s, time=%s",
        payload.get("rail_type", "ktx"),
        payload.get("departure", "서울"),
        payload.get("arrival", "부산"),
        payload.get("departure_date", ""),
        payload.get("departure_time", ""),
    )
    return jsonify({"trains": trains})


@app.post("/api/run/start")
def api_run_start():
    payload = request.get_json(silent=True) or {}
    worker.start(payload)
    logging.info("Reservation start requested")
    return jsonify({"ok": True, "status": worker.status()})


@app.post("/api/run/stop")
def api_run_stop():
    worker.stop()
    logging.info("Reservation stop requested")
    return jsonify({"ok": True, "status": worker.status()})


@app.get("/api/status")
def api_status():
    return jsonify(worker.status())


@app.get("/api/logs")
def api_logs():
    tail = int(request.args.get("tail", "100"))
    if not os.path.exists(LOG_FILE_PATH):
        return jsonify({"logs": []})

    with open(LOG_FILE_PATH, "r", encoding="utf-8") as f:
        lines = f.readlines()

    return jsonify({"logs": lines[-tail:]})


if __name__ == "__main__":
    configure_logging()
    options = load_options()

    host = options.get("host") or os.getenv("SUPERK_HOST", "0.0.0.0")
    port = int(options.get("port") or os.getenv("SUPERK_PORT", "5000"))

    logging.info("Starting Flask web UI on %s:%s", host, port)
    app.run(host=host, port=port)
