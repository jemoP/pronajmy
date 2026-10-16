"""Nouzová správa dat přes Django admin."""

from django.contrib import admin

from .models import Property


@admin.register(Property)
class PropertyAdmin(admin.ModelAdmin[Property]):
    list_display = ["name", "address", "layout", "active"]
