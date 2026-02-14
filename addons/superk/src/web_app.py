import json
import logging
import os
import random
import sys
import threading
import time
from datetime import datetime

import requests
from flask import Flask, jsonify, redirect, render_template, request, url_for


DATA_DIR = "/data"
LOG_FILE_PATH = os.path.join(DATA_DIR, "superk.log")
OPTIONS_FILE_PATH = os.path.join(DATA_DIR, "options.json")

RESERVATION_LOG_KEYWORDS = (
    "Train search",
    "Reservation",
    "예약",
    "🔄",
    "→",
    "⏳",
    "✓",
    "✗",
    "텔레그램",
)

RESERVATION_LOG_EXCLUDE_KEYWORDS = (
    "HTTP/1.1",
    "GET /api/logs",
)


def _is_reservation_log_line(line: str) -> bool:
    if any(keyword in line for keyword in RESERVATION_LOG_EXCLUDE_KEYWORDS):
        return False
    return any(keyword in line for keyword in RESERVATION_LOG_KEYWORDS)


app = Flask(__name__)
APP_SRC_DIR = os.path.dirname(os.path.abspath(__file__))
if APP_SRC_DIR not in sys.path:
    sys.path.insert(0, APP_SRC_DIR)


class InternalServer:
    """Home Assistant add-on 예약 워커."""

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
        payload = _extract_run_context(self._active_payload)
        selected_train_no = payload.get("selected_train_no")
        if not selected_train_no:
            logging.warning("선택된 열차 번호가 없어 예약을 시작할 수 없습니다")
            self._status = "stopped"
            self._last_message = "선택된 열차가 없습니다"
            self._running.clear()
            return

        self._send_telegram(payload, _build_start_message(payload))

        attempt = 0
        while self._running.is_set():
            attempt += 1
            self._last_message = f"예약 시도 #{attempt}"
            logging.info("🔄 예약 시도 #%s", attempt)
            try:
                self._try_reserve(payload)
                self._status = "completed"
                self._last_message = "예약 성공"
                self._running.clear()
                return
            except RuntimeError as exc:
                logging.info("  ✗ %s 예약 실패: %s", selected_train_no, exc)
                if "WRR800029" in str(exc):
                    self._send_telegram(payload, f"⚠️ 중복 예약 감지: {exc}")
                    self._status = "stopped"
                    self._last_message = "중복 예약으로 중지"
                    self._running.clear()
                    return
            except Exception as exc:
                logging.exception("예약 시도 중 오류")
                self._send_telegram(payload, f"⚠️ 예약 오류 발생: {exc}")

            delay = random.uniform(1.5, 3.8)
            logging.info("⏳ %.1f초 후 재시도...", delay)
            time.sleep(delay)

    def _try_reserve(self, payload: dict) -> None:
        rail_type = payload.get("rail_type", "ktx")
        if rail_type == "srt":
            self._try_reserve_srt(payload)
            return
        self._try_reserve_ktx(payload)

    def _try_reserve_ktx(self, payload: dict) -> None:
        from infrastructure.external.ktx import Korail, ReserveOption, TrainType as KorailTrainType

        client = Korail(auto_login=False)
        client.login(payload["user_id"], payload["user_pw"])
        trains = client.search_train(
            dep=payload["departure"],
            arr=payload["arrival"],
            date=payload["departure_date"],
            time=f"{payload['departure_time']}00",
            train_type=KorailTrainType.KTX,
            passengers=_build_ktx_passengers(payload),
            include_no_seats=True,
            include_waiting_list=True,
        )
        target = next((t for t in trains if t.train_no == payload["selected_train_no"]), None)
        if not target:
            raise RuntimeError("선택한 열차를 찾을 수 없습니다")

        logging.info("  → %s 예약 시도 중...", target.train_no)
        if not (target.has_special_seat() or target.has_general_seat() or target.has_waiting_list()):
            raise RuntimeError("No available seats")

        option = _to_ktx_reserve_option(payload.get("seat_preference", "general_first"), ReserveOption)
        reservation = client.reserve(target, passengers=_build_ktx_passengers(payload), option=option)
        seat_info = _seat_preference_label(payload.get("seat_preference", "general_first"))

        try:
            ticket_info = client.ticket_info(reservation.rsv_id)
            if ticket_info and isinstance(ticket_info, tuple) and ticket_info[0]:
                seat_info = ", ".join(str(seat) for seat in ticket_info[0])
        except Exception:
            logging.exception("좌석 정보 조회 실패")

        logging.info("  ✓ %s 예약 성공! 예약번호: %s", target.train_no, reservation.rsv_id)
        self._send_telegram(payload, _build_success_message(payload, target.train_no, reservation.rsv_id, seat_info))

        if _has_payment_info(payload):
            card_type = "S" if payload.get("is_corporate_card") else "J"
            try:
                paid = client.pay_with_card(
                    reservation,
                    payload["card_number"],
                    payload["card_password_2"],
                    payload["birth_date"],
                    payload["card_expire"],
                    card_type=card_type,
                )
                if paid:
                    self._send_telegram(
                        payload,
                        _build_payment_complete_message(
                            payload,
                            target.train_no,
                            reservation.rsv_id,
                            reservation.rsv_id,
                            seat_info,
                        ),
                    )
                else:
                    self._send_telegram(
                        payload,
                        _build_payment_required_message(payload, target.train_no, reservation.rsv_id, seat_info),
                    )
            except Exception as exc:
                logging.warning("자동 결제 실패(KTX): %s", exc)
                self._send_telegram(
                    payload,
                    _build_payment_required_message(payload, target.train_no, reservation.rsv_id, seat_info),
                )
        else:
            self._send_telegram(payload, _build_payment_required_message(payload, target.train_no, reservation.rsv_id, seat_info))

    def _try_reserve_srt(self, payload: dict) -> None:
        from infrastructure.external.srt import SRT, SeatType

        client = SRT(auto_login=False)
        client.login(payload["user_id"], payload["user_pw"])
        trains = client.search_train(
            dep=payload["departure"],
            arr=payload["arrival"],
            date=payload["departure_date"],
            time=f"{payload['departure_time']}00",
            passengers=_build_srt_passengers(payload),
            available_only=False,
        )
        target = next((t for t in trains if t.train_number == payload["selected_train_no"]), None)
        if not target:
            raise RuntimeError("선택한 열차를 찾을 수 없습니다")

        logging.info("  → %s 예약 시도 중...", target.train_number)
        if not (target.general_seat_available() or target.special_seat_available() or target.reserve_standby_available()):
            raise RuntimeError("No available seats")

        option = _to_srt_reserve_option(payload.get("seat_preference", "general_first"), SeatType)
        reservation = client.reserve(target, passengers=_build_srt_passengers(payload), option=option)
        seat_info = _seat_preference_label(payload.get("seat_preference", "general_first"))
        if getattr(reservation, "tickets", None):
            seat_info = ", ".join(str(ticket) for ticket in reservation.tickets)

        logging.info("  ✓ %s 예약 성공! 예약번호: %s", target.train_number, reservation.reservation_number)
        self._send_telegram(payload, _build_success_message(payload, target.train_number, reservation.reservation_number, seat_info))

        if _has_payment_info(payload):
            card_type = "S" if payload.get("is_corporate_card") else "J"
            try:
                paid = client.pay_with_card(
                    reservation,
                    payload["card_number"],
                    payload["card_password_2"],
                    payload["birth_date"],
                    payload["card_expire"],
                    card_type=card_type,
                )
                if paid:
                    self._send_telegram(
                        payload,
                        _build_payment_complete_message(
                            payload,
                            target.train_number,
                            reservation.reservation_number,
                            reservation.reservation_number,
                            seat_info,
                        ),
                    )
                else:
                    self._send_telegram(
                        payload,
                        _build_payment_required_message(payload, target.train_number, reservation.reservation_number, seat_info),
                    )
            except Exception as exc:
                logging.warning("자동 결제 실패(SRT): %s", exc)
                self._send_telegram(
                    payload,
                    _build_payment_required_message(payload, target.train_number, reservation.reservation_number, seat_info),
                )
        else:
            self._send_telegram(
                payload,
                _build_payment_required_message(payload, target.train_number, reservation.reservation_number, seat_info),
            )

    def _send_telegram(self, payload: dict, message: str) -> None:
        token = payload.get("telegram_token", "").strip()
        chat_id = payload.get("telegram_chat_id", "").strip()
        if not token or not chat_id:
            return

        try:
            response = requests.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat_id, "text": message},
                timeout=5,
            )
            if response.ok:
                logging.info("📨 텔레그램 알림 전송 완료")
            else:
                logging.warning("⚠️ 텔레그램 알림 전송 실패: %s", response.status_code)
        except Exception as exc:
            logging.warning("⚠️ 텔레그램 알림 오류: %s", exc)

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


