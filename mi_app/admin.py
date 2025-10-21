from django.contrib import admin, messages
from django.core.exceptions import ValidationError
from django.contrib.admin import TabularInline, helpers
from django.shortcuts import redirect
from django.urls import path
from django.db import transaction
from django.db.models import Case, When, IntegerField, Value, F
from django.utils.html import format_html, strip_tags
from django import forms
from datetime import time as _time
from django.db.models.functions import Coalesce
from django.db import IntegrityError, transaction
from .utils import calcular_mps
from django.template.response import TemplateResponse
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

@admin.register(Institucion)
class InstitucionAdmin(admin.ModelAdmin):
    # Lista
    list_display = ("nombre", "slug", "duracion_hora_minutos")
    change_list_template = "admin/mi_app/institucion/change_list_institucion.html"

    # --- Bloque explicativo arriba de los campos ---
    fieldsets = (
        (None, {
            "fields": ("nombre", "slug", "duracion_hora_minutos"),
            "description": format_html(
                "<div style='background:#F9FAFB;border:1px solid #E5E7EB;"
                "padding:10px 12px;border-radius:8px;margin-bottom:8px;'>"
                "<b>¿Qué es la hora institucional?</b><br>"
                "Es la duración real, en minutos, que tu institución considera como "
                "una 'hora' de clase (p. ej. 45, 50 o 60).<br><br>"
                "<b>¿Para qué se usa?</b><br>"
                "Al crear asignaturas, el sistema convierte las <i>horas totales</i> "
                "en <i>minutos totales</i> usando esta duración, los reparte por "
                "semanas y ajusta a bloques de 15 minutos para que el horario quede "
                "cuadrado sin huecos raros."
                "</div>"
            )
        }),
    )

    # --- (permisos/visibilidad) ---
    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        perfil = getattr(request.user, "perfil", None)
        if perfil and perfil.institucion_id:
            return qs.filter(id=perfil.institucion_id)
        return qs.none()

    def get_readonly_fields(self, request, obj=None):
        if request.user.is_superuser:
            return ()
        return ("nombre", "slug",)  # el staff solo edita duracion_hora_minutos

    # Importante: ya no usamos get_fields; fieldsets manda.
    # def get_fields(self, request, obj=None):
    #     ...

    def has_module_permission(self, request):
        return request.user.is_superuser or request.user.is_staff

    def has_view_permission(self, request, obj=None):
        return request.user.is_superuser or request.user.is_staff

    def has_add_permission(self, request):
        return request.user.is_superuser

    def has_change_permission(self, request, obj=None):
        if request.user.is_superuser:
            return True
        perfil = getattr(request.user, "perfil", None)
        if not perfil or not perfil.institucion_id:
            return False
        if obj is None:
            return True
        return obj.id == perfil.institucion_id

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser


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
class DescansoMultiForm(forms.ModelForm):
    # Campo extra: elegir uno o más días
    dias = forms.ModelMultipleChoiceField(
        label="Días",
        queryset=DiaSemana.objects.none(),
        required=True,
        help_text="Selecciona uno o más días para asignar este descanso."
    )

    class Meta:
        model = Descanso
        # Solo lo necesario en el form
        fields = ["nombre", "hora_inicio", "hora_fin"]

    def __init__(self, *args, **kwargs):
        request = kwargs.pop("request", None)
        super().__init__(*args, **kwargs)

        # Limitar queryset de días por institución del usuario
        inst = getattr(getattr(getattr(request, "user", None), "perfil", None), "institucion", None)
        if inst:
            self.fields["dias"].queryset = DiaSemana.objects.filter(institucion=inst).order_by("orden")
        else:
            self.fields["dias"].queryset = DiaSemana.objects.none()

        # En edición: preseleccionar los “hermanos” (mismo grupo)
        if self.instance and self.instance.pk:
            inst_id = getattr(self.instance, "institucion_id", None)
            usr_id  = getattr(self.instance, "usuario_id", None)
            hi      = getattr(self.instance, "hora_inicio", None)
            hf      = getattr(self.instance, "hora_fin", None)
            nom     = getattr(self.instance, "nombre", "")

            if inst_id and usr_id and hi is not None and hf is not None:
                hermanos = (Descanso.objects
                            .filter(institucion_id=inst_id,
                                    usuario_id=usr_id,
                                    hora_inicio=hi,
                                    hora_fin=hf,
                                    nombre=nom)
                            .values_list("dia_id", flat=True))
                self.fields["dias"].initial = list(hermanos)


