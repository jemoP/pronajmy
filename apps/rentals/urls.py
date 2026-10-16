from django.urls import path

from . import views

app_name = "rentals"
urlpatterns = [
    path("properties", views.properties, name="properties"),
    path("properties/new", views.property_form, name="property_new"),
    path("properties/<int:pk>/edit", views.property_form, name="property_edit"),
]
