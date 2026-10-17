"""Stránky pronájmů: přehled, byty, nájemníci (P04), smlouvy a dodatky (P05),
předpisy, platby a jistota (P06, P07)."""

from collections.abc import Callable
from datetime import date
from typing import Any

from django import forms
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import Http404, HttpRequest, HttpResponse, HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.core.formatting import czech_sort_key
from apps.core.forms import first_errors
from apps.core.web import opt_int
from apps.money.models import Entry
from apps.money.services.accounts import account_choices, list_accounts
from apps.money.services.entries import result_for
from apps.rentals.forms import (
    AmendmentForm,
    ChargeForm,
    EndLeaseForm,
    LeaseForm,
    OffsetForm,
    PaymentForm,
    PayOutForm,
    TenantForm,
)
from apps.rentals.models import (
    MONTHLY_KINDS,
    Lease,
    LeaseAmendment,
    LeaseStatus,
    PaymentKind,
    Property,
    RentCharge,
    RentPayment,
    Tenant,
)
from apps.rentals.services.attachments import attachments_block
from apps.rentals.services.charges import (
    BALANCE_PREFETCH,
    ensure_all_charges,
    ensure_charges,
    lease_balance,
)
from apps.rentals.services.leases import (
    current_lease,
    lease_end,
    leases_with_details,
    save_amendment,
    save_lease,
    tenant_names,
    terms_at,
    terms_history,
)
from apps.rentals.services.maintenance import plan_states
from apps.rentals.services.payments import (
    end_with_settlement,
    link_entry,
    offset_deposit,
    pay_out,
    record_payment,
    suggestions,
    unlink,
)
from apps.rentals.services.properties import (
    PropertyInput,
    format_area,
    list_properties,
    parse_area,
    save_property,
)


def add_errors(form: forms.BaseForm, exc: ValidationError) -> None:
    """Chyby ze služby k polím formuláře (neznámá pole jako obecná chyba)."""
    for field, errors in exc.message_dict.items():
        form.add_error(field if field in form.fields else None, errors)


def form_page(
    request: HttpRequest,
    form: forms.BaseForm,
    *,
    nav: str,
    title: str,
    back: str,
    submit: str = "Uložit",
    attachments: dict[str, Any] | None = None,
    entry: Entry | None = None,
    delete_url: str | None = None,
    delete_confirm: str = "",
) -> HttpResponse:
    """Obecná stránka formuláře; volitelně s přílohami, odkazem na náklad a smazáním."""
    return render(
        request,
        "rentals/form.html",
        {
            "nav": nav,
            "form": form,
            "title": title,
            "back": back,
            "submit": submit,
            "attachments": attachments,
            "entry": entry,
            "delete_url": delete_url,
            "delete_confirm": delete_confirm,
        },
    )


# --- Přehled -----------------------------------------------------------------


def debtors(today: date) -> list[dict[str, Any]]:
    """Všechny smlouvy (i ukončené) s částkou po splatnosti, největší dluh nahoře."""
    leases = (
        Lease.objects.exclude(status=LeaseStatus.DRAFT)
        .select_related("property")
        .prefetch_related(*BALANCE_PREFETCH, "lease_tenants__tenant")
    )
    rows: list[dict[str, Any]] = []
    for lease in leases:
        balance = lease_balance(lease, today)
        if balance.overdue > 0:
            rows.append({"lease": lease, "tenants": tenant_names(lease), "balance": balance})
    rows.sort(key=lambda d: -d["balance"].overdue)
    return rows


