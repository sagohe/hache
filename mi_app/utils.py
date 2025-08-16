from datetime import datetime, timedelta, time
from .models import NoDisponibilidad, Horario, Aula, Descanso


def obtener_bloques_por_jornada(jornada):
    rangos = {
        'Mañana': (time(7, 30), time(12, 50)),
        'Tarde': (time(13, 30), time(18, 15)),
        'Noche': (time(18, 15), time(21, 45)),
    }
    return rangos.get(jornada, (None, None))

def calcular_mps(asignatura):
    """
    Devuelve un dict con:
      - mps_original: minutos/semana (float) = (horas_totales * duracion_hora) / semanas
      - mps_ajustado: int, múltiplo de 15 más cercano (y ≥ 60)
      - exacto: bool (True si mps_original ya era múltiplo de 15 y sin decimales)
      - detalle: dict con info para mensajes (horas/semana decimales, diferencia, etc.)
    """
    inst = asignatura.institucion
    if not inst or not hasattr(inst, "duracion_hora_minutos"):
        # fallback prudente
        dh = 45
    else:
        dh = inst.duracion_hora_minutos

    ht = asignatura.horas_totales or 0
    ss = asignatura.semanas or 0
    if ht <= 0 or ss <= 0:
        return {
            "mps_original": 0.0,
            "mps_ajustado": 0,
            "exacto": False,
            "detalle": {"motivo": "HT o SS inválidos"}
        }

    minutos_totales = ht * dh
    mps = minutos_totales / ss  # puede ser decimal

    # exactitud: entero y múltiplo de 15
    entero = abs(mps - round(mps)) < 1e-9
    exacto = (entero and (int(round(mps)) % 15 == 0) and int(round(mps)) >= 60)

    # ajuste al múltiplo de 15 más cercano, mínimo 60
    # si empate (x.5 bloques de 15), sesgamos hacia arriba
    bloques = mps / 15.0
    bloques_red = int(bloques + 0.5)  # round-half-up
    mps_aj = max(60, bloques_red * 15)

    detalle = {
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
    return {
        "mps_original": mps,
        "mps_ajustado": int(mps_aj),
        "exacto": bool(exacto),
        "detalle": detalle,
    }


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
    descansos=None,          # lista de Descanso del usuario
    usuario=None,
    institucion=None,
    con_motivo=False
):
    """
    Asigna TODA la carga semanal de la asignatura en el PRIMER día disponible
    (según orden de Carrera.dias_clase) y parte en múltiples segmentos si hay descansos
    o bloqueos, sin asignar dentro de los descansos.

    Crea 1..N filas Horario (segmentos contiguos) el mismo día, respetando:
      - no_disponibilidades (docente)
      - conflictos de aula / semestre
      - descansos del usuario (no se asigna dentro; se parte alrededor)
    """
    def _ret(ok, motivo=""):
        return (ok, motivo) if con_motivo else ok

    descansos = list(descansos or [])

    # ===== validaciones básicas =====
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

    # ===== parámetros de institución y carga =====
    inst_ctx = institucion or getattr(asignatura, "institucion", None)
    dur_hora = getattr(inst_ctx, "duracion_hora_minutos", 45)
    horas_totales = getattr(asignatura, "horas_totales", 0) or 0
    semanas = getattr(asignatura, "semanas", 0) or 0
    if horas_totales <= 0:
        return _ret(False, "Horas totales inválidas")
    if semanas <= 0:
        return _ret(False, "Semanas inválidas")

    minutos_totales = horas_totales * dur_hora
    mps = minutos_totales / semanas  # minutos por semana (decimal)
    # Ajustar a múltiplo de 15, mínimo 60
    bloques = mps / 15.0
    bloques_redondeados = int(bloques + 0.5)
    minutos_semana = max(60, bloques_redondeados * 15)
    restante = minutos_semana

    # Rango por jornada
    rangos_jornada = {
        'Mañana': (time(7, 30), time(12, 50)),
        'Tarde':  (time(13, 30), time(18, 15)),
        'Noche':  (time(18, 15), time(21, 45)),
    }
    if jornada not in rangos_jornada:
        return _ret(False, f"Jornada inválida: {jornada}")
    inicio_jornada, fin_jornada = rangos_jornada[jornada]

    # 👉 Aulas del contexto
    aulas_qs = Aula.objects.all()
    if institucion is not None:
        aulas_qs = aulas_qs.filter(institucion=institucion)
    elif usuario is not None and hasattr(Aula, "usuario_id"):
        aulas_qs = aulas_qs.filter(usuario=usuario)
    aulas = list(aulas_qs)

    # Aula prefijada en la asignatura si pertenece al contexto
    aula_prefijada = asignatura.aula
    if aula_prefijada:
        if institucion is not None and getattr(aula_prefijada, "institucion_id", None) != getattr(institucion, "id", None):
            aula_prefijada = None
        elif institucion is None and usuario is not None and hasattr(aula_prefijada, "usuario_id") and getattr(aula_prefijada, "usuario_id", None) != getattr(usuario, "id", None):
            aula_prefijada = None

    if not aulas and not aula_prefijada:
        return _ret(False, "No hay aulas disponibles")

    # ===== utilidades =====
    paso = timedelta(minutes=15)

    def overlaps(a_start, a_end, b_start, b_end):
        return a_start < b_end and b_start < a_end

    # descansos del día actual (por FK DiaSemana)
    def descansos_del_dia(dia_obj):
        return [d for d in descansos if d.dia_id == dia_obj.id]

    # chequeo rápido con reglas existentes (usa el mismo helper global)
    from .utils import puede_asignar_horario_mem as _puede

    # ===== estrategia: usar SOLO el PRIMER día y completar toda la carga =====
    dia = dias_validos[0]

    # recorrer la jornada en pasos de 15', partiendo por descansos/choques
    current = datetime.combine(datetime.today(), inicio_jornada)
    jornada_fin_dt = datetime.combine(datetime.today(), fin_jornada)
    seg_inicio = None
    seg_aula = None

    nuevos_segmentos = []

    ds = descansos_del_dia(dia)

    def segmento_disponible(aula, t0, t1):
        # usa el helper existente (docente/aula/semestre + desc)
        return _puede(
            docente=aula and docente,
            aula=aula,
            asignatura=asignatura,
            dia=dia,
            jornada=jornada,
            hora_inicio=t0.time(),
            hora_fin=t1.time(),
            horarios=horarios,
            no_disponibilidades=no_disponibilidades,
            descansos=ds
        )

    # función para cerrar un segmento acumulado si existe
    def cerrar_segmento(hasta_dt):
        nonlocal seg_inicio, seg_aula, restante
        if seg_inicio is None or seg_aula is None:
            return
        dur_min = int((hasta_dt - seg_inicio).total_seconds() // 60)
        if dur_min > 0:
            # recorta si excede el restante
            if dur_min > restante:
                hasta_dt = seg_inicio + timedelta(minutes=restante)
                dur_min = restante
            nuevo = Horario(
                usuario=usuario,
                institucion=institucion,
                asignatura=asignatura,
                docente=docente,
                aula=seg_aula,
                dia=dia,
                jornada=jornada,
                hora_inicio=seg_inicio.time(),
                hora_fin=hasta_dt.time()
            )
            nuevos_segmentos.append(nuevo)
            restante -= dur_min
        seg_inicio = None
        seg_aula = None

    while current < jornada_fin_dt and restante > 0:
        next_dt = min(current + paso, jornada_fin_dt)

        # si el paso cruza un descanso, cortamos justo antes del descanso
        cruzo_descanso = None
        for d in ds:
            d_ini = datetime.combine(current.date(), d.hora_inicio)
            d_fin = datetime.combine(current.date(), d.hora_fin)
            if overlaps(current, next_dt, d_ini, d_fin):
                cruzo_descanso = (d_ini, d_fin)
                break

        if cruzo_descanso:
            d_ini, d_fin = cruzo_descanso
            # 1) cierra segmento antes del descanso
            if seg_inicio is not None:
                cerrar_segmento(min(d_ini, next_dt))
                if restante <= 0:
                    break
            # 2) salta al final del descanso
            current = max(current, d_fin)
            continue

        # si no hay descanso en este paso, intentamos encajar recursos
        if seg_inicio is None:
            # intentar comenzar un segmento en 'current'
            candidato_aulas = [aula_prefijada] if aula_prefijada else aulas
            elegido = None
            for aula in candidato_aulas:
                if segmento_disponible(aula, current, next_dt):
                    elegido = aula
                    break
            if elegido:
                seg_inicio = current
                seg_aula = elegido
            # si no cabe en este paso, avanzamos
            current = next_dt
        else:
            # ya venimos acumulando: intentar extender con MISMA aula
            if segmento_disponible(seg_aula, seg_inicio, next_dt):
                # extendemos sin cerrar
                current = next_dt
            else:
                # cerramos segmento hasta 'current' (sin incluir next_dt)
                cerrar_segmento(current)
                # si aún falta, intentamos reabrir con otra aula desde 'current'
                if restante > 0:
                    candidato_aulas = [aula_prefijada] if aula_prefijada else aulas
                    elegido = None
                    for aula in candidato_aulas:
                        if segmento_disponible(aula, current, next_dt):
                            elegido = aula
                            break
                    if elegido:
                        seg_inicio = current
                        seg_aula = elegido
                    current = next_dt

    # cerrar si algo quedó abierto
    if restante > 0 and seg_inicio is not None:
        cerrar_segmento(min(current, jornada_fin_dt))

    if restante > 0:
        # no alcanzó a completar la carga semanal en ese día
        # (díselo al usuario; puede ampliar jornada/días/semanas)
        if nuevos_segmentos:
            # guardamos lo que sí se pudo
            Horario.objects.bulk_create(nuevos_segmentos)
            horarios.extend(nuevos_segmentos)
            return _ret(False, f"No se completó toda la carga semanal ({minutos_semana} min). Faltaron {restante} min.")
        return _ret(False, "No se encontró hueco compatible en el día priorizado")

    # OK completo
    if nuevos_segmentos:
        Horario.objects.bulk_create(nuevos_segmentos)
        horarios.extend(nuevos_segmentos)
        return _ret(True, "")

    return _ret(False, "No se generó ningún segmento")