from django.shortcuts import render, get_object_or_404, redirect
from .models import Horario, CarreraUniversitaria, Docente
from django.template.loader import render_to_string
from django.http import HttpResponse, HttpResponseForbidden
from weasyprint import HTML, CSS
from django.db.models import Q
from django.core.serializers.json import DjangoJSONEncoder
import json, os
from datetime import datetime, timedelta
from google_auth_oauthlib.flow import Flow
from django.conf import settings
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from django.utils.timezone import make_aware
import pytz
from django.contrib.auth.decorators import login_required
from django.urls import reverse

@login_required(login_url='/admin/login/')
def panel_inicio(request):
    if not request.user.is_staff:
        return HttpResponseForbidden("No tienes permiso para acceder a esta página.")
    return render(request, 'panel_inicio.html')

SCOPES = ['https://www.googleapis.com/auth/calendar']
BASE_DIR = settings.BASE_DIR

@login_required
def sincronizar_calendario_view(request, docente_id):
    credentials_data = request.session.get('google_credentials')
    if not credentials_data:
        return HttpResponse("Credenciales no encontradas en la sesión.", status=400)

    docente = get_object_or_404(Docente, id=docente_id)

    eventos_creados = sincronizar_calendario(docente, credentials_data)
    return HttpResponse(f"Sincronización completada. {eventos_creados} eventos creados.")

def autorizar_google(request, docente_id):
    flow = Flow.from_client_secrets_file(
        os.path.join(BASE_DIR, 'credentials.json'),
        scopes=SCOPES,
        redirect_uri='http://127.0.0.1:8000/oauth2callback/'
    )

    authorization_url, state = flow.authorization_url(
        access_type='offline',
        include_granted_scopes='true',
        prompt='consent'
    )

    request.session['state'] = state
    request.session['docente_id'] = docente_id  # Almacenar el ID del docente en la sesión
    request.session.save()

    return redirect(authorization_url)

def oauth2callback(request):
    try:
        os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'

        state = request.session.get('state')
        state_from_url = request.GET.get('state')

        if not state or state != state_from_url:
            return HttpResponse("Estado inválido. Inicia el proceso desde el principio.", status=400)

        flow = Flow.from_client_secrets_file(
            os.path.join(BASE_DIR, 'credentials.json'),
            scopes=SCOPES,
            state=state,
            redirect_uri='http://127.0.0.1:8000/oauth2callback/'
        )

        flow.fetch_token(authorization_response=request.build_absolute_uri())
        credentials = flow.credentials

        request.session['google_credentials'] = {
            'token': credentials.token,
            'refresh_token': credentials.refresh_token,
            'token_uri': credentials.token_uri,
            'client_id': credentials.client_id,
            'client_secret': credentials.client_secret,
            'scopes': credentials.scopes
        }

        docente_id = request.session.get('docente_id')
        if not docente_id:
            return HttpResponse("ID del docente no encontrado en la sesión.", status=400)

        return redirect('sincronizar_calendario', docente_id=docente_id)

    except Exception as e:
        return HttpResponse(f"Error durante la autorización: {str(e)}", status=500)
    

# Mapeo de los días de la semana en texto a números (0=Lunes, 1=Martes, ..., 6=Domingo)
DIA_SEMANA_MAP = {
    'Lunes': 0,
    'Martes': 1,
    'Miércoles': 2,
    'Jueves': 3,
    'Viernes': 4,
    'Sábado': 5,
    'Domingo': 6,
}
GOOGLE_WEEKDAYS = {
    'Lunes': 'MO',
    'Martes': 'TU',
    'Miércoles': 'WE',
    'Jueves': 'TH',
    'Viernes': 'FR',
    'Sábado': 'SA',
    'Domingo': 'SU',
}

def inicio(request):
    horarios = Horario.objects.all().order_by('dia', 'hora_inicio')
    return render(request, 'inicio.html', {'horarios': horarios})


