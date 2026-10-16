from datetime import date

import pytest

from apps.core.formatting import (
    NBSP,
    czech_sort_key,
    fold,
    format_amount_input,
    format_czk,
    format_date,
    mask_account_number,
    parse_czk,
)


def test_format_czk() -> None:
    assert format_czk(123_450) == f"1{NBSP}234,50{NBSP}Kč"
    assert format_czk(5) == f"0,05{NBSP}Kč"
    assert format_czk(-63_151_000) == f"-631{NBSP}510,00{NBSP}Kč"


def test_format_date() -> None:
    assert format_date(date(2026, 10, 5)) == "5. 10. 2026"


def test_mask_account_number() -> None:
    assert mask_account_number("000019-1234567890", "0800") == "****7890/0800"
    assert mask_account_number("123") == "****"
    assert mask_account_number(None) == ""


def test_parse_czk() -> None:
    assert parse_czk("1 234,50") == 123_450
    assert parse_czk(f"1{NBSP}234,5 Kč") == 123_450
    assert parse_czk("99.99") == 9_999
    assert parse_czk("150") == 15_000
    assert parse_czk("-20", allow_negative=True) == -2_000


@pytest.mark.parametrize("value", ["", "abc", "1,234", "1.2.3", "-5", "12,"])
def test_parse_czk_rejects(value: str) -> None:
    with pytest.raises(ValueError, match="1 234,50"):
        parse_czk(value)


def test_format_amount_input() -> None:
    assert format_amount_input(123_450) == "1234,50"
    assert format_amount_input(15_000) == "150"
    assert parse_czk(format_amount_input(5)) == 5


def test_fold() -> None:
    assert fold("Lékárna – BRÝLE") == "lekarna – bryle"
    assert fold(None) is None


def test_czech_sort_key() -> None:
    names = [
        "Škola",
        "Sport",
        "Auto",
        "Čaj",
        "Cukr",
        "Chata",
        "Hračky",
        "Úroky",
        "Zahrada",
        "Žvýkačky",
    ]
    assert sorted(names, key=czech_sort_key) == [
        "Auto",
        "Cukr",
        "Čaj",
        "Hračky",
        "Chata",
        "Sport",
        "Škola",
        "Úroky",
        "Zahrada",
        "Žvýkačky",
    ]
