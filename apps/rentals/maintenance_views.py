"""Stránky údržby: komunikace (P08), opravy (P09), revize (P10) a přílohy."""

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.http import FileResponse, Http404, HttpRequest, HttpResponse, HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.core.web import opt_int, safe_back
from apps.rentals.forms import (
    CommunicationForm,
    InspectionForm,
    InspectionPlanForm,
    InspectionTypeForm,
    RepairForm,
)
from apps.rentals.models import (
    OPEN_REPAIR,
    Attachment,
    Communication,
    Inspection,
    InspectionPlan,
    InspectionType,
    Lease,
    LeaseAmendment,
    Property,
    Repair,
    TenantRole,
    with_attachment_count,
)
from apps.rentals.services.attachments import add_attachment, attachments_block
from apps.rentals.services.leases import current_lease, leases_with_details
from apps.rentals.services.maintenance import (
    open_follow_ups,
    open_repairs,
    plan_states,
    save_inspection,
    save_repair,
)
from apps.rentals.views import add_errors, form_page

NAV = "maintenance"


def property_page(prop: Property, anchor: str) -> str:
    return f"{reverse('rentals:property', args=[prop.pk])}#{anchor}"


def deleted(request: HttpRequest, message: str, back: str) -> HttpResponseRedirect:
    messages.success(request, message)
    return redirect(back)


# --- Komunikace --------------------------------------------------------------


def communications(request: HttpRequest) -> HttpResponse:
    recent = with_attachment_count(Communication.objects.all()).select_related("property", "tenant")
    return render(
        request,
        "rentals/communications.html",
        {
            "nav": NAV,
            "tab": "communications",
            "open": open_follow_ups(),
            "recent": recent.order_by("-occurred_at")[:50],
            "today": timezone.localdate(),
        },
    )


def communication_form(
    request: HttpRequest, pk: int | None = None, property_pk: int | None = None
) -> HttpResponse:
    if pk:
        item = get_object_or_404(
            Communication.objects.select_related("property", "lease__property"), pk=pk
        )
        prop = item.property or (item.lease.property if item.lease else None)
        if prop is None:
            raise Http404
    else:
        prop = get_object_or_404(
            Property.objects.prefetch_related(leases_with_details()), pk=property_pk
        )
        lease = current_lease(prop, timezone.localdate())
        main = (
            next(
                (lt.tenant for lt in lease.lease_tenants.all() if lt.role == TenantRole.MAIN), None
            )
            if lease
            else None
        )
        item = Communication(property=prop, lease=lease, tenant=main, occurred_at=timezone.now())
    form = CommunicationForm(request.POST or None, instance=item, prop=prop)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Komunikace uložena.")
        return redirect(property_page(prop, "komunikace"))
    return form_page(
        request,
        form,
        nav=NAV,
        title=f"Komunikace – {prop}",
        back=property_page(prop, "komunikace"),
        attachments=attachments_block("communication", item) if pk else None,
        delete_url=reverse("rentals:communication_delete", args=[pk]) if pk else None,
        delete_confirm="Smazat záznam komunikace i s přílohami?",
    )


@require_POST
def communication_done(request: HttpRequest, pk: int) -> HttpResponseRedirect:
    item = get_object_or_404(Communication, pk=pk)
    item.follow_up_done = True
    item.save(update_fields=["follow_up_done"])
    messages.success(request, "Označeno jako vyřízené.")
    return redirect(safe_back(request.POST.get("back"), "/"))


@require_POST
def communication_delete(request: HttpRequest, pk: int) -> HttpResponseRedirect:
    item = get_object_or_404(Communication.objects.select_related("property"), pk=pk)
    back = (
        property_page(item.property, "komunikace")
        if item.property
        else reverse("rentals:communications")
    )
    item.delete()
    return deleted(request, "Komunikace smazána.", back)


# --- Opravy ------------------------------------------------------------------


def repairs(request: HttpRequest) -> HttpResponse:
    done = with_attachment_count(Repair.objects.exclude(status__in=OPEN_REPAIR)).select_related(
        "property"
    )
    return render(
        request,
        "rentals/repairs.html",
        {
            "nav": NAV,
            "tab": "repairs",
            "open": open_repairs(),
            "done": done.order_by("-reported_date", "-id")[:50],
        },
    )


