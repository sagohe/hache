from django.core.management.base import BaseCommand
from mi_app.models import DiaSemana, Asignatura, Horario

class Command(BaseCommand):
    help = 'Asigna el campo orden a los días de la semana y corrige los campos "dia" en Asignatura y Horario'

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
        
        # Actualizar el orden de los días de la semana
        for i, (codigo, nombre) in enumerate(dias, start=1):
            dia = DiaSemana.objects.filter(nombre=nombre).first()
            if dia:
                dia.orden = i
                dia.save()
                self.stdout.write(self.style.SUCCESS(f'{nombre} actualizado a orden {i}'))
            else:
                self.stdout.write(self.style.WARNING(f'{nombre} no encontrado'))

        # Corregir el campo 'dia' de Asignatura con instancias válidas
        for asignatura in Asignatura.objects.all():
            if asignatura.dia and isinstance(asignatura.dia, str):
                try:
                    dia_instancia = DiaSemana.objects.get(nombre__iexact=asignatura.dia.strip())
                    asignatura.dia = dia_instancia
                    asignatura.save()
                    self.stdout.write(self.style.SUCCESS(f"Asignatura '{asignatura.nombre}' actualizada."))
                except DiaSemana.DoesNotExist:
                    self.stdout.write(self.style.ERROR(f"Día '{asignatura.dia}' no encontrado para '{asignatura.nombre}'"))

        # Corregir el campo 'dia' de Horario con instancias válidas
        for horario in Horario.objects.all():
            if horario.dia and hasattr(horario.dia, 'nombre'):
                try:
                    dia_instancia = DiaSemana.objects.get(nombre__iexact=horario.dia.nombre.strip())
                    horario.dia = dia_instancia
                    horario.save()
                    self.stdout.write(self.style.SUCCESS(f"Horario de '{horario.asignatura.nombre}' actualizado."))
                except DiaSemana.DoesNotExist:
                    self.stdout.write(self.style.ERROR(f"Día '{horario.dia.nombre}' no encontrado para '{horario.asignatura.nombre}'"))
