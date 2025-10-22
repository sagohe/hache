# generar_horarios.py
from django.contrib import messages
from datetime import time as _time
from django.db import transaction
from .utils import (
    asignar_horario_automatico,
    calcular_mps,
    obtener_institucion,
    obtener_asignatura_descanso,
    obtener_docente_placeholder,
    obtener_aula_placeholder,
    obtener_orden_dias,
)

from .models import (
    Institucion, Docente, Asignatura, NoDisponibilidad, Aula,
    Horario, Descanso
)
import gc, time
from django.shortcuts import redirect

def generar_horarios_view(request, admin_instance):
    """Genera horarios en lotes pequeños para evitar OOM en Render"""

    # 1) Resolver institucion (misma lógica que tenías)
    if request.user.is_superuser:
        inst_id = request.GET.get("institucion")
        if inst_id:
            inst = Institucion.objects.filter(id=inst_id).first()
            if not inst:
                messages.error(request, "La institución indicada no existe.")
                return redirect("..")
        else:
            instituciones = list(Institucion.objects.all())
            if not instituciones:
                messages.error(request, "No hay instituciones creadas.")
                return redirect("..")
            if len(instituciones) == 1:
                inst = instituciones[0]
            else:
                opciones = ", ".join(f"{i.id} - {i.nombre}" for i in instituciones)
                messages.error(request, f"Superusuario: usa ?institucion=<id>. Opciones: {opciones}")
                return redirect("..")
    else:
        if hasattr(request.user, "perfil") and request.user.perfil and request.user.perfil.institucion_id:
            inst = request.user.perfil.institucion
        else:
            messages.error(request, "Tu usuario no tiene institución asociada.")
            return redirect("..")

    # 2) Limpiar horarios anteriores del usuario+institucion
    Horario.objects.filter(usuario=request.user, institucion=inst).delete()

    # 3) Cargar datos base de forma ligera
    # traemos horarios existentes COMO dicts ligeros (reduce memoria)
    todos_los_horarios_qs = Horario.objects.filter(institucion=inst).select_related('aula','dia','asignatura','docente')
    todos_los_horarios = [
        {
            'id': h.id,
            'aula_id': h.aula_id,
            'hora_inicio': h.hora_inicio,
            'hora_fin': h.hora_fin,
            'dia_id': h.dia_id,
            'asignatura_id': h.asignatura_id,
            'docente_id': h.docente_id,
            'jornada': h.jornada,
        } for h in todos_los_horarios_qs.iterator()
    ]

    todas_las_no_disponibilidades = list(NoDisponibilidad.objects.filter(institucion=inst))
    todos_los_descansos = list(Descanso.objects.filter(institucion=inst, usuario=request.user))

    asig_descanso = obtener_asignatura_descanso(inst)
    docente_placeholder = obtener_docente_placeholder()
    aula_placeholder = obtener_aula_placeholder()

    # iterator() evita cargar todos los Asignatura en memoria de golpe
    asignaturas_qs = Asignatura.objects.select_related('semestre__carrera').prefetch_related('docentes').filter(institucion=inst).exclude(nombre="DESCANSO")
    # si deseas, puedes convertir a lista pequeña; pero iterator() ahorra memoria
    def dividir_en_lotes_iter(qs, tamano):
        buf = []
        for a in qs.iterator():
            buf.append(a)
            if len(buf) >= tamano:
                yield buf
                buf = []
        if buf:
            yield buf

    errores = []

    # Procesar lotes pequeños (10 por lote)
    for lote in dividir_en_lotes_iter(asignaturas_qs, 10):
        with transaction.atomic():
            # Pre-extraer docentes de este lote (prefetch cache ya presente)
            docentes_por_asig = {a.id: list(a.docentes.all()) for a in lote}
            for asignatura in lote:
                docentes_precargados = docentes_por_asig.get(asignatura.id, [])
                ok, motivo = asignar_horario_automatico(
                    asignatura=asignatura,
                    horarios=todos_los_horarios,
                    no_disponibilidades=todas_las_no_disponibilidades,
                    descansos=todos_los_descansos,
                    usuario=request.user,
                    institucion=inst,
                    docentes_precargados=docentes_precargados,
                    con_motivo=True,
                )
                if not ok:
                    errores.append(f"{asignatura.nombre} → {motivo}")
        # liberamos referencias y CPU
        gc.collect()
        time.sleep(0.25)

    # Crear descansos materializados (igual que antes)
    nuevos_descansos = []
    for d in todos_los_descansos:
        if d.hora_inicio < _time(13, 30):
            jornada = "Mañana"
        elif d.hora_inicio < _time(18, 15):
            jornada = "Tarde"
        else:
            jornada = "Noche"

        nuevos_descansos.append(Horario(
            usuario=request.user,
            institucion=inst,
            asignatura=asig_descanso,
            docente=docente_placeholder,
            aula=aula_placeholder,
            dia=d.dia,
            jornada=jornada,
            hora_inicio=d.hora_inicio,
            hora_fin=d.hora_fin,
        ))

    if nuevos_descansos:
        Horario.objects.bulk_create(nuevos_descansos)

    # Mensajes finales
    if errores:
        for e in errores:
            messages.warning(request, e)
    else:
        messages.success(request, "¡Horarios generados exitosamente!")

    return redirect("..")
