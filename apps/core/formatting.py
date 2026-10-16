"""České formátování a zadávání částek a dat, maskování čísel účtů, řazení."""

import re
import unicodedata
from datetime import date
from decimal import Decimal

NBSP = " "
_AMOUNT_RE = re.compile(r"^-?\d+(?:[.,]\d{1,2})?$")
# Č, Ř, Š, Ž a CH jsou v české abecedě samostatná písmena za C, R, S, Z a H.
_CZECH_LETTERS = (("ch", "h￿"), ("č", "c￿"), ("ř", "r￿"), ("š", "s￿"), ("ž", "z￿"))


def format_czk(cents: int) -> str:
    """Haléře → „1 234,50 Kč“ (s nezlomitelnými mezerami)."""
    sign = "-" if cents < 0 else ""
    korun, haler = divmod(abs(cents), 100)
    grouped = f"{korun:,}".replace(",", NBSP)
    return f"{sign}{grouped},{haler:02d}{NBSP}Kč"


def format_amount_input(cents: int) -> str:
    """Haléře → hodnota do formuláře („1234,50“, celé koruny bez desetin)."""
    sign = "-" if cents < 0 else ""
    korun, haler = divmod(abs(cents), 100)
    return f"{sign}{korun},{haler:02d}" if haler else f"{sign}{korun}"


def parse_czk(text: str, *, allow_negative: bool = False) -> int:
    """„1 234,50“ / „1234.5“ / „1 234 Kč“ → haléře. Při chybě ValueError s českou hláškou."""
    cleaned = re.sub(r"\s", "", text.replace(NBSP, "")).removesuffix("Kč").removesuffix("kč")
    if not _AMOUNT_RE.match(cleaned) or (cleaned.startswith("-") and not allow_negative):
        raise ValueError("Zadej částku ve tvaru 1 234,50.")
    return int(Decimal(cleaned.replace(",", ".")) * 100)


def format_date(value: date) -> str:
    """Datum → „15. 10. 2026“."""
    return f"{value.day}. {value.month}. {value.year}"


def mask_account_number(number: str | None, bank_code: str | None = None) -> str:
    """Zobrazí jen poslední 4 číslice čísla účtu: „****7890/0800“."""
    if not number:
        return ""
    digits = "".join(ch for ch in number if ch.isdigit())
    masked = "****" + digits[-4:] if len(digits) > 4 else "****"
    return f"{masked}/{bank_code}" if bank_code else masked


def fold(text: str | None) -> str | None:
    """Malá písmena bez diakritiky – pro hledání („Lékárna“ → „lekarna“)."""
    if text is None:
        return None
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def czech_sort_key(text: str) -> tuple[str, str]:
    """Klíč pro řazení podle české abecedy (Č za C, Š za S, CH za H…)."""
    lowered = text.casefold()
    for letter, replacement in _CZECH_LETTERS:
        lowered = lowered.replace(letter, replacement)
    return fold(lowered) or "", text


MONTH_NAMES = [
    "leden",
    "únor",
    "březen",
    "duben",
    "květen",
    "červen",
    "červenec",
    "srpen",
    "září",
    "říjen",
    "listopad",
    "prosinec",
]
MONTH_SHORT = ["led", "úno", "bře", "dub", "kvě", "čvn", "čvc", "srp", "zář", "říj", "lis", "pro"]


def format_change(current: int, previous: int | None) -> str:
    """Změna proti předchozímu období v % („+12,3 %“); bez základu „–“."""
    if not previous:
        return "–"
    change = (current - previous) / abs(previous) * 100
    return f"{change:+.1f}".replace(".", ",").replace("-", "−") + f"{NBSP}%"


def format_share(value: float) -> str:
    """Podíl v procentech s jedním desetinným místem („12,3 %“)."""
    return f"{value:.1f}".replace(".", ",") + f"{NBSP}%"
