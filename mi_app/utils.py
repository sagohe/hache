from datetime import datetime, timedelta, time
from .models import NoDisponibilidad, Horario, Aula, Descanso


def obtener_bloques_por_jornada(jornada):
    rangos = {
        'Mañana': (time(7, 30), time(12, 50)),
        'Tarde': (time(13, 30), time(18, 15)),
        'Noche': (time(18, 15), time(21, 45)),
    }
    return rangos.get(jornada, (None, None))

def hay_descanso_mem(dia, hora_inicio, hora_fin, descansos):
    """
    True si (hora_inicio, hora_fin) pisa algún descanso del usuario para ese día.
    Robusto: compara por ID de DiaSemana y, si no hay, por nombre.
    """
    dia_id = getattr(dia, "id", None)
    dia_nombre = getattr(dia, "nombre", None)

    for d in descansos:
        # Coincidencia por FK id o por nombre (fallback)
        mismo_dia = (
            (dia_id is not None and d.dia_id == dia_id) or
            (dia_id is None and dia_nombre is not None and getattr(d.dia, "nombre", None) == dia_nombre)
        )
        if not mismo_dia:
            continue

        # Solape estricto (cubre casos iguales a los bordes)
        if d.hora_inicio < hora_fin and d.hora_fin > hora_inicio:
            return True
    return False



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
    # choques con no disponibilidad
    for nd in no_disponibilidades:
        if (
            nd.docente == docente and
            nd.dia == dia.nombre and   # DiaSemana es global; NoDisponibilidad guarda string de día
            nd.jornada == jornada and
            nd.hora_inicio < hora_fin and
            nd.hora_fin > hora_inicio
        ):
            return False

    # choques con otros horarios del mismo docente
    for h in horarios:
        if (
            h.docente == docente and
            h.dia == dia and
            h.hora_inicio < hora_fin and
            h.hora_fin > hora_inicio
        ):
            return False

    return True


def puede_asignar_horario_mem(docente, aula, asignatura, dia, jornada, hora_inicio, hora_fin, horarios, no_disponibilidades,descansos=None):
    descansos = descansos or []
    return (
        docente_esta_disponible_mem(docente, jornada, dia, hora_inicio, hora_fin, horarios, no_disponibilidades) and
        aula_disponible_en_memoria(aula, dia, hora_inicio, hora_fin, horarios) and
        not hay_conflicto_estudiantes_mem(asignatura, dia, hora_inicio, hora_fin, horarios) and
        all(h.asignatura != asignatura or h.dia != dia for h in horarios) and
        not hay_descanso_mem(dia, hora_inicio, hora_fin, descansos)
    )


def asignar_horario_automatico(
    asignatura,
    horarios,
    no_disponibilidades,
    descansos=None,          # ← nuevo parámetro
    usuario=None,
    institucion=None,
    con_motivo=False
):
    """
    Si con_motivo=True -> devuelve (ok, motivo). Si con_motivo=False -> solo True/False.
    Todo se genera en el contexto del 'usuario' y/o 'institucion' (aulas, etc. del dueño).
    Respeta los 'descansos' (lista de objetos Descanso del usuario) para NO asignar dentro de esos rangos.
    """
    def _ret(ok, motivo=""):
        return (ok, motivo) if con_motivo else ok

    from datetime import datetime, timedelta, time  # por si no están arriba
    descansos = list(descansos or [])

    jornada = asignatura.jornada
    semestre = asignatura.semestre
    if not semestre:
        return _ret(False, "Sin semestre")

    carrera = semestre.carrera
    dias_validos = list(carrera.dias_clase.all())
    if not dias_validos:
        return _ret(False, "Carrera sin días de clase")

    intensidad = asignatura.intensidad_horaria
    docente = asignatura.docentes.first()
    if not docente:
        return _ret(False, "Asignatura sin docente")

    rangos_jornada = {
        'Mañana': (time(7, 30), time(12, 50)),
        'Tarde':  (time(13, 30), time(18, 15)),
        'Noche':  (time(18, 15), time(21, 45)),
    }
    if jornada not in rangos_jornada:
        return _ret(False, f"Jornada inválida: {jornada}")

    inicio_jornada, fin_jornada = rangos_jornada[jornada]
    duracion_requerida = timedelta(minutes=intensidad)

    if datetime.combine(datetime.today(), inicio_jornada) + duracion_requerida > datetime.combine(datetime.today(), fin_jornada):
        return _ret(False, "Intensidad no cabe en la jornada")

    # 👉 Aulas filtradas por institucion (preferente) o por usuario
    aulas_qs = Aula.objects.all()
    if institucion is not None:
        aulas_qs = aulas_qs.filter(institucion=institucion)
    elif usuario is not None:
        aulas_qs = aulas_qs.filter(usuario=usuario)
    aulas = list(aulas_qs)

    # Si la asignatura trae aula, validar que pertenezca al contexto
    aula_prefijada = asignatura.aula
    if aula_prefijada:
        if institucion is not None and getattr(aula_prefijada, "institucion_id", None) != getattr(institucion, "id", None):
            aula_prefijada = None
        elif institucion is None and usuario is not None and getattr(aula_prefijada, "usuario_id", None) != getattr(usuario, "id", None):
            aula_prefijada = None

    if not aulas and not aula_prefijada:
        return _ret(False, "No hay aulas disponibles")

    bloques = 15
    horarios_para_guardar = []

    for dia in dias_validos:
        hora_actual = datetime.combine(datetime.today(), inicio_jornada)

        while hora_actual + duracion_requerida <= datetime.combine(datetime.today(), fin_jornada):
            hora_fin = hora_actual + duracion_requerida
            hora_inicio_time = hora_actual.time()
            hora_fin_time = hora_fin.time()

            aula_asignada = aula_prefijada
            if not aula_asignada:
                for aula in aulas:
                    if puede_asignar_horario_mem(
                        docente, aula, asignatura, dia, jornada,
                        hora_inicio_time, hora_fin_time, horarios, no_disponibilidades,
                        descansos
                    ):
                        aula_asignada = aula
                        break
            else:
                if not puede_asignar_horario_mem(
                    docente, aula_asignada, asignatura, dia, jornada,
                    hora_inicio_time, hora_fin_time, horarios, no_disponibilidades,
                    descansos=descansos
                ):
                    aula_asignada = None

            if aula_asignada:
                nuevo_horario = Horario(
                    usuario=usuario,
                    institucion=institucion,
                    asignatura=asignatura,
                    docente=docente,
                    aula=aula_asignada,
                    dia=dia,
                    jornada=jornada,
                    hora_inicio=hora_inicio_time,
                    hora_fin=hora_fin_time
                )
                horarios_para_guardar.append(nuevo_horario)
                Horario.objects.bulk_create(horarios_para_guardar)
                horarios.extend(horarios_para_guardar)
                return _ret(True, "")

            hora_actual += timedelta(minutes=bloques)

    return _ret(False, "No se encontró hueco compatible")
