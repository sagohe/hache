from django.shortcuts import render, get_object_or_404
from .models import Horario, CarreraUniversitaria, Docente
from django.template.loader import render_to_string
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, HttpResponseForbidden
from weasyprint import HTML, CSS
from django.db.models import Q


@login_required(login_url='/admin/login/')
def panel_inicio(request):
    if not request.user.is_staff:
        return HttpResponseForbidden("No tienes permiso para acceder a esta página.")
    return render(request, 'panel_inicio.html')

    
def inicio(request):
    horarios = Horario.objects.all().order_by('dia', 'hora_inicio')
    return render(request, 'inicio.html', {'horarios': horarios})


def horarios_admin(request):
    """Vista administrativa para visualizar los horarios agrupados por día."""
    carrera_id = request.GET.get('carrera')
    carreras = CarreraUniversitaria.objects.all()

    if carrera_id:
        horarios = Horario.objects.filter(asignatura__semestre__carrera__id=carrera_id)
    else:
        horarios = Horario.objects.all()

    # Ordenar los horarios por día y hora de inicio
    horarios = horarios.order_by("dia", "hora_inicio")

    # Agrupar los horarios por día
    horarios_por_dia = {}
    for horario in horarios:
        if horario.dia not in horarios_por_dia:
            horarios_por_dia[horario.dia] = []
        horarios_por_dia[horario.dia].append(horario)

    context = {
        'horarios_por_dia': horarios_por_dia,
        'carreras': carreras,
        'carrera_seleccionada': int(carrera_id) if carrera_id else None,
    }

    return render(request, 'admin/horarios.html', context)


# Vista para ver horarios organizados por día
def ver_horarios(request):
    carrera_id = request.GET.get("carrera")
    carreras_disponibles = CarreraUniversitaria.objects.all()

    if carrera_id:
        horarios = Horario.objects.filter(asignatura__semestre__carrera__id=carrera_id)
    else:
        horarios = Horario.objects.all()

    horarios = horarios.order_by("dia", "hora_inicio")
    horarios_por_dia = {}

    for horario in horarios:
        if horario.dia not in horarios_por_dia:
            horarios_por_dia[horario.dia] = []
        horarios_por_dia[horario.dia].append(horario)

    return render(request, "horarios.html", {
        "horarios_por_dia": horarios_por_dia,
        "carreras_disponibles": carreras_disponibles,
        "request": request
    })

def horario_docente(request, docente_id):
    docente = get_object_or_404(Docente, id=docente_id)
    horarios = Horario.objects.filter(docente=docente).select_related(
        'asignatura__semestre__carrera', 
        'aula'
    ).order_by('dia', 'hora_inicio')

    horarios_por_dia = {}
    for horario in horarios:
        if horario.dia not in horarios_por_dia:
            horarios_por_dia[horario.dia] = []
        horarios_por_dia[horario.dia].append(horario)

    context = {
        'docente': docente,
        'horarios_por_dia': horarios_por_dia,
    }
    return render(request, 'admin/mi_app/horario_docente.html', context)

# Exportar todos los horarios a PDF con filtros
def exportar_horarios_pdf(request, docente_id=None):
    queryset = Horario.objects.select_related("asignatura", "docente", "aula")

    if docente_id:
        queryset = queryset.filter(docente_id=docente_id)

    filters = {}
    for key in request.GET:
        if key == "q":
            continue
        value = request.GET.get(key)
        if value:
            filters[key] = value

    try:
        queryset = queryset.filter(**filters)
    except Exception as e:
        return HttpResponse(f"Error al aplicar filtros: {e}", status=500)

    q = request.GET.get("q")
    if q:
        queryset = queryset.filter(
            Q(asignatura__nombre__icontains=q) |
            Q(docente__nombre__icontains=q) |
            Q(aula__nombre__icontains=q)
        )

    horarios = queryset.order_by("dia", "hora_inicio")

    html_string = render_to_string("pdf_horarios.html", {"horarios": horarios})
    pdf = HTML(string=html_string).write_pdf(stylesheets=[CSS(string='@page { size: 297mm 210mm; margin: 1cm; }')])

    response = HttpResponse(pdf, content_type="application/pdf")
    response["Content-Disposition"] = "inline; filename=horarios_filtrados.pdf"
    return response