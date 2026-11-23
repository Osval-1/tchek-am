from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("tchekam.core.urls")),
    path("", include("tchekam.messaging.urls")),
]
