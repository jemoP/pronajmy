"""Stránky peněz: pohyby (P02), účty (P01), účely (P03), export pohybů."""

from datetime import date, timedelta
from typing import Any

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.http import Http404, HttpRequest, HttpResponse, HttpResponseRedirect, QueryDict
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.core.export import FORMATS, Column, Table, export_response
from apps.core.formatting import format_amount_input, format_czk, parse_czk
from apps.core.forms import first_errors
from apps.core.web import opt_date, opt_int, safe_back, with_params
from apps.money.forms import FIELDS, EntryForm
from apps.money.models import Account, AccountKind, Category, CategoryKind, Entry, EntryKind
from apps.money.services.accounts import AccountInput, account_choices, list_accounts, save_account
from apps.money.services.bulk_delete import delete_entries, delete_summary
from apps.money.services.categories import (
    CategoryInput,
    category_choices,
    delete_category,
    list_categories,
    save_category,
)
from apps.money.services.entries import (
    SORT_FIELDS,
    EntryFilter,
    create_entry,
    delete_entry,
    filtered,
    list_entries,
    recategorize,
    update_entry,
)
from apps.rentals.services.properties import property_choices

# Parametry rychlého zadání, které se do filtru ani odkazů nepřenáší.
ENTRY_PARAMS = ("saved", "copy", "last_date", "last_kind", "last_account", "deleted")


def list_url() -> str:
    return reverse("money:entries")


# --- Pohyby -----------------------------------------------------------------


def parse_filter(params: QueryDict) -> EntryFilter:
    sort = params.get("sort", "")
    kind = params.get("kind", "")
    return EntryFilter(
        date_from=opt_date(params.get("date_from")),
        date_to=opt_date(params.get("date_to")),
        kind=kind if kind in EntryKind.values else None,
        category_id=opt_int(params.get("category")),
        property_id=opt_int(params.get("property")),
        account_id=opt_int(params.get("account")),
        text=params.get("q") or None,
        sort=sort if sort.lstrip("-") in SORT_FIELDS else "-date",
        page=opt_int(params.get("page")) or 1,
    )


def month_end(day: date) -> date:
    return (day.replace(day=1) + timedelta(days=32)).replace(day=1) - timedelta(days=1)


def presets(today: date) -> list[tuple[str, date, date]]:
    first = today.replace(day=1)
    previous = first - timedelta(days=1)
    return [
        ("Tento měsíc", first, month_end(today)),
        ("Minulý měsíc", previous.replace(day=1), previous),
        ("Letos", date(today.year, 1, 1), date(today.year, 12, 31)),
        ("Loni", date(today.year - 1, 1, 1), date(today.year - 1, 12, 31)),
    ]


def values_from(entry: Entry, day: date | None = None) -> dict[str, str]:
    return {
        "date": (day or entry.date).isoformat(),
        "kind": entry.kind,
        "amount": format_amount_input(entry.amount_cents),
        "account_id": str(entry.account_id),
        "to_account_id": str(entry.to_account_id or ""),
        "category_id": str(entry.category_id or ""),
        "property_id": str(entry.property_id or ""),
        "note": entry.note,
    }


def form_choices(values: dict[str, str]) -> dict[str, Any]:
    keep_accounts = {i for k in ("account_id", "to_account_id") if (i := opt_int(values.get(k)))}
    keep_category = {i for i in [opt_int(values.get("category_id"))] if i}
    keep_property = {i for i in [opt_int(values.get("property_id"))] if i}
    return {
        "accounts": account_choices(keep_accounts),
        "categories": category_choices(keep_category),
        "properties": property_choices(keep_property),
    }


def default_values(params: QueryDict, today: date) -> dict[str, str]:
    copy = opt_int(params.get("copy"))
    source = Entry.objects.filter(pk=copy).first() if copy else None
    if source:
        return values_from(source, today)
    account = params.get("last_account")
    if not account and (accounts := account_choices()):
        account = str(accounts[0].id)
    return {
        "date": params.get("last_date") or today.isoformat(),
        "kind": params.get("last_kind") or EntryKind.INCOME,
        "account_id": account or "",
    }


def render_list(
    request: HttpRequest,
    values: dict[str, str] | None = None,
    errors: dict[str, str] | None = None,
) -> HttpResponse:
    params = request.GET
    today = timezone.localdate()
    entry_filter = parse_filter(params)
    values = values if values is not None else default_values(params, today)
    return render(
        request,
        "money/entries.html",
        {
            "nav": "entries",
            "page": list_entries(entry_filter, today),
            "filter": entry_filter,
            "values": values,
            "errors": errors or {},
            "choices": form_choices(values),
            "all_accounts": account_choices({entry_filter.account_id or 0}),
            "all_categories": category_choices({entry_filter.category_id or 0}),
            "all_properties": property_choices({entry_filter.property_id or 0}),
            "presets": presets(today),
            "today": today,
            "saved_id": opt_int(params.get("saved")),
            "deleted": params.get("deleted") == "1",
            "copying": bool(params.get("copy")),
            # Aktuální seznam bez parametrů rychlého zadání – cíl formuláře a návrat z úprav.
            "here": with_params(f"{list_url()}?{params.urlencode()}", drop=ENTRY_PARAMS),
        },
    )


