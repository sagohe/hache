from django.contrib import admin, messages
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
    Institucion, PerfilUsuario,
    Docente, Asignatura, NoDisponibilidad, Aula,
    CarreraUniversitaria, Semestre, DiaSemana, Horario, Descanso
)
import gc,time
from django.shortcuts import redirect

def generar_horarios_view(request, admin_instance):
    """Genera horarios en lotes pequeños para evitar OOM en Render"""

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
        if hasattr(request.user, "perfil") and request.user.perfil and request.user.perfil.institucion_id:
            inst = request.user.perfil.institucion
        else:
            messages.error(request, "Tu usuario no tiene institución asociada.")
            return redirect("..")

    # 2️⃣ Limpiar horarios anteriores
    Horario.objects.filter(usuario=request.user, institucion=inst).delete()

    # 3️⃣ Cargar datos base
    todos_los_horarios = list(Horario.objects.filter(institucion=inst))
    todas_las_no_disponibilidades = list(NoDisponibilidad.objects.filter(institucion=inst))
    todos_los_descansos = list(Descanso.objects.filter(institucion=inst, usuario=request.user))
    asig_descanso = obtener_asignatura_descanso(inst)
    docente_placeholder = obtener_docente_placeholder()
    aula_placeholder = obtener_aula_placeholder()

    asignaturas = list(
        Asignatura.objects
        .select_related('semestre__carrera')
        .prefetch_related('docentes')
        .filter(institucion=inst)
        .exclude(nombre="DESCANSO")
        )
    docentes_por_asig = {a.id: list(a.docentes.all()) for a in asignaturas}

    # 🧩 Dividir en lotes
    def dividir_en_lotes(iterable, tamano):
        for i in range(0, len(iterable), tamano):
            yield iterable[i:i + tamano]

    errores = []

    # 🧠 Procesar por lotes
    def procesar_lote(lote):
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

    for lote in dividir_en_lotes(asignaturas, 10):
        with transaction.atomic():
            procesar_lote(lote)
        gc.collect()
        time.sleep(0.3)

    # 🕒 Crear descansos materializados
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
        todos_los_horarios.extend(nuevos_descansos)

    # ✅ Mensajes finales
    if errores:
        for e in errores:
            messages.warning(request, e)
    else:
        messages.success(request, "¡Horarios generados exitosamente!")

    return redirect("..")