def overview(request: HttpRequest) -> HttpResponse:
    """Přehled pronájmů: dlužníci, byty s aktuální smlouvou a saldem, výsledek, zůstatky."""
    today = timezone.localdate()
    ensure_all_charges(today)
    qs = Property.objects.filter(active=True).prefetch_related(leases_with_details())
    current = {}
    for prop in qs:
        lease = current_lease(prop, today)
        if lease:
            current[prop.pk] = lease
    balances = {
        lease.pk: lease_balance(lease, today)
        for lease in Lease.objects.filter(
            pk__in=[le.pk for le in current.values()]
        ).prefetch_related(*BALANCE_PREFETCH)
    }
    rows = []
    for prop in sorted(qs, key=lambda p: czech_sort_key(p.name)):
        lease = current.get(prop.pk)
        rows.append(
            {
                "property": prop,
                "lease": lease,
                "tenants": tenant_names(lease) if lease else "",
                "terms": terms_at(lease, today) if lease else None,
                "end": lease_end(lease) if lease else None,
                "balance": balances.get(lease.pk) if lease else None,
            }
        )
    debtor_rows = debtors(today)
    accounts = list_accounts(today)
    return render(
        request,
        "rentals/overview.html",
        {
            "nav": "home",
            "today": today,
            "rows": rows,
            "debtors": debtor_rows,
            "overdue_total": sum(d["balance"].overdue for d in debtor_rows),
            "accounts": accounts,
            "total": sum(a.balance_cents for a in accounts),
            "result": result_for(date(today.year, 1, 1), date(today.year, 12, 31), today),
            "planned_count": Entry.objects.filter(date__gt=today).count(),
        },
    )


# --- Byty --------------------------------------------------------------------

PROPERTY_FIELDS = ("name", "address", "unit", "layout", "floor_area", "account_id", "note")


def properties(request: HttpRequest) -> HttpResponse:
    include_inactive = request.GET.get("inactive") == "1"
    return render(
        request,
        "rentals/properties.html",
        {
            "nav": "properties",
            "rows": list_properties(include_inactive),
            "include_inactive": include_inactive,
        },
    )


def property_values(prop: Property | None) -> dict[str, str]:
    if prop is None:
        return {"active": "on"}
    return {
        "name": prop.name,
        "address": prop.address,
        "unit": prop.unit,
        "layout": prop.layout,
        "floor_area": format_area(prop.floor_area),
        "account_id": str(prop.account_id or ""),
        "active": "on" if prop.active else "",
        "note": prop.note,
    }


def property_form(request: HttpRequest, pk: int | None = None) -> HttpResponse:
    prop = get_object_or_404(Property, pk=pk) if pk else None
    errors: dict[str, str] = {}
    if request.method == "POST":
        values = {name: request.POST.get(name, "") for name in (*PROPERTY_FIELDS, "active")}
        try:
            area = parse_area(values["floor_area"])
            saved = save_property(
                prop,
                PropertyInput(
                    name=values["name"],
                    address=values["address"],
                    unit=values["unit"],
                    layout=values["layout"],
                    floor_area=area,
                    account_id=opt_int(values["account_id"]),
                    active=values["active"] == "on",
                    note=values["note"],
                ),
            )
        except ValueError as exc:
            errors = {"floor_area": str(exc)}
        except ValidationError as exc:
            errors = first_errors(exc)
        else:
            messages.success(request, "Byt uložen.")
            return redirect("rentals:property", saved.pk)
    else:
        values = property_values(prop)
    keep = {i for i in [opt_int(values.get("account_id"))] if i}
    return render(
        request,
        "rentals/property_form.html",
        {
            "nav": "properties",
            "property": prop,
            "values": values,
            "errors": errors,
            "accounts": account_choices(keep),
        },
    )


def property_detail(request: HttpRequest, pk: int) -> HttpResponse:
    """Karta bytu: aktuální smlouva se saldem, historie smluv, poslední pohyby."""
    today = timezone.localdate()
    prop = get_object_or_404(
        Property.objects.select_related("account").prefetch_related(leases_with_details()), pk=pk
    )
    lease = current_lease(prop, today)
    balance = None
    if lease and lease.status != LeaseStatus.DRAFT:
        ensure_charges(lease, today)
        balance = lease_balance(
            Lease.objects.prefetch_related(*BALANCE_PREFETCH).get(pk=lease.pk), today
        )
    leases = [
        {"lease": item, "tenants": tenant_names(item), "end": lease_end(item)}
        for item in prop.leases.all()
    ]
    repairs = prop.repairs.order_by("-reported_date", "-id")
    communications = prop.communications.select_related("tenant").order_by("-occurred_at")
    entries = (
        Entry.objects.filter(property=prop)
        .select_related("category", "account")
        .order_by("-date", "-id")[:20]
    )
    return render(
        request,
        "rentals/property_detail.html",
        {
            "nav": "properties",
            "property": prop,
            "lease": lease,
            "terms": terms_at(lease, today) if lease else None,
            "end": lease_end(lease) if lease else None,
            "tenants": [lt.tenant for lt in lease.lease_tenants.all()] if lease else [],
            "balance": balance,
            "leases": leases,
            "entries": entries,
            "today": today,
            "plans": plan_states(today, prop),
            "repairs": repairs[:20],
            "communications": communications[:20],
            "result": result_for(date(today.year, 1, 1), date(today.year, 12, 31), today, prop.pk),
        },
    )


