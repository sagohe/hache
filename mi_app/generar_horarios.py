
import time, gc, logging
from datetime import time as _time
from django.shortcuts import redirect
from django.contrib import messages
from django.db import transaction
from mi_app.models import (
    Horario, NoDisponibilidad, Descanso,
    Institucion, Asignatura
)
from mi_app.utils import (
    obtener_asignatura_descanso, obtener_docente_placeholder,
    obtener_aula_placeholder, asignar_horario_automatico
)
from mi_app.tasks import generar_horarios_task

logger = logging.getLogger(__name__)

def generar_horarios_view(request, admin_instance):
    """
    Genera los horarios usando Celery si está disponible.
    Si se ejecuta en entorno local (sin Redis/Celery), lo hace directamente en lotes.
    """

    # 1️⃣ Resolver institución
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
        perfil = getattr(request.user, "perfil", None)
        if perfil and perfil.institucion_id:
            inst = perfil.institucion
        else:
            messages.error(request, "Tu usuario no tiene institución asociada.")
            return redirect("..")

    # 2️⃣ Limpieza inicial
    Horario.objects.filter(usuario=request.user, institucion=inst).delete()

    # 3️⃣ Si Celery está activo, ejecutar en segundo plano
    try:
        from mi_proyecto.celery import current_app
        if current_app.control.inspect().active():
            generar_horarios_task.delay(request.user.id, inst.id)
            messages.success(request, "Generación de horarios enviada a Celery. Se procesará en segundo plano.")
            return redirect("..")
    except Exception as e:
        logger.warning(f"Celery no disponible: {e}")

    # 4️⃣ Si no hay Celery, ejecuta localmente (modo Render)
    todos_los_horarios_qs = Horario.objects.filter(institucion=inst).select_related(
        "aula", "dia", "asignatura", "docente"
    )
    todos_los_horarios = [
        {
            "id": h.id,
            "aula_id": h.aula_id,
            "hora_inicio": h.hora_inicio,
            "hora_fin": h.hora_fin,
            "dia_id": h.dia_id,
            "asignatura_id": h.asignatura_id,
            "docente_id": h.docente_id,
            "jornada": h.jornada,
            "semestre_id": getattr(h.asignatura.semestre, "id", None),
        }
        for h in todos_los_horarios_qs.iterator(chunk_size=30)
    ]

    todas_las_no_disp = list(NoDisponibilidad.objects.filter(institucion=inst))
    todos_los_descansos = list(Descanso.objects.filter(institucion=inst, usuario=request.user))

    asig_descanso = obtener_asignatura_descanso(inst)
    docente_placeholder = obtener_docente_placeholder(inst)
    aula_placeholder = obtener_aula_placeholder(inst)

    asignaturas_qs = (
        Asignatura.objects.select_related("semestre__carrera")
        .prefetch_related("docentes")
        .filter(institucion=inst)
        .exclude(nombre="DESCANSO")
        .order_by("semestre__carrera__nombre", "semestre__numero", "nombre")
    )

    def dividir_en_lotes_iter(qs, tamano):
        buf = []
        for a in qs.iterator(chunk_size=25):
            buf.append(a)
            if len(buf) >= tamano:
                yield buf
                buf = []
        if buf:
            yield buf

    errores = []

    # 5️⃣ Procesar en lotes pequeños
    for lote in dividir_en_lotes_iter(asignaturas_qs, 8):
        with transaction.atomic():
            docentes_por_asig = {a.id: list(a.docentes.all()) for a in lote}
            for asignatura in lote:
                docentes_precargados = docentes_por_asig.get(asignatura.id, [])
                ok, motivo = asignar_horario_automatico(
                    asignatura=asignatura,
                    horarios=todos_los_horarios,
                    no_disponibilidades=todas_las_no_disp,
                    descansos=todos_los_descansos,
                    usuario=request.user,
                    institucion=inst,
                    docentes_precargados=docentes_precargados,
                    con_motivo=True,
                )
                if not ok:
                    errores.append(f"{asignatura.nombre} → {motivo}")
        gc.collect()
        time.sleep(0.3)

    # 6️⃣ Crear descansos
    nuevos_descansos = []
    for d in todos_los_descansos:
        if d.hora_inicio < _time(13, 30):
            jornada = "Mañana"
        elif d.hora_inicio < _time(18, 15):
            jornada = "Tarde"
        else:
            jornada = "Noche"

        nuevos_descansos.append(
            Horario(
                usuario=request.user,
                institucion=inst,
                asignatura=asig_descanso,
                docente=docente_placeholder,
                aula=aula_placeholder,
                dia=d.dia,
                jornada=jornada,
                hora_inicio=d.hora_inicio,
                hora_fin=d.hora_fin,
            )
        )
    if nuevos_descansos:
        Horario.objects.bulk_create(nuevos_descansos)

    # 7️⃣ Mensaje final
    if errores:
        if len(errores) > 20:
            errores = errores[:20] + ["... (algunas asignaturas más sin espacio)"]
        for e in errores:
            messages.warning(request, e)
    else:
        messages.success(request, "✅ ¡Horarios generados exitosamente!")

    return redirect("..")
