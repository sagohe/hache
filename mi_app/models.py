from django.db import models
from django.core.exceptions import ValidationError
from datetime import time
from django.contrib.auth.models import User

# Jornadas y días (listas estáticas)
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
    ('Sabado', 'Sabado'),
    ('Domingo', 'Domingo'),
]

# ==========================
# Multi-tenant base
# ==========================
class Institucion(models.Model):
    nombre = models.CharField(max_length=150, unique=True)
    slug = models.SlugField(max_length=160, unique=True)

    DURACIONES_HORA = [(40, "40 min"), (45, "45 min"), (50, "50 min"), (60, "60 min")]
    duracion_hora_minutos = models.PositiveIntegerField(
        choices=DURACIONES_HORA,
        default=45,
        help_text=(
            "Cuántos minutos dura una 'hora institucional' en esta institución. "
            "Afecta a TODAS las asignaturas al convertir las horas totales de la asignatura "
            "en minutos totales y luego distribuirlos por semana."
        )
    )

    def __str__(self):
        return self.nombre


class PerfilUsuario(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='perfil')
    institucion = models.ForeignKey(Institucion, on_delete=models.CASCADE, related_name='usuarios')
    
    class Meta:
        verbose_name = "Perfil usuario"
        verbose_name_plural = "Perfil usuario" 

    def __str__(self):
        return f"{self.user.username} @ {self.institucion.nombre}"
    
class Descanso(models.Model):
    """
    Rango de tiempo no asignable creado por el usuario para un día específico.
    Se aplica por institución + usuario + día (FK a DiaSemana).
    """
    institucion = models.ForeignKey(Institucion, on_delete=models.CASCADE, related_name="descansos", null=False, blank=False)
    usuario = models.ForeignKey(User, on_delete=models.CASCADE, related_name="descansos")
    dia = models.ForeignKey('DiaSemana', on_delete=models.CASCADE, related_name="descansos")
    hora_inicio = models.TimeField()
    hora_fin = models.TimeField()
    nombre = models.CharField(max_length=80, blank=True, help_text="Opcional (ej. Almuerzo, Pausa)")
    color_hex = models.CharField(max_length=7, default="#FFE0E0", help_text="Color para pintar el descanso en la grilla")

    class Meta:
        ordering = ['dia__orden', 'hora_inicio']
        verbose_name = "Descanso"
        verbose_name_plural = "Descansos"
        indexes = [
            models.Index(fields=['institucion', 'usuario']),
            models.Index(fields=['institucion', 'usuario', 'dia']),
        ]

    def __str__(self):
        titulo = self.nombre or "Descanso"
        return f"{titulo} - {self.dia.nombre} {self.hora_inicio}-{self.hora_fin}"

    def clean(self):
        errors = {}

        if self.hora_inicio and self.hora_fin and self.hora_fin <= self.hora_inicio:
            errors['hora_fin'] = "La hora de fin debe ser mayor que la hora de inicio."

        # Si todavía no hay FK seteadas, no chequear solapes
        if not self.institucion_id or not self.usuario_id or not self.dia_id:
            if errors:
                raise ValidationError(errors)
            return

        if getattr(self.dia, 'institucion_id', None) and self.dia.institucion_id != self.institucion_id:
            errors['dia'] = "El día seleccionado no pertenece a tu institución."

        if self.hora_inicio and self.hora_fin:
            existe_solape = Descanso.objects.filter(
                institucion_id=self.institucion_id,
                usuario_id=self.usuario_id,
                dia_id=self.dia_id,
                hora_inicio__lt=self.hora_fin,
                hora_fin__gt=self.hora_inicio,
            ).exclude(pk=self.pk).exists()
            if existe_solape:
                msg = "Este descanso se solapa con otro ya existente."
                errors['hora_inicio'] = msg
                errors['hora_fin'] = msg

        if errors:
            raise ValidationError(errors)




# (Si usas este modelo, es global; si no, puedes eliminarlo)
class Jornadas(models.Model):
    nombre = models.CharField(max_length=50)

    def __str__(self):
        return self.nombre


# ==========================
# Modelos de dominio (aislados por institucion)
# ==========================
class Docente(models.Model):
    institucion = models.ForeignKey(Institucion, on_delete=models.CASCADE, related_name="docentes",null=False, blank=False)
    nombre = models.CharField(max_length=100)
    correo = models.EmailField()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['institucion', 'correo'], name='uniq_docente_correo_por_institucion'),
        ]

    def __str__(self):
        return self.nombre


class DiaSemana(models.Model):
    institucion = models.ForeignKey(Institucion, on_delete=models.CASCADE, related_name="dias",null=False, blank=False)
    codigo = models.CharField(max_length=2)
    nombre = models.CharField(max_length=20)
    orden = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['orden']
        constraints = [
            models.UniqueConstraint(fields=['institucion', 'codigo'], name='uniq_dia_codigo_por_institucion'),
            models.UniqueConstraint(fields=['institucion', 'nombre'], name='uniq_dia_nombre_por_institucion'),
        ]

    def __str__(self):
        return self.nombre


