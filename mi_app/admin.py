from django.contrib import admin, messages
from django.contrib.admin import TabularInline
from django.shortcuts import redirect
from django.urls import path
from django.db import transaction
from django.db.models import Case, When, IntegerField, Value
from .models import Docente, Asignatura, NoDisponibilidad, Aula, CarreraUniversitaria, Semestre, DiaSemana, Horario
from .utils import asignar_horario_automatico
from django.utils.html import format_html
from django import forms
#admin.site.register(Asignatura)

#dia de clase
class SemestreInline(TabularInline):
    model = Semestre
    extra = 1
    
class AsignaturaForm(forms.ModelForm):
    class Meta:
        model = Asignatura
        fields = '__all__'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in ('semestre', 'aula'):
            if field in self.fields:
                widget = self.fields[field].widget
                for attr in (
                    'can_add_related',
                    'can_change_related',
                    'can_view_related',
                    'can_delete_related',  # ✅ Esta es la que faltaba
                ):
                    setattr(widget, attr, False)
class AsignaturaAdmin(admin.ModelAdmin):
    form = AsignaturaForm

    list_display = ('nombre', 'semestre', 'mostrar_docentes', 'aula', 'mostrar_jornadas', 'intensidad_horaria')
    list_filter = ('semestre__carrera', 'docentes', 'semestre', 'jornada')
    search_fields = ('nombre', 'semestre__numero', 'docentes__nombre')
    
    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.prefetch_related('docentes', 'semestre', 'aula')


    def mostrar_docentes(self, obj):
        return ", ".join(docente.nombre for docente in obj.docentes.all())
    mostrar_docentes.short_description = "Docentes"

    def mostrar_jornadas(self, obj):
        return obj.jornada
    mostrar_jornadas.short_description = "Jornada"
    
    
@admin.register(DiaSemana)
class DiaSemanaAdmin(admin.ModelAdmin):
    list_display = ('codigo', 'nombre', 'orden')
    ordering = ('orden',)  # Esto asegura que se muestren ordenados

class CarreraAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'mostrar_dias_clase')
    list_filter = ('dias_clase',)
    inlines = [SemestreInline]
    filter_horizontal = ('dias_clase',)

    def mostrar_dias_clase(self, obj):
        return ", ".join([d.nombre for d in obj.dias_clase.all().order_by('orden')])
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
    "Miercoles": 3,
    "Jueves": 4,
    "Viernes": 5,
    "Sabado": 6,
    "Domingo": 7,
}
# Obtener los días desde la base de datos y construir el mapeo
def obtener_orden_dias():
    dias = DiaSemana.objects.all()
    return {
        dia: DIAS_ORDENADOS.get(dia.nombre, 99)
        for dia in dias
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

        # Obtener los objetos DiaSemana con sus nombres
        dia_ordenes = obtener_orden_dias()

        dia_order = Case(
            *[When(dia=dia_obj, then=orden) for dia_obj, orden in dia_ordenes.items()],
            default=99,
            output_field=IntegerField()
        )

        if jornada_seleccionada:
            qs = qs.filter(jornada=jornada_seleccionada)

        return qs.annotate(dia_orden=dia_order).order_by(
            "dia_orden", 
            "asignatura__semestre__carrera__nombre", 
            "asignatura__semestre__numero", 
            "hora_inicio"
        )
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
        Horario.objects.all().delete()
        asignaturas = Asignatura.objects.select_related(
            'semestre__carrera', 'aula'
        ).prefetch_related('docentes').all()

        errores = []

        # ✅ Paso 1: precargar datos en memoria
        todos_los_horarios = list(Horario.objects.select_related(
            'docente', 'aula', 'asignatura__semestre__carrera'
        ))

        todas_las_no_disponibilidades = list(NoDisponibilidad.objects.select_related('docente'))

        with transaction.atomic():
            for asignatura in asignaturas:
                exito = asignar_horario_automatico(
                    asignatura,
                    todos_los_horarios,
                    todas_las_no_disponibilidades
                )
                if not exito:
                    errores.append(f"No se pudo asignar horario para la asignatura '{asignatura.nombre}'")

        if errores:
            for e in errores:
                messages.warning(request, e)
        else:
            messages.success(request, "¡Horarios generados exitosamente!")

        return redirect("..")

admin.site.register(Horario, HorarioAdmin)
#asignaturas