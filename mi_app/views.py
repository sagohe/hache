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
                return redirect('/admin/')
    else:
        form = RegistrationForm()

    # ⬇️ usa tu plantilla real
    return render(request, 'register.html', {'form': form})


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
