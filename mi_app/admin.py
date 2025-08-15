from django.contrib import admin, messages
from django.contrib.admin import TabularInline
from django.shortcuts import redirect
from django.urls import path
from django.db import transaction
from django.db.models import Case, When, IntegerField, Value, F
from django.utils.html import format_html
from django import forms
from datetime import time as _time
from django.db.models.functions import Coalesce
from .models import (
    Institucion, PerfilUsuario,
    Docente, Asignatura, NoDisponibilidad, Aula,
    CarreraUniversitaria, Semestre, DiaSemana, Horario, Descanso
)
from .utils import asignar_horario_automatico

# === auth admin visibles solo para superuser ===
from django.contrib.auth.models import User, Group
from django.contrib.auth.admin import UserAdmin, GroupAdmin


# ==========================
# Abrir admin a staff (sin mapear permisos)
# ==========================
class OpenToStaffAdminMixin:
    def has_module_permission(self, request):
        return request.user.is_staff or request.user.is_superuser

    def get_model_perms(self, request):
        if request.user.is_superuser:
            return super().get_model_perms(request)
        return {'add': True, 'change': True, 'delete': True, 'view': True}

    def has_view_permission(self, request, obj=None):
        return request.user.is_superuser or request.user.is_staff

    def has_add_permission(self, request):
        return request.user.is_superuser or request.user.is_staff

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser or request.user.is_staff

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser or request.user.is_staff


# ==========================
# Mixin multi-tenant por institución
# ==========================
class TenantScopedAdminMixin(OpenToStaffAdminMixin):
    """
    - Oculta el campo 'institucion'
    - Asigna institucion=request.user.perfil.institucion al guardar
    - Filtra queryset por la institución (para staff)
    - Filtra FKs/M2M a registros de la misma institución
    """
    tenant_field = 'institucion'

    def _tenant(self, request):
        return getattr(getattr(request.user, 'perfil', None), 'institucion', None)

    def get_form(self, request, obj=None, **kwargs):
        # Esconde el campo institucion
        if any(f.name == self.tenant_field for f in self.model._meta.fields):
            excl = set(kwargs.get('exclude') or ())
            excl.add(self.tenant_field)
            kwargs['exclude'] = tuple(excl)
        return super().get_form(request, obj, **kwargs)

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        if any(f.name == self.tenant_field for f in self.model._meta.fields):
            tenant = self._tenant(request)
            qs = qs.filter(**{self.tenant_field: tenant})
        return qs

    def save_model(self, request, obj, form, change):
        if any(f.name == self.tenant_field for f in self.model._meta.fields):
            if getattr(obj, self.tenant_field, None) is None:
                setattr(obj, self.tenant_field, self._tenant(request))
        super().save_model(request, obj, form, change)

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        field = super().formfield_for_foreignkey(db_field, request, **kwargs)
        if request.user.is_superuser:
            return field
        rel_model = db_field.remote_field.model
        if hasattr(rel_model, '_meta') and any(f.name == 'institucion' for f in rel_model._meta.fields):
            tenant = self._tenant(request)
            field.queryset = rel_model.objects.filter(institucion=tenant)
        return field

    def formfield_for_manytomany(self, db_field, request, **kwargs):
        field = super().formfield_for_manytomany(db_field, request, **kwargs)
        if request.user.is_superuser:
            return field
        rel_model = db_field.remote_field.model
        if hasattr(rel_model, '_meta') and any(f.name == 'institucion' for f in rel_model._meta.fields):
            tenant = self._tenant(request)
            field.queryset = rel_model.objects.filter(institucion=tenant)
        return field


# ==========================
# OCULTAR "Instituciones" del admin (no se muestra)
# ==========================
# Si estaba registrado en algún momento, lo desregistramos por si acaso.
try:
    admin.site.unregister(Institucion)
except admin.sites.NotRegistered:
    pass
# (No registramos Institucion de nuevo)


# ==========================
# "Perfil de usuario" SOLO LECTURA (visible SOLO para staff, oculto a superuser)
# ==========================
class PerfilSoloLecturaAdmin(admin.ModelAdmin):
    list_display = ("user", "institucion")
    search_fields = ("user__username", "institucion__nombre")

    # Mostrar módulo solo a staff normal (no a superusuario)
    def has_module_permission(self, request):
        return request.user.is_staff and not request.user.is_superuser

    # Permisos: solo ver
    def has_view_permission(self, request, obj=None):
        return request.user.is_staff and not request.user.is_superuser

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        # Sin permisos de edición
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    # Cada usuario staff solo ve su propio perfil
    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            # superuser no verá el módulo (has_module_permission False), pero igual limitamos
            return qs.none()
        return qs.filter(user=request.user)

