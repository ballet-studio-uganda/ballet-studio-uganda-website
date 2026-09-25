"""
Django settings for the Ballet Dance Studio UG project.

Brand:  Ballet Dance Studio UG  --  "Resilience. Hope. Dreams."
Docs:   https://docs.djangoproject.com/en/6.0/ref/settings/
"""

import os
from pathlib import Path

import dj_database_url

BASE_DIR = Path(__file__).resolve().parent.parent


def env(key, default=None):
    return os.environ.get(key, default)


def env_bool(key, default=False):
    raw = os.environ.get(key)
    if raw is None:
        return default
    return raw.strip().lower() in {'1', 'true', 'yes', 'on'}


def env_list(key, default=''):
    raw = os.environ.get(key, default)
    return [item.strip() for item in raw.split(',') if item.strip()]


# ---------------------------------------------------------------------------
# Core
# ---------------------------------------------------------------------------
SECRET_KEY = env(
    'DJANGO_SECRET_KEY',
    'django-insecure-4s7e!jpl=_3mkk7kga#y7qly+7@sm+4umeq2o3bz^h@m0qor0@',
)

DEBUG = env_bool('DJANGO_DEBUG', True)

ALLOWED_HOSTS = env_list('DJANGO_ALLOWED_HOSTS', 'localhost,127.0.0.1,[::1],testserver')

CSRF_TRUSTED_ORIGINS = env_list('DJANGO_CSRF_TRUSTED_ORIGINS')

# Render injects the service's own hostname. Trusting it automatically means a
# fresh deploy works before anyone has set a custom domain.
RENDER_HOSTNAME = env('RENDER_EXTERNAL_HOSTNAME')
if RENDER_HOSTNAME:
    ALLOWED_HOSTS.append(RENDER_HOSTNAME)
    CSRF_TRUSTED_ORIGINS.append(f'https://{RENDER_HOSTNAME}')


# ---------------------------------------------------------------------------
# Applications
# ---------------------------------------------------------------------------
INSTALLED_APPS = [
    'jazzmin',

    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.humanize',

    # Third party
    'crispy_forms',
    'crispy_bootstrap5',
    'phonenumber_field',

    # Local
    'apps.accounts',
    'apps.website',
    'apps.academics',
    'apps.finance',
    'apps.events',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    # Serves the collected static files straight from the web process, so the
    # deployment needs no separate static host or CDN to work.
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'ballet_dance_studio.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'apps.website.context_processors.site_settings',
            ],
        },
    },
]

WSGI_APPLICATION = 'ballet_dance_studio.wsgi.application'
ASGI_APPLICATION = 'ballet_dance_studio.asgi.application'


# ---------------------------------------------------------------------------
# Database  --  SQLite for local dev, DATABASE_URL (Postgres) in production
# ---------------------------------------------------------------------------
DATABASES = {
    'default': dj_database_url.config(
        default='sqlite:///' + str(BASE_DIR / 'db.sqlite3'),
        conn_max_age=600,
        conn_health_checks=True,
    )
}


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------
AUTH_USER_MODEL = 'accounts.User'

AUTHENTICATION_BACKENDS = [
    'apps.accounts.backends.EmailOrUsernameBackend',
    'django.contrib.auth.backends.ModelBackend',
]

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
     'OPTIONS': {'min_length': 8}},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LOGIN_URL = 'accounts:login'
LOGIN_REDIRECT_URL = 'dashboard:home'
LOGOUT_REDIRECT_URL = 'website:home'

SESSION_COOKIE_AGE = 60 * 60 * 12          # 12 hours
SESSION_EXPIRE_AT_BROWSER_CLOSE = False
SESSION_SAVE_EVERY_REQUEST = True


# ---------------------------------------------------------------------------
# Internationalisation
# ---------------------------------------------------------------------------
LANGUAGE_CODE = 'en-gb'
TIME_ZONE = 'Africa/Kampala'
USE_I18N = True
USE_TZ = True

# Studio currency
CURRENCY_CODE = 'UGX'
CURRENCY_SYMBOL = 'UGX'


# ---------------------------------------------------------------------------
# Static & media
# ---------------------------------------------------------------------------
STATIC_URL = 'static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_DIRS = [BASE_DIR / 'static']

# Uploads: the hero video, gallery photos, dancer portraits, payment proofs.
#
# On Render the container filesystem is WIPED on every deploy, so MEDIA_ROOT
# must point at a mounted persistent disk (set MEDIA_ROOT=/var/media and attach
# a disk at that path) or these files vanish on the next push. See DEPLOY.md.
MEDIA_URL = '/media/'
MEDIA_ROOT = Path(env('MEDIA_ROOT', str(BASE_DIR / 'media')))

PRIVATE_MEDIA_ROOT = Path(env('PRIVATE_MEDIA_ROOT', str(BASE_DIR / 'private_media')))

# Serve uploads from Django when nothing else is fronting them. Turn this off
# once media moves to object storage or a CDN.
SERVE_MEDIA = env_bool('SERVE_MEDIA', True)

FILE_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024      # 10 MB
DATA_UPLOAD_MAX_MEMORY_SIZE = 25 * 1024 * 1024      # 25 MB

STORAGES = {
    'default': {
        'BACKEND': 'django.core.files.storage.FileSystemStorage',
    },
    'staticfiles': {
        # Hashed filenames + gzip/brotli, so static assets can be cached
        # forever. Falls back to the plain backend in development, where the
        # manifest would only get in the way.
        'BACKEND': (
            'ballet_dance_studio.storage.ForgivingManifestStaticFilesStorage'
            if not DEBUG else
            'django.contrib.staticfiles.storage.StaticFilesStorage'
        ),
    },
}

