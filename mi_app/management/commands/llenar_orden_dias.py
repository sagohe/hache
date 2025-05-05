from django.core.management.base import BaseCommand
from mi_app.models import DiaSemana

class Command(BaseCommand):
    help = 'Asigna el campo orden a los días de la semana'

    def handle(self, *args, **kwargs):
        dias = [
            ('LU', 'Lunes'),
            ('MA', 'Martes'),
            ('MI', 'Miercoles'),
            ('JU', 'Jueves'),
            ('VI', 'Viernes'),
            ('SA', 'Sabado'),
            ('DO', 'Domingo'),
        ]
        for i, (codigo, nombre) in enumerate(dias, start=1):
            dia = DiaSemana.objects.filter(nombre=nombre).first()
            if dia:
                dia.orden = i
                dia.save()
                self.stdout.write(self.style.SUCCESS(f'{nombre} actualizado a orden {i}'))
            else:
                self.stdout.write(self.style.WARNING(f'{nombre} no encontrado'))
