from datetime import datetime, timedelta, time
from .models import NoDisponibilidad, Horario, Aula


def obtener_bloques_por_jornada(jornada):
    rangos = {
        'Mañana': (time(7, 30), time(12, 50)),
        'Tarde': (time(13, 30), time(18, 15)),
        'Noche': (time(18, 15), time(21, 45)),
    }
    return rangos.get(jornada, (None, None))

def esta_disponible(docente, jornada, dia, hora_inicio, hora_fin):
    return not NoDisponibilidad.objects.filter(
        docente=docente,
        jornada=jornada,
        dia=dia,
        hora_inicio__lt=hora_fin,
        hora_fin__gt=hora_inicio
    ).exists()

def aula_disponible(aula, dia, hora_inicio, hora_fin):
    return not Horario.objects.filter(
        aula=aula,
        dia=dia,
        hora_inicio__lt=hora_fin,
        hora_fin__gt=hora_inicio
    ).exists()

def docente_disponible(docente, dia, hora_inicio, hora_fin):
    return not Horario.objects.filter(
        docente=docente,
        dia=dia,
        hora_inicio__lt=hora_fin,
        hora_fin__gt=hora_inicio
    ).exists()

def hay_conflicto_estudiantes(asignatura, dia, hora_inicio, hora_fin):
    return not Horario.objects.filter(
        asignatura__semestre=asignatura.semestre,
        asignatura__semestre__carrera=asignatura.semestre.carrera,
        jornada=asignatura.jornada,
        dia=dia,
        hora_inicio__lt=hora_fin,
        hora_fin__gt=hora_inicio
    ).exclude(
        asignatura=asignatura
    ).exists()
    
def docente_esta_disponible(docente, jornada, dia, hora_inicio, hora_fin):
    sin_no_disponibilidad = not NoDisponibilidad.objects.filter(
        docente=docente,
        jornada=jornada,
        dia=dia,
        hora_inicio__lt=hora_fin,
        hora_fin__gt=hora_inicio
    ).exists()

    sin_otra_clase = not Horario.objects.filter(
        docente=docente,
        dia=dia,
        hora_inicio__lt=hora_fin,
        hora_fin__gt=hora_inicio
    ).exists()

    return sin_no_disponibilidad and sin_otra_clase

def puede_asignar_horario(docente, aula, asignatura, dia, jornada, hora_inicio, hora_fin):
    return (
        docente_esta_disponible(docente, jornada, dia, hora_inicio, hora_fin) and
        aula_disponible(aula, dia, hora_inicio, hora_fin) and
        hay_conflicto_estudiantes(asignatura, dia, hora_inicio, hora_fin) and
        not Horario.objects.filter(asignatura=asignatura, dia=dia).exists()
    )

def obtener_dias_disponibles_carrera(carrera):
    """
    Retorna una lista de nombres de días disponibles para la carrera.
    """
    return list(carrera.dias_clase.values_list('nombre', flat=True))

def asignar_horario_automatico(asignatura):
    jornada = asignatura.jornada
    semestre = asignatura.semestre

    if not semestre:
        return False

    carrera = semestre.carrera
    dias_validos = list(carrera.dias_clase.values_list('nombre', flat=True))
    intensidad = asignatura.intensidad_horaria  # en minutos

    docente = asignatura.docentes.first()

    if not docente:
        return False

    # Rangos por jornada
    rangos_jornada = {
        'Mañana': (time(7, 30), time(12, 50)),
        'Tarde': (time(13, 30), time(18, 15)),
        'Noche': (time(18, 15), time(21, 45)),
    }

    if jornada not in rangos_jornada:
        return False

    inicio_jornada, fin_jornada = rangos_jornada[jornada]
    duracion_requerida = timedelta(minutes=intensidad)
    bloques = 15  # tamaño del bloque en minutos

    for dia in dias_validos:
        hora_actual = datetime.combine(datetime.today(), inicio_jornada)
        hora_fin_jornada = datetime.combine(datetime.today(), fin_jornada)

        while hora_actual + duracion_requerida <= hora_fin_jornada:
            hora_fin = hora_actual + duracion_requerida
            hora_inicio_time = hora_actual.time()
            hora_fin_time = hora_fin.time()

            aula_asignada = asignatura.aula

            # Si no tiene aula asignada, buscar una disponible
            if not aula_asignada:
                aulas_disponibles = Aula.objects.all()
                for aula in aulas_disponibles:
                    if puede_asignar_horario(docente, aula, asignatura, dia, jornada, hora_inicio_time, hora_fin_time):
                        aula_asignada = aula
                        break
            else:
                if not puede_asignar_horario(docente, aula_asignada, asignatura, dia, jornada, hora_inicio_time, hora_fin_time):
                    aula_asignada = None

            if aula_asignada:
                Horario.objects.create(
                    asignatura=asignatura,
                    docente=docente,
                    aula=aula_asignada,
                    dia=dia,
                    jornada=jornada,
                    hora_inicio=hora_inicio_time,
                    hora_fin=hora_fin_time
                )
                return True

            hora_actual += timedelta(minutes=bloques)

    return False