# --- Nájemníci ---------------------------------------------------------------


def tenants(request: HttpRequest) -> HttpResponse:
    include_inactive = request.GET.get("inactive") == "1"
    qs = Tenant.objects.prefetch_related("lease_tenants__lease__property")
    if not include_inactive:
        qs = qs.filter(active=True)
    rows = sorted(qs, key=lambda t: czech_sort_key(t.name))
    return render(
        request,
        "rentals/tenants.html",
        {"nav": "tenants", "rows": rows, "include_inactive": include_inactive},
    )


def tenant_form(request: HttpRequest, pk: int | None = None) -> HttpResponse:
    tenant = get_object_or_404(Tenant, pk=pk) if pk else None
    form = TenantForm(request.POST or None, instance=tenant)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Nájemník uložen.")
        return redirect("rentals:tenants")
    title = f"Úprava nájemníka {tenant}" if tenant else "Nový nájemník"
    return form_page(request, form, nav="tenants", title=title, back=reverse("rentals:tenants"))


# --- Smlouvy a dodatky -------------------------------------------------------


def lease_url(lease: Lease) -> str:
    return reverse("rentals:lease", args=[lease.pk])


def lease_form(request: HttpRequest, pk: int | None = None) -> HttpResponse:
    if pk:
        lease = get_object_or_404(Lease.objects.select_related("property"), pk=pk)
    else:
        prop = get_object_or_404(Property, pk=opt_int(request.GET.get("property")) or 0)
        lease = Lease(property=prop, account=prop.account)
    form = LeaseForm(request.POST or None, instance=lease)
    if request.method == "POST" and form.is_valid():
        try:
            with transaction.atomic():
                saved = save_lease(
                    form.save(commit=False),
                    form.cleaned_data["main_tenant"],
                    list(form.cleaned_data["co_tenants"]),
                )
        except ValidationError as exc:
            add_errors(form, exc)
        else:
            messages.success(request, "Smlouva uložena.")
            return redirect("rentals:lease", saved.pk)
    back = lease_url(lease) if pk else reverse("rentals:property", args=[lease.property_id])
    title = f"Úprava smlouvy – {lease.property}" if pk else f"Nová smlouva – {lease.property}"
    return form_page(request, form, nav="properties", title=title, back=back)


def get_lease(pk: int) -> Lease:
    return get_object_or_404(Lease.objects.select_related("property", "account"), pk=pk)


def payment_account(lease: Lease) -> Any:
    """Výchozí účet pro platby: účet smlouvy, jinak účet bytu."""
    return lease.account or lease.property.account


