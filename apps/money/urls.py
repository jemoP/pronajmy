from django.urls import path

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
]