admin.site.register(PerfilUsuario, PerfilSoloLecturaAdmin)


# ==========================
# Descansi
# ==========================
@admin.register(Descanso)
class DescansoAdmin(TenantScopedAdminMixin, admin.ModelAdmin):
    list_display = ("nombre", "usuario", "institucion", "dia", "hora_inicio", "hora_fin")
    list_filter = ("dia__institucion", "dia",)
    search_fields = ("nombre", "dia__nombre", "usuario__username")
    ordering = ("dia__orden", "hora_inicio")

    # Suministra initial también aquí (se usa al abrir el formulario "Agregar")
    def get_changeform_initial_data(self, request):
        data = super().get_changeform_initial_data(request)
        if hasattr(request.user, "perfil") and request.user.perfil and request.user.perfil.institucion_id:
            data.setdefault("institucion", request.user.perfil.institucion_id)
        data.setdefault("usuario", request.user.id)
        return data

    # Usamos get_form base, marcamos campos ocultos y NO requeridos (el modelo los exige pero los fijamos en save_model)
    def get_form(self, request, obj=None, **kwargs):
        form = admin.ModelAdmin.get_form(self, request, obj, **kwargs)

        if 'usuario' in form.base_fields:
            form.base_fields['usuario'].required = False
            form.base_fields['usuario'].widget = forms.HiddenInput()
            if not obj:
                form.base_fields['usuario'].initial = request.user

        if 'institucion' in form.base_fields:
            form.base_fields['institucion'].required = False
            form.base_fields['institucion'].widget = forms.HiddenInput()
            if not obj and hasattr(request.user, 'perfil') and request.user.perfil.institucion_id:
                form.base_fields['institucion'].initial = request.user.perfil.institucion

        return form

    def save_model(self, request, obj, form, change):
        # Fijar SIEMPRE antes de validar modelo/guardar
        if getattr(obj, 'usuario_id', None) is None:
            obj.usuario = request.user
        if getattr(obj, 'institucion_id', None) is None and hasattr(request.user, 'perfil'):
            obj.institucion = request.user.perfil.institucion
        super().save_model(request, obj, form, change)


# ==========================
# Inlines
# ==========================
class SemestreInline(TabularInline):
    model = Semestre
    extra = 1

    # Ocultar institucion en el inline
    def get_formset(self, request, obj=None, **kwargs):
        excl = set(kwargs.get('exclude') or ())
        excl.add('institucion')
        kwargs['exclude'] = tuple(excl)
        return super().get_formset(request, obj, **kwargs)


# ==========================
# Asignatura
# ==========================
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
                    'can_add_related', 'can_change_related',
                    'can_view_related', 'can_delete_related',
                ):
                    setattr(widget, attr, False)


class AsignaturaAdmin(TenantScopedAdminMixin, admin.ModelAdmin):
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


# ==========================
# Día de la semana
# ==========================
@admin.register(DiaSemana)
class DiaSemanaAdmin(TenantScopedAdminMixin, admin.ModelAdmin):
    list_display = ('codigo', 'nombre', 'orden')
    ordering = ('orden',)


# ==========================
# Carrera (con Semestres inline)
# ==========================
class CarreraAdmin(TenantScopedAdminMixin, admin.ModelAdmin):
    list_display = ('nombre', 'mostrar_dias_clase')
    list_filter = ('dias_clase',)
    inlines = [SemestreInline]
    filter_horizontal = ('dias_clase',)

    def mostrar_dias_clase(self, obj):
        return ", ".join([d.nombre for d in obj.dias_clase.all().order_by('orden')])
    mostrar_dias_clase.short_description = "Días de Clase"


admin.site.register(Asignatura, AsignaturaAdmin)
admin.site.register(CarreraUniversitaria, CarreraAdmin)


class SemestreAdmin(TenantScopedAdminMixin, admin.ModelAdmin):
    list_display = ('numero', 'carrera')
    list_filter = ('carrera',)
    search_fields = ('numero', 'carrera__nombre')

admin.site.register(Semestre, SemestreAdmin)