def _extract_run_context(payload: dict) -> dict:
    login = payload.get("login", {}) if isinstance(payload.get("login"), dict) else {}
    telegram = payload.get("telegram", {}) if isinstance(payload.get("telegram"), dict) else {}
    search = payload.get("search", {}) if isinstance(payload.get("search"), dict) else {}
    payment = payload.get("payment", {}) if isinstance(payload.get("payment"), dict) else {}

    return {
        "rail_type": str(payload.get("rail_type", "ktx")).lower(),
        "user_id": (login.get("user_id") or payload.get("user_id") or "").strip(),
        "user_pw": (login.get("user_pw") or payload.get("user_pw") or "").strip(),
        "telegram_token": (telegram.get("telegram_token") or payload.get("telegram_token") or "").strip(),
        "telegram_chat_id": (telegram.get("telegram_chat_id") or payload.get("telegram_chat_id") or "").strip(),
        "departure": (search.get("departure") or payload.get("departure") or "").strip(),
        "arrival": (search.get("arrival") or payload.get("arrival") or "").strip(),
        "departure_date": _normalize_date_yyyymmdd(search.get("departure_date") or payload.get("departure_date")),
        "departure_time": _normalize_time_to_hhmm(search.get("departure_time") or payload.get("departure_time")),
        "seat_preference": (search.get("seat_preference") or payload.get("seat_preference") or "general_first").strip(),
        "adult": _to_non_negative_int(search.get("adult", payload.get("adult", 1)), default=1),
        "child": _to_non_negative_int(search.get("child", payload.get("child", 0)), default=0),
        "path_index": _to_non_negative_int(search.get("path_index", payload.get("path_index", 0)), default=0),
        "selected_train_no": str(search.get("selected_train_no") or payload.get("selected_train_no") or "").strip(),
        "card_number": (payment.get("card_number") or payload.get("card_number") or "").strip(),
        "card_password_2": (payment.get("card_password_2") or payload.get("card_password_2") or "").strip(),
        "is_corporate_card": _to_bool(payment.get("is_corporate_card", payload.get("is_corporate_card", False))),
        "birth_date": (payment.get("birth_date") or payload.get("birth_date") or "").strip(),
        "card_expire": (payment.get("card_expire") or payload.get("card_expire") or "").strip(),
    }


