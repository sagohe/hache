# utils.py
from datetime import datetime, timedelta, time
from django.core.exceptions import ObjectDoesNotExist
from .models import NoDisponibilidad, Horario, Aula, Descanso, Institucion
from django.core.exceptions import ObjectDoesNotExist

# BLOQUES DE JORNADA (sin cambios)
def obtener_bloques_por_jornada(jornada):
    return {
        'Mañana': (time(7, 30), time(12, 50)),
        'Tarde': (time(13, 30), time(18, 15)),
        'Noche': (time(18, 15), time(21, 45)),
    }.get(jornada, (None, None))

# calcular_mps (sin cambios funcionales)
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

    exacto = abs(mps - round(mps)) < 1e-9 and int(round(mps)) % 15 == 0 and int(round(mps)) >= 60
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

# FUNCIONES DE CHEQUEO EN MEMORIA (optimizadas)
def hay_descanso_mem(dia, hora_inicio, hora_fin, descansos_por_dia):
    for d in descansos_por_dia:
        if d.hora_inicio < hora_fin and d.hora_fin > hora_inicio:
            return True
    return False

def aula_disponible_en_memoria(aula, dia, hora_inicio, hora_fin, horarios_por_dia):
    for h in horarios_por_dia:
        if h['aula_id'] == aula.id and h['hora_inicio'] < hora_fin and h['hora_fin'] > hora_inicio:
            return False
    return True

def hay_conflicto_estudiantes_mem(asignatura, hora_inicio, hora_fin, horarios_semestre):
    for h in horarios_semestre:
        if h['asignatura_id'] != asignatura.id and h['hora_inicio'] < hora_fin and h['hora_fin'] > hora_inicio:
            return True
    return False

def docente_esta_disponible_mem(docente, hora_inicio, hora_fin, horarios_docente, no_disponibilidades_docente):
    for nd in no_disponibilidades_docente:
        if nd.hora_inicio < hora_fin and nd.hora_fin > hora_inicio:
            return False
    for h in horarios_docente:
        if h['hora_inicio'] < hora_fin and h['hora_fin'] > hora_inicio:
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