# ==========================
# No Disponibilidad (inline en Docente)
# ==========================
class NoDisponibilidadInline(TabularInline):
    model = NoDisponibilidad
    extra = 1
    verbose_name = "Horario NO disponible"
    verbose_name_plural = "Horarios en que el docente NO está disponible"

    def get_formset(self, request, obj=None, **kwargs):
        excl = set(kwargs.get('exclude') or ())
        excl.add('institucion')
        kwargs['exclude'] = tuple(excl)
        return super().get_formset(request, obj, **kwargs)

    def save_formset(self, request, form, formset, change):
        instances = formset.save(commit=False)
        inst = getattr(request.user, 'perfil', None)
        tenant = getattr(inst, 'institucion', None)
        for i in instances:
            if getattr(i, 'institucion_id', None) is None:
                i.institucion = tenant
            i.save()
        for obj in formset.deleted_objects:
            obj.delete()
        formset.save_m2m()


# ==========================
# Docente
# ==========================
class DocenteAdmin(TenantScopedAdminMixin, admin.ModelAdmin):
    list_display = ('nombre', 'correo', 'mostrar_asignaturas', 'ver_horario_link')
    search_fields = ('nombre', 'correo')
    inlines = [NoDisponibilidadInline]

    def mostrar_asignaturas(self, obj):
        return ", ".join(asig.nombre for asig in obj.asignaturas_asignadas.all())
    mostrar_asignaturas.short_description = "Asignaturas"

    def ver_horario_link(self, obj):
        return format_html('<a class="button" href="/horarios-docente/{}/" target="_blank">Ver horario</a>', obj.id)
    ver_horario_link.short_description = "Horario"
    ver_horario_link.allow_tags = True


admin.site.register(Docente, DocenteAdmin)


# ==========================
# Aula
# ==========================
class AulaAdmin(TenantScopedAdminMixin, admin.ModelAdmin):
    list_display = ('nombre',)
    search_fields = ('nombre',)


admin.site.register(Aula, AulaAdmin)


# ==========================
# Títulos
# ==========================
admin.site.site_header = "HACHE"
admin.site.site_title = "HACHE"
admin.site.index_title = "Gestión de Hache"


# ==========================
# Utilidades para Horario
# ==========================
DIAS_ORDENADOS = {
    "Lunes": 1, "Martes": 2, "Miercoles": 3, "Jueves": 4,
    "Viernes": 5, "Sabado": 6, "Domingo": 7,
}
def obtener_orden_dias(request=None):
    # Filtra días por institución del usuario
    qs = DiaSemana.objects.all()
    if request and not request.user.is_superuser and hasattr(request.user, 'perfil'):
        qs = qs.filter(institucion=request.user.perfil.institucion)
    return {dia: DIAS_ORDENADOS.get(dia.nombre, 99) for dia in qs}


class CarreraFilter(admin.SimpleListFilter):
    title = 'Carrera'
    parameter_name = 'carrera'

    def lookups(self, request, model_admin):
        qs = CarreraUniversitaria.objects.all()
        if not request.user.is_superuser and hasattr(request.user, 'perfil'):
            qs = qs.filter(institucion=request.user.perfil.institucion)
        return [(c.id, c.nombre) for c in qs]

    def queryset(self, request, queryset):
        if self.value():
            return queryset.filter(asignatura__semestre__carrera__id=self.value())
        return queryset


# ==========================
# Horario (aislado por institucion + usuario) + botón “Generar”
# ==========================
class HorarioAdmin(TenantScopedAdminMixin, admin.ModelAdmin):
    list_display = ("dia", "get_carrera", "get_semestre", "jornada", "col_actividad", "col_docente", "col_aula", "hora_inicio", "hora_fin")
    list_filter = (CarreraFilter, "asignatura__semestre", "jornada", "dia")
    search_fields = ("asignatura__nombre", "docente__nombre", "aula__nombre")
    change_list_template = 'admin/mi_app/horarios_change_list.html'

    @admin.display(description="Carrera", ordering='asignatura__semestre__carrera__nombre')
    def get_carrera(self, obj):
        # Para DESCANSO no mostramos carrera
        if getattr(obj.asignatura, "nombre", "") == "DESCANSO":
            return "—"
        sem = getattr(obj.asignatura, 'semestre', None)
        car = getattr(sem, 'carrera', None)
        return getattr(car, 'nombre', '—')

    @admin.display(description="Semestre", ordering='asignatura__semestre__numero')
    def get_semestre(self, obj):
        # Para DESCANSO no mostramos semestre
        if getattr(obj.asignatura, "nombre", "") == "DESCANSO":
            return "—"
        sem = getattr(obj.asignatura, 'semestre', None)
        return getattr(sem, 'numero', '—')

    def get_queryset(self, request):
        qs = super().get_queryset(request)  # Mixin ya filtra por institucion
        jornada_seleccionada = request.GET.get("jornada", None)

        # Orden de días
        dia_ordenes = obtener_orden_dias(request)
        dia_order = Case(
            *[When(dia=dia_obj, then=orden) for dia_obj, orden in dia_ordenes.items()],
            default=99, output_field=IntegerField()
        )

        # Evitar que NULLs en carrera/semestre manden al final
        qs = qs.annotate(
            dia_orden=dia_order,
            carrera_nombre=Coalesce(F('asignatura__semestre__carrera__nombre'), Value("")),
            sem_num=Coalesce(F('asignatura__semestre__numero'), Value(0)),
        )

        if jornada_seleccionada:
            qs = qs.filter(jornada=jornada_seleccionada)

        # Orden cronológico primero; luego detalles académicos
        return qs.order_by(
            "dia_orden",
            "hora_inicio",
            "jornada",
            "carrera_nombre",
            "sem_num",
            "id",
        )

    # ====== helpers descanso ======
    def _es_descanso(self, obj):
        try:
            return (obj.asignatura and obj.asignatura.nombre == "DESCANSO")
        except Exception:
            return False

    def _titulo_descanso(self, obj):
        # Busca el Descanso que materializamos en este Horario (mismo usuario/inst, día y rango)
        from .models import Descanso
        d = Descanso.objects.filter(
            institucion=obj.institucion,
            usuario=obj.usuario,
            dia=obj.dia,
            hora_inicio=obj.hora_inicio,
            hora_fin=obj.hora_fin,
        ).first()
        return d.nombre if d and d.nombre else "Descanso"

    @admin.display(description="Actividad")
    def col_actividad(self, obj):
        if self._es_descanso(obj):
            titulo = self._titulo_descanso(obj)
            # Badge centrado y bonito (incluye clase para estilizar fila en el template)
            return format_html(
                '<div style="display:flex;justify-content:center;">'
                '<span class="badge-descanso" '
                'style="background:#F2F4F7;border:1px solid #E5E7EB;color:#111827;'
                'padding:4px 10px;border-radius:9999px;font-weight:600;">{}</span>'
                '</div>',
                titulo
            )
        # No es descanso → muestra Asignatura normal
        return str(obj.asignatura)

    @admin.display(description="Docente")
    def col_docente(self, obj):
        return "—" if self._es_descanso(obj) else (obj.docente.nombre if obj.docente_id else "—")

    @admin.display(description="Aula")
    def col_aula(self, obj):
        return "—" if self._es_descanso(obj) else (obj.aula.nombre if obj.aula_id else "—")

    # ====== form/save ======
    def get_form(self, request, obj=None, **kwargs):
        # Oculta también 'usuario'; lo llenamos en save_model
        form = super().get_form(request, obj, **kwargs)
        if 'usuario' in form.base_fields:
            # FIX: usar HiddenInput (no existe AdminHiddenInput)
            form.base_fields['usuario'].widget = forms.HiddenInput()
        return form

    def save_model(self, request, obj, form, change):
        # Asignar institucion y usuario automáticamente
        if getattr(obj, 'usuario_id', None) is None:
            obj.usuario = request.user
        if getattr(obj, 'institucion_id', None) is None and hasattr(request.user, 'perfil'):
            obj.institucion = request.user.perfil.institucion
        super().save_model(request, obj, form, change)

    # ====== generar horarios ======
    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path('generar_horarios/', self.admin_site.admin_view(self.generar_horarios), name='generar_horarios'),
        ]
        return custom_urls + urls

    def generar_horarios(self, request):
        """
        Genera horarios:
        - Staff normal: en SU institución (tomada del perfil).
        - Superusuario: puede elegir institución con ?institucion=<id>. Si hay solo una,
          se usa automáticamente. Si hay varias y no pasa el parámetro, se le pide elegir.
        """


        # 1) Resolver institución
        if request.user.is_superuser:
            inst = None
            inst_id = request.GET.get("institucion")
            if inst_id:
                inst = Institucion.objects.filter(id=inst_id).first()
                if not inst:
                    messages.error(request, "La institución indicada no existe.")
                    return redirect("..")
            else:
                total = Institucion.objects.count()
                if total == 0:
                    messages.error(request, "No hay instituciones creadas.")
                    return redirect("..")
                elif total == 1:
                    inst = Institucion.objects.first()
                else:
                    opciones = ", ".join(f"{i.id} - {i.nombre}" for i in Institucion.objects.all())
                    messages.error(
                        request,
                        f"Superusuario: especifica la institución con ?institucion=<id>. Opciones: {opciones}"
                    )
                    return redirect("..")
        else:
            if hasattr(request.user, "perfil") and request.user.perfil and request.user.perfil.institucion_id:
                inst = request.user.perfil.institucion
            else:
                messages.error(request, "Tu usuario no tiene institución asociada. Pídele al admin que la configure.")
                return redirect("..")

        # 2) Limpiar solo los horarios del usuario + institución
        Horario.objects.filter(usuario=request.user, institucion=inst).delete()

        # 3) Traer datos de la MISMA institución
        asignaturas = (Asignatura.objects
                       .select_related('semestre__carrera', 'aula', 'institucion')
                       .prefetch_related('docentes')
                       .filter(institucion=inst))

        errores = []

        todos_los_horarios = list(
            Horario.objects
            .filter(usuario=request.user, institucion=inst)
            .select_related('docente', 'aula', 'asignatura__semestre__carrera', 'institucion')
        )

        # NoDisponibilidad filtrada por institución si tiene FK
        no_disp_qs = NoDisponibilidad.objects.select_related('docente')
        if hasattr(NoDisponibilidad, "institucion_id"):
            no_disp_qs = no_disp_qs.filter(institucion=inst)
        todas_las_no_disponibilidades = list(no_disp_qs)

        # Descansos del usuario en la institución
        descansos_qs = Descanso.objects.filter(institucion=inst, usuario=request.user).select_related('dia')
        todos_los_descansos = list(descansos_qs)

        with transaction.atomic():
            for asignatura in asignaturas:
                ok, motivo = asignar_horario_automatico(
                    asignatura=asignatura,
                    horarios=todos_los_horarios,
                    no_disponibilidades=todas_las_no_disponibilidades,
                    descansos=todos_los_descansos,
                    usuario=request.user,
                    institucion=inst,     # 👈 clave
                    con_motivo=True,
                )
                if not ok:
                    errores.append(f"{asignatura.nombre} → {motivo}")

        # ==== Materializar DESCANSOS como filas Horario (para que se vean en la grilla) ====
        # Asignatura especial "DESCANSO" (una por institución)
        asig_descanso, _ = Asignatura.objects.get_or_create(
            institucion=inst,
            nombre="DESCANSO",
            semestre=None,  # tu modelo permite null/blank en semestre
            defaults={"jornada": "Mañana", "intensidad_horaria": 30},
        )

        # Placeholders (uno por institución). Evita duplicados con get_or_create
        aula_placeholder, _ = Aula.objects.get_or_create(institucion=inst, nombre="—")
        docente_placeholder, _ = Docente.objects.get_or_create(
            institucion=inst,
            correo="placeholder@hache.local",  # cumple UniqueConstraint (institucion, correo)
            defaults={"nombre": "—"},
        )

        # Crear filas Horario a partir de cada Descanso del usuario (bypassea clean() usando bulk_create)
        nuevos_descansos = []
        for d in todos_los_descansos:
            # Jornada solo para fines visuales/orden (no afecta bloqueo)
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
            Horario.objects.bulk_create(nuevos_descansos)  # no ejecuta clean(), así que no choca con validaciones de jornada
            todos_los_horarios.extend(nuevos_descansos)
        # ==== FIN materialización de DESCANSOS ====

        if errores:
            for e in errores:
                messages.warning(request, e)
        else:
            messages.success(request, "¡Horarios generados exitosamente!")

        return redirect("..")




admin.site.register(Horario, HorarioAdmin)


# ==========================
# User / Group SOLO superuser
# ==========================
class CustomUserAdmin(UserAdmin):
    def has_module_permission(self, request):
        return request.user.is_superuser

    def get_model_perms(self, request):
        if request.user.is_superuser:
            return super().get_model_perms(request)
        return {'add': False, 'change': False, 'delete': False, 'view': False}


class CustomGroupAdmin(GroupAdmin):
    def has_module_permission(self, request):
        return request.user.is_superuser

    def get_model_perms(self, request):
        if request.user.is_superuser:
            return super().get_model_perms(request)
        return {'add': False, 'change': False, 'delete': False, 'view': False}


# Reemplazar con nuestras versiones
try:
    admin.site.unregister(User)
except admin.sites.NotRegistered:
    pass
try:
    admin.site.unregister(Group)
except admin.sites.NotRegistered:
    pass
admin.site.register(User, CustomUserAdmin)
admin.site.register(Group, CustomGroupAdmin)