def _build_ktx_passengers(payload: dict) -> list[object]:
    from infrastructure.external.ktx import AdultPassenger, ChildPassenger, SeniorPassenger

    passengers = []
    if payload.get("adult", 0) > 0:
        passengers.append(AdultPassenger(payload["adult"]))
    if payload.get("child", 0) > 0:
        passengers.append(ChildPassenger(payload["child"]))
    if payload.get("path_index", 0) > 0:
        passengers.append(SeniorPassenger(payload["path_index"]))
    return passengers or [AdultPassenger(1)]


def _build_srt_passengers(payload: dict) -> list[object]:
    from infrastructure.external.srt import Adult, Child, Senior

    passengers = []
    if payload.get("adult", 0) > 0:
        passengers.append(Adult(payload["adult"]))
    if payload.get("child", 0) > 0:
        passengers.append(Child(payload["child"]))
    if payload.get("path_index", 0) > 0:
        passengers.append(Senior(payload["path_index"]))
    return passengers or [Adult(1)]


def _to_ktx_reserve_option(seat_preference: str, reserve_option_class: object) -> object:
    mapping = {
        "general_first": reserve_option_class.GENERAL_FIRST,
        "general_only": reserve_option_class.GENERAL_ONLY,
        "special_first": reserve_option_class.SPECIAL_FIRST,
        "special_only": reserve_option_class.SPECIAL_ONLY,
    }
    return mapping.get(str(seat_preference).lower(), reserve_option_class.GENERAL_FIRST)


