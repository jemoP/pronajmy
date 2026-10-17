"""Nouzová správa pronájmů přes Django admin. Kontakty nájemníků se v seznamu nezobrazují."""

from django.contrib import admin

from .models import (
    Lease,
    LeaseAmendment,
    LeaseTenant,
    Property,
    RentCharge,
    RentPayment,
    Tenant,
)


@admin.register(Property)
class PropertyAdmin(admin.ModelAdmin[Property]):
    list_display = ["name", "address", "layout", "active"]


@admin.register(Tenant)
class TenantAdmin(admin.ModelAdmin[Tenant]):
    list_display = ["name", "active"]
    search_fields = ["name"]


class LeaseTenantInline(admin.TabularInline[LeaseTenant, Lease]):
    model = LeaseTenant
    extra = 0


class LeaseAmendmentInline(admin.StackedInline[LeaseAmendment, Lease]):
    model = LeaseAmendment
    extra = 0


@admin.register(Lease)
class LeaseAdmin(admin.ModelAdmin[Lease]):
    list_display = ["property", "number", "start_date", "end_date", "status"]
    list_filter = ["status", "property"]
    inlines = [LeaseTenantInline, LeaseAmendmentInline]


@admin.register(RentCharge)
class RentChargeAdmin(admin.ModelAdmin[RentCharge]):
    list_display = ["lease", "kind", "period", "due_date", "amount_cents", "manual"]
    list_filter = ["kind"]


@admin.register(RentPayment)
class RentPaymentAdmin(admin.ModelAdmin[RentPayment]):
    list_display = ["lease", "kind", "amount_cents", "entry"]
    raw_id_fields = ["entry"]
