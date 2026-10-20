from django.conf import settings
from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path

from apps.core.views import demo_password_blocked

urlpatterns = [
    path("login/", auth_views.LoginView.as_view(), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path(
        "password/",
        # V demu se heslo nemění (ZM-010).
        demo_password_blocked if settings.DEMO_MODE else auth_views.PasswordChangeView.as_view(),
        name="password_change",
    ),
    path(
        "password/done/", auth_views.PasswordChangeDoneView.as_view(), name="password_change_done"
    ),
    path("admin/", admin.site.urls),
    path("", include("apps.money.urls")),
    path("", include("apps.rentals.urls")),
    path("", include("apps.core.urls")),
]
