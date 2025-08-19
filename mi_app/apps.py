from django.apps import AppConfig

class MiAppConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'mi_app'
    verbose_name = 'Hache'

    def ready(self):
        # importa tus señales al arrancar la app
        import mi_app.signals  # asegúrate que el archivo se llame signals.py
