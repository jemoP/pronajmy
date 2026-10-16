"""Nouzová správa dat přes Django admin. Čísla účtů se v seznamu nezobrazují."""

from django.contrib import admin

from .models import Account, Category, Entry


@admin.register(Account)
class AccountAdmin(admin.ModelAdmin[Account]):
    list_display = ["name", "kind", "active"]


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin[Category]):
    list_display = ["name", "kind", "code", "sort", "active"]
    list_filter = ["kind", "active"]


@admin.register(Entry)
class EntryAdmin(admin.ModelAdmin[Entry]):
    list_display = ["date", "kind", "amount_cents", "category", "property", "note"]
    list_filter = ["kind"]
    date_hierarchy = "date"
    raw_id_fields = ["account", "to_account", "category", "property"]
