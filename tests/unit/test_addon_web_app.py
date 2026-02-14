from addons.superk.src.web_app import (
    _normalize_date_yyyymmdd,
    _normalize_time_to_hhmm,
    build_form_values,
    build_waiting_form_values,
    search_real_trains,
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
