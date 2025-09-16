
from django.contrib import admin
from django.urls import path, include
from mi_app.views import exportar_horarios_pdf, panel_inicio
from django.views.generic import RedirectView



urlpatterns = [
    path('', RedirectView.as_view(pattern_name='admin:index', permanent=False)),

    path('', include('mi_app.urls')),    
    path('admin/', admin.site.urls),
]


