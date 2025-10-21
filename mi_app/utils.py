from datetime import datetime, timedelta, time
from django.core.exceptions import ObjectDoesNotExist
from .models import NoDisponibilidad, Horario, Aula, Descanso

# ==========================================================
# OPTIMIZACIÓN SEGURA: se mantienen resultados exactos
# ==========================================================

def obtener_bloques_por_jornada(jornada):
    return {
        'Mañana': (time(7, 30), time(12, 50)),
        'Tarde': (time(13, 30), time(18, 15)),
        'Noche': (time(18, 15), time(21, 45)),
    }.get(jornada, (None, None))


# ==========================================================
# CÁLCULO DE MINUTOS POR SEMANA (sin cambios funcionales)
# ==========================================================
def calcular_mps(asignatura):
    try:
        inst = asignatura.institucion
        dh = getattr(inst, "duracion_hora_minutos", 45)
    except ObjectDoesNotExist:
        dh = 45

    ht = asignatura.horas_totales or 0
    ss = asignatura.semanas or 0
    if ht <= 0 or ss <= 0:
        return {"mps_original": 0.0, "mps_ajustado": 0, "exacto": False,
                "detalle": {"motivo": "HT o SS inválidos"}}

    minutos_totales = ht * dh
    mps = minutos_totales / ss

    entero = abs(mps - round(mps)) < 1e-9
    exacto = entero and int(round(mps)) % 15 == 0 and int(round(mps)) >= 60

    bloques_red = int(mps / 15.0 + 0.5)
    mps_aj = max(60, bloques_red * 15)

    return {
        "mps_original": mps,
        "mps_ajustado": mps_aj,
        "exacto": exacto,
        "detalle": {
            "minutos_totales": minutos_totales,
            "mps_decimal": mps,
            "horas_sem_decimal": mps / 60.0,
            "mps_ajustado": mps_aj,
            "dif_por_sem": mps_aj - mps,
            "dif_total": (mps_aj - mps) * ss,
            "dh": dh,
            "ht": ht,
            "ss": ss,
        }
    }


# ==========================================================
# FUNCIONES DE CHEQUEO EN MEMORIA (optimizadas)
# ==========================================================

def hay_descanso_mem(dia, hora_inicio, hora_fin, descansos_por_dia):
    for d in descansos_por_dia:
        if d.hora_inicio < hora_fin and d.hora_fin > hora_inicio:
            return True
    return False


def aula_disponible_en_memoria(aula, dia, hora_inicio, hora_fin, horarios_por_dia):
    for h in horarios_por_dia:
        if h.aula == aula and h.hora_inicio < hora_fin and h.hora_fin > hora_inicio:
            return False
    return True


def hay_conflicto_estudiantes_mem(asignatura, hora_inicio, hora_fin, horarios_semestre):
    for h in horarios_semestre:
        if h.asignatura != asignatura and h.hora_inicio < hora_fin and h.hora_fin > hora_inicio:
            return True
    return False


def docente_esta_disponible_mem(docente, hora_inicio, hora_fin, horarios_docente, no_disponibilidades_docente):
    for nd in no_disponibilidades_docente:
        if nd.hora_inicio < hora_fin and nd.hora_fin > hora_inicio:
            return False
    for h in horarios_docente:
        if h.hora_inicio < hora_fin and h.hora_fin > hora_inicio:
            return False
    return True


def puede_asignar_horario_mem(docente, aula, asignatura, dia, jornada,
                              hora_inicio, hora_fin,
                              horarios_por_dia, horarios_docente,
                              horarios_semestre, no_disp_docente, descansos_por_dia):
    return (
        docente_esta_disponible_mem(docente, hora_inicio, hora_fin, horarios_docente, no_disp_docente)
        and aula_disponible_en_memoria(aula, dia, hora_inicio, hora_fin, horarios_por_dia)
        and not hay_conflicto_estudiantes_mem(asignatura, hora_inicio, hora_fin, horarios_semestre)
        and not hay_descanso_mem(dia, hora_inicio, hora_fin, descansos_por_dia)
    )


# ==========================================================
# FUNCIÓN PRINCIPAL: ASIGNAR HORARIO AUTOMÁTICO (optimizada)
# ==========================================================

