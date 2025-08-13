from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth import login as auth_login
from .forms import RegistrationForm
from django.http import HttpResponse
from weasyprint import HTML
from django.template.loader import get_template

from django.db import transaction

from .models import (
    Horario, CarreraUniversitaria, Docente, Asignatura, Institucion,PerfilUsuario,Aula, DiaSemana, HorarioGuardado, NoDisponibilidad
)
from .utils import asignar_horario_automatico


# ============ AUTENTICACIÓN (REGISTRO SIMPLE) ============
def register(request):
    """
    Registro con institución:
    - Crear institución (genera slug/código único)
    - Unirse con código (slug)
    """
    if request.method == 'POST':
        form = RegistrationForm(request.POST)
        if form.is_valid():
            with transaction.atomic():
                user = form.save(commit=False)
                # Para que pueda entrar al admin “abierto”
                user.is_staff = True
                user.is_superuser = False
                user.save()

                modo = form.cleaned_data['modo']
                if modo == 'crear':
                    nombre = form.cleaned_data['institucion_nombre']
                    slug_unico = RegistrationForm.slug_unico(nombre)
                    inst = Institucion.objects.create(nombre=nombre.strip(), slug=slug_unico)
                else:
                    codigo = form.cleaned_data['institucion_codigo'].strip().lower()
                    inst = Institucion.objects.get(slug=codigo)

                PerfilUsuario.objects.get_or_create(user=user, defaults={"institucion": inst})

                auth_login(request, user)
                messages.success(
                    request,
                    f"Cuenta creada. ¡Bienvenido! Tu institución es '{inst.nombre}' (código: {inst.slug})."
                )
                return redirect('panel_usuario')
    else:
        form = RegistrationForm()

    # ⬇️ usa tu plantilla real
    return render(request, 'register.html', {'form': form})

# ============ PANEL DE USUARIO ============
@login_required
def panel_usuario(request):
    return render(request, 'panel_usuario.html')


@login_required
def mi_horario(request):
    """
    Lista SIEMPRE el horario del usuario actual (persistente).
    """
    filas = (Horario.objects
             .filter(usuario=request.user)
             .select_related('asignatura__semestre__carrera', 'docente', 'aula', 'dia')
             .order_by('dia__orden', 'hora_inicio'))
    return render(request, 'mi_horario.html', {'horarios': filas})


# ============ GENERAR / REGENERAR POR USUARIO ============
@login_required
def generar_mi_horario(request):
    if Horario.objects.filter(usuario=request.user).exists():
        messages.info(request, "Ya tienes un horario. Si deseas reemplazarlo, usa 'Regenerar'.")
        return redirect('mi_horario')

    errores = _generar_para_usuario(request.user)
    if errores:
        for e in errores:
            messages.warning(request, e)
    else:
        messages.success(request, "Horario generado.")
    return redirect('mi_horario')


@login_required
def regenerar_mi_horario(request):
    Horario.objects.filter(usuario=request.user).delete()
    errores = _generar_para_usuario(request.user)
    if errores:
        for e in errores:
            messages.warning(request, e)
    else:
        messages.success(request, "Horario regenerado.")
    return redirect('mi_horario')


def _generar_para_usuario(user):
    """
    Punto CLAVE: ahora todo se filtra por 'usuario=user'
    para NO mezclar datos de distintas cuentas.
    """
    asignaturas = (Asignatura.objects
                   .filter(usuario=user)
                   .select_related('semestre__carrera', 'aula')
                   .prefetch_related('docentes'))

    # Solo los horarios del usuario para validaciones en memoria
    todos_los_horarios = list(
        Horario.objects.filter(usuario=user).select_related(
            'docente', 'aula', 'asignatura__semestre__carrera'
        )
    )

    # Solo no disponibilidades del usuario
    todas_las_no_disp = list(
        NoDisponibilidad.objects.filter(usuario=user).select_related('docente')
    )

    errores = []
    with transaction.atomic():
        for asignatura in asignaturas:
            ok, motivo = asignar_horario_automatico(
                asignatura=asignatura,
                horarios=todos_los_horarios,
                no_disponibilidades=todas_las_no_disp,
                usuario=user,
                con_motivo=True,
            )
            if not ok:
                errores.append(f"{asignatura.nombre} → {motivo}")
    return errores


# ============ Snapshots ============
@login_required
def guardar_horario(request):
    if request.method == "POST":
        nombre = request.POST.get("nombre", "Mi horario")
        filas = (Horario.objects
                 .filter(usuario=request.user)
                 .select_related("asignatura__semestre__carrera", "docente", "aula", "dia"))

        datos = []
        for h in filas:
            datos.append({
                "asignatura_id": h.asignatura_id,
                "docente_id": h.docente_id,
                "aula_id": h.aula_id,
                "dia_id": h.dia_id,
                "jornada": h.jornada,
                "hora_inicio": str(h.hora_inicio) if h.hora_inicio else None,
                "hora_fin": str(h.hora_fin) if h.hora_fin else None,
            })

        HorarioGuardado.objects.create(
            usuario=request.user,
            nombre=nombre,
            datos=datos
        )
        messages.success(request, "Horario guardado correctamente.")
        return redirect("mis_horarios")

    return render(request, "guardar_horario.html")


