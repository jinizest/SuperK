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


def _normalize_time_to_hhmm(value: str | None, default: str = "0700") -> str:
    """시간 문자열을 HHMM 포맷으로 정규화한다."""
    candidate = (value or default).strip()
    if len(candidate) == 6 and candidate.isdigit():
        candidate = candidate[:4]

    if len(candidate) != 4 or not candidate.isdigit():
        return default

    hh = int(candidate[:2])
    mm = int(candidate[2:])
    if not (0 <= hh <= 23 and 0 <= mm <= 59):
        return default

    return f"{hh:02d}{mm:02d}"


def _normalize_date_yyyymmdd(value: str | None) -> str:
    candidate = (value or datetime.now().strftime("%Y%m%d")).strip()
    return candidate if len(candidate) == 8 and candidate.isdigit() else datetime.now().strftime("%Y%m%d")


def _to_non_negative_int(value: object, default: int = 0) -> int:
    try:
        return max(int(value), 0)
    except (TypeError, ValueError):
        return default


def _format_ktx_status(train: object) -> str:
    special = "특실 가능" if train.has_special_seat() else "특실 매진"
    general = "일반실 가능" if train.has_general_seat() else "일반실 매진"
    wait = ""
    if getattr(train, "wait_reserve_flag", -1) >= 0:
        wait = ", 대기 가능" if train.has_waiting_list() else ", 대기 매진"
    return f"{general} / {special}{wait}"


def _format_srt_status(train: object) -> str:
    general = "일반실 가능" if train.general_seat_available() else "일반실 매진"
    special = "특실 가능" if train.special_seat_available() else "특실 매진"
    wait = ", 대기 가능" if train.reserve_standby_available() else ""
    return f"{general} / {special}{wait}"


def search_real_trains(payload: dict) -> list[dict]:
    """실제 KTX/SRT API를 호출해 열차 목록을 조회한다."""
    rail_type = str(payload.get("rail_type", "ktx")).lower()
    departure = (payload.get("departure") or "").strip()
    arrival = (payload.get("arrival") or "").strip()
    date = _normalize_date_yyyymmdd(payload.get("departure_date"))
    time_hhmm = _normalize_time_to_hhmm(payload.get("departure_time"))
    time_hhmmss = f"{time_hhmm}00"

    user_id = ((payload.get("login") or {}).get("user_id") if isinstance(payload.get("login"), dict) else payload.get("user_id") or "")
    user_pw = ((payload.get("login") or {}).get("user_pw") if isinstance(payload.get("login"), dict) else payload.get("user_pw") or "")

    if not user_id or not user_pw:
        raise ValueError("실제 조회를 위해 로그인 정보(아이디/비밀번호)를 입력해주세요.")
    if not departure or not arrival:
        raise ValueError("출발역/도착역을 입력해주세요.")

    adult = _to_non_negative_int(payload.get("adult"), default=1)
    child = _to_non_negative_int(payload.get("child"), default=0)
    senior = _to_non_negative_int(payload.get("path_index"), default=0)

    if rail_type == "srt":
        from src.infrastructure.external.srt import SRT, Adult, Child, Senior

        client = SRT(auto_login=False)
        client.login(user_id, user_pw)
        passengers = []
        if adult > 0:
            passengers.append(Adult(adult))
        if child > 0:
            passengers.append(Child(child))
        if senior > 0:
            passengers.append(Senior(senior))
        if not passengers:
            passengers = [Adult(1)]

        trains = client.search_train(
            dep=departure,
            arr=arrival,
            date=date,
            time=time_hhmmss,
            passengers=passengers,
            available_only=False,
        )

        return [
            {
                "train_no": train.train_number,
                "route": f"{train.dep_station_name} → {train.arr_station_name}",
                "date": train.dep_date,
                "depart_at": f"{train.dep_time[:2]}:{train.dep_time[2:4]}",
                "arrive_at": f"{train.arr_time[:2]}:{train.arr_time[2:4]}",
                "status": _format_srt_status(train),
            }
            for train in trains
        ]

    from src.infrastructure.external.ktx import (
        Korail,
        AdultPassenger,
        ChildPassenger,
        SeniorPassenger,
        TrainType as KorailTrainType,
    )

    client = Korail(auto_login=False)
    client.login(user_id, user_pw)
    passengers = []
    if adult > 0:
        passengers.append(AdultPassenger(adult))
    if child > 0:
        passengers.append(ChildPassenger(child))
    if senior > 0:
        passengers.append(SeniorPassenger(senior))
    if not passengers:
        passengers = [AdultPassenger(1)]

    trains = client.search_train(
        dep=departure,
        arr=arrival,
        date=date,
        time=time_hhmmss,
        train_type=KorailTrainType.KTX,
        passengers=passengers,
        include_no_seats=True,
        include_waiting_list=True,
    )

    return [
        {
            "train_no": train.train_no,
            "route": f"{train.dep_name} → {train.arr_name}",
            "date": train.dep_date,
            "depart_at": f"{train.dep_time[:2]}:{train.dep_time[2:4]}",
            "arrive_at": f"{train.arr_time[:2]}:{train.arr_time[2:4]}",
            "status": _format_ktx_status(train),
        }
        for train in trains
    ]


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
        "departure": search.get("departure", options.get("departure", "서대구")),
        "arrival": search.get("arrival", options.get("arrival", "행신")),
        "departure_date": search.get(
            "departure_date", options.get("departure_date", datetime.now().strftime("%Y%m%d"))
        ),
        "departure_time": search.get("departure_time", options.get("departure_time", "0700")),
        "seat_preference": search.get(
            "seat_preference", options.get("seat_preference", "general_first")
        ),
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


def build_waiting_form_values() -> dict:
    """초기 렌더링 시 add-on 저장값을 노출하지 않는 입력 대기 기본값."""
    return {
        "rail_type": "ktx",
        "user_id": "",
        "user_pw": "",
        "save_login": False,
        "telegram_token": "",
        "telegram_chat_id": "",
        "save_telegram": False,
        "departure": "",
        "arrival": "",
        "departure_date": "",
        "departure_time": "",
        "seat_preference": "general_first",
        "adult": 1,
        "child": 0,
        "path_index": 0,
        "card_number": "",
        "card_password_2": "",
        "is_corporate_card": False,
        "birth_date": "",
        "card_expire": "",
        "save_payment": False,
    }


@app.route("/")
def index():
    options = load_options()
    return render_template(
        "index.html",
        status=worker.status(),
        options=options,
        form_values=build_waiting_form_values(),
        preset_values=build_form_values(options),
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
    try:
        trains = search_real_trains(payload)
    except Exception as exc:
        logging.exception("Train search failed")
        return jsonify({"trains": [], "error": str(exc)}), 400
    logging.info(
        "Train search requested: type=%s, %s->%s, date=%s, time=%s, seat=%s",
        payload.get("rail_type", "ktx"),
        payload.get("departure", "서대구"),
        payload.get("arrival", "행신"),
        payload.get("departure_date", ""),
        payload.get("departure_time", ""),
        payload.get("seat_preference", "general_first"),
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
    port = int(options.get("port") or os.getenv("SUPERK_PORT", "5555"))

    logging.info("Starting Flask web UI on %s:%s", host, port)
    app.run(host=host, port=port)