def render_lease(request: HttpRequest, lease: Lease, **failed: forms.BaseForm) -> HttpResponse:
    """Detail smlouvy s předpisy, platbami a formuláři (failed = formulář s chybami)."""
    today = timezone.localdate()
    ensure_charges(lease, today)
    lease = (
        Lease.objects.select_related("property__account", "account")
        .prefetch_related(*BALANCE_PREFETCH, "lease_tenants__tenant")
        .get(pk=lease.pk)
    )
    balance = lease_balance(lease, today)
    terms = terms_at(lease, today)
    end = lease_end(lease)
    debt = max(balance.balance, 0)
    held = balance.deposit.held
    account = payment_account(lease)
    page_forms: dict[str, forms.BaseForm] = {
        "payment_form": PaymentForm(
            account=account,
            initial={"day": today, "amount": debt or terms.total_cents, "account": account},
        ),
        "refund_form": PayOutForm(
            account=account,
            initial={"day": today, "amount": max(-balance.balance, 0) or None, "account": account},
        ),
        "return_form": PayOutForm(
            account=account, initial={"day": today, "amount": held or None, "account": account}
        ),
        "offset_form": OffsetForm(initial={"day": today, "amount": min(held, debt) or None}),
        "end_form": EndLeaseForm(initial={"terminated_on": end or today}),
    }
    page_forms.update(failed)
    payments = sorted(lease.payments.all(), key=lambda p: (p.paid_on or today, p.pk), reverse=True)
    return render(
        request,
        "rentals/lease_detail.html",
        {
            "nav": "properties",
            "lease": lease,
            "lease_tenants": list(lease.lease_tenants.all()),
            "history": terms_history(lease),
            "terms": terms,
            "end": end,
            "today": today,
            "balance": balance,
            "charges": list(reversed(balance.charges)),
            "payments": payments,
            "suggestions": suggestions(lease, today),
            "attachments": attachments_block("lease", lease),
            "open_section": next(iter(failed), ""),
            **page_forms,
        },
    )


def lease_detail(request: HttpRequest, pk: int) -> HttpResponse:
    return render_lease(request, get_lease(pk))


def lease_action(
    request: HttpRequest,
    lease: Lease,
    form_name: str,
    form: forms.Form,
    action: Callable[[dict[str, Any]], object],
    message: str,
) -> HttpResponse:
    """Společný průběh akce na smlouvě: validace, služba, přesměrování / formulář s chybou."""
    if form.is_valid():
        try:
            action(form.cleaned_data)
        except ValidationError as exc:
            add_errors(form, exc)
        else:
            messages.success(request, message)
            return redirect("rentals:lease", lease.pk)
    return render_lease(request, lease, **{form_name: form})


@require_POST
def lease_end_view(request: HttpRequest, pk: int) -> HttpResponse:
    lease = get_lease(pk)
    today = timezone.localdate()
    return lease_action(
        request,
        lease,
        "end_form",
        EndLeaseForm(request.POST),
        lambda d: end_with_settlement(
            lease, d["terminated_on"], d["reason"], today=today, confirm=d["confirm"]
        ),
        "Smlouva ukončena.",
    )


@require_POST
def lease_payment(request: HttpRequest, pk: int) -> HttpResponse:
    lease = get_lease(pk)
    today = timezone.localdate()
    return lease_action(
        request,
        lease,
        "payment_form",
        PaymentForm(request.POST, account=payment_account(lease)),
        lambda d: record_payment(
            lease,
            day=d["day"],
            amount=d["amount"] or 0,
            deposit_amount=d["deposit_amount"] or 0,
            account_id=d["account"].pk,
            note=d["note"],
            today=today,
        ),
        "Platba zapsána.",
    )


@require_POST
def lease_payout(request: HttpRequest, pk: int, kind: str) -> HttpResponse:
    if kind not in (PaymentKind.REFUND, PaymentKind.DEPOSIT_RETURN):
        raise Http404
    lease = get_lease(pk)
    today = timezone.localdate()
    return lease_action(
        request,
        lease,
        "refund_form" if kind == PaymentKind.REFUND else "return_form",
        PayOutForm(request.POST, account=payment_account(lease)),
        lambda d: pay_out(
            lease,
            kind=kind,
            day=d["day"],
            amount=d["amount"],
            account_id=d["account"].pk,
            note=d["note"],
            today=today,
        ),
        "Vrácení zapsáno.",
    )


@require_POST
def lease_offset(request: HttpRequest, pk: int) -> HttpResponse:
    lease = get_lease(pk)
    return lease_action(
        request,
        lease,
        "offset_form",
        OffsetForm(request.POST),
        lambda d: offset_deposit(lease, day=d["day"], amount=d["amount"], note=d["note"]),
        "Jistota započtena na dluh.",
    )