@admin.register(Descanso)
class DescansoAdmin(TenantScopedAdminMixin, admin.ModelAdmin):
    form = DescansoMultiForm

    # Listado simple (sin día)
    list_display = ("nombre", "hora_inicio", "hora_fin")
    search_fields = ("nombre", "usuario__username")
    ordering = ("dia__orden", "hora_inicio")

    # No mostramos estos campos en el form (los seteamos en save_model)
    exclude = ("dia", "color_hex", "institucion", "usuario")

    # Pasar request al form para limitar días por institución y preseleccionar en change
    def get_form(self, request, obj=None, **kwargs):
        FormClass = super().get_form(request, obj, **kwargs)
        class RequestAwareForm(FormClass):
            def __init__(self2, *a, **kw):
                kw["request"] = request
                super().__init__(*a, **kw)
        return RequestAwareForm

    def save_model(self, request, obj, form, change):
        # Setear institución/usuario siempre antes de validar/guardar
        if getattr(obj, "usuario_id", None) is None:
            obj.usuario = request.user
        if getattr(obj, "institucion_id", None) is None and hasattr(request.user, "perfil"):
            obj.institucion = request.user.perfil.institucion

        # Datos del “grupo”
        inst_id = getattr(obj, "institucion_id", None)
        usr_id  = getattr(obj, "usuario_id", None)
        hi      = getattr(obj, "hora_inicio", None)
        hf      = getattr(obj, "hora_fin", None)
        nom     = getattr(obj, "nombre", "")

        dias_sel = form.cleaned_data.get("dias") or []

        if change:
            # Sincronizar: crear faltantes y borrar deseleccionados
            existentes = Descanso.objects.filter(
                institucion_id=inst_id,
                usuario_id=usr_id,
                hora_inicio=hi,
                hora_fin=hf,
                nombre=nom,
            )
            actuales_ids = set(existentes.values_list("dia_id", flat=True))
            nuevos_ids   = set(dias_sel.values_list("id", flat=True))

            # Crear nuevos
            para_crear = nuevos_ids - actuales_ids
            for dia_id in para_crear:
                nuevo = Descanso(
                    institucion_id=inst_id,
                    usuario_id=usr_id,
                    dia_id=dia_id,
                    hora_inicio=hi,
                    hora_fin=hf,
                    nombre=nom,
                )
                nuevo.full_clean()
                nuevo.save()

            # Eliminar los que sobraron
            para_borrar = actuales_ids - nuevos_ids
            if para_borrar:
                Descanso.objects.filter(
                    institucion_id=inst_id,
                    usuario_id=usr_id,
                    hora_inicio=hi,
                    hora_fin=hf,
                    nombre=nom,
                    dia_id__in=para_borrar,
                ).delete()

            # Mantener el registro actual consistente (por si su día ya no está seleccionado)
            if nuevos_ids and obj.dia_id not in nuevos_ids:
                obj.dia_id = next(iter(nuevos_ids))

            # Guardar este (actualiza nombre/horas si cambiaron)
            super().save_model(request, obj, form, change)
            return

        # ADD: crear un descanso por cada día
        if not dias_sel:
            messages.error(request, "Debes seleccionar al menos un día.")
            return

        creados = 0
        ultimo = None
        for d in dias_sel:
            nuevo = Descanso(
                institucion=obj.institucion,
                usuario=obj.usuario,
                dia=d,  # 👉 día correcto
                hora_inicio=obj.hora_inicio,
                hora_fin=obj.hora_fin,
                nombre=obj.nombre,
            )
            nuevo.full_clean()
            nuevo.save()
            ultimo = nuevo
            creados += 1

        messages.success(request, f"Se crearon {creados} descansos (uno por cada día seleccionado).")

        # No guardamos el “obj plantilla”; dejamos que el admin redirija sin error
        if ultimo:
            obj.pk = ultimo.pk
            obj.id = ultimo.id
        return

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
    # Campo “virtual” solo para el formulario
    explicacion_horas = forms.CharField(
        label="Explicación de la carga semanal",
        required=False,
        widget=forms.Textarea(attrs={
            "rows": 6,
            "readonly": "readonly",
            "style": "background:#f9fafb"
        })
    )

    class Meta:
        model = Asignatura
        fields = '__all__'  # incluye todos los de modelo; el extra es este campo

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # bloquear plus/editar en selects
        for field in ('semestre', 'aula'):
            if field in self.fields:
                widget = self.fields[field].widget
                for attr in ('can_add_related','can_change_related','can_view_related','can_delete_related'):
                    setattr(widget, attr, False)

        # rellenar la explicación (texto plano para que no se escape HTML)
        texto_html = _ayuda_carga_sem(self.instance)  # tu helper devuelve HTML
        self.fields['explicacion_horas'].initial = strip_tags(texto_html)  # lo ponemos plano