# Long cache lifetime is safe because the manifest storage fingerprints names.
WHITENOISE_MAX_AGE = 0 if DEBUG else 60 * 60 * 24 * 365

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'


# ---------------------------------------------------------------------------
# Email
# ---------------------------------------------------------------------------
if env('EMAIL_HOST'):
    EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
    EMAIL_HOST = env('EMAIL_HOST')
    EMAIL_PORT = int(env('EMAIL_PORT', 587))
    EMAIL_USE_TLS = env_bool('EMAIL_USE_TLS', True)
    EMAIL_HOST_USER = env('EMAIL_HOST_USER', '')
    EMAIL_HOST_PASSWORD = env('EMAIL_HOST_PASSWORD', '')
else:
    EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'

DEFAULT_FROM_EMAIL = env(
    'DEFAULT_FROM_EMAIL',
    'Ballet Dance Studio UG <info@balletdancestudioug.com>',
)
SERVER_EMAIL = DEFAULT_FROM_EMAIL


# ---------------------------------------------------------------------------
# Third party
# ---------------------------------------------------------------------------
CRISPY_ALLOWED_TEMPLATE_PACKS = 'bootstrap5'
CRISPY_TEMPLATE_PACK = 'bootstrap5'

PHONENUMBER_DEFAULT_REGION = 'UG'
PHONENUMBER_DEFAULT_FORMAT = 'INTERNATIONAL'

MESSAGE_STORAGE = 'django.contrib.messages.storage.session.SessionStorage'


# ---------------------------------------------------------------------------
# Security (tightened automatically when DEBUG is off)
# ---------------------------------------------------------------------------
if not DEBUG:
    SECURE_SSL_REDIRECT = env_bool('SECURE_SSL_REDIRECT', True)
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = 60 * 60 * 24 * 365
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    X_FRAME_OPTIONS = 'DENY'


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {'format': '[{asctime}] {levelname} {name} :: {message}', 'style': '{'},
    },
    'handlers': {
        'console': {'class': 'logging.StreamHandler', 'formatter': 'verbose'},
    },
    'root': {'handlers': ['console'], 'level': 'INFO'},
    'loggers': {
        'django.db.backends': {'level': 'WARNING', 'handlers': ['console'], 'propagate': False},
    },
}


# ---------------------------------------------------------------------------
# Test mode
# ---------------------------------------------------------------------------
import sys  # noqa: E402

TESTING = 'test' in sys.argv or 'pytest' in sys.modules

if TESTING:
    # PBKDF2 dominates the runtime of an auth-heavy suite; MD5 is fine here
    # because no test asserts anything about hashing itself.
    PASSWORD_HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher']

    # Permission denials and 404s are *expected* in the access-control tests;
    # letting Django log their tracebacks buries the actual results.
    LOGGING['loggers']['django.request'] = {
        'handlers': ['console'], 'level': 'CRITICAL', 'propagate': False,
    }

    # Never touch the real upload tree from a test run.
    MEDIA_ROOT = BASE_DIR / 'test_media'


# ---------------------------------------------------------------------------
# Django admin (Jazzmin) -- the studio's day-to-day work happens in the custom
# dashboards; this stays as a technical back-door for the developer/director.
# ---------------------------------------------------------------------------
JAZZMIN_SETTINGS = {
    'site_title': 'BDSU Admin',
    'site_header': 'Ballet Dance Studio UG',
    'site_brand': 'Ballet Dance Studio UG',
    'welcome_sign': 'Ballet Dance Studio UG - Resilience. Hope. Dreams.',
    'copyright': 'Ballet Dance Studio UG',
    'search_model': ['accounts.User', 'academics.Student'],
    'user_avatar': 'photo',
    'topmenu_links': [
        {'name': 'Website', 'url': '/', 'new_window': True},
        {'name': 'Dashboard', 'url': '/dashboard/', 'new_window': True},
    ],
    'order_with_respect_to': [
        'accounts', 'academics', 'finance', 'events', 'website', 'auth',
    ],
    'icons': {
        'accounts': 'fas fa-users-cog',
        'accounts.User': 'fas fa-user',
        'accounts.StaffProfile': 'fas fa-chalkboard-teacher',
        'accounts.GuardianProfile': 'fas fa-user-friends',
        'academics': 'fas fa-graduation-cap',
        'academics.Student': 'fas fa-child',
        'academics.Program': 'fas fa-layer-group',
        'academics.DanceClass': 'fas fa-shoe-prints',
        'academics.Attendance': 'fas fa-clipboard-check',
        'academics.ProgressReport': 'fas fa-chart-line',
        'finance': 'fas fa-coins',
        'finance.Invoice': 'fas fa-file-invoice-dollar',
        'finance.Payment': 'fas fa-receipt',
        'finance.Expense': 'fas fa-money-bill-wave',
        'events': 'fas fa-calendar-alt',
        'events.Event': 'fas fa-calendar-day',
        'events.Recital': 'fas fa-star',
        'website': 'fas fa-globe-africa',
        'website.NewsPost': 'fas fa-newspaper',
        'website.GalleryAlbum': 'fas fa-images',
    },
    'related_modal_active': True,
}

JAZZMIN_UI_TWEAKS = {
    'theme': 'litera',
    'dark_mode_theme': 'darkly',
    'accent': 'accent-danger',
    'navbar': 'navbar-dark',
    'sidebar': 'sidebar-dark-danger',
    'button_classes': {
        'primary': 'btn-outline-primary',
        'success': 'btn-outline-success',
        'danger': 'btn-outline-danger',
    },
}
