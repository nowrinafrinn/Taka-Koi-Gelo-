"""
Django settings for Taka Koi Gelo?

Values that differ between your laptop and production (secrets, debug mode,
allowed hosts) are read from environment variables. Locally they come from a
`.env` file (see `.env.example`); in production the host sets them.
"""

import os
from pathlib import Path

import dj_database_url
from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# Load variables from .env if the file exists. Real environment variables win.
load_dotenv(BASE_DIR / '.env')


def env_bool(name, default=False):
    return os.environ.get(name, str(default)).strip().lower() in ('1', 'true', 'yes')


def env_list(name, default=''):
    return [item.strip() for item in os.environ.get(name, default).split(',') if item.strip()]


# Safe by default: debug is OFF unless explicitly turned on.
DEBUG = env_bool('DJANGO_DEBUG', default=False)

SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY')
if not SECRET_KEY:
    if DEBUG:
        # Only acceptable on a developer machine.
        SECRET_KEY = 'django-insecure-local-development-only'
    else:
        raise ImproperlyConfigured('DJANGO_SECRET_KEY must be set when DJANGO_DEBUG is False.')

ALLOWED_HOSTS = env_list('DJANGO_ALLOWED_HOSTS', default='localhost,127.0.0.1')
CSRF_TRUSTED_ORIGINS = env_list('DJANGO_CSRF_TRUSTED_ORIGINS')

# On Vercel, trust the hostnames Vercel itself assigns to this deployment
# (production domain, branch URL, and the unique per-deployment URL).
for vercel_var in ('VERCEL_PROJECT_PRODUCTION_URL', 'VERCEL_BRANCH_URL', 'VERCEL_URL'):
    vercel_host = os.environ.get(vercel_var)
    if vercel_host and vercel_host not in ALLOWED_HOSTS:
        ALLOWED_HOSTS.append(vercel_host)
        CSRF_TRUSTED_ORIGINS.append(f'https://{vercel_host}')

# Production-only HTTPS hardening (checked by `manage.py check --deploy`).
if not DEBUG:
    # Vercel terminates HTTPS and forwards the request over HTTP with this
    # header, so Django can tell the original request was secure.
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
    SECURE_SSL_REDIRECT = env_bool('DJANGO_SECURE_SSL_REDIRECT', default=True)
    SESSION_COOKIE_SECURE = True   # session cookie only sent over HTTPS
    CSRF_COOKIE_SECURE = True
    # HSTS tells browsers to use HTTPS only. Start short (1 hour); raise it
    # once the deployment is known to work, because it cannot be undone early.
    SECURE_HSTS_SECONDS = int(os.environ.get('DJANGO_HSTS_SECONDS', '3600'))
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    # A *.vercel.app subdomain cannot be submitted to the browser preload list.
    SILENCED_SYSTEM_CHECKS = ['security.W021']

# Already Django defaults; stated here so the security posture is visible.
SESSION_COOKIE_HTTPONLY = True          # JavaScript cannot read the session cookie
X_FRAME_OPTIONS = 'DENY'                # the app cannot be embedded in other sites (clickjacking)
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = 'same-origin'


# Application definition

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    # Project apps
    'accounts',
    'finance',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        # Project-wide templates (base.html etc.) live in /templates.
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'


# Authentication
# Where @login_required sends anonymous visitors, and where users land
# after logging in or out. Names are URL names, resolved at request time.

LOGIN_URL = 'accounts:login'
LOGIN_REDIRECT_URL = 'finance:dashboard'
LOGOUT_REDIRECT_URL = 'finance:home'


# Database
# PostgreSQL everywhere, configured by one URL:
#   local:      Docker container from docker-compose.yml (see .env.example)
#   production: Supabase transaction pooler (port 6543)

DATABASE_URL = os.environ.get('DATABASE_URL')
if not DATABASE_URL:
    raise ImproperlyConfigured('DATABASE_URL must be set. Copy .env.example to .env for local development.')

DATABASES = {
    'default': dj_database_url.parse(
        DATABASE_URL,
        # 0 = close the connection after each request. Right for serverless,
        # where a pooler (not Django) keeps connections open.
        conn_max_age=int(os.environ.get('DB_CONN_MAX_AGE', '0')),
        conn_health_checks=True,
    )
}
DATABASES['default'].update({
    # Transaction-mode poolers hand each transaction a possibly different
    # connection, so these two Postgres features must not be relied on.
    'DISABLE_SERVER_SIDE_CURSORS': True,
    'OPTIONS': {
        **DATABASES['default'].get('OPTIONS', {}),
        'prepare_threshold': None,  # psycopg 3: never create prepared statements
    },
})
if env_bool('DB_SSL_REQUIRE', default=False):
    DATABASES['default']['OPTIONS']['sslmode'] = 'require'


# Password validation
# https://docs.djangoproject.com/en/5.2/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]


# Internationalization
# All "current month" logic uses Bangladesh time, so a transaction made at
# 11:30 pm on the 31st in Dhaka is never counted in the next month.

LANGUAGE_CODE = 'en-us'

TIME_ZONE = 'Asia/Dhaka'

USE_I18N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)

STATIC_URL = 'static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATIC_ROOT = BASE_DIR / 'staticfiles'  # where `collectstatic` gathers files for production

# In production, collectstatic adds a content hash to each filename
# (app.css -> app.4f2a9c.css), so browsers never keep a stale copy after a deploy.
STORAGES = {
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {
        'BACKEND': (
            'django.contrib.staticfiles.storage.StaticFilesStorage' if DEBUG
            else 'django.contrib.staticfiles.storage.ManifestStaticFilesStorage'
        ),
    },
}

# Logging
# Django's default only prints errors to the console when DEBUG is True. In
# production we need the traceback of every 500 in Vercel's function logs,
# so send warnings and errors to the console (stderr) in all environments.
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'simple': {'format': '{levelname} {name}: {message}', 'style': '{'},
    },
    'handlers': {
        'console': {'class': 'logging.StreamHandler', 'formatter': 'simple'},
    },
    'root': {'handlers': ['console'], 'level': 'WARNING'},
    'loggers': {
        # 'django.request' logs 5xx errors with the full traceback.
        'django': {'handlers': ['console'], 'level': os.environ.get('DJANGO_LOG_LEVEL', 'WARNING'), 'propagate': False},
    },
}

# Shared secret Vercel sends with its daily cron request (see config/views.py).
CRON_SECRET = os.environ.get('CRON_SECRET', '')

# Default primary key field type

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
