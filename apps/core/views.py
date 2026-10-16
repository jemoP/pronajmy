from django.contrib.auth.decorators import login_not_required
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import render


def home(request: HttpRequest) -> HttpResponse:
    return render(request, "core/home.html", {"nav": "home"})


@login_not_required
def health(request: HttpRequest) -> JsonResponse:
    return JsonResponse({"status": "ok"})
