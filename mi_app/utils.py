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

def aula_disponible_en_memoria(aula, hora_inicio, hora_fin, horarios_por_dia):
    """Comprueba solape de aula usando horarios_ligeros (lista de dicts)."""
    for h in horarios_por_dia:
        # h['aula_id'] puede ser None
        if h.get('aula_id') is not None and aula is not None and h['aula_id'] == aula.id:
            if h['hora_inicio'] < hora_fin and h['hora_fin'] > hora_inicio:
                return False
    return True

def hay_conflicto_estudiantes_mem(semestre_id, hora_inicio, hora_fin, horarios_semestre):
    """
    Conflicto si YA existe cualquier horario para el MISMO semestre
    (distinta asignatura posible) que solape en tiempo.
    horarios_semestre: lista de dicts ligeros que contienen 'semestre_id', 'hora_inicio', 'hora_fin'.
    """
    if semestre_id is None:
        return False
    for h in horarios_semestre:
        # Solo interesan los que pertenecen al mismo semestre
        if h.get('semestre_id') == semestre_id:
            if h['hora_inicio'] < hora_fin and h['hora_fin'] > hora_inicio:
                return True
    return False

def docente_esta_disponible_mem(docente_id, hora_inicio, hora_fin, horarios_docente, no_disponibilidades_docente):
    for nd in no_disponibilidades_docente:
        if nd.hora_inicio < hora_fin and nd.hora_fin > hora_inicio:
            return False
    for h in horarios_docente:
        if h['hora_inicio'] < hora_fin and h['hora_fin'] > hora_inicio:
            return False
    return True

