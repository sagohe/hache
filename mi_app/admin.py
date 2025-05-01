from django.contrib import admin, messages
from django.contrib.admin import TabularInline
from django.shortcuts import redirect
from django.urls import path
from django.db import transaction
from django.db.models import Case, When, IntegerField
from .models import Docente, Asignatura, NoDisponibilidad, Aula, CarreraUniversitaria, Semestre, DiaSemana, Horario, Jornadas
from .utils import puede_asignar_horario, obtener_bloques_por_jornada, obtener_dias_disponibles_carrera
from datetime import datetime, timedelta, time
from django.utils.html import format_html


class SemestreInline(TabularInline):
    model = Semestre
    extra = 1


class AsignaturaAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'semestre', 'mostrar_docentes', 'aula', 'mostrar_jornadas', 'intensidad_horaria')
    list_filter = ('semestre__carrera', 'docentes', 'semestre', 'jornada')
    search_fields = ('nombre', 'semestre__numero', 'docentes__nombre')

    def mostrar_docentes(self, obj):
        return ", ".join([docente.nombre for docente in obj.docentes.all()])
    mostrar_docentes.short_description = "Docentes"

    def mostrar_jornadas(self, obj):
        return obj.jornada  # Es un campo de texto, no una relación

    mostrar_jornadas.short_description = "Jornada"

@admin.register(DiaSemana)
class DiaSemanaAdmin(admin.ModelAdmin):
    list_display = ('codigo', 'nombre')


class CarreraAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'mostrar_dias_clase')
    list_filter = ('dias_clase',)
    inlines = [SemestreInline]
    filter_horizontal = ('dias_clase',)

    def mostrar_dias_clase(self, obj):
        return ", ".join([d.nombre for d in obj.dias_clase.all()])
    mostrar_dias_clase.short_description = "Días de Clase"


admin.site.register(Asignatura, AsignaturaAdmin)
admin.site.register(CarreraUniversitaria, CarreraAdmin)
admin.site.register(Semestre)


class NoDisponibilidadInline(admin.TabularInline):
    model = NoDisponibilidad
    extra = 1
    verbose_name = "Horario NO disponible"
    verbose_name_plural = "Horarios en que el docente NO está disponible"


class DocenteAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'correo', 'mostrar_asignaturas', 'ver_horario_link')  # 👈 Añadimos la nueva columna
    search_fields = ('nombre', 'correo')
    readonly_fields = ('mostrar_asignaturas',)
    inlines = [NoDisponibilidadInline]

    def mostrar_asignaturas(self, obj):
        return ", ".join(asig.nombre for asig in obj.asignaturas_asignadas.all())
    mostrar_asignaturas.short_description = "Asignaturas"

    def ver_horario_link(self, obj):
        return format_html('<a class="button" href="/horarios-docente/{}/" target="_blank">Ver horario</a>', obj.id)
    ver_horario_link.short_description = "Horario"
    ver_horario_link.allow_tags = True


admin.site.register(Docente, DocenteAdmin)


class AulaAdmin(admin.ModelAdmin):
    list_display = ('nombre',)
    search_fields = ('nombre',)


admin.site.register(Aula, AulaAdmin)

admin.site.site_header = "HACHE"
admin.site.site_title = "HACHE"
admin.site.index_title = "Gestión de Hache"


class CarreraFilter(admin.SimpleListFilter):
    title = 'Carrera'
    parameter_name = 'carrera'

    def lookups(self, request, model_admin):
        carreras = CarreraUniversitaria.objects.all()
        return [(c.id, c.nombre) for c in carreras]

    def queryset(self, request, queryset):
        if self.value():
            return queryset.filter(asignatura__semestre__carrera__id=self.value())
        return queryset


DIAS_ORDENADOS = {
    "Lunes": 1,
    "Martes": 2,
    "Miércoles": 3,
    "Jueves": 4,
    "Viernes": 5,
    "Sábado": 6,
    "Domingo": 7,
}


class HorarioAdmin(admin.ModelAdmin):
    list_display = ("dia", "get_carrera", "get_semestre", "jornada", "asignatura", "docente", "aula", "hora_inicio", "hora_fin")
    list_filter = (CarreraFilter, "asignatura__semestre", "jornada", "dia")
    search_fields = ("asignatura__nombre", "docente__nombre", "aula__nombre")
    readonly_fields = ("dia", "hora_inicio", "hora_fin")
    change_list_template = 'admin/mi_app/horarios_change_list.html'

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        jornada_seleccionada = request.GET.get("jornada", None)

        dia_order = Case(
            *[When(dia=dia, then=valor) for dia, valor in DIAS_ORDENADOS.items()],
            default=99,
            output_field=IntegerField(),
        )

        if jornada_seleccionada:
            qs = qs.filter(jornada=jornada_seleccionada)

        return qs.annotate(dia_orden=dia_order).order_by("dia_orden", "asignatura__semestre__carrera__nombre", "asignatura__semestre__numero", "hora_inicio")

    def get_carrera(self, obj):
        return obj.asignatura.semestre.carrera.nombre
    get_carrera.short_description = "Carrera"

    def get_semestre(self, obj):
        return obj.asignatura.semestre.numero
    get_semestre.short_description = "Semestre"

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path('generar_horarios/', self.admin_site.admin_view(self.generar_horarios), name='generar_horarios'),
        ]
        return custom_urls + urls

    def generar_horarios(self, request):
          # Elimina todos los horarios previos
        Horario.objects.all().delete()
        
        asignaturas = Asignatura.objects.all()

        with transaction.atomic():
            for asignatura in asignaturas:
                minutos_disponibles = asignatura.intensidad_horaria  # intensidad en minutos
                docente = asignatura.docentes.first()
                jornada = asignatura.jornada
                aula = asignatura.aula
                semestre = asignatura.semestre
                carrera = semestre.carrera if semestre else None

                if not docente or not aula or not carrera:
                    print(f"[ERROR] La asignatura '{asignatura.nombre}' no tiene docente asignado.")
                    continue

                bloques = obtener_bloques_por_jornada(jornada)
                dias_disponibles = obtener_dias_disponibles_carrera(carrera)

                for dia in dias_disponibles:
                    if minutos_disponibles <= 0:
                        break

                    for hora_inicio in bloques:
                        duracion_bloque = min(minutos_disponibles, 300)  # intenta bloques de 300 minutos, o lo que quede
                        hora_fin = (datetime.combine(datetime.today(), hora_inicio) + timedelta(minutes=duracion_bloque)).time()

                        if puede_asignar_horario(docente, aula, asignatura, dia, jornada, hora_inicio, hora_fin):
                            Horario.objects.create(
                                asignatura=asignatura,
                                docente=docente,
                                aula=aula,
                                dia=dia,
                                jornada=jornada,
                                hora_inicio=hora_inicio,
                                hora_fin=hora_fin
                            )
                            minutos_disponibles -= duracion_bloque
                            if minutos_disponibles <= 0:
                                break

        messages.success(request, "¡Horarios generados exitosamente!")
        return redirect("..")


admin.site.register(Horario, HorarioAdmin)