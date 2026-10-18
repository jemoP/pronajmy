"""Stránka Platby: předpisy plateb dodavatelům, splátky k zaplacení, výhled (ZM-006)."""

from typing import Any

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.core.formatting import format_amount_input, parse_czk
from apps.core.web import opt_int
from apps.money.models import CategoryKind, Payable, PayableDue
from apps.money.payable_forms import ChangeFromForm, PayableForm, PayDuesForm
from apps.money.services.categories import category_choices
from apps.money.services.payables import (
    ItemInput,
    change_from,
    current_payables,
    delete_payable,
    due_amount,
    dues_by_payable,
    ensure_dues,
    forecast,
    monthly_amount,
    open_dues,
    pay_dues,
    save_payable,
    set_due_amount,
    set_skipped,
)
from apps.rentals.services.properties import property_choices
from apps.rentals.views import add_errors

NAV = "payables"
ITEM_ROWS = 6  # řádků rozpisu ve formuláři (prázdné se ignorují)


def payables_url() -> str:
    return reverse("money:payables")


def render_payables(request: HttpRequest, pay_form: PayDuesForm | None = None) -> HttpResponse:
    today = timezone.localdate()
    include_ended = request.GET.get("ended") == "1"
    dues = [(due, due_amount(due)) for due in open_dues(today)]
    rows = []
    for payable in current_payables(today, include_ended):
        upcoming = payable.dues.filter(entries__isnull=True, skipped=False).order_by("due_date")
        rows.append(
            {"payable": payable, "monthly": monthly_amount(payable), "next": upcoming.first()}
        )
    response = render(
        request,
        "money/payables.html",
        {
            "nav": NAV,
            "today": today,
            "dues": dues,
            "dues_total": sum(amount for _, amount in dues),
            "rows": rows,
            "include_ended": include_ended,
            "forecast": forecast(today),
            "pay_form": pay_form or PayDuesForm(initial={"date_mode": "due"}),
        },
    )
    if pay_form is not None:
        response["HX-Push-Url"] = payables_url()
    return response


def payables(request: HttpRequest) -> HttpResponse:
    ensure_dues(timezone.localdate())
    return render_payables(request)


def pay(request: HttpRequest) -> HttpResponse:
    """Zaplacení splátek: tlačítko u řádku (single) nebo označené (dues)."""
    if request.method != "POST":
        return redirect(payables_url())
    today = timezone.localdate()
    single = opt_int(request.POST.get("single"))
    ids = [single] if single else [i for v in request.POST.getlist("dues") if (i := opt_int(v))]
    form = PayDuesForm(request.POST)
    if form.is_valid():
        data = form.cleaned_data
        try:
            created = pay_dues(
                ids,
                day=data["day"] if data["date_mode"] == "day" else None,
                today=today,
                note=data["note"],
            )
        except ValidationError as exc:
            add_errors(form, exc)
        else:
            messages.success(request, f"Zapsáno nákladů: {len(created)}.")
            back = request.POST.get("back") or payables_url()
            return redirect(back if back.startswith("/") and not back.startswith("//") else "/")
    return render_payables(request, form)


# --- Předpis -----------------------------------------------------------------


def item_rows(payable: Payable | None, post: Any = None) -> list[dict[str, str]]:
    """Řádky rozpisu pro formulář: z POST, nebo z předpisu + prázdné."""
    if post is not None:
        count = max(ITEM_ROWS, opt_int(post.get("item_count")) or 0)
        return [
            {
                "category": post.get(f"item_category_{n}", ""),
                "property": post.get(f"item_property_{n}", ""),
                "amount": post.get(f"item_amount_{n}", ""),
                "label": post.get(f"item_label_{n}", ""),
            }
            for n in range(count)
        ]
    rows = [
        {
            "category": str(i.category_id),
            "property": str(i.property_id or ""),
            "amount": format_amount_input(i.amount_cents),
            "label": i.label,
        }
        for i in (payable.items.order_by("id") if payable and payable.pk else [])
    ]
    empty = {"category": "", "property": "", "amount": "", "label": ""}
    return rows + [dict(empty) for _ in range(max(ITEM_ROWS - len(rows), 2))]


def parse_items(rows: list[dict[str, str]]) -> tuple[list[ItemInput], dict[str, str]]:
    items: list[ItemInput] = []
    errors: dict[str, str] = {}
    for n, row in enumerate(rows):
        amount: int | None = None
        if row["amount"].strip():
            try:
                amount = parse_czk(row["amount"])
            except ValueError as exc:
                errors[f"item_{n}"] = str(exc)
        items.append(
            ItemInput(opt_int(row["category"]), opt_int(row["property"]), amount, row["label"])
        )
    return items, errors


