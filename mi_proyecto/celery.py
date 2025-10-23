import os
from celery import Celery

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'mi_proyecto.settings')

app = Celery('mi_proyecto')
app.config_from_object('django.conf:settings', namespace='CELERY')
app.autodiscover_tasks()