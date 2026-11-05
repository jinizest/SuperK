"""Compatibility vector from VictorJeon/korail-mobile-api tests/test_dynapath.py.
Reference commit: 484c294d088080c92264c021d038b27a6efbe532.
Checks token encoding without calling Korail or making a reservation.
"""
from src.infrastructure.external.ktx import DynaPathMasterEngine


def test_token_matches_published_reference():
    engine = DynaPathMasterEngine()
    engine.app_start_ts = "1712345600000"
    token = engine.generate_token("7f000001-android-probe", 1712345678901, "A1B2")
    assert token == (
        "bEeEPLYj144a44lDm54Mg4Pv4ff4fGKguKkDK1FdDwFGP4Gdlqujn5nfujYP4GudEqyRufK9v5Jy1"
        "mkP5u95u95ug5EMuRqqYYJFy5KgqYYPum9vKqu99qndyvn3kJmGmlgPCPmKfPREJllPafJ3wnG95jk"
        "PagPkYm1DPCJJ35m1w9vRqjkJnuuffJ3mPjkJ4CJnuuffJ3mJKqqjkJnuuffJ3mJwwdlRP4Kqq19vf"
        "qCP5CC5CumKfm1g5u95u95JFqFdnjlmFCmlDmnymwunGf5ug9vMqCP5JFuj1njlmEjJlmdlEfCM4vnm"
        "l9fjFqwDnj1uRqqYYJFy9vRwKmwEv55455P"
    )

