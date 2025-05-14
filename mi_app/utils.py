from datetime import datetime, timedelta, time
from .models import NoDisponibilidad, Horario, Aula, DiaSemana


def obtener_bloques_por_jornada(jornada):
    rangos = {
        'Mañana': (time(7, 30), time(12, 50)),
        'Tarde': (time(13, 30), time(18, 15)),
        'Noche': (time(18, 15), time(21, 45)),
    }
    return rangos.get(jornada, (None, None))

def aula_disponible_en_memoria(aula, dia, hora_inicio, hora_fin, horarios):
    for h in horarios:
        if h.aula == aula and h.dia == dia and h.hora_inicio < hora_fin and h.hora_fin > hora_inicio:
            return False
    return True

def hay_conflicto_estudiantes_mem(asignatura, dia, hora_inicio, hora_fin, horarios):
    for h in horarios:
        if (
            h.asignatura.semestre == asignatura.semestre and
            h.asignatura != asignatura and
            h.dia == dia and
            h.jornada == asignatura.jornada and
            h.hora_inicio < hora_fin and
            h.hora_fin > hora_inicio
        ):
            return True
    return False

def docente_esta_disponible_mem(docente, jornada, dia, hora_inicio, hora_fin, horarios, no_disponibilidades):
    for nd in no_disponibilidades:
        if nd.docente == docente and nd.dia == dia and nd.jornada == jornada and nd.hora_inicio < hora_fin and nd.hora_fin > hora_inicio:
            return False
    for h in horarios:
        if h.docente == docente and h.dia == dia and h.hora_inicio < hora_fin and h.hora_fin > hora_inicio:
            return False
    return True


def puede_asignar_horario_mem(docente, aula, asignatura, dia, jornada, hora_inicio, hora_fin, horarios, no_disponibilidades):
    return (
        docente_esta_disponible_mem(docente, jornada, dia, hora_inicio, hora_fin, horarios, no_disponibilidades) and
        aula_disponible_en_memoria(aula, dia, hora_inicio, hora_fin, horarios) and
        not hay_conflicto_estudiantes_mem(asignatura, dia, hora_inicio, hora_fin, horarios) and
        all(h.asignatura != asignatura or h.dia != dia for h in horarios)
    )

def obtener_dias_disponibles_carrera(carrera):
    """
    Retorna una lista de nombres de días disponibles para la carrera.
    """
    return list(carrera.dias_clase.values_list('nombre', flat=True))

def asignar_horario_automatico(asignatura, horarios, no_disponibilidades):
    jornada = asignatura.jornada
    semestre = asignatura.semestre

    if not semestre:
        return False

    carrera = semestre.carrera
    dias_validos = list(carrera.dias_clase.all())  # instancias de DiaSemana
    intensidad = asignatura.intensidad_horaria  # en minutos

    docente = asignatura.docentes.first()
    if not docente:
        return False

    rangos_jornada = {
        'Mañana': (time(7, 30), time(12, 50)),
        'Tarde': (time(13, 30), time(18, 15)),
        'Noche': (time(18, 15), time(21, 45)),
    }

    if jornada not in rangos_jornada:
        return False

    inicio_jornada, fin_jornada = rangos_jornada[jornada]
    duracion_requerida = timedelta(minutes=intensidad)
    bloques = 15  # bloques de 15 minutos

    aulas = list(Aula.objects.all())
    horarios_para_guardar = []

    for dia in dias_validos:
        hora_actual = datetime.combine(datetime.today(), inicio_jornada)
        hora_fin_jornada = datetime.combine(datetime.today(), fin_jornada)

        while hora_actual + duracion_requerida <= hora_fin_jornada:
            hora_fin = hora_actual + duracion_requerida
            hora_inicio_time = hora_actual.time()
            hora_fin_time = hora_fin.time()

            aula_asignada = asignatura.aula

            if not aula_asignada:
                for aula in aulas:
                    if puede_asignar_horario_mem(docente, aula, asignatura, dia, jornada, hora_inicio_time, hora_fin_time, horarios, no_disponibilidades):
                        aula_asignada = aula
                        break
            else:
                if not puede_asignar_horario_mem(docente, aula_asignada, asignatura, dia, jornada, hora_inicio_time, hora_fin_time, horarios, no_disponibilidades):
                    aula_asignada = None

            if aula_asignada:
                nuevo_horario = Horario(
                    asignatura=asignatura,
                    docente=docente,
                    aula=aula_asignada,
                    dia=dia,
                    jornada=jornada,
                    hora_inicio=hora_inicio_time,
                    hora_fin=hora_fin_time
                )
                horarios_para_guardar.append(nuevo_horario)
                # ✅ Solo se crea uno, salimos de los bucles
                Horario.objects.bulk_create(horarios_para_guardar)
                horarios.extend(horarios_para_guardar)
                return True  # asignación exitosa

            hora_actual += timedelta(minutes=bloques)

    return False  # No se pudo asignar
