"""Účty a jejich zůstatky (aktuální bez plánovaných pohybů, nebo k datu)."""

from dataclasses import dataclass
from datetime import date

from django.core.exceptions import ValidationError
from django.db.models import Sum

from apps.core.formatting import czech_sort_key
from apps.money.models import INCOMING_KINDS, OUTGOING_KINDS, Account, AccountKind, Entry

KIND_ORDER = list(AccountKind.values)


@dataclass(frozen=True)
class AccountBalance:
    account: Account
    balance_cents: int


def _sums(field: str, at: date, kinds: tuple[str, ...] | None = None) -> dict[int, int]:
    qs = Entry.objects.filter(date__lte=at, **{f"{field}__isnull": False})
    if kinds is not None:
        qs = qs.filter(kind__in=kinds)
    rows = qs.values(field).annotate(total=Sum("amount_cents")).order_by()
    return {row[field]: row["total"] for row in rows}


def balances_at(at: date) -> dict[int, int]:
    """Zůstatky všech účtů včetně pohybů s datem do `at` včetně.
    Aktuální zůstatek = balances_at(dnes) – plánované (budoucí) pohyby se nepočítají."""
    incoming = _sums("account_id", at, INCOMING_KINDS)
    outgoing = _sums("account_id", at, OUTGOING_KINDS)
    transfers_in = _sums("to_account_id", at)
    return {
        account.id: account.opening_balance_cents
        + incoming.get(account.id, 0)
        + transfers_in.get(account.id, 0)
        - outgoing.get(account.id, 0)
        for account in Account.objects.all()
    }


def list_accounts(at: date, include_inactive: bool = False) -> list[AccountBalance]:
    balances = balances_at(at)
    qs = Account.objects.all() if include_inactive else Account.objects.filter(active=True)
    accounts = sorted(
        qs, key=lambda a: (not a.active, KIND_ORDER.index(a.kind), czech_sort_key(a.name))
    )
    return [AccountBalance(a, balances.get(a.id, 0)) for a in accounts]


def account_choices(keep_ids: set[int] | None = None) -> list[Account]:
    """Účty do výběru ve formuláři; neaktivní jen pokud jsou už vybrané."""
    keep = keep_ids or set()
    return [
        a
        for a in sorted(Account.objects.all(), key=lambda a: czech_sort_key(a.name))
        if a.active or a.id in keep
    ]


@dataclass(frozen=True)
class AccountInput:
    name: str
    kind: str
    bank_code: str
    # None = číslo účtu neměnit (v UI se nikdy nezobrazuje celé).
    account_number: str | None
    opening_balance_cents: int
    active: bool


def save_account(account: Account | None, data: AccountInput) -> Account:
    errors: dict[str, str] = {}
    name = data.name.strip()
    if not name:
        errors["name"] = "Zadej název účtu."
    if data.kind not in AccountKind.values:
        errors["kind"] = "Vyber druh účtu."
    if errors:
        raise ValidationError(errors)
    account = account or Account()
    account.name = name
    account.kind = data.kind
    account.bank_code = data.bank_code.strip()
    if data.account_number is not None:
        account.account_number = data.account_number.strip()
    account.opening_balance_cents = data.opening_balance_cents
    account.active = data.active
    account.save()
    return account
