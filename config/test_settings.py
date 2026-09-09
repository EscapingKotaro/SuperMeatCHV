from .settings import *
DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}
MIGRATION_MODULES = {"crm": None}
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
