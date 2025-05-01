from django.urls import path
from . import views
from .views import sincronizar_calendario_view

urlpatterns = [
    path('', views.inicio, name='inicio'),  # Esta línea es la nueva
    path('horarios-docente/<int:docente_id>/', views.horario_docente, name='horario_docente'),
    path('exportar_horario/<int:docente_id>/', views.exportar_horarios_pdf, name='exportar_horarios_pdf'),
    path('autorizar_google/<int:docente_id>/', views.autorizar_google, name='autorizar_google'),  # Añadido docente_id
    path('oauth2callback/', views.oauth2callback, name='oauth2callback'),
    path('sincronizar_calendario/<int:docente_id>/', views.sincronizar_calendario_view, name='sincronizar_calendario'),
]
