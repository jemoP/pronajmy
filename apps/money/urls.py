from django.urls import path

from . import payable_views as pv
from . import views

app_name = "money"
urlpatterns = [
    path("entries", views.entries, name="entries"),
    path("entries/export.<str:fmt>", views.entries_export, name="entries_export"),
    path("entries/<int:pk>/edit", views.entry_edit, name="entry_edit"),
    path("entries/<int:pk>/delete", views.entry_delete, name="entry_delete"),
    path("accounts", views.accounts, name="accounts"),
    path("accounts/new", views.account_form, name="account_new"),
    path("accounts/<int:pk>/edit", views.account_form, name="account_edit"),
    path("categories", views.categories, name="categories"),
    path("categories/<int:pk>/edit", views.category_edit, name="category_edit"),
    path("categories/<int:pk>/delete", views.category_delete, name="category_delete"),
    # Platby dodavatelům (ZM-006)
    path("payables", pv.payables, name="payables"),
    path("payables/new", pv.payable_form, name="payable_new"),
    path("payables/pay", pv.pay, name="payables_pay"),
    path("payables/<int:pk>", pv.payable_detail, name="payable"),
    path("payables/<int:pk>/edit", pv.payable_form, name="payable_edit"),
    path("payables/<int:pk>/change", pv.payable_change, name="payable_change"),
    path("payables/<int:pk>/delete", pv.payable_delete, name="payable_delete"),
    path("dues/<int:pk>/skip", pv.due_skip, name="due_skip"),
    path("dues/<int:pk>/amount", pv.due_amount_view, name="due_amount"),
]
