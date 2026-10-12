from pathlib import Path
import os
from urllib.parse import urlsplit

import dj_database_url
from dotenv import load_dotenv
from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent
# Load local developer settings without overriding values injected by Vercel/CI.
load_dotenv(BASE_DIR / ".env", override=False)

IS_VERCEL = bool(os.environ.get("VERCEL") or os.environ.get("VERCEL_ENV"))
DEBUG = os.environ.get("DJANGO_DEBUG", "0" if IS_VERCEL else "1") == "1"

_secret_key = os.environ.get("DJANGO_SECRET_KEY", "").strip()
if not _secret_key:
    if not DEBUG or IS_VERCEL:
        raise ImproperlyConfigured(
            "DJANGO_SECRET_KEY must be configured for Vercel or whenever DJANGO_DEBUG=0."
        )
    _secret_key = "django-insecure-bidsphere-local-only-change-before-deployment"
SECRET_KEY = _secret_key

_default_hosts = "127.0.0.1,localhost,.vercel.app"
ALLOWED_HOSTS = [
    value.strip()
    for value in os.environ.get("DJANGO_ALLOWED_HOSTS", _default_hosts).split(",")
    if value.strip()
]


def _clean_domain(value):
    if not value:
        return ""
    value = value.strip()
    if "://" in value:
        value = urlsplit(value).netloc
    return value.split("/")[0].strip()


for _host_var in ("VERCEL_URL", "VERCEL_PROJECT_PRODUCTION_URL", "DJANGO_PRIMARY_DOMAIN"):
    _host = _clean_domain(os.environ.get(_host_var, ""))
    if _host and _host not in ALLOWED_HOSTS:
        ALLOWED_HOSTS.append(_host)

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "auction.apps.AuctionConfig",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "bidsphere.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "auction.context_processors.notifications",
            ],
        },
    },
]

WSGI_APPLICATION = "bidsphere.wsgi.application"


def _first_env(*names):
    for name in names:
        value = os.environ.get(name)
        if value:
            return value
    return None


def _discover_database_url():
    value = _first_env(
        "DATABASE_URL",
        "DATABASE_POSTGRES_URL",
        "DATABASE_POSTGRES_URL_NON_POOLING",
        "DATABASE_POSTGRES_URL_UNPOOLED",
        "POSTGRES_URL",
        "POSTGRES_PRISMA_URL",
        "POSTGRES_URL_NON_POOLING",
    )
    if value:
        return value

    # Vercel Marketplace integrations can prefix provider variables (e.g. STORAGE1_).
    preferred_suffixes = (
        "_DATABASE_URL",
        "_POSTGRES_URL_NON_POOLING",
        "_POSTGRES_URL",
    )
    for suffix in preferred_suffixes:
        for key, candidate in os.environ.items():
            if candidate and key.endswith(suffix):
                return candidate
    return None


database_url = _discover_database_url()
if database_url:
    DATABASES = {
        "default": dj_database_url.parse(
            database_url,
            conn_max_age=0,
            conn_health_checks=True,
            # Require TLS in deployed/prod environments, but let local and CI
            # PostgreSQL services run without TLS when DEBUG=1 outside Vercel.
            ssl_require=(not DEBUG or IS_VERCEL),
        )
    }
elif DEBUG and not IS_VERCEL:
    # Convenient local development only. Vercel must never silently fall back
    # to an ephemeral SQLite file on a serverless instance.
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }
else:
    raise ImproperlyConfigured(
        "Set DATABASE_URL (or a supported PostgreSQL provider URL) in production."
    )

if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_SSL_REDIRECT = True
    # Vercel and the configured custom domain are HTTPS-only in production.
    # Do not enable includeSubDomains/preload by default: a custom domain may
    # have unrelated subdomains managed outside this project.
    SECURE_HSTS_SECONDS = int(os.environ.get("DJANGO_SECURE_HSTS_SECONDS", "31536000"))
    SECURE_HSTS_INCLUDE_SUBDOMAINS = os.environ.get("DJANGO_HSTS_INCLUDE_SUBDOMAINS", "0") == "1"
    SECURE_HSTS_PRELOAD = os.environ.get("DJANGO_HSTS_PRELOAD", "0") == "1"
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SECURE_REFERRER_POLICY = "same-origin"
    X_FRAME_OPTIONS = "DENY"
    CSRF_TRUSTED_ORIGINS = ["https://*.vercel.app"]
    primary_domain = _clean_domain(os.environ.get("DJANGO_PRIMARY_DOMAIN", ""))
    if primary_domain:
        CSRF_TRUSTED_ORIGINS.append(f"https://{primary_domain}")

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 12}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "Asia/Kolkata"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"] if (BASE_DIR / "static").is_dir() else []
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

# Use S3-compatible object storage (AWS S3, Cloudflare R2, etc.) when configured.
# Vercel's local filesystem is not durable for uploaded media. For production,
# configure AWS_STORAGE_BUCKET_NAME and the provider's credentials/endpoint.
_storage_bucket = os.environ.get("AWS_STORAGE_BUCKET_NAME", "").strip()
if _storage_bucket:
    INSTALLED_APPS.append("storages")
    STORAGES = {
        "default": {"BACKEND": "storages.backends.s3.S3Storage"},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    }
    AWS_STORAGE_BUCKET_NAME = _storage_bucket
    AWS_S3_REGION_NAME = os.environ.get("AWS_S3_REGION_NAME") or None
    AWS_S3_ENDPOINT_URL = os.environ.get("AWS_S3_ENDPOINT_URL") or None
    AWS_S3_CUSTOM_DOMAIN = os.environ.get("AWS_S3_CUSTOM_DOMAIN") or None
    AWS_S3_URL_PROTOCOL = "https:"
    AWS_ACCESS_KEY_ID = os.environ.get("AWS_ACCESS_KEY_ID") or None
    AWS_SECRET_ACCESS_KEY = os.environ.get("AWS_SECRET_ACCESS_KEY") or None
    AWS_S3_ADDRESSING_STYLE = os.environ.get("AWS_S3_ADDRESSING_STYLE", "auto")
    AWS_S3_FILE_OVERWRITE = False
    AWS_DEFAULT_ACL = None
    AWS_QUERYSTRING_AUTH = os.environ.get("AWS_QUERYSTRING_AUTH", "0") == "1"
    AWS_S3_OBJECT_PARAMETERS = {"CacheControl": "max-age=86400"}
else:
    STORAGES = {
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    }

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "dashboard"
LOGOUT_REDIRECT_URL = "home"

ANTI_SNIPE_WINDOW_SECONDS = 120
ANTI_SNIPE_EXTENSION_SECONDS = 120