@login_required
def mis_horarios(request):
    guardados = HorarioGuardado.objects.filter(usuario=request.user).order_by("-fecha_creacion")
    return render(request, "mis_horarios.html", {"guardados": guardados})


@login_required
def cargar_horario(request, horario_id):
    hg = get_object_or_404(HorarioGuardado, id=horario_id, usuario=request.user)
    Horario.objects.filter(usuario=request.user).delete()
    for item in hg.datos:
        Horario.objects.create(
            usuario=request.user,
            asignatura_id=item["asignatura_id"],
            docente_id=item["docente_id"],
            aula_id=item["aula_id"],
            dia_id=item["dia_id"],
            jornada=item["jornada"],
            hora_inicio=item["hora_inicio"],
            hora_fin=item["hora_fin"],
        )
    messages.success(request, f"Horario '{hg.nombre}' cargado.")
    return redirect("mi_horario")


# ============ Vistas “públicas” per-user ============
@login_required
def panel_inicio(request):
    return render(request, 'panel_inicio.html')


@login_required
def inicio(request):
    """
    Muestra SOLO mis horarios
    """
    horarios = (Horario.objects
                .filter(usuario=request.user)
                .select_related('asignatura__semestre__carrera', 'docente', 'aula', 'dia')
                .order_by('dia__orden', 'hora_inicio'))
    return render(request, 'inicio.html', {'horarios': horarios})


@login_required
def horarios_admin(request):
    """
    Vista de “listado por día” pero SIEMPRE dentro de mis datos.
    """
    carrera_id = request.GET.get('carrera')
    carreras = CarreraUniversitaria.objects.filter(usuario=request.user)

    qs = (Horario.objects
          .filter(usuario=request.user)
          .select_related('asignatura__semestre__carrera', 'docente', 'aula', 'dia'))

    if carrera_id:
        qs = qs.filter(asignatura__semestre__carrera__id=carrera_id)

    qs = qs.order_by("dia__orden", "hora_inicio")

    horarios_por_dia = {}
    for h in qs:
        horarios_por_dia.setdefault(h.dia, []).append(h)

    context = {
        'horarios_por_dia': horarios_por_dia,
        'carreras': carreras,
        'carrera_seleccionada': int(carrera_id) if carrera_id else None,
    }
    return render(request, 'admin/horarios.html', context)


@login_required
def ver_horarios(request):
    """
    Igual que arriba: vista “pública” pero solo mis horarios.
    """
    carrera_id = request.GET.get("carrera")
    carreras_disponibles = CarreraUniversitaria.objects.filter(usuario=request.user)

    qs = (Horario.objects
          .filter(usuario=request.user)
          .select_related('asignatura__semestre__carrera', 'docente', 'aula', 'dia'))

    if carrera_id:
        qs = qs.filter(asignatura__semestre__carrera__id=carrera_id)

    qs = qs.order_by("dia__orden", "hora_inicio")

    horarios_por_dia = {}
    for h in qs:
        horarios_por_dia.setdefault(h.dia, []).append(h)

    return render(request, "horarios.html", {
        "horarios_por_dia": horarios_por_dia,
        "carreras_disponibles": carreras_disponibles,
        "request": request
    })


@login_required
def horario_docente(request, docente_id):
    """
    Horarios de un docente, pero SOLO dentro de mis datos.
    """
    docente = get_object_or_404(Docente, id=docente_id, usuario=request.user)
    horarios = (Horario.objects
                .filter(usuario=request.user, docente=docente)
                .select_related('asignatura__semestre__carrera', 'aula', 'dia')
                .order_by('dia__orden', 'hora_inicio'))

    horarios_por_dia = {}
    for h in horarios:
        horarios_por_dia.setdefault(h.dia, []).append(h)

    context = {
        'docente': docente,
        'horarios_por_dia': horarios_por_dia,
    }
    return render(request, 'admin/mi_app/horario_docente.html', context)


@login_required
def exportar_horarios_pdf(request):
    """
    Exporta SOLO el horario del usuario autenticado.
    """
    queryset = (Horario.objects
                .filter(usuario=request.user)
                .select_related('asignatura__semestre__carrera', 'docente', 'aula', 'dia')
                .order_by('dia__orden', 'hora_inicio'))

    template = get_template("pdf_horarios.html")
    html_string = template.render({"horarios": queryset, "usuario": request.user})

    pdf_file = HTML(string=html_string).write_pdf()

    response = HttpResponse(pdf_file, content_type='application/pdf')
    response['Content-Disposition'] = 'attachment; filename="mi_horario.pdf"'
    return response
