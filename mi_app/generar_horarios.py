import gc
import time
from datetime import time as _time
from django.db import transaction
from django.shortcuts import redirect
from django.contrib import messages
from .models import (
    Institucion, Horario, NoDisponibilidad, Descanso, Asignatura
)
from .utils import (
    asignar_horario_automatico,
    obtener_asignatura_descanso,
    obtener_docente_placeholder,
    obtener_aula_placeholder,
)

def generar_horarios_view(request, admin_instance):
    """Genera horarios en lotes pequeños para evitar OOM o timeouts en Render"""

    # 1️⃣ Determinar institución (mantiene tu misma lógica original)
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

    # 2️⃣ Limpiar horarios previos del usuario + institución
    Horario.objects.filter(usuario=request.user, institucion=inst).delete()

    # 3️⃣ Cargar datos base de forma ligera
    todos_los_horarios_qs = (
        Horario.objects.filter(institucion=inst)
        .select_related('aula', 'dia', 'asignatura', 'docente')
    )

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
            'semestre_id': getattr(h.asignatura.semestre, "id", None),
        }
        for h in todos_los_horarios_qs.iterator(chunk_size=100)
    ]

    todas_las_no_disponibilidades = list(NoDisponibilidad.objects.filter(institucion=inst))
    todos_los_descansos = list(Descanso.objects.filter(institucion=inst, usuario=request.user))

    # 4️⃣ Objetos auxiliares (sin repetir consultas)
    asig_descanso = obtener_asignatura_descanso(inst)
    docente_placeholder = obtener_docente_placeholder()
    aula_placeholder = obtener_aula_placeholder()

    # 5️⃣ Traer asignaturas (sin usar iterator + prefetch juntos)
    asignaturas_qs = (
        Asignatura.objects
        .select_related('semestre__carrera')
        .prefetch_related('docentes')
        .filter(institucion=inst)
        .exclude(nombre="DESCANSO")
    )

    def dividir_en_lotes(qs, tamano):
        """Divide queryset en lotes pequeños para no agotar memoria"""
        buffer = []
        for asignatura in qs:  # sin iterator() aquí
            buffer.append(asignatura)
            if len(buffer) >= tamano:
                yield buffer
                buffer = []
        if buffer:
            yield buffer

    errores = []

    # 6️⃣ Procesar asignaturas en lotes de 10
    for lote in dividir_en_lotes(asignaturas_qs, 10):
        with transaction.atomic():
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

        # Liberar memoria gradualmente
        gc.collect()
        time.sleep(0.1)

    # 7️⃣ Crear descansos (igual que antes)
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
        Horario.objects.bulk_create(nuevos_descansos, batch_size=100)

    # 8️⃣ Mostrar mensajes finales
    if errores:
        for e in errores:
            messages.warning(request, e)
    else:
        messages.success(request, "¡Horarios generados exitosamente!")

    return redirect("..")
