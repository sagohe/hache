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
    Coloca toda la carga semanal de la asignatura en UN solo día (el primero que tenga hueco),
    permitiendo partir SOLO por descansos (del día). Si no cabe completa en ese día,
    se descarta y se intenta el siguiente día. No se reparte entre días.

    Respeta:
      - descansos del usuario (no se asigna dentro)
      - no_disponibilidades del docente
      - conflictos de aula y de semestre
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

    # descansos por día (por FK DiaSemana)
    def descansos_del_dia(dia_obj):
        return [d for d in descansos if d.dia_id == dia_obj.id]

    # helper existente (docente/aula/semestre + desc)
    from .utils import puede_asignar_horario_mem as _puede

    # función que intenta colocar TODO en un solo día, partiendo solo por descansos
    def intentar_en_dia(dia_obj):
        ds = descansos_del_dia(dia_obj)
        restante = minutos_semana

        def segmento_disponible(aula, t0, t1):
            return _puede(
                docente=docente,
                aula=aula,
                asignatura=asignatura,
                dia=dia_obj,
                jornada=jornada,
                hora_inicio=t0.time(),
                hora_fin=t1.time(),
                horarios=horarios,
                no_disponibilidades=no_disponibilidades,
                descansos=ds
            )

        current = datetime.combine(datetime.today(), inicio_jornada)
        jornada_fin_dt = datetime.combine(datetime.today(), fin_jornada)

        seg_inicio = None
        seg_aula = None
        segmentos_dia = []  # ← solo los confirmamos si el día logra cubrir TODO

        def cerrar_segmento(hasta_dt):
            nonlocal seg_inicio, seg_aula, restante
            if seg_inicio is None or seg_aula is None:
                return True  # nada que cerrar, pero no es error
            dur_min = int((hasta_dt - seg_inicio).total_seconds() // 60)
            if dur_min <= 0:
                seg_inicio = None
                seg_aula = None
                return True
            # si se pasa del restante, recorta
            if dur_min > restante:
                hasta_dt = seg_inicio + timedelta(minutes=restante)
                dur_min = restante
            segmentos_dia.append(Horario(
                usuario=usuario,
                institucion=institucion,
                asignatura=asignatura,
                docente=docente,
                aula=seg_aula,
                dia=dia_obj,
                jornada=jornada,
                hora_inicio=seg_inicio.time(),
                hora_fin=hasta_dt.time()
            ))
            restante -= dur_min
            seg_inicio = None
            seg_aula = None
            return True

        # Recorremos la jornada; si hay interrupción que NO es descanso → fallar el día.
        while current < jornada_fin_dt and restante > 0:
            next_dt = min(current + paso, jornada_fin_dt)

            # ¿este paso pisa un descanso?
            descanso_cruzado = None
            for d in ds:
                d_ini = datetime.combine(current.date(), d.hora_inicio)
                d_fin = datetime.combine(current.date(), d.hora_fin)
                if overlaps(current, next_dt, d_ini, d_fin):
                    descanso_cruzado = (d_ini, d_fin)
                    break

            if descanso_cruzado:
                d_ini, d_fin = descanso_cruzado
                # cerramos segmento justo antes del descanso (si existe)
                if seg_inicio is not None:
                    if not cerrar_segmento(min(d_ini, next_dt)):
                        return None  # error formal (no debería)
                    if restante <= 0:
                        break
                # saltamos al final del descanso (no cuenta para la duración)
                current = max(current, d_fin)
                continue

            # No hay descanso en este paso
            if seg_inicio is None:
                # Intentar abrir segmento en 'current'
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
                else:
                    # Interrupción por algo que NO es descanso → este día no sirve.
                    return None
            else:
                # Ya estamos abiertos: intentar extender con la misma aula
                if segmento_disponible(seg_aula, seg_inicio, next_dt):
                    current = next_dt
                else:
                    # Interrupción por algo que NO es descanso → este día no sirve.
                    return None

        # Cerrar si quedó abierto y aún falta/queda tiempo
        if restante > 0 and seg_inicio is not None:
            if not cerrar_segmento(min(current, jornada_fin_dt)):
                return None

        # ¿Se logró cubrir TODO?
        if restante == 0:
            return segmentos_dia
        # No cupo completo en este día → no sirve
        return None

    # Probar día por día (en orden). En el primero que encaje COMPLETO, guardar y listo.
    for dia in dias_validos:
        segs = intentar_en_dia(dia)
        if segs:
            Horario.objects.bulk_create(segs)
            horarios.extend(segs)
            return _ret(True, "")

    # Ningún día pudo albergar toda la carga semanal
    return _ret(False, f"No se encontró un día con hueco suficiente para {minutos_semana} minutos (solo se permite dividir por descansos).")