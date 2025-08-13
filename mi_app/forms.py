from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.utils.text import slugify
from django.contrib.auth.models import User
from .models import Institucion

class RegistrationForm(UserCreationForm):
    MODO_CHOICES = (
        ('crear', 'Crear institución'),
        ('unirme', 'Unirme con código'),
    )

    modo = forms.ChoiceField(choices=MODO_CHOICES, widget=forms.RadioSelect, initial='crear')
    institucion_nombre = forms.CharField(
        label="Nombre de la institución",
        required=False,
        help_text="Ej: INTEP Roldanillo"
    )
    institucion_codigo = forms.CharField(
        label="Código de institución (slug)",
        required=False,
        help_text="Ej: intep-roldanillo"
    )

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("username",)

    def clean(self):
        cleaned = super().clean()
        modo = cleaned.get("modo")
        nombre = cleaned.get("institucion_nombre") or ""
        codigo = (cleaned.get("institucion_codigo") or "").strip().lower()

        if modo == 'crear':
            if not nombre.strip():
                self.add_error("institucion_nombre", "Ingresa el nombre de la institución.")
        else:  # unirme
            if not codigo:
                self.add_error("institucion_codigo", "Ingresa el código de institución.")
            else:
                if not Institucion.objects.filter(slug=codigo).exists():
                    self.add_error("institucion_codigo", "No existe una institución con ese código.")

        return cleaned

    @staticmethod
    def slug_unico(base: str) -> str:
        base_slug = slugify(base) or "institucion"
        slug = base_slug
        i = 2
        while Institucion.objects.filter(slug=slug).exists():
            slug = f"{base_slug}-{i}"
            i += 1
        return slug
