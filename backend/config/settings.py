"""
智能简历筛选系统 — Django 配置。

Demo 默认：SQLite + Celery eager（同步执行，免装 Redis）。
生产可通过环境变量切换 PostgreSQL，并启用 Celery + Redis。
"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def env_bool(key, default=False):
    return os.environ.get(key, str(default)).lower() in ("1", "true", "yes", "on")


SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "demo-insecure-secret-key-change-me")
DEBUG = env_bool("DJANGO_DEBUG", True)
ALLOWED_HOSTS = os.environ.get("DJANGO_ALLOWED_HOSTS", "*").split(",")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # 第三方
    "rest_framework",
    "rest_framework.authtoken",
    "corsheaders",
    "django_filters",
    # 业务 app
    "apps.accounts",
    "apps.core",
    "apps.ingestion",
    "apps.pipeline",
    "apps.api",
]

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# 数据库：默认 SQLite，设置 POSTGRES_DB 时切换 PostgreSQL
if os.environ.get("POSTGRES_DB"):
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": os.environ["POSTGRES_DB"],
            "USER": os.environ.get("POSTGRES_USER", "postgres"),
            "PASSWORD": os.environ.get("POSTGRES_PASSWORD", "postgres"),
            "HOST": os.environ.get("POSTGRES_HOST", "localhost"),
            "PORT": os.environ.get("POSTGRES_PORT", "5432"),
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }

AUTH_USER_MODEL = "accounts.User"

AUTH_PASSWORD_VALIDATORS = []

LANGUAGE_CODE = "zh-hans"
TIME_ZONE = "Asia/Shanghai"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"
if os.environ.get("FILE_UPLOAD_TEMP_DIR"):
    FILE_UPLOAD_TEMP_DIR = os.environ["FILE_UPLOAD_TEMP_DIR"]
DATA_UPLOAD_MAX_MEMORY_SIZE = None

# 扫描版 PDF 仅在 AI 正文抽取不足时进入本地 OCR；限制均可由部署环境覆盖。
RESUME_OCR_MAX_PAGES = int(os.environ.get("RESUME_OCR_MAX_PAGES", "20"))
RESUME_OCR_DPI = int(os.environ.get("RESUME_OCR_DPI", "200"))
RESUME_OCR_TIMEOUT_SECONDS = int(
    os.environ.get("RESUME_OCR_TIMEOUT_SECONDS", "120")
)
RESUME_OCR_CONCURRENCY = int(os.environ.get("RESUME_OCR_CONCURRENCY", "2"))

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# DRF：正式项目默认启用登录态。W3 接入前，本地开发使用 Token 登录。
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.TokenAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_PAGINATION_CLASS": "apps.api.pagination.StandardResultsSetPagination",
    "PAGE_SIZE": 20,
    "DEFAULT_FILTER_BACKENDS": ["django_filters.rest_framework.DjangoFilterBackend"],
}

# CORS：demo 允许全部来源（前端 dev server 调用）
CORS_ALLOW_ALL_ORIGINS = True

# Celery：demo 默认 eager（同步执行，不需要 Redis/worker）
CELERY_BROKER_URL = os.environ.get("CELERY_BROKER_URL", "redis://localhost:6379/0")
CELERY_RESULT_BACKEND = os.environ.get("CELERY_RESULT_BACKEND", "redis://localhost:6379/1")
CELERY_TASK_ALWAYS_EAGER = env_bool("CELERY_TASK_ALWAYS_EAGER", True)
CELERY_TASK_EAGER_PROPAGATES = True
CELERY_TASK_DEFAULT_QUEUE = "default"
CELERY_TASK_ROUTES = {
    "apps.pipeline.tasks.process_ai_scope_item_task": {"queue": "ai"},
}
CELERY_WORKER_PREFETCH_MULTIPLIER = 1
# 候选人任务只包含一次模型调用及其有限重试；为 Redis broker 留足可见性窗口，
# 防止长超时请求尚未结束就被重复投递。worker 丢失仍由 acks_late 立即重投。
CELERY_BROKER_TRANSPORT_OPTIONS = {"visibility_timeout": 21600}
