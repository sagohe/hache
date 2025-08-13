from django.urls import path
from django.contrib.auth import views as auth_views
from . import views

urlpatterns = [
    # Panel del usuario
    path('', views.panel_usuario, name='panel_usuario'),

    # Auth propias
    path('accounts/login/', auth_views.LoginView.as_view(template_name='login.html'), name='login'),
    path('accounts/logout/', auth_views.LogoutView.as_view(), name='logout'),
    path('accounts/register/', views.register, name='register'),

    # Mi horario persistente
    path('mi-horario/', views.mi_horario, name='mi_horario'),
    path('generar/', views.generar_mi_horario, name='generar_mi_horario'),
    path('regenerar/', views.regenerar_mi_horario, name='regenerar_mi_horario'),

    # Snapshots
    path('guardar-horario/', views.guardar_horario, name='guardar_horario'),
    path('mis-horarios/', views.mis_horarios, name='mis_horarios'),
    path('cargar-horario/<int:horario_id>/', views.cargar_horario, name='cargar_horario'),
    path('exportar-horarios/', views.exportar_horarios_pdf, name='exportar_horarios_pdf'),
]


# path('sincronizar_calendario/<int:docente_id>/', views.sincronizar_calendario_view, name='sincronizar_calendario'),
# path('autorizar_google/<int:docente_id>/', views.autorizar_google, name='autorizar_google'),  # Añadido docente_id
# path('oauth2callback/', views.oauth2callback, name='oauth2callback'),