def _ayuda_carga_sem(obj):
    if not obj:
        return format_html(
            "<p>Ingrese <b>Horas totales</b> y <b>Semanas</b> para ver el cálculo según la "
            "duración de la hora institucional.</p>"
            "<ul>"
            "<li>Horas totales × min/hora institucional = <b>minutos totales</b></li>"
            "<li>Minutos totales ÷ semanas = <b>minutos/semana</b></li>"
            "<li>Se recomienda usar múltiplos de 15 min, pero se conservarán tus valores exactos.</li>"
            "</ul>"
        )

    if not obj.semanas or not obj.horas_totales or not getattr(obj, "institucion", None):
        return format_html(
            "<p>Complete <b>Horas totales</b>, <b>Semanas</b> y la <b>Institución</b> para ver el cálculo.</p>"
        )

    dh = getattr(obj.institucion, "duracion_hora_minutos", 45)
    mt = obj.horas_totales * dh
    mps = mt / obj.semanas

    # calcular múltiplo de 15 solo para sugerir (no usar)
    bloques = mps / 15.0
    bloques_redondeados = int(round(bloques))
    sugerido = bloques_redondeados * 15

    mensaje = (
        f"<div>"
        f"<p>👉 Indicó <b>{obj.horas_totales}</b> horas en <b>{obj.semanas}</b> semanas, "
        f"con hora institucional de <b>{dh}</b> min.</p>"
        f"<ul>"
        f"<li>Minutos totales: <b>{mt}</b></li>"
        f"<li>Minutos/semana: <b>{mps:.2f}</b></li>"
        f"</ul>"
    )

    if mps % 15 != 0:
        mensaje += (
            f"<p style='color:#b58900;'>⚠️ Se recomienda usar un múltiplo de 15 min "
            f"(por ejemplo, <b>{sugerido} min/semana</b>) para facilitar la asignación, "
            f"pero se conservarán tus valores exactos.</p>"
        )
    else:
        mensaje += "<p>✅ Es un valor exacto en múltiplos de 15 min.</p>"

    mensaje += "</div>"
    return format_html(mensaje)



class AsignaturaAdmin(TenantScopedAdminMixin, admin.ModelAdmin):
    form = AsignaturaForm
    list_display = ('nombre','semestre','mostrar_docentes','aula','mostrar_jornadas','horas_totales','semanas')
    list_filter = ('semestre__carrera','docentes','semestre','jornada')
    search_fields = ('nombre','semestre__numero','docentes__nombre')

    fieldsets = (
        (None, {'fields': ('nombre','semestre','jornada','aula','docentes')}),
        ('Carga y cálculo', {'fields': ('horas_totales','semanas','explicacion_horas')}),
    )

    def explicacion_horas(self, obj):
        return _ayuda_carga_sem(obj)
    explicacion_horas.short_description = "Explicación de la carga semanal"

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.prefetch_related('docentes','semestre','aula')

    def mostrar_docentes(self, obj):
        return ", ".join(d.nombre for d in obj.docentes.all())
    mostrar_docentes.short_description = "Docentes"

    def mostrar_jornadas(self, obj):
        return obj.jornada
    mostrar_jornadas.short_description = "Jornada"
    
    def message_user(self, request, message, level=messages.INFO, extra_tags='', fail_silently=False):
        if isinstance(message, str):
            message = message.replace("El asignatura", "La asignatura")
            # Elimina etiquetas HTML
            message = strip_tags(message)
        super().message_user(request, message, level, extra_tags, fail_silently)


 
    def save_model(self, request, obj, form, change):
        self._duplicado_detectado = False  # bandera interna

        # --- Asignar institución automáticamente ---
        if not getattr(obj, 'institucion_id', None):
            inst = getattr(request, 'institucion', None) or getattr(request.user, 'institucion', None)
            if inst:
                obj.institucion = inst
            else:
                from .models import Institucion
                institutos = Institucion.objects.all()
                if institutos.count() == 1:
                    obj.institucion = institutos.first()
                else:
                    messages.error(
                        request,
                        "❌ No se pudo determinar la institución. Selecciónala manualmente."
                    )
                    return  # detenemos el guardado sin error

        # --- Mostrar advertencia si minutos/semana no son múltiplos de 15 ---
        try:
            info = calcular_mps(obj)
            if not info.get("exacto", False):
                # no mostrar advertencia por ahora
                pass
        except Exception:
            pass

        # --- Guardado con control de duplicados ---
        try:
            with transaction.atomic():
                super().save_model(request, obj, form, change)
        except IntegrityError:
            self._duplicado_detectado = True  # marcamos bandera
            messages.error(
                request,
                f"❌ Ya existe una asignatura llamada '{obj.nombre}' en el semestre '{obj.semestre}' de esta institución.",
            )
            return  # detenemos aquí

    def save_related(self, request, form, formsets, change):
        # Evitar guardar relaciones si se detectó duplicado
        if getattr(self, "_duplicado_detectado", False):
            return
        super().save_related(request, form, formsets, change)
        
    def response_add(self, request, obj, post_url_continue=None):
        # Si hubo duplicado, no mostrar el mensaje de éxito ni redirigir
        if getattr(self, "_duplicado_detectado", False):
            # Limpiar mensajes de éxito que Django haya preparado
            storage = messages.get_messages(request)
            storage.used = True

            # Preparar un formulario limpio con los datos actuales
            ModelForm = self.get_form(request)
            form = ModelForm(instance=obj)

            # Generar el contexto mínimo que espera render_change_form
            context = {
                **self.admin_site.each_context(request),
                'title': 'Agregar asignatura',
                'adminform': helpers.AdminForm(
                    form,
                    self.get_fieldsets(request, obj),
                    self.get_prepopulated_fields(request, obj),
                    self.get_readonly_fields(request, obj),
                    model_admin=self,
                ),
                'object_id': None,
                'original': None,
                'is_popup': False,
                'to_field': None,
                'add': True,
                'change': False,
                'has_add_permission': self.has_add_permission(request),
                'has_change_permission': self.has_change_permission(request),
                'has_view_permission': self.has_view_permission(request),
                'has_delete_permission': self.has_delete_permission(request),
                'save_as': self.save_as,
                'show_save': True,
                'inline_admin_formsets': [],  # sin inlines
            }

            return TemplateResponse(
                request,
                self.change_form_template or [
                    f"admin/{self.model._meta.app_label}/{self.model._meta.model_name}/change_form.html",
                    f"admin/{self.model._meta.app_label}/change_form.html",
                    "admin/change_form.html",
                ],
                context,
            )

        # Si no hubo duplicado, seguir con el flujo normal
        return super().response_add(request, obj, post_url_continue)

try:
    admin.site.unregister(Asignatura)
except admin.sites.NotRegistered:
    pass
admin.site.register(Asignatura, AsignaturaAdmin)

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
    show_change_link = True
    fk_name = 'docente'
    classes = ('tab',)
    verbose_name = "Horario NO disponible"
    verbose_name_plural = "No disponibilidad del docente"

    # —— Permisos para que el STAFF vea/edite el inline ——
    def has_view_permission(self, request, obj=None):
        return request.user.is_superuser or request.user.is_staff

    def has_add_permission(self, request, obj=None):
        return request.user.is_superuser or request.user.is_staff

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser or request.user.is_staff

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser or request.user.is_staff

    # —— Multi-tenant: ocultamos institucion, la seteamos al guardar ——
    def get_formset(self, request, obj=None, **kwargs):
        excl = set(kwargs.get('exclude') or ())
        excl.add('institucion')
        kwargs['exclude'] = tuple(excl)
        return super().get_formset(request, obj, **kwargs)

    def save_formset(self, request, form, formset, change):
        # 'obj' es el Docente padre en la vista de cambio
        parent_inst = getattr(getattr(form.instance, 'institucion', None), 'id', None)
        instances = formset.save(commit=False)

        for i in instances:
            # toma la institución del padre (Docente) como fuente de verdad
            if getattr(i, 'institucion_id', None) is None:
                if parent_inst:
                    i.institucion_id = parent_inst
                elif getattr(i, 'docente_id', None):
                    # fallback por si acaso
                    i.institucion_id = i.docente.institucion_id
                else:
                    # último fallback: perfil del usuario (evita dejarlo en NULL)
                    perfil = getattr(request.user, 'perfil', None)
                    if perfil and perfil.institucion_id:
                        i.institucion_id = perfil.institucion_id
            i.save()

        # borra eliminados y guarda M2M si existiera
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

    # ⬇️ ESTE método es la clave
    def save_formset(self, request, form, formset, change):
        """
        Django llama al save_formset del ModelAdmin (padre), no al del inline.
        Aquí aseguramos institucion y docente antes de guardar NoDisponibilidad.
        """
        if formset.model is NoDisponibilidad:
            parent_docente = form.instance  # el Docente que estamos editando
            instances = formset.save(commit=False)

            for nd in instances:
                # Garantiza institución desde el docente padre
                if not getattr(nd, 'institucion_id', None):
                    nd.institucion_id = parent_docente.institucion_id
                # Garantiza vínculo al mismo docente padre
                if not getattr(nd, 'docente_id', None):
                    nd.docente = parent_docente
                nd.save()

            # borrar los eliminados y guardar M2M si existiera
            for obj in formset.deleted_objects:
                obj.delete()
            formset.save_m2m()
        else:
            # para otros inlines (si los hubiera)
            formset.save()
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
                        .filter(institucion=inst)
                        .exclude(nombre="DESCANSO"))

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
            defaults={
                "jornada": "Mañana",
                # Como ahora ya no existe 'intensidad_horaria', usa los nuevos campos:
                "horas_totales": 0,   # no se usa para pintar el bloque de descanso
                "semanas": 16,        # valor neutro
            },
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
