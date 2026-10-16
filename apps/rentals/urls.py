from django.urls import path

from . import views

app_name = "rentals"
urlpatterns = [
    path("", views.overview, name="overview"),
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
]
