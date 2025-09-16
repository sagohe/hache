from django.contrib import admin
from django.urls import path, include
from django.views.generic import RedirectView



urlpatterns = [
    # root -> register (landing para nuevos usuarios)
    path('', RedirectView.as_view(pattern_name='register', permanent=False)),

    # rutas de la app (login, register, etc.)
    path('', include('mi_app.urls')),

    # admin al final
    path('admin/', admin.site.urls),
]