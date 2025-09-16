"""
Django settings for mi_proyecto project.
"""

from pathlib import Path
import os
import dj_database_url

# Build paths inside the project
BASE_DIR = Path(__file__).resolve().parent.parent

# ==============================
# Seguridad y configuración base
# ==============================
SECRET_KEY = os.getenv("SECRET_KEY", "django-insecure-default-for-dev-only")

DEBUG = os.getenv("DEBUG", "False").lower() in ("1", "true", "yes")

allowed = os.getenv("ALLOWED_HOSTS", "localhost,127.0.0.1")
ALLOWED_HOSTS = [h.strip() for h in allowed.split(",") if h.strip()]

# ==============================
# Redirecciones de login/logout
# ==============================
LOGIN_URL = '/accounts/login/'
LOGIN_REDIRECT_URL = '/admin/'
LOGOUT_REDIRECT_URL = '/accounts/login/'

# ==============================
# Aplicaciones instaladas
# ==============================
INSTALLED_APPS = [
    'jazzmin',
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    "mi_app.apps.MiAppConfig",
    "widget_tweaks",
]

# ==============================
# Middleware
# ==============================
MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'mi_proyecto.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'mi_app' / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'mi_proyecto.wsgi.application'

# ==============================
# Base de datos
# ==============================
# Render → usará DATABASE_URL (interna o externa) desde el panel
# Local → si no encuentra DATABASE_URL, usa SQLite
DATABASES = {
    "default": dj_database_url.config(
        default=os.getenv("DATABASE_URL", f"sqlite:///{BASE_DIR / 'horario_intep.db'}"),
        conn_max_age=600,
        ssl_require=True if os.getenv("RENDER", "") else False,
    )
}

# ==============================
# Validación de contraseñas
# ==============================
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {"NAME": 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {"NAME": 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {"NAME": 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

# ==============================
# Internacionalización
# ==============================
LANGUAGE_CODE = 'es'
TIME_ZONE = 'America/Bogota'
USE_I18N = True
USE_L10N = True
USE_TZ = True

# ==============================
# Archivos estáticos
# ==============================
STATIC_URL = '/static/'
STATICFILES_DIRS = [BASE_DIR / "mi_app" / "static"]
STATIC_ROOT = BASE_DIR / 'staticfiles'

STATICFILES_STORAGE = 'django.contrib.staticfiles.storage.ManifestStaticFilesStorage'

# ==============================
# Configuración Jazzmin
# ==============================
JAZZMIN_SETTINGS = {
    "site_title": "Panel Administrativo",
    "site_header": "HACHE",
    "site_logo": "mi_app/img/logo.png",
    "site_logo_classes": "img-fluid",
    "custom_css": "mi_app/css/admin_custom.css",
    "welcome_sign": "Bienvenido al administrador",
    "site_brand": "HACHE",
}

# ==============================
# Sesiones
# ==============================
SESSION_ENGINE = 'django.contrib.sessions.backends.db'
SESSION_COOKIE_NAME = 'sessionid'
SESSION_EXPIRE_AT_BROWSER_CLOSE = False

SESSION_COOKIE_SAMESITE = None
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SAMESITE = None
CSRF_COOKIE_SECURE = False