def _to_srt_reserve_option(seat_preference: str, seat_type_class: object) -> object:
    mapping = {
        "general_first": seat_type_class.GENERAL_FIRST,
        "general_only": seat_type_class.GENERAL_ONLY,
        "special_first": seat_type_class.SPECIAL_FIRST,
        "special_only": seat_type_class.SPECIAL_ONLY,
    }
    return mapping.get(str(seat_preference).lower(), seat_type_class.GENERAL_FIRST)


def _rail_type_label(payload: dict) -> str:
    return "SRT" if str(payload.get("rail_type", "ktx")).lower() == "srt" else "KTX"


def _seat_preference_label(seat_preference: str) -> str:
    mapping = {
        "general_first": "일반실 우선",
        "general_only": "일반실만",
        "special_first": "특실 우선",
        "special_only": "특실만",
    }
    return mapping.get(str(seat_preference).lower(), "일반실 우선")


def _format_passenger_summary(payload: dict) -> tuple[int, str]:
    adult = _to_non_negative_int(payload.get("adult"), default=1)
    child = _to_non_negative_int(payload.get("child"), default=0)
    senior = _to_non_negative_int(payload.get("path_index"), default=0)

    parts = []
    if adult:
        parts.append(f"어른 {adult}")
    if child:
        parts.append(f"어린이 {child}")
    if senior:
        parts.append(f"경로 {senior}")

    total = adult + child + senior
    if total <= 0:
        return 1, "어른 1"
    return total, ", ".join(parts)


def _format_date_iso(yyyymmdd: str) -> str:
    if len(yyyymmdd) != 8 or not yyyymmdd.isdigit():
        return yyyymmdd
    dt = datetime.strptime(yyyymmdd, "%Y%m%d")
    return dt.strftime("%Y-%m-%d")


def _format_date_with_day(yyyymmdd: str) -> str:
    iso = _format_date_iso(yyyymmdd)
    if len(yyyymmdd) != 8 or not yyyymmdd.isdigit():
        return iso
    dt = datetime.strptime(yyyymmdd, "%Y%m%d")
    days = ["월", "화", "수", "목", "금", "토", "일"]
    return f"{iso}({days[dt.weekday()]})"


def _format_date_time(payload: dict) -> str:
    date = _format_date_with_day(payload.get("departure_date", ""))
    time_hhmm = _normalize_time_to_hhmm(payload.get("departure_time"), default="0700")
    return f"{date} {time_hhmm[:2]}:{time_hhmm[2:]}"


def _build_start_message(payload: dict) -> str:
    rail_type = _rail_type_label(payload)
    total, breakdown = _format_passenger_summary(payload)
    seat_info = _seat_preference_label(payload.get("seat_preference", "general_first"))
    return (
        f"🚀 {rail_type} 예약 시작\n"
        f"좌석 옵션: {seat_info}\n"
        f"예약 인원: 총 {total}명 ({breakdown})\n"
        "선택 열차 정보:\n"
        f"- {payload.get('selected_train_no')} | {_format_date_time(payload)} | {payload.get('departure')}→{payload.get('arrival')}\n"
        "예약 매크로 실행이 시작되었습니다."
    )


