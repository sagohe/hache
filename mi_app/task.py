from mi_proyecto.celery import shared_task
from django.contrib.auth import get_user_model
from .models import Institucion
from .generar_horarios import generar_horarios_view

@shared_task
def generar_horarios_task(user_id, institucion_id=None):
    User = get_user_model()
    user = User.objects.get(id=user_id)
    inst = Institucion.objects.get(id=institucion_id) if institucion_id else None

    class DummyRequest:
        def __init__(self, user):
            self.user = user
            self.GET = {}

    dummy_request = DummyRequest(user)
    return generar_horarios_view(dummy_request, None)