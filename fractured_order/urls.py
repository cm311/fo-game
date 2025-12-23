from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("FO_game.urls")),          # pages at /
    # API is already under /api/ inside FO_game.urls paths
]
