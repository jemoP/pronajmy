from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_not_required
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import redirect


@login_not_required
def health(request: HttpRequest) -> JsonResponse:
    return JsonResponse({"status": "ok", "version": settings.APP_VERSION})


def demo_password_blocked(request: HttpRequest) -> HttpResponse:
    """V demu se heslo nemění – přihlášení demo/demo platí pro všechny (ZM-010)."""
    messages.warning(
        request, "V demu nejde měnit heslo – přihlášení demo / demo platí pro všechny."
    )
    return redirect("rentals:overview")
