from django.urls import path

from . import maintenance_views as mv
from . import report_views, views

app_name = "rentals"
urlpatterns = [
    path("", views.overview, name="overview"),
    path("report", report_views.report, name="report"),
    path("report/export.<str:fmt>", report_views.report_export, name="report_export"),
    path("properties", views.properties, name="properties"),
    path("properties/new", views.property_form, name="property_new"),
    path("properties/<int:pk>", views.property_detail, name="property"),
    path("properties/<int:pk>/edit", views.property_form, name="property_edit"),
    path("tenants", views.tenants, name="tenants"),
    path("tenants/new", views.tenant_form, name="tenant_new"),
    path("tenants/<int:pk>/edit", views.tenant_form, name="tenant_edit"),
    path("leases/new", views.lease_form, name="lease_new"),
    path("leases/<int:pk>", views.lease_detail, name="lease"),
    path("leases/<int:pk>/edit", views.lease_form, name="lease_edit"),
    path("leases/<int:pk>/delete", views.lease_delete, name="lease_delete"),
    path("leases/<int:pk>/end", views.lease_end_view, name="lease_end"),
    path("leases/<int:pk>/payment", views.lease_payment, name="lease_payment"),
    path("leases/<int:pk>/payout/<str:kind>", views.lease_payout, name="lease_payout"),
    path("leases/<int:pk>/offset", views.lease_offset, name="lease_offset"),
    path("leases/<int:pk>/link", views.lease_link, name="lease_link"),
    path(
        "leases/<int:pk>/payments/<int:payment_pk>/unlink",
        views.payment_unlink,
        name="payment_unlink",
    ),
    path("leases/<int:pk>/charges/new", views.charge_form, name="charge_new"),
    path("leases/<int:pk>/charges/<int:charge_pk>/edit", views.charge_form, name="charge_edit"),
    path(
        "leases/<int:pk>/charges/<int:charge_pk>/delete", views.charge_delete, name="charge_delete"
    ),
    path("leases/<int:lease_pk>/amendments/new", views.amendment_form, name="amendment_new"),
    path(
        "leases/<int:lease_pk>/amendments/<int:pk>/edit",
        views.amendment_form,
        name="amendment_edit",
    ),
    path(
        "leases/<int:lease_pk>/amendments/<int:pk>/delete",
        views.amendment_delete,
        name="amendment_delete",
    ),
    # Údržba
    path("maintenance/repairs", mv.repairs, name="repairs"),
    path("maintenance/inspections", mv.inspections, name="inspections"),
    path("maintenance/communications", mv.communications, name="communications"),
    path("properties/<int:property_pk>/repairs/new", mv.repair_form, name="repair_new"),
    path("repairs/<int:pk>/edit", mv.repair_form, name="repair_edit"),
    path("repairs/<int:pk>/delete", mv.repair_delete, name="repair_delete"),
    path(
        "properties/<int:property_pk>/communications/new",
        mv.communication_form,
        name="communication_new",
    ),
    path("communications/<int:pk>/edit", mv.communication_form, name="communication_edit"),
    path("communications/<int:pk>/done", mv.communication_done, name="communication_done"),
    path("communications/<int:pk>/delete", mv.communication_delete, name="communication_delete"),
    path("inspection-types", mv.inspection_types, name="inspection_types"),
    path("inspection-types/new", mv.inspection_type_form, name="inspection_type_new"),
    path("inspection-types/<int:pk>/edit", mv.inspection_type_form, name="inspection_type_edit"),
    path(
        "properties/<int:property_pk>/inspection-plans/new",
        mv.inspection_plan_form,
        name="inspection_plan_new",
    ),
    path("inspection-plans/<int:pk>/edit", mv.inspection_plan_form, name="inspection_plan_edit"),
    path(
        "inspection-plans/<int:pk>/delete",
        mv.inspection_plan_delete,
        name="inspection_plan_delete",
    ),
    path(
        "inspection-plans/<int:plan_pk>/inspections/new",
        mv.inspection_form,
        name="inspection_new",
    ),
    path("inspections/<int:pk>/edit", mv.inspection_form, name="inspection_edit"),
    path("inspections/<int:pk>/delete", mv.inspection_delete, name="inspection_delete"),
    # Přílohy
    path("attachments/upload", mv.attachment_upload, name="attachment_upload"),
    path("attachments/<int:pk>", mv.attachment_download, name="attachment"),
    path("attachments/<int:pk>/delete", mv.attachment_delete, name="attachment_delete"),
]