def _build_success_message(payload: dict, train_no: str, reservation_no: str, seat_info: str) -> str:
    rail_type = _rail_type_label(payload)
    time_hhmm = _normalize_time_to_hhmm(payload.get("departure_time"), default="0700")
    return (
        f"✅ {rail_type} 예약 성공\n"
        f"열차: {train_no}\n"
        f"구간: {payload.get('departure')} → {payload.get('arrival')}\n"
        f"출발: {_format_date_iso(payload.get('departure_date', ''))} {time_hhmm[:2]}:{time_hhmm[2:]}\n"
        f"좌석 정보: {seat_info}\n"
        f"예약번호: {reservation_no}"
    )


def _build_payment_complete_message(payload: dict, train_no: str, reservation_no: str, payment_no: str, seat_info: str) -> str:
    rail_type = _rail_type_label(payload)
    time_hhmm = _normalize_time_to_hhmm(payload.get("departure_time"), default="0700")
    return (
        f"💳 {rail_type} 결제 완료\n"
        f"열차: {train_no}\n"
        f"구간: {payload.get('departure')} → {payload.get('arrival')}\n"
        f"출발: {_format_date_iso(payload.get('departure_date', ''))} {time_hhmm[:2]}:{time_hhmm[2:]}\n"
        f"좌석 정보: {seat_info}\n"
        f"예약번호: {reservation_no}\n"
        f"결제예약번호: {payment_no}"
    )


def _build_payment_required_message(payload: dict, train_no: str, reservation_no: str, seat_info: str) -> str:
    rail_type = _rail_type_label(payload)
    time_hhmm = _normalize_time_to_hhmm(payload.get("departure_time"), default="0700")
    return (
        f"⚠️ {rail_type} 결제 필요\n"
        f"열차: {train_no}\n"
        f"구간: {payload.get('departure')} → {payload.get('arrival')}\n"
        f"출발: {_format_date_iso(payload.get('departure_date', ''))} {time_hhmm[:2]}:{time_hhmm[2:]}\n"
        f"좌석 정보: {seat_info}\n"
        f"예약번호: {reservation_no}\n"
        "자동 결제를 진행하지 못했습니다.\n"
        "앱에서 10분 내 결제를 완료해주세요."
    )


def _has_payment_info(payload: dict) -> bool:
    required = [
        payload.get("card_number", "").strip(),
        payload.get("card_password_2", "").strip(),
        payload.get("birth_date", "").strip(),
        payload.get("card_expire", "").strip(),
    ]
    return all(required)


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
        from infrastructure.external.srt import SRT, Adult, Child, Senior

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

    from infrastructure.external.ktx import (
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
    requested_tail = int(request.args.get("tail", "200"))
    tail = max(1, min(requested_tail, 1000))
    if not os.path.exists(LOG_FILE_PATH):
        return jsonify({"logs": []})

    with open(LOG_FILE_PATH, "r", encoding="utf-8") as f:
        lines = f.readlines()

    reservation_only = request.args.get("reservation_only", "0") != "0"
    if reservation_only:
        lines = [line for line in lines if _is_reservation_log_line(line)]

    latest_first = list(reversed(lines[-tail:]))
    return jsonify({"logs": latest_first})


if __name__ == "__main__":
    configure_logging()
    options = load_options()

    host = options.get("host") or os.getenv("SUPERK_HOST", "0.0.0.0")
    port = int(options.get("port") or os.getenv("SUPERK_PORT", "5555"))

    logging.info("Starting Flask web UI on %s:%s", host, port)
    app.run(host=host, port=port)
