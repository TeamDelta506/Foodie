"""WSGI entry point for gunicorn (Docker / production)."""


def create_app():
    from app import app

    return app
