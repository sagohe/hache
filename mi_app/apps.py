from django.apps import AppConfig


class HacheConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'mi_app' # nombre de la carpeta de la app
    verbose_name = "Hache"  # Nombre visible en Django Admin