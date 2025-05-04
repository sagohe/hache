"""mi_proyecto URL Configuration

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/3.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include
from mi_app.views import exportar_horarios_pdf, panel_inicio



urlpatterns = [
    path('admin/', admin.site.urls),
    path('', panel_inicio, name='panel_inicio'),
    path("exportar-horarios/", exportar_horarios_pdf, name="exportar_horarios_pdf"),
    path('', include('mi_app.urls')),
]