def puede_asignar_horario_mem(docente_id, aula, asignatura, dia, jornada,
                              hora_inicio, hora_fin,
                              horarios_por_dia, horarios_docente,
                              horarios_semestre, no_disp_docente, descansos_por_dia):
    """
    Usa IDs/estructuras ligeras:
    - docente_id: int
    - aula: objeto Aula (puede ser None)
    - horarios_por_dia: lista de dicts con keys 'aula_id','hora_inicio','hora_fin',...
    - horarios_docente: lista de dicts
    - horarios_semestre: lista de dicts que contienen 'semestre_id'
    - no_disp_docente: lista de NoDisponibilidad (objetos)
    - descansos_por_dia: lista de Descanso (objetos)
    """
    if not docente_esta_disponible_mem(docente_id, hora_inicio, hora_fin, horarios_docente, no_disp_docente):
        return False
    if not aula_disponible_en_memoria(aula, hora_inicio, hora_fin, horarios_por_dia):
        return False
    semestre_id = getattr(asignatura.semestre, "id", None)
    if hay_conflicto_estudiantes_mem(semestre_id, hora_inicio, hora_fin, horarios_semestre):
        return False
    if hay_descanso_mem(dia, hora_inicio, hora_fin, descansos_por_dia):
        return False
    return True

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
    Versión que distribuye la carga en varios días y evita solapes de estudiantes por SEMESTRE.
    Requiere que los `horarios` ligeros incluyan 'semestre_id' en sus dicts (generar_horarios_view
    ya lo debe proveer cuando crea la lista).
    """
    def _ret(ok, motivo=""):
        return (ok, motivo) if con_motivo else ok

    # seleccionar docente (prefiere precargados / prefetch)
    docente = None
    if docentes_precargados and len(docentes_precargados) > 0:
        docente = docentes_precargados[0]
    else:
        docente_qs = getattr(asignatura, '_prefetched_objects_cache', {}).get('docentes')
        docente = docente_qs[0] if docente_qs and len(docente_qs) > 0 else asignatura.docentes.first()

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
    except Exception:
        dur_hora = 45

    horas_totales = getattr(asignatura, "horas_totales", 0) or 0
    semanas = getattr(asignatura, "semanas", 0) or 0
    if horas_totales <= 0 or semanas <= 0:
        return _ret(False, "Horas totales o semanas inválidas")

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

    # convertir horarios a forma ligera (si es que vienen objetos)
    horarios_ligeros = []
    if horarios:
        if isinstance(horarios[0], dict):
            horarios_ligeros = horarios[:]  # ya vienen dicts ligeros
        else:
            for h in horarios:
                horarios_ligeros.append({
                    'id': h.id,
                    'aula_id': getattr(h.aula, 'id', None),
                    'hora_inicio': h.hora_inicio,
                    'hora_fin': h.hora_fin,
                    'dia_id': getattr(h.dia, 'id', None),
                    'asignatura_id': getattr(h.asignatura, 'id', None),
                    'docente_id': getattr(h.docente, 'id', None),
                    # IMPORTANTE: el view que construye 'horarios' debe incluir semestre_id
                    'semestre_id': getattr(getattr(h.asignatura, 'semestre', None), 'id', None),
                    'jornada': h.jornada,
                })

    # indexación por día
    horarios_por_dia = {}
    for h in horarios_ligeros:
        horarios_por_dia.setdefault(h.get('dia_id'), []).append(h)

    # horarios del docente y del semestre
    docente_id = docente.id
    horarios_docente = [h for h in horarios_ligeros if h.get('docente_id') == docente_id]
    semestre_id = getattr(semestre, 'id', None)
    horarios_semestre = [h for h in horarios_ligeros if h.get('semestre_id') == semestre_id]

    no_disp_docente = [nd for nd in no_disponibilidades if nd.docente_id == docente_id]
    descansos_por_dia = {}
    for d in descansos:
        descansos_por_dia.setdefault(getattr(d, 'dia_id', None), []).append(d)

    # balanceo por carga (para buscar días menos ocupados primero)
    carga_por_dia = {dia.id: len(horarios_por_dia.get(dia.id, [])) for dia in dias_validos}
    dias_ordenados = sorted(dias_validos, key=lambda d: (carga_por_dia.get(d.id, 0), d.orden))

        # intentar distribuir la carga entre todos los días posibles
    restante = minutos_semana
    segmentos_totales = []

    for dia in dias_ordenados:
        if restante <= 0:
            break

        dia_id = dia.id
        ds_dia = descansos_por_dia.get(dia_id, [])
        horarios_dia = horarios_por_dia.get(dia_id, [])

        current = datetime.combine(datetime.today(), inicio_jornada)
        fin_dt = datetime.combine(datetime.today(), fin_jornada)
        seg_inicio = None
        seg_aula = None
        segmentos_dia = []

        while current < fin_dt and restante > 0:
            next_dt = min(current + paso, fin_dt)

            # Verificar si hay un descanso en este rango
            if any(d.hora_inicio < next_dt.time() and d.hora_fin > current.time() for d in ds_dia):
                if seg_inicio:
                    dur = int((current - seg_inicio).total_seconds() // 60)
                    if dur > 0:
                        take = min(dur, restante)
                        segmentos_dia.append({
                            'usuario': usuario,
                            'institucion': institucion,
                            'asignatura': asignatura,
                            'docente': docente,
                            'aula': seg_aula,
                            'dia': dia,
                            'jornada': jornada,
                            'hora_inicio': seg_inicio.time(),
                            'hora_fin': (seg_inicio + timedelta(minutes=take)).time()
                        })
                        restante -= take
                    seg_inicio, seg_aula = None, None
                current = datetime.combine(current.date(), max(d.hora_fin for d in ds_dia))
                continue

            # Intentar abrir un nuevo bloque si no hay uno activo
            if not seg_inicio:
                for aula in ([aula_prefijada] if aula_prefijada else aulas):
                    if puede_asignar_horario_mem(
                        docente_id, aula, asignatura, dia, jornada,
                        current.time(), next_dt.time(),
                        horarios_dia, horarios_docente, horarios_semestre,
                        no_disp_docente, ds_dia
                    ):
                        seg_inicio = current
                        seg_aula = aula
                        break
                current += paso
                continue

            # Si ya hay bloque activo, comprobar si puede continuar
            if puede_asignar_horario_mem(
                docente_id, seg_aula, asignatura, dia, jornada,
                seg_inicio.time(), next_dt.time(),
                horarios_dia, horarios_docente, horarios_semestre,
                no_disp_docente, ds_dia
            ):
                current = next_dt
            else:
                dur = int((current - seg_inicio).total_seconds() // 60)
                if dur > 0:
                    take = min(dur, restante)
                    segmentos_dia.append({
                        'usuario': usuario,
                        'institucion': institucion,
                        'asignatura': asignatura,
                        'docente': docente,
                        'aula': seg_aula,
                        'dia': dia,
                        'jornada': jornada,
                        'hora_inicio': seg_inicio.time(),
                        'hora_fin': (seg_inicio + timedelta(minutes=take)).time()
                    })
                    restante -= take
                seg_inicio, seg_aula = None, None
                current = next_dt

        # Cerrar bloque si queda abierto
        if seg_inicio and restante > 0:
            dur = int((fin_dt - seg_inicio).total_seconds() // 60)
            if dur > 0:
                take = min(dur, restante)
                segmentos_dia.append({
                    'usuario': usuario,
                    'institucion': institucion,
                    'asignatura': asignatura,
                    'docente': docente,
                    'aula': seg_aula,
                    'dia': dia,
                    'jornada': jornada,
                    'hora_inicio': seg_inicio.time(),
                    'hora_fin': (seg_inicio + timedelta(minutes=take)).time()
                })
                restante -= take

        # Solo agregamos si realmente hay algo asignado en el día
        if segmentos_dia:
            segmentos_totales.extend(segmentos_dia)

    # Si aún queda tiempo sin asignar, continuar probando otros días (no se detiene prematuramente)
    if restante > 0 and len(segmentos_totales) > 0:
        # Intento extra: reordenar días y repetir
        for dia in reversed(dias_ordenados):
            if restante <= 0:
                break
            dia_id = dia.id
            horarios_dia = horarios_por_dia.get(dia_id, [])
            ds_dia = descansos_por_dia.get(dia_id, [])
            current = datetime.combine(datetime.today(), inicio_jornada)
            fin_dt = datetime.combine(datetime.today(), fin_jornada)
            while current < fin_dt and restante > 0:
                next_dt = min(current + paso, fin_dt)
                for aula in ([aula_prefijada] if aula_prefijada else aulas):
                    if puede_asignar_horario_mem(
                        docente_id, aula, asignatura, dia, jornada,
                        current.time(), next_dt.time(),
                        horarios_dia, horarios_docente, horarios_semestre,
                        no_disp_docente, ds_dia
                    ):
                        take = min(15, restante)
                        segmentos_totales.append({
                            'usuario': usuario,
                            'institucion': institucion,
                            'asignatura': asignatura,
                            'docente': docente,
                            'aula': aula,
                            'dia': dia,
                            'jornada': jornada,
                            'hora_inicio': current.time(),
                            'hora_fin': (current + timedelta(minutes=take)).time()
                        })
                        restante -= take
                current = next_dt


    # si conseguimos crear segmentos los persistimos
    if segmentos_totales:
        objs = [Horario(**seg) for seg in segmentos_totales]
        Horario.objects.bulk_create(objs)
        # actualizar la lista ligera 'horarios' con lo nuevo (para evitar reclashes posteriores)
        horarios.extend([{
            'aula_id': o.aula.id if getattr(o, 'aula', None) else None,
            'hora_inicio': o.hora_inicio,
            'hora_fin': o.hora_fin,
            'dia_id': o.dia.id,
            'asignatura_id': o.asignatura.id,
            'docente_id': o.docente.id,
            'semestre_id': getattr(o.asignatura.semestre, 'id', None),
            'jornada': o.jornada,
        } for o in objs])
        # si quedó tiempo restante -> asignada parcialmente
        if restante > 0:
            return _ret(True, f"Asignada parcialmente ({minutos_semana - restante}/{minutos_semana} min)")
        return _ret(True, "Asignada completamente")

    return _ret(False, f"No se encontró hueco suficiente para {minutos_semana} minutos")



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