def payable_form(request: HttpRequest, pk: int | None = None) -> HttpResponse:
    payable = get_object_or_404(Payable, pk=pk) if pk else Payable(valid_from=timezone.localdate())
    form = PayableForm(request.POST or None, instance=payable)
    rows = item_rows(payable, request.POST if request.method == "POST" else None)
    item_errors: dict[str, str] = {}
    if request.method == "POST":
        items, item_errors = parse_items(rows)
        if form.is_valid() and not item_errors:
            saved = form.save(commit=False)
            new_account = request.POST.get("supplier_account", "").strip()
            if new_account or not pk:
                saved.supplier_account = new_account
            try:
                save_payable(saved, items)
            except ValidationError as exc:
                for key, messages_ in exc.message_dict.items():
                    if key.startswith("item"):
                        item_errors[key] = messages_[0]
                    else:
                        form.add_error(key if key in form.fields else None, messages_)
            else:
                ensure_dues(timezone.localdate())
                messages.success(request, "Předpis platby uložen.")
                return redirect("money:payable", saved.pk)
    for n, row in enumerate(rows):
        row["error"] = item_errors.get(f"item_{n}", "")
    keep_categories = {i for r in rows if (i := opt_int(r["category"]))}
    keep_properties = {i for r in rows if (i := opt_int(r["property"]))}
    return render(
        request,
        "money/payable_form.html",
        {
            "nav": NAV,
            "form": form,
            "payable": payable if pk else None,
            "rows": rows,
            "item_errors": item_errors,
            "items_error": item_errors.get("items", ""),
            "categories": [
                c for c in category_choices(keep_categories) if c.kind == CategoryKind.EXPENSE
            ],
            "properties": property_choices(keep_properties),
        },
    )


def payable_detail(
    request: HttpRequest, pk: int, change_form: ChangeFromForm | None = None
) -> HttpResponse:
    ensure_dues(timezone.localdate())
    payable = get_object_or_404(
        Payable.objects.select_related("account", "previous").prefetch_related(
            "items__category", "items__property"
        ),
        pk=pk,
    )
    successor = Payable.objects.filter(previous=payable).first()
    rows = dues_by_payable(payable)
    return render(
        request,
        "money/payable_detail.html",
        {
            "nav": NAV,
            "payable": payable,
            "successor": successor,
            "total": sum(i.amount_cents for i in payable.items.all()),
            "single_item": payable.items.count() == 1,
            "rows": rows,
            "has_paid": any(entries for _, _, entries in rows),
            "today": timezone.localdate(),
            "change_form": change_form or ChangeFromForm(),
            "pay_form": PayDuesForm(initial={"date_mode": "due"}),
        },
    )


@require_POST
def payable_change(request: HttpRequest, pk: int) -> HttpResponse:
    payable = get_object_or_404(Payable, pk=pk)
    form = ChangeFromForm(request.POST)
    if form.is_valid():
        try:
            new = change_from(payable, form.cleaned_data["day"])
        except ValidationError as exc:
            add_errors(form, exc)
        else:
            messages.success(request, "Založen navazující předpis – uprav v něm, co se mění.")
            return redirect("money:payable_edit", new.pk)
    response = payable_detail(request, pk, change_form=form)
    response["HX-Push-Url"] = reverse("money:payable", args=[pk])
    return response


@require_POST
def payable_delete(request: HttpRequest, pk: int) -> HttpResponseRedirect:
    payable = get_object_or_404(Payable, pk=pk)
    try:
        delete_payable(payable)
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
        return redirect("money:payable", pk)
    messages.success(request, "Předpis platby smazán.")
    return redirect(payables_url())


@require_POST
def due_skip(request: HttpRequest, pk: int) -> HttpResponseRedirect:
    due = get_object_or_404(PayableDue, pk=pk)
    try:
        set_skipped(due, request.POST.get("skip") == "1")
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
    return redirect("money:payable", due.payable_id)


@require_POST
def due_amount_view(request: HttpRequest, pk: int) -> HttpResponseRedirect:
    due = get_object_or_404(PayableDue, pk=pk)
    text = request.POST.get("amount", "").strip()
    try:
        set_due_amount(due, parse_czk(text) if text else None)
    except ValueError as exc:
        messages.error(request, str(exc))
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
    else:
        messages.success(request, "Částka splátky uložena.")
    return redirect("money:payable", due.payable_id)
