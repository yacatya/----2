from flask import Flask
import os

def create_app():
    app = Flask(__name__)
    app.secret_key = os.environ.get('SECRET_KEY', 'verevery-change-in-production')
    app.permanent_session_lifetime = 60 * 60 * 24 * 30  # 30 days

    from .db import init_db
    init_db()

    from .routes import main
    app.register_blueprint(main)
    return app