def asignar_horario_automatico(
    asignatura,
    horarios,
    no_disponibilidades,
    descansos=None,
    usuario=None,
    institucion=None,
    con_motivo=False
):
    """
    Versión optimizada:
    - Agrupa horarios por docente/día/semestre para evitar bucles repetidos.
    - Usa estructuras en memoria (diccionarios) para consultas O(1).
    - Misma lógica y resultados.
    """

    def _ret(ok, motivo=""):
        return (ok, motivo) if con_motivo else ok

    descansos = list(descansos or [])
    jornada = asignatura.jornada
    semestre = asignatura.semestre
    if not semestre:
        return _ret(False, "Sin semestre")

    carrera = semestre.carrera
    dias_validos = list(carrera.dias_clase.all().order_by('orden'))
    if not dias_validos:
        return _ret(False, "Carrera sin días de clase")

    docente = asignatura.docentes.first()
    if not docente:
        return _ret(False, "Asignatura sin docente")

    try:
        inst = asignatura.institucion
        dur_hora = getattr(inst, "duracion_hora_minutos", 45)
    except ObjectDoesNotExist:
        dur_hora = 45

    horas_totales = getattr(asignatura, "horas_totales", 0) or 0
    semanas = getattr(asignatura, "semanas", 0) or 0
    if horas_totales <= 0:
        return _ret(False, "Horas totales inválidas")
    if semanas <= 0:
        return _ret(False, "Semanas inválidas")

    minutos_semana = max(60, int(round((horas_totales * dur_hora / semanas) / 15.0 + 0.5) * 15))

    rangos_jornada = {
        'Mañana': (time(7, 30), time(12, 50)),
        'Tarde': (time(13, 30), time(18, 15)),
        'Noche': (time(18, 15), time(21, 45)),
    }
    if jornada not in rangos_jornada:
        return _ret(False, f"Jornada inválida: {jornada}")
    inicio_jornada, fin_jornada = rangos_jornada[jornada]

    aulas_qs = Aula.objects.all()
    if institucion:
        aulas_qs = aulas_qs.filter(institucion=institucion)
    elif usuario and hasattr(Aula, "usuario_id"):
        aulas_qs = aulas_qs.filter(usuario=usuario)
    aulas = list(aulas_qs)

    aula_prefijada = asignatura.aula if getattr(asignatura, "aula", None) in aulas else None
    if not aulas and not aula_prefijada:
        return _ret(False, "No hay aulas disponibles")

    paso = timedelta(minutes=15)
    overlaps = lambda a1, a2, b1, b2: a1 < b2 and b1 < a2

    # ==================================================
    # INDEXACIÓN EN MEMORIA (OPTIMIZACIÓN MAYOR)
    # ==================================================
    horarios_por_dia = {}
    horarios_docente = []
    horarios_semestre = []

    for h in horarios:
        horarios_por_dia.setdefault(h.dia.id, []).append(h)
        if h.docente == docente:
            horarios_docente.append(h)
        if h.asignatura.semestre == semestre:
            horarios_semestre.append(h)

    no_disp_docente = [nd for nd in no_disponibilidades if nd.docente == docente]
    descansos_por_dia = {d.dia_id: [] for d in descansos}
    for d in descansos:
        descansos_por_dia.setdefault(d.dia_id, []).append(d)

    # ==================================================
    # LÓGICA PRINCIPAL (idéntica pero más rápida)
    # ==================================================
    for dia in dias_validos:
        dia_id = dia.id
        ds_dia = descansos_por_dia.get(dia_id, [])
        horarios_dia = horarios_por_dia.get(dia_id, [])

        restante = minutos_semana
        current = datetime.combine(datetime.today(), inicio_jornada)
        fin_dt = datetime.combine(datetime.today(), fin_jornada)
        seg_inicio = None
        seg_aula = None
        segmentos_dia = []

        while current < fin_dt and restante > 0:
            next_dt = min(current + paso, fin_dt)

            # comprobar descanso
            descanso_cruzado = next((d for d in ds_dia if overlaps(
                current, next_dt,
                datetime.combine(current.date(), d.hora_inicio),
                datetime.combine(current.date(), d.hora_fin)
            )), None)

            if descanso_cruzado:
                if seg_inicio:
                    dur = int((datetime.combine(current.date(), descanso_cruzado.hora_inicio) - seg_inicio).total_seconds() // 60)
                    if dur > 0:
                        if dur > restante:
                            dur = restante
                        segmentos_dia.append(Horario(
                            usuario=usuario, institucion=institucion,
                            asignatura=asignatura, docente=docente,
                            aula=seg_aula, dia=dia, jornada=jornada,
                            hora_inicio=seg_inicio.time(),
                            hora_fin=(seg_inicio + timedelta(minutes=dur)).time()
                        ))
                        restante -= dur
                    seg_inicio = None
                    seg_aula = None
                current = datetime.combine(current.date(), descanso_cruzado.hora_fin)
                continue

            # buscar aula disponible
            if not seg_inicio:
                for aula in ([aula_prefijada] if aula_prefijada else aulas):
                    if puede_asignar_horario_mem(
                        docente, aula, asignatura, dia, jornada,
                        current.time(), next_dt.time(),
                        horarios_dia, horarios_docente, horarios_semestre,
                        no_disp_docente, ds_dia
                    ):
                        seg_inicio = current
                        seg_aula = aula
                        break
                if not seg_inicio:
                    # interrupción no descanso: descartar día
                    break
            current = next_dt

        if restante == 0 and segmentos_dia:
            Horario.objects.bulk_create(segmentos_dia)
            horarios.extend(segmentos_dia)
            return _ret(True, "")

    return _ret(False, f"No se encontró un día con hueco suficiente para {minutos_semana} minutos")
