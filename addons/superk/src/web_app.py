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

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return

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
        }


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


@app.route("/")
def index():
    options = load_options()
    return render_template(
        "index.html",
        status=worker.status(),
        options=options,
        log_file=LOG_FILE_PATH,
    )


@app.post("/start")
def start_server():
    worker.start()
    return redirect(url_for("index"))


@app.post("/stop")
def stop_server():
    worker.stop()
    return redirect(url_for("index"))


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
