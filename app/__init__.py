import logging
import os
from datetime import timedelta

from flask import Flask


def create_app():
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s %(levelname)s %(name)s: %(message)s',
    )

    app = Flask(__name__)
    app.secret_key = os.environ.get('SECRET_KEY', 'verevery-change-in-production')
    app.permanent_session_lifetime = timedelta(days=30)

    from .db import init_db
    init_db()

    from .routes import main
    app.register_blueprint(main)
    return app