def sincronizar_calendario(docente, credentials):
    """Sincroniza los horarios del docente con Google Calendar."""
    creds = Credentials.from_authorized_user_info(info=credentials)  # Cargar las credenciales
    service = build("calendar", "v3", credentials=creds)  # Conectar con la API de Google Calendar

    zona_horario = "America/Bogota"
    tz = pytz.timezone(zona_horario)  # Zona horaria

    # Mapeo de días de la semana para Google Calendar
    dias_semana = {
        'Lunes': 'MO', 'Martes': 'TU', 'Miércoles': 'WE', 'Jueves': 'TH',
        'Viernes': 'FR', 'Sábado': 'SA', 'Domingo': 'SU'
    }

    # Filtrar los horarios del docente
    horarios = Horario.objects.filter(docente=docente)
    eventos_creados = 0

    # Crear los eventos en Google Calendar
    for horario in horarios:
        asignatura = horario.asignatura
        dia_codigo = dias_semana.get(horario.dia)
        if not dia_codigo:
            continue

        hoy = datetime.now(tz)
        dia_actual = hoy.weekday()
        dia_objetivo = list(dias_semana.keys()).index(horario.dia)
        dias_diferencia = (dia_objetivo - dia_actual) % 7
        fecha_clase = hoy + timedelta(days=dias_diferencia)

        # Ajustar la hora de inicio y fin
        inicio_datetime = tz.localize(datetime.combine(fecha_clase.date(), horario.hora_inicio))
        fin_datetime = tz.localize(datetime.combine(fecha_clase.date(), horario.hora_fin))

        # Duración del evento semanal
        semanas_duracion = 16  # Duración por 16 semanas
        fin_recurrencia = (inicio_datetime + timedelta(weeks=semanas_duracion)).strftime("%Y%m%dT%H%M%SZ")

        # Crear el evento para Google Calendar
        evento = {
            'summary': f'{asignatura.nombre} - {docente.nombre}',
            'location': horario.aula.nombre if horario.aula else '',
            'description': f'Clase semanal de {asignatura.nombre}',
            'start': {
                'dateTime': inicio_datetime.isoformat(),
                'timeZone': zona_horario,
            },
            'end': {
                'dateTime': fin_datetime.isoformat(),
                'timeZone': zona_horario,
            },
            'recurrence': [
                f'RRULE:FREQ=WEEKLY;UNTIL={fin_recurrencia};BYDAY={dia_codigo}'
            ],
        }

        # Insertar el evento en Google Calendar
        try:
            service.events().insert(calendarId='primary', body=evento).execute()
            eventos_creados += 1
        except Exception as e:
            print("Error creando evento:", e)

    return eventos_creados


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


# Exportar todos los horarios a PDF con filtros
def exportar_horarios_pdf(request, docente_id):
    # Filtrar los horarios del docente específico
    queryset = Horario.objects.select_related("asignatura", "docente", "aula").filter(docente_id=docente_id)

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
    
    # Crear el HTML para el PDF
    html_string = render_to_string("pdf_horarios.html", {"horarios": horarios})

    # Generar el PDF con WeasyPrint
    pdf = HTML(string=html_string).write_pdf(stylesheets=[CSS(string='@page { size: 297mm 210mm; margin: 1cm; }')])

    # Crear la respuesta HTTP con el PDF
    response = HttpResponse(pdf, content_type="application/pdf")
    response["Content-Disposition"] = "inline; filename=horarios_filtrados.pdf"
    return response

# Vista clásica de horario del docente, agrupado por día
def horario_docente(request, docente_id):
    docente = get_object_or_404(Docente, id=docente_id)
    
    # Optimización de consultas con select_related
    horarios = Horario.objects.filter(docente=docente).select_related(
        'asignatura__semestre__carrera', 
        'aula'
    ).order_by('dia', 'hora_inicio')

    # Estructura para agrupar por día (vista clásica)
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