def entries(request: HttpRequest) -> HttpResponse:
    if request.method != "POST":
        return render_list(request)
    form = EntryForm(request.POST)
    values = {name: request.POST.get(name, "") for name in FIELDS}
    if not form.is_valid():
        return render_list(request, values, first_errors(form.errors))
    try:
        entry = create_entry(form.to_input())
    except ValidationError as exc:
        return render_list(request, values, first_errors(exc))
    here = with_params(f"{list_url()}?{request.GET.urlencode()}", drop=(*ENTRY_PARAMS, "page"))
    return redirect(
        with_params(
            here,
            saved=entry.id,
            last_date=values["date"],
            last_kind=values["kind"],
            last_account=values["account_id"],
        )
    )


@require_POST
def entries_recategorize(request: HttpRequest) -> HttpResponseRedirect:
    """Hromadná změna účelu označených pohybů (ZM-007); návrat na seznam se stejným filtrem."""
    back = safe_back(request.POST.get("back"), list_url())
    ids = [i for v in request.POST.getlist("entries") if (i := opt_int(v))]
    try:
        count = recategorize(ids, opt_int(request.POST.get("category_id")))
    except ValidationError as exc:
        for message in exc.messages:
            messages.error(request, message)
    else:
        messages.success(request, f"Účel změněn u pohybů: {count}.")
    return redirect(back)


def entries_delete(request: HttpRequest) -> HttpResponse:
    """Hromadné smazání (ZM-009): bez „confirm“ ukáže souhrn a dopady, s ním smaže."""
    back = safe_back(request.POST.get("back"), list_url())
    if request.method != "POST":
        return redirect(list_url())
    ids = [i for v in request.POST.getlist("entries") if (i := opt_int(v))]
    try:
        if request.POST.get("confirm") == "1":
            summary = delete_entries(ids, request.POST.get("token", ""))
        else:
            summary = delete_summary(ids)
    except ValidationError as exc:
        for message in exc.messages:
            messages.error(request, message)
        return redirect(back)
    if request.POST.get("confirm") == "1":
        sums = ", ".join(
            f"{label.lower()} {format_czk(amount)}" for label, amount in summary.sums_labeled
        )
        messages.success(request, f"Smazáno pohybů: {summary.count} ({sums}).")
        return redirect(back)
    ids_param = ",".join(str(e.pk) for e in summary.entries)
    return render(
        request,
        "money/entries_delete.html",
        {
            "nav": "entries",
            "summary": summary,
            "back": back,
            "export_url": f"{reverse('money:entries_export', args=['csv'])}?ids={ids_param}",
            "today": timezone.localdate(),
        },
    )


ENTRY_COLUMNS = [
    Column("Datum", "date"),
    Column("Druh", width=20),
    Column("Účel", width=24),
    Column("Byt", width=20),
    Column("Částka", "money"),
    Column("Účet", width=22),
    Column("Na účet", width=22),
    Column("Poznámka", width=40),
    Column("Plánováno", width=10),
]


def entries_export(request: HttpRequest, fmt: str) -> HttpResponse:
    """Export celého výsledku filtru. Čísla účtů se neexportují, jen názvy."""
    if fmt not in FORMATS:
        raise Http404
    today = timezone.localdate()
    ids = [i for v in request.GET.get("ids", "").split(",") if (i := opt_int(v))]
    # Export označených pohybů (před hromadným smazáním, ZM-009), jinak podle filtru.
    base = Entry.objects.filter(pk__in=ids) if ids else filtered(parse_filter(request.GET))
    qs = base.select_related("account", "to_account", "category", "property").order_by("date", "id")
    rows = (
        [
            e.date,
            e.get_kind_display(),
            e.category.name if e.category else "",
            e.property.name if e.property else "",
            e.amount_cents,
            e.account.name,
            e.to_account.name if e.to_account else "",
            e.note,
            "ano" if e.date > today else "",
        ]
        for e in qs.iterator(chunk_size=2000)
    )
    table = Table("Pohyby", ENTRY_COLUMNS, rows)
    return export_response(fmt, [table], f"pohyby-{today.isoformat()}")


def entry_edit(request: HttpRequest, pk: int) -> HttpResponse:
    entry = get_object_or_404(Entry, pk=pk)
    back = safe_back(request.GET.get("back"), list_url())
    errors: dict[str, str] = {}
    if request.method == "POST":
        form = EntryForm(request.POST)
        values = {name: request.POST.get(name, "") for name in FIELDS}
        if form.is_valid():
            try:
                update_entry(entry, form.to_input())
            except ValidationError as exc:
                errors = first_errors(exc)
            else:
                return redirect(with_params(back, saved=entry.id))
        else:
            errors = first_errors(form.errors)
    else:
        values = values_from(entry)
    return render(
        request,
        "money/entry_edit.html",
        {
            "nav": "entries",
            "entry": entry,
            "values": values,
            "errors": errors,
            "choices": form_choices(values),
            "back": back,
        },
    )


