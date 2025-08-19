# mi_app/signals.py
from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import Institucion, DiaSemana

DIAS = [
    ("LU", "Lunes", 1),
    ("MA", "Martes", 2),
    ("MI", "Miercoles", 3),
    ("JU", "Jueves", 4),
    ("VI", "Viernes", 5),
    ("SA", "Sabado", 6),
    ("DO", "Domingo", 7),
]

@receiver(post_save, sender=Institucion)
def crear_dias_por_defecto(sender, instance, created, **kwargs):
    if not created:
        return
    for codigo, nombre, orden in DIAS:
        DiaSemana.objects.get_or_create(
            institucion=instance,
            codigo=codigo,
            defaults={"nombre": nombre, "orden": orden},
        )