def repair_form(
    request: HttpRequest, pk: int | None = None, property_pk: int | None = None
) -> HttpResponse:
    today = timezone.localdate()
    if pk:
        repair = get_object_or_404(Repair.objects.select_related("property__account"), pk=pk)
        prop = repair.property
    else:
        prop = get_object_or_404(
            Property.objects.select_related("account").prefetch_related(leases_with_details()),
            pk=property_pk,
        )
        repair = Repair(property=prop, reported_date=today, lease=current_lease(prop, today))
    form = RepairForm(request.POST or None, instance=repair, prop=prop)
    if request.method == "POST" and form.is_valid():
        account = form.cleaned_data.get("expense_account")
        try:
            with transaction.atomic():
                save_repair(
                    form.save(commit=False), account_id=account.pk if account else None, today=today
                )
        except ValidationError as exc:
            add_errors(form, exc)
        else:
            messages.success(request, "Oprava uložena.")
            return redirect(property_page(prop, "opravy"))
    return form_page(
        request,
        form,
        nav=NAV,
        title=f"Úprava opravy – {prop}" if pk else f"Nová oprava – {prop}",
        back=property_page(prop, "opravy"),
        attachments=attachments_block("repair", repair) if pk else None,
        entry=repair.entry if pk else None,
        delete_url=reverse("rentals:repair_delete", args=[pk]) if pk else None,
        delete_confirm="Smazat opravu i s přílohami? Zapsaný náklad v pohybech zůstane.",
    )


@require_POST
def repair_delete(request: HttpRequest, pk: int) -> HttpResponseRedirect:
    repair = get_object_or_404(Repair.objects.select_related("property"), pk=pk)
    back = property_page(repair.property, "opravy")
    repair.delete()
    return deleted(request, "Oprava smazána – náklad v pohybech zůstal.", back)


# --- Revize ------------------------------------------------------------------


def inspections(request: HttpRequest) -> HttpResponse:
    return render(
        request,
        "rentals/inspections.html",
        {"nav": NAV, "tab": "inspections", "states": plan_states(timezone.localdate())},
    )


def inspection_types(request: HttpRequest) -> HttpResponse:
    return render(
        request,
        "rentals/inspection_types.html",
        {"nav": "categories", "tab": "inspection_types", "types": InspectionType.objects.all()},
    )


def inspection_type_form(request: HttpRequest, pk: int | None = None) -> HttpResponse:
    item = get_object_or_404(InspectionType, pk=pk) if pk else None
    form = InspectionTypeForm(request.POST or None, instance=item)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Druh revize uložen.")
        return redirect("rentals:inspection_types")
    return form_page(
        request,
        form,
        nav="categories",
        title=f"Druh revize {item}" if item else "Nový druh revize",
        back=reverse("rentals:inspection_types"),
    )


def inspection_plan_form(
    request: HttpRequest, pk: int | None = None, property_pk: int | None = None
) -> HttpResponse:
    if pk:
        plan = get_object_or_404(InspectionPlan.objects.select_related("property"), pk=pk)
        prop = plan.property
    else:
        prop = get_object_or_404(Property, pk=property_pk)
        plan = InspectionPlan(property=prop)
    form = InspectionPlanForm(request.POST or None, instance=plan)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Plán revize uložen.")
        return redirect(property_page(prop, "revize"))
    can_delete = bool(pk) and not plan.inspections.exists()
    return form_page(
        request,
        form,
        nav=NAV,
        title=f"Plán revize – {prop}",
        back=property_page(prop, "revize"),
        delete_url=reverse("rentals:inspection_plan_delete", args=[pk]) if can_delete else None,
        delete_confirm="Smazat plán revize?",
    )