@require_POST
def entry_delete(request: HttpRequest, pk: int) -> HttpResponseRedirect:
    delete_entry(get_object_or_404(Entry, pk=pk))
    back = safe_back(request.GET.get("back"), list_url())
    return redirect(with_params(back, deleted=1))


# --- Účty -------------------------------------------------------------------


def accounts(request: HttpRequest) -> HttpResponse:
    at = opt_date(request.GET.get("at"))
    include_inactive = request.GET.get("inactive") == "1"
    rows = list_accounts(at or timezone.localdate(), include_inactive)
    return render(
        request,
        "money/accounts.html",
        {
            "nav": "categories",
            "tab": "accounts",
            "rows": rows,
            "at": at,
            "include_inactive": include_inactive,
            "total": sum(r.balance_cents for r in rows),
        },
    )


def account_values(account: Account | None) -> dict[str, str]:
    if account is None:
        return {"kind": AccountKind.BANK, "opening": "0", "active": "on"}
    return {
        "name": account.name,
        "kind": account.kind,
        "bank_code": account.bank_code,
        "account_number": "",
        "opening": format_amount_input(account.opening_balance_cents),
        "active": "on" if account.active else "",
    }


def account_form(request: HttpRequest, pk: int | None = None) -> HttpResponse:
    account = get_object_or_404(Account, pk=pk) if pk else None
    errors: dict[str, str] = {}
    if request.method == "POST":
        names = ("name", "kind", "bank_code", "account_number", "opening", "active")
        values = {name: request.POST.get(name, "") for name in names}
        try:
            opening = parse_czk(values["opening"] or "0", allow_negative=True)
            save_account(
                account,
                AccountInput(
                    name=values["name"],
                    kind=values["kind"],
                    bank_code=values["bank_code"],
                    account_number=values["account_number"] or None,
                    opening_balance_cents=opening,
                    active=values["active"] == "on",
                ),
            )
        except ValueError as exc:
            errors = {"opening": str(exc)}
        except ValidationError as exc:
            errors = first_errors(exc)
        else:
            messages.success(request, "Účet uložen.")
            return redirect("money:accounts")
    else:
        values = account_values(account)
    return render(
        request,
        "money/account_form.html",
        {"nav": "categories", "account": account, "values": values, "errors": errors},
    )


# --- Účely ------------------------------------------------------------------

CATEGORY_FIELDS = ("name", "kind", "sort", "active", "taxable", "is_service")


def category_input(values: dict[str, str]) -> CategoryInput:
    return CategoryInput(
        name=values["name"],
        kind=values["kind"],
        sort=opt_int(values["sort"]) or 0,
        active=values["active"] == "on",
        taxable=values["taxable"] == "on",
        is_service=values["is_service"] == "on",
    )


def categories(request: HttpRequest) -> HttpResponse:
    values = {"kind": CategoryKind.EXPENSE, "active": "on", "taxable": "on"}
    errors: dict[str, str] = {}
    if request.method == "POST":
        values = {name: request.POST.get(name, "") for name in CATEGORY_FIELDS}
        values["active"] = "on"
        try:
            category = save_category(None, category_input(values))
        except ValidationError as exc:
            errors = first_errors(exc)
        else:
            messages.success(request, f"Účel „{category.name}“ přidán.")
            return redirect("money:categories")
    return render(
        request,
        "money/categories.html",
        {
            "nav": "categories",
            "tab": "categories",
            "rows": list_categories(),
            "values": values,
            "errors": errors,
        },
    )


def category_edit(request: HttpRequest, pk: int) -> HttpResponse:
    category = get_object_or_404(Category, pk=pk)
    errors: dict[str, str] = {}
    if request.method == "POST":
        values = {name: request.POST.get(name, "") for name in CATEGORY_FIELDS}
        try:
            save_category(category, category_input(values))
        except ValidationError as exc:
            errors = first_errors(exc)
        else:
            messages.success(request, "Účel uložen.")
            return redirect("money:categories")
    else:
        values = {
            "name": category.name,
            "kind": category.kind,
            "sort": str(category.sort),
            "active": "on" if category.active else "",
            "taxable": "on" if category.taxable else "",
            "is_service": "on" if category.is_service else "",
        }
    return render(
        request,
        "money/category_edit.html",
        {"nav": "categories", "category": category, "values": values, "errors": errors},
    )


@require_POST
def category_delete(request: HttpRequest, pk: int) -> HttpResponseRedirect:
    category = get_object_or_404(Category, pk=pk)
    try:
        delete_category(category)
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
    else:
        messages.success(request, f"Účel „{category.name}“ smazán.")
    return redirect("money:categories")
