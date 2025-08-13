from django.urls import path
from django.contrib.auth import views as auth_views
from . import views

urlpatterns = [

    # Auth propias
    path('accounts/login/', auth_views.LoginView.as_view(template_name='login.html'), name='login'),
    path('accounts/logout/', auth_views.LogoutView.as_view(), name='logout'),
    path('accounts/register/', views.register, name='register'),
    path('exportar-horarios/', views.exportar_horarios_pdf, name='exportar_horarios_pdf'),
]


# path('sincronizar_calendario/<int:docente_id>/', views.sincronizar_calendario_view, name='sincronizar_calendario'),
# path('autorizar_google/<int:docente_id>/', views.autorizar_google, name='autorizar_google'),  # Añadido docente_id
# path('oauth2callback/', views.oauth2callback, name='oauth2callback'),