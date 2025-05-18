from django.db import models
from django.core.exceptions import ValidationError
from datetime import time

JORNADAS = [
    ('Mañana', 'Mañana'),
    ('Tarde', 'Tarde'),
    ('Noche', 'Noche'),
]

DIAS_SEMANA = [
    ('Lunes', 'Lunes'),
    ('Martes', 'Martes'),
    ('Miercoles', 'Miercoles'),
    ('Jueves', 'Jueves'),
    ('Viernes', 'Viernes'),
    ('Sabado', 'Sa|bado'),
    ('Domingo', 'Domingo'),
]

class Jornadas(models.Model):
    nombre = models.CharField(max_length=50)  # Ejemplo: 'Mañana', 'Tarde', 'Noche' jornada


    def __str__(self):
        return self.nombre

class Docente(models.Model):
    nombre = models.CharField(max_length=100)
    correo = models.EmailField(unique=True)

    def __str__(self):
        return self.nombre

class NoDisponibilidad(models.Model):
    docente = models.ForeignKey(Docente, on_delete=models.CASCADE, related_name="no_disponibilidades")
    dia = models.CharField(max_length=10, choices=DIAS_SEMANA)
    jornada = models.CharField(max_length=10, choices=JORNADAS)
    hora_inicio = models.TimeField()
    hora_fin = models.TimeField()

    def __str__(self):
        return f"{self.docente.nombre} NO disponible - {self.dia} ({self.jornada} {self.hora_inicio}-{self.hora_fin})"


class Aula(models.Model):
    nombre = models.CharField(max_length=100, unique=True)

    def __str__(self):
        return self.nombre

class DiaSemana(models.Model):
    codigo = models.CharField(max_length=2, unique=True)
    nombre = models.CharField(max_length=20)
    orden = models.PositiveIntegerField(default=0)  # nuevo campo

    class Meta:
        ordering = ['orden']  # Django usará esto al hacer .all()

    def __str__(self):
        return self.nombre

class CarreraUniversitaria(models.Model):
    nombre = models.CharField(max_length=100)
    dias_clase = models.ManyToManyField(DiaSemana, blank=True)
    jornadas = models.ManyToManyField(Jornadas, related_name='carreras', blank=True)

    def __str__(self):
        return self.nombre

class Semestre(models.Model):
    numero = models.PositiveIntegerField()
    carrera = models.ForeignKey(CarreraUniversitaria, on_delete=models.CASCADE, related_name="semestres")

    def __str__(self):
        return f"Semestre {self.numero} - {self.carrera.nombre}"

class Asignatura(models.Model):
    nombre = models.CharField(max_length=100)
    docentes = models.ManyToManyField(Docente, related_name="asignaturas_asignadas", blank=True)
    aula = models.ForeignKey(Aula, on_delete=models.SET_NULL, null=True, blank=True)
    jornada = models.CharField(max_length=10, choices=JORNADAS, default='Mañana')
    intensidad_horaria = models.PositiveIntegerField(default=90)
    semestre = models.ForeignKey(Semestre, on_delete=models.CASCADE, null=True, blank=True)

    def get_intensidad_horas(self):
        return f"{self.intensidad_horaria / 60:.1f} horas"

    def asignar_docente(self, docente):
        if not docente.disponibilidades.exists():
            return f"El docente {docente.nombre} no tiene disponibilidad registrada."

        self.docentes.add(docente)
        return f"Docente {docente.nombre} asignado a {self.nombre}"

    def __str__(self):
        return f"{self.nombre} ({self.semestre}) - {self.jornada} ({self.get_intensidad_horas()} por semana )"

class Horario(models.Model):
    asignatura = models.ForeignKey(Asignatura, on_delete=models.CASCADE)
    docente = models.ForeignKey(Docente, on_delete=models.CASCADE)
    aula = models.ForeignKey(Aula, on_delete=models.CASCADE)
    dia = models.ForeignKey(DiaSemana, on_delete=models.CASCADE)
    jornada = models.CharField(max_length=10, choices=JORNADAS)
    hora_inicio = models.TimeField(blank=True, null=True)
    hora_fin = models.TimeField(blank=True, null=True)

    def clean(self):
        super().clean()
        if self.hora_inicio and self.hora_fin:
            if self.jornada == 'Mañana' and not (time(7, 30) <= self.hora_inicio <= time(12, 50)):
                raise ValidationError("La hora no coincide con la jornada que estás eligiendo (Mañana: 07:30 - 12:50).")
            elif self.jornada == 'Tarde' and not (time(13, 30) <= self.hora_inicio <= time(18, 15)):
                raise ValidationError("La hora no coincide con la jornada que estás eligiendo (Tarde: 13:30 - 18:15).")
            elif self.jornada == 'Noche' and not (time(18, 15) <= self.hora_inicio <= time(21, 45)):
                raise ValidationError("La hora no coincide con la jornada que estás eligiendo (Noche: 18:15 - 21:45).")

    def save(self, *args, **kwargs):
        if not self.dia or not self.hora_inicio or not self.hora_fin:
            raise ValidationError("Debes especificar el día, hora de inicio y fin.") 

        conflictos = NoDisponibilidad.objects.filter(
            docente=self.docente,
            jornada=self.jornada,
            dia=self.dia,
            hora_inicio__lt=self.hora_fin,
            hora_fin__gt=self.hora_inicio
        )

        if conflictos.exists():
            raise ValidationError("El docente no está disponible en ese horario.")

        self.full_clean()
        super().save(*args, **kwargs)

