from datetime import date

from django.contrib.auth.decorators import login_not_required
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import render
from django.utils import timezone

from apps.money.models import Entry
from apps.money.services.accounts import list_accounts
from apps.money.services.entries import result_for


def home(request: HttpRequest) -> HttpResponse:
    """Přehled: zůstatky účtů a výsledek za letošní rok."""
    today = timezone.localdate()
    accounts = list_accounts(today)
    return render(
        request,
        "core/home.html",
        {
            "nav": "home",
            "today": today,
            "accounts": accounts,
            "total": sum(a.balance_cents for a in accounts),
            "result": result_for(date(today.year, 1, 1), date(today.year, 12, 31), today),
            "planned_count": Entry.objects.filter(date__gt=today).count(),
        },
    )


@login_not_required
def health(request: HttpRequest) -> JsonResponse:
    return JsonResponse({"status": "ok"})
