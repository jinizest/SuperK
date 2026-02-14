from addons.superk.src.web_app import (
    _normalize_date_yyyymmdd,
    _normalize_time_to_hhmm,
    build_form_values,
    build_waiting_form_values,
    search_real_trains,
    _extract_run_context,
    _to_ktx_reserve_option,
    _is_reservation_log_line,
)


def test_normalize_time_accepts_hhmmss():
    assert _normalize_time_to_hhmm("093000") == "0930"


def test_normalize_date_fallback_for_invalid():
    date = _normalize_date_yyyymmdd("abc")
    assert len(date) == 8
    assert date.isdigit()


def test_search_real_trains_requires_login_credentials():
    try:
        search_real_trains({"departure": "서대구", "arrival": "행신"})
        assert False, "Expected ValueError"
    except ValueError as exc:
        assert "로그인 정보" in str(exc)


def test_build_form_values_default_stations():
    values = build_form_values({})

    assert values["departure"] == "서대구"
    assert values["arrival"] == "행신"


def test_build_waiting_form_values_is_blank_for_sensitive_fields():
    values = build_waiting_form_values()

    assert values["user_id"] == ""
    assert values["user_pw"] == ""
    assert values["departure"] == ""
    assert values["arrival"] == ""


def test_extract_run_context_reads_nested_payload():
    payload = {
        "rail_type": "ktx",
        "login": {"user_id": "u", "user_pw": "p"},
        "search": {
            "departure": "서대구",
            "arrival": "행신",
            "departure_date": "20260222",
            "departure_time": "1400",
            "selected_train_no": "212",
        },
    }

    context = _extract_run_context(payload)

    assert context["user_id"] == "u"
    assert context["selected_train_no"] == "212"


def test_to_ktx_reserve_option_defaults_to_general_first():
    class StubOption:
        GENERAL_FIRST = "gf"
        GENERAL_ONLY = "go"
        SPECIAL_FIRST = "sf"
        SPECIAL_ONLY = "so"

    assert _to_ktx_reserve_option("unknown", StubOption) == "gf"
    assert _to_ktx_reserve_option("special_only", StubOption) == "so"



def test_is_reservation_log_line_filters_http_access_logs():
    assert _is_reservation_log_line('2026 [INFO] 192.168.0.1 "GET /api/logs HTTP/1.1"') is False


def test_is_reservation_log_line_allows_reservation_events():
    assert _is_reservation_log_line("2026 [INFO] 🔄 예약 시도 #1") is True
