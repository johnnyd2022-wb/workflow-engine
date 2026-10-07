"""Gunicorn entry point: `gunicorn --config gunicorn.admin.conf.py app.admin_site.wsgi:app`."""

from app.admin_site.app_factory import create_admin_app

app = create_admin_app()