@require_POST
def inspection_plan_delete(request: HttpRequest, pk: int) -> HttpResponseRedirect:
    plan = get_object_or_404(InspectionPlan.objects.select_related("property"), pk=pk)
    back = property_page(plan.property, "revize")
    if plan.inspections.exists():
        messages.error(request, "Plán má zapsané revize – nejde smazat, můžeš ho deaktivovat.")
        return redirect(back)
    plan.delete()
    return deleted(request, "Plán revize smazán.", back)


def inspection_form(
    request: HttpRequest, pk: int | None = None, plan_pk: int | None = None
) -> HttpResponse:
    if pk:
        item = get_object_or_404(
            Inspection.objects.select_related("plan__property__account", "plan__type"), pk=pk
        )
        plan = item.plan
    else:
        plan = get_object_or_404(
            InspectionPlan.objects.select_related("property__account", "type"), pk=plan_pk
        )
        item = Inspection(plan=plan, done_date=timezone.localdate())
    prop = plan.property
    form = InspectionForm(request.POST or None, instance=item, prop=prop)
    if request.method == "POST" and form.is_valid():
        account = form.cleaned_data.get("expense_account")
        try:
            with transaction.atomic():
                save_inspection(form.save(commit=False), account_id=account.pk if account else None)
        except ValidationError as exc:
            add_errors(form, exc)
        else:
            messages.success(request, "Revize uložena.")
            return redirect(property_page(prop, "revize"))
    return form_page(
        request,
        form,
        nav=NAV,
        title=f"Revize {plan} – {prop}",
        back=property_page(prop, "revize"),
        attachments=attachments_block("inspection", item) if pk else None,
        entry=item.entry if pk else None,
        delete_url=reverse("rentals:inspection_delete", args=[pk]) if pk else None,
        delete_confirm="Smazat revizi i s přílohami? Zapsaný náklad v pohybech zůstane.",
    )


@require_POST
def inspection_delete(request: HttpRequest, pk: int) -> HttpResponseRedirect:
    item = get_object_or_404(Inspection.objects.select_related("plan__property"), pk=pk)
    back = property_page(item.plan.property, "revize")
    item.delete()
    return deleted(request, "Revize smazána – náklad v pohybech zůstal.", back)


# --- Přílohy -----------------------------------------------------------------

ATTACHMENT_MODELS: dict[str, type[models.Model]] = {
    "lease": Lease,
    "amendment": LeaseAmendment,
    "communication": Communication,
    "repair": Repair,
    "inspection": Inspection,
}


@require_POST
def attachment_upload(request: HttpRequest) -> HttpResponseRedirect:
    owner = request.POST.get("owner", "")
    model = ATTACHMENT_MODELS.get(owner)
    if model is None:
        raise Http404
    obj = get_object_or_404(model, pk=opt_int(request.POST.get("id")) or 0)
    back = safe_back(request.POST.get("back"), "/")
    files = request.FILES.getlist("file")
    if not files:
        messages.error(request, "Vyber soubor.")
        return redirect(back)
    saved = 0
    for upload in files:
        try:
            add_attachment(owner, obj, upload)
        except ValidationError as exc:
            text = " ".join(m for ms in exc.message_dict.values() for m in ms)
            messages.error(request, f"{upload.name}: {text}")
        else:
            saved += 1
    if saved:
        messages.success(request, f"Nahráno příloh: {saved}.")
    return redirect(back)


def attachment_download(request: HttpRequest, pk: int) -> FileResponse:
    attachment = get_object_or_404(Attachment, pk=pk)
    try:
        handle = attachment.file.open("rb")
    except FileNotFoundError as exc:
        raise Http404("Soubor přílohy chybí.") from exc
    # PDF a obrázky se zobrazí v prohlížeči; typ je ověřený při nahrání.
    response = FileResponse(
        handle, content_type=attachment.content_type, filename=attachment.original_name
    )
    response["Cache-Control"] = "private, no-store"
    response["X-Content-Type-Options"] = "nosniff"
    return response


@require_POST
def attachment_delete(request: HttpRequest, pk: int) -> HttpResponseRedirect:
    attachment = get_object_or_404(Attachment, pk=pk)
    attachment.delete()  # soubor smaže signál post_delete
    messages.success(request, "Příloha smazána.")
    return redirect(safe_back(request.POST.get("back"), "/"))
