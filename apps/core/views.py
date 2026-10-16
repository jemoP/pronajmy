from django.contrib.auth.decorators import login_not_required
from django.http import HttpRequest, JsonResponse


@login_not_required
def health(request: HttpRequest) -> JsonResponse:
    return JsonResponse({"status": "ok"})