@require_POST
def lease_link(request: HttpRequest, pk: int) -> HttpResponseRedirect:
    lease = get_lease(pk)
    entry = get_object_or_404(Entry, pk=opt_int(request.POST.get("entry")) or 0)
    kind = request.POST.get("kind") or PaymentKind.PAYMENT
    try:
        link_entry(lease, entry, kind)
    except ValidationError as exc:
        messages.error(request, " ".join(m for ms in exc.message_dict.values() for m in ms))
    else:
        messages.success(request, "Pohyb přiřazen ke smlouvě.")
    return redirect("rentals:lease", lease.pk)


@require_POST
def payment_unlink(request: HttpRequest, pk: int, payment_pk: int) -> HttpResponseRedirect:
    unlink(get_object_or_404(RentPayment, pk=payment_pk, lease_id=pk))
    messages.success(request, "Vazba odebrána – pohyb zůstal.")
    return redirect("rentals:lease", pk)


def charge_form(request: HttpRequest, pk: int, charge_pk: int | None = None) -> HttpResponse:
    lease = get_lease(pk)
    charge = (
        get_object_or_404(RentCharge, pk=charge_pk, lease=lease)
        if charge_pk
        else RentCharge(lease=lease, due_date=timezone.localdate())
    )
    form = ChargeForm(request.POST or None, instance=charge)
    if request.method == "POST" and form.is_valid():
        saved = form.save(commit=False)
        saved.manual = True
        saved.save()
        messages.success(request, "Předpis uložen.")
        return redirect("rentals:lease", lease.pk)
    title = "Úprava předpisu" if charge_pk else "Nový předpis"
    return form_page(
        request, form, nav="properties", title=f"{title} – {lease}", back=lease_url(lease)
    )


@require_POST
def charge_delete(request: HttpRequest, pk: int, charge_pk: int) -> HttpResponseRedirect:
    """Smaže ruční předpis; upravený měsíční předpis se tím vrátí na automatický."""
    charge = get_object_or_404(RentCharge, pk=charge_pk, lease_id=pk, manual=True)
    restored = charge.kind in MONTHLY_KINDS
    charge.delete()
    messages.success(request, "Předpis vrácen na automatický." if restored else "Předpis smazán.")
    return redirect("rentals:lease", pk)


def amendment_form(request: HttpRequest, lease_pk: int, pk: int | None = None) -> HttpResponse:
    lease = get_lease(lease_pk)
    amendment = (
        get_object_or_404(LeaseAmendment, pk=pk, lease=lease) if pk else LeaseAmendment(lease=lease)
    )
    form = AmendmentForm(request.POST or None, instance=amendment)
    if request.method == "POST" and form.is_valid():
        try:
            with transaction.atomic():
                save_amendment(form.save(commit=False))
        except ValidationError as exc:
            add_errors(form, exc)
        else:
            messages.success(request, "Dodatek uložen.")
            return redirect("rentals:lease", lease.pk)
    title = f"Úprava dodatku – {lease}" if pk else f"Nový dodatek – {lease}"
    return form_page(
        request,
        form,
        nav="properties",
        title=title,
        back=lease_url(lease),
        attachments=attachments_block("amendment", amendment) if pk else None,
    )


@require_POST
def amendment_delete(request: HttpRequest, lease_pk: int, pk: int) -> HttpResponseRedirect:
    amendment = get_object_or_404(LeaseAmendment, pk=pk, lease_id=lease_pk)
    amendment.delete()
    messages.success(request, "Dodatek smazán.")
    return redirect("rentals:lease", lease_pk)


@require_POST
def lease_delete(request: HttpRequest, pk: int) -> HttpResponseRedirect:
    """Smazat jde jen návrh smlouvy; platná a ukončená zůstávají v historii."""
    lease = get_object_or_404(Lease, pk=pk)
    if lease.status != LeaseStatus.DRAFT:
        messages.error(request, "Smazat jde jen návrh smlouvy.")
        return redirect("rentals:lease", pk)
    property_id = lease.property_id
    lease.delete()
    messages.success(request, "Návrh smlouvy smazán.")
    return redirect("rentals:property", property_id)