class Aula(models.Model):
    institucion = models.ForeignKey(Institucion, on_delete=models.CASCADE, related_name="aulas",null=False, blank=False)
    nombre = models.CharField(max_length=100)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['institucion', 'nombre'], name='uniq_aula_por_institucion'),
        ]

    def __str__(self):
        return self.nombre


class CarreraUniversitaria(models.Model):
    institucion = models.ForeignKey(Institucion, on_delete=models.CASCADE, related_name="carreras",null=False, blank=False)
    nombre = models.CharField(max_length=100)
    dias_clase = models.ManyToManyField(DiaSemana, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['institucion', 'nombre'], name='uniq_carrera_por_institucion'),
        ]

    def __str__(self):
        return self.nombre


class Semestre(models.Model):
    institucion = models.ForeignKey(Institucion, on_delete=models.CASCADE, related_name="semestres",null=False, blank=False)
    numero = models.PositiveIntegerField()
    carrera = models.ForeignKey(CarreraUniversitaria, on_delete=models.CASCADE, related_name="semestres")

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['institucion', 'carrera', 'numero'], name='uniq_semestre_por_institucion'),
        ]

    def __str__(self):
        return f"Semestre {self.numero} - {self.carrera.nombre}"


class Asignatura(models.Model):
    institucion = models.ForeignKey(Institucion, on_delete=models.CASCADE, related_name="asignaturas",null=False, blank=False)
    nombre = models.CharField(max_length=100)
    docentes = models.ManyToManyField(Docente, related_name="asignaturas_asignadas", blank=True)
    aula = models.ForeignKey(Aula, on_delete=models.SET_NULL, null=True, blank=True)
    jornada = models.CharField(max_length=10, choices=JORNADAS, default='Mañana')
    semestre = models.ForeignKey(Semestre, on_delete=models.CASCADE, null=True, blank=True)
    horas_totales = models.PositiveIntegerField(
    help_text="Horas totales de la asignatura en HORAS INSTITUCIONALES (según la duración de hora definida en la institución).")
    semanas = models.PositiveIntegerField(default=16,help_text="Cantidad de semanas en que se verá esta asignatura (≥ 1).")


    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['institucion', 'nombre', 'semestre'], name='uniq_asignatura_nombr_sem_por_institucion'),
        ]

    def __str__(self):
        sem_txt = f" ({self.semestre})" if self.semestre else ""
        return f"{self.nombre}{sem_txt} - {self.jornada} [{self.horas_totales} h inst., {self.semanas} sem]"


class NoDisponibilidad(models.Model):
    institucion = models.ForeignKey(Institucion, on_delete=models.CASCADE, related_name="no_disponibilidades",null=False, blank=False)
    docente = models.ForeignKey(Docente, on_delete=models.CASCADE, related_name="no_disponibilidades")
    # Guardas el día como string del choice (tu lógica actual lo usa así):
    dia = models.CharField(max_length=10, choices=DIAS_SEMANA)
    jornada = models.CharField(max_length=10, choices=JORNADAS)
    hora_inicio = models.TimeField()
    hora_fin = models.TimeField()

    def __str__(self):
        return f"{self.docente.nombre} NO disponible - {self.dia} ({self.jornada} {self.hora_inicio}-{self.hora_fin})"


class Horario(models.Model):
    institucion = models.ForeignKey(Institucion, on_delete=models.CASCADE, related_name="horarios",null=False, blank=False)
    usuario = models.ForeignKey(User, on_delete=models.CASCADE, related_name="horarios")
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
                raise ValidationError("La hora no coincide con la jornada (Mañana: 07:30 - 12:50).")
            elif self.jornada == 'Tarde' and not (time(13, 30) <= self.hora_inicio <= time(18, 15)):
                raise ValidationError("La hora no coincide con la jornada (Tarde: 13:30 - 18:15).")
            elif self.jornada == 'Noche' and not (time(18, 15) <= self.hora_inicio <= time(21, 45)):
                raise ValidationError("La hora no coincide con la jornada (Noche: 18:15 - 21:45).")

    def save(self, *args, **kwargs):
        if not self.dia_id or not self.hora_inicio or not self.hora_fin:
            raise ValidationError("Debes especificar el día, hora de inicio y fin.")

        conflictos = NoDisponibilidad.objects.filter(
            institucion=self.institucion,
            docente=self.docente,
            jornada=self.jornada,
            dia=self.dia.nombre,   # NoDisponibilidad.dia es string; DiaSemana.nombre coincide
            hora_inicio__lt=self.hora_fin,
            hora_fin__gt=self.hora_inicio
        )
        if conflictos.exists():
            raise ValidationError("El docente no está disponible en ese horario.")

        self.full_clean()
        super().save(*args, **kwargs)


class HorarioGuardado(models.Model):
    institucion = models.ForeignKey(Institucion, on_delete=models.CASCADE, related_name="horarios_guardados",null=False, blank=False)
    usuario = models.ForeignKey(User, on_delete=models.CASCADE, related_name="horarios_guardados")
    nombre = models.CharField(max_length=100, default="Horario sin nombre")
    datos = models.JSONField()
    fecha_creacion = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.nombre} - {self.usuario.username}"