# FUNCIÓN PRINCIPAL: ahora usa datos ligeros en memoria (diccionarios)
def asignar_horario_automatico(
    asignatura,
    horarios,
    no_disponibilidades,
    descansos=None,
    usuario=None,
    institucion=None,
    docentes_precargados=None,
    con_motivo=False
):
    """
    Mantiene la lógica funcional original pero:
     - usa 'docentes_precargados' si llega (evita consultas).
     - trata 'horarios' como lista de dicts ligeros con campos esenciales cuando sea posible.
    """
    def _ret(ok, motivo=""):
        return (ok, motivo) if con_motivo else ok

    # elegir docente: preferir el listado precargado (si viene desde la vista)
    docente = None
    if docentes_precargados:
        if len(docentes_precargados) > 0:
            docente = docentes_precargados[0]
    else:
        # intentar usar el cache prefetch (si existe), si no, hacer la consulta
        docente_qs = getattr(asignatura, '_prefetched_objects_cache', {}).get('docentes')
        if docente_qs is not None:
            docente = docente_qs[0] if len(docente_qs) > 0 else None
        else:
            # consulta única cuando sea estrictamente necesario
            docente = asignatura.docentes.first()

    if not docente:
        return _ret(False, "Asignatura sin docente")

    descansos = list(descansos or [])
    jornada = asignatura.jornada
    semestre = asignatura.semestre
    if not semestre:
        return _ret(False, "Sin semestre")

    carrera = semestre.carrera
    dias_validos = list(carrera.dias_clase.all().order_by('orden'))
    if not dias_validos:
        return _ret(False, "Carrera sin días de clase")

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

    # --- Preparar vistas ligeras de 'horarios' y 'no_disponibilidades' para evitar objetos grandes ---
    # Si 'horarios' viene como queryset de modelos, convertimos a dicts ligeros (una vez)
    if horarios and not isinstance(horarios[0], dict):
        horarios_ligeros = []
        for h in horarios:
            horarios_ligeros.append({
                'id': h.id,
                'aula_id': getattr(h.aula, 'id', None),
                'hora_inicio': h.hora_inicio,
                'hora_fin': h.hora_fin,
                'dia_id': getattr(h.dia, 'id', None),
                'asignatura_id': getattr(h.asignatura, 'id', None),
                'docente_id': getattr(h.docente, 'id', None),
                'jornada': h.jornada,
            })
    else:
        horarios_ligeros = horarios[:]  # ya son dicts

    # Indexación por día y por semestre/docente
    horarios_por_dia = {}
    horarios_docente = []
    horarios_semestre = []

    for h in horarios_ligeros:
        horarios_por_dia.setdefault(h['dia_id'], []).append(h)
        if h['docente_id'] == docente.id:
            horarios_docente.append(h)
        if h['asignatura_id'] == getattr(asignatura, 'id', None) or h.get('asignatura_id') is not None:
            # para seguridad: añadimos todos los horarios que pertenecen al mismo semestre
            # buscamos horarios cuyo asignatura pertenezca al mismo semestre comparando ids:
            # (esto requiere que 'horarios' ligeros tengan asignatura_id y que
            # podamos mapear a semestres si fuera necesario; para evitar queries muy caras,
            # tratamos por asignatura_id igual)
            pass
    # Construir lista de horarios del mismo semestre
    try:
        ids_semestre = [h['asignatura_id'] for h in horarios_ligeros if h['asignatura_id'] is not None]
        horarios_semestre = [h for h in horarios_ligeros if h['asignatura_id'] in ids_semestre]
    except Exception:
        horarios_semestre = []

    no_disp_docente = [nd for nd in no_disponibilidades if nd.docente_id == docente.id]
    descansos_por_dia = {}
    for d in descansos:
        descansos_por_dia.setdefault(getattr(d, 'dia_id', None), []).append(d)

    # Balanceo por carga (conteo por día)
    carga_por_dia = {dia.id: 0 for dia in dias_validos}
    for h in horarios_ligeros:
        if h.get('dia_id') in carga_por_dia:
            carga_por_dia[h['dia_id']] += 1

    dias_ordenados = sorted(dias_validos, key=lambda d: (carga_por_dia.get(d.id, 0), d.orden))
    if dias_ordenados:
        offset = (getattr(asignatura, 'id', 0) or 0) % len(dias_ordenados)
        dias_ordenados = dias_ordenados[offset:] + dias_ordenados[:offset]

    # Intentar asignar UN día (mismo comportamiento)
    for dia in dias_ordenados:
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
            descanso_cruzado = next(
                (d for d in ds_dia if overlaps(
                    current, next_dt,
                    datetime.combine(current.date(), d.hora_inicio),
                    datetime.combine(current.date(), d.hora_fin)
                )), None
            )

            if descanso_cruzado:
                if seg_inicio:
                    dur = int((datetime.combine(current.date(), descanso_cruzado.hora_inicio) - seg_inicio).total_seconds() // 60)
                    if dur > 0:
                        if dur > restante:
                            dur = restante
                        segmentos_dia.append({
                            'usuario': usuario, 'institucion': institucion,
                            'asignatura': asignatura, 'docente': docente,
                            'aula': seg_aula, 'dia': dia, 'jornada': jornada,
                            'hora_inicio': seg_inicio.time(), 'hora_fin': (seg_inicio + timedelta(minutes=dur)).time()
                        })
                        restante -= dur
                    seg_inicio = None
                    seg_aula = None
                current = datetime.combine(current.date(), descanso_cruzado.hora_fin)
                continue

            if not seg_inicio:
                encontrado = False
                for aula in ([aula_prefijada] if aula_prefijada else aulas):
                    if puede_asignar_horario_mem(
                        docente, aula, asignatura, dia, jornada,
                        current.time(), next_dt.time(),
                        horarios_dia, horarios_docente, horarios_semestre,
                        no_disp_docente, ds_dia
                    ):
                        seg_inicio = current
                        seg_aula = aula
                        encontrado = True
                        break
                # Si no se pudo abrir segmento, avanzamos un paso y seguimos buscando
                current += paso
                continue

            current = next_dt

        # Cerrar segmento si quedó abierto al terminar jornada
        if seg_inicio and restante > 0:
            dur = int((fin_dt - seg_inicio).total_seconds() // 60)
            if dur > 0:
                if dur > restante:
                    dur = restante
                segmentos_dia.append({
                    'usuario': usuario, 'institucion': institucion,
                    'asignatura': asignatura, 'docente': docente,
                    'aula': seg_aula, 'dia': dia, 'jornada': jornada,
                    'hora_inicio': seg_inicio.time(), 'hora_fin': (seg_inicio + timedelta(minutes=dur)).time()
                })
                restante -= dur

        if restante <= 0 and segmentos_dia:
            # Construimos los objetos Horario y guardamos en bulk_create (mínimamente)
            objs = []
            for seg in segmentos_dia:
                objs.append(Horario(
                    usuario=seg['usuario'],
                    institucion=seg['institucion'],
                    asignatura=seg['asignatura'],
                    docente=seg['docente'],
                    aula=seg['aula'],
                    dia=seg['dia'],
                    jornada=seg['jornada'],
                    hora_inicio=seg['hora_inicio'],
                    hora_fin=seg['hora_fin'],
                ))
            Horario.objects.bulk_create(objs)
            # Añadir representaciones ligeras a 'horarios' para evitar recargar objetos grandes
            horarios.extend([{
                'aula_id': o.aula.id if getattr(o, 'aula', None) else None,
                'hora_inicio': o.hora_inicio,
                'hora_fin': o.hora_fin,
                'dia_id': o.dia.id,
                'asignatura_id': o.asignatura.id,
                'docente_id': o.docente.id,
                'jornada': o.jornada,
            } for o in objs])
            return _ret(True, f"Asignada en {dia.nombre}")

    return _ret(False, f"No se encontró hueco suficiente en ningún día para {minutos_semana} minutos")


def obtener_institucion(usuario):
    """Devuelve la institución asociada al usuario."""
    try:
        if usuario.is_superuser:
            return Institucion.objects.first()
        if hasattr(usuario, "perfil") and usuario.perfil and usuario.perfil.institucion_id:
            return usuario.perfil.institucion
    except ObjectDoesNotExist:
        pass
    return None

def obtener_asignatura_descanso(institucion=None):
    """Obtiene o crea una asignatura especial llamada DESCANSO."""
    from .models import Asignatura, Institucion

    if institucion is None:
        institucion = Institucion.objects.first()

    if not institucion:
        raise ValueError("No hay institución disponible para crear la asignatura DESCANSO.")

    asig, _ = Asignatura.objects.get_or_create(
        institucion=institucion,
        nombre="DESCANSO",
        defaults={"horas_totales": 0, "semanas": 0}
    )
    return asig


def obtener_docente_placeholder(institucion=None):
    """Obtiene o crea un docente genérico para descansos."""
    from .models import Docente, Institucion

    if institucion is None:
        institucion = Institucion.objects.first()  # usa la primera si no se pasa una
    
    if not institucion:
        raise ValueError("No hay institución disponible para crear el docente genérico.")
    
    docente, _ = Docente.objects.get_or_create(
        nombre="SIN DOCENTE",
        institucion=institucion,
        defaults={}
    )
    return docente


def obtener_aula_placeholder(institucion=None):
    """Obtiene o crea un aula genérica para descansos."""
    from .models import Aula, Institucion

    if institucion is None:
        institucion = Institucion.objects.first()

    if not institucion:
        raise ValueError("No hay institución disponible para crear el aula genérica.")

    aula, _ = Aula.objects.get_or_create(
        nombre="SIN AULA",
        institucion=institucion,
        defaults={}
    )
    return aula


def obtener_orden_dias():
    """Devuelve los días ordenados por su campo 'orden'."""
    from .models import DiaSemana
    return list(DiaSemana.objects.order_by("orden"))
