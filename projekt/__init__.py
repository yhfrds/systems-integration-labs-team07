# projekt/__init__.py

from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager

# App und Konfiguration initialisieren
app = Flask(__name__)
app.config['SECRET_KEY'] = 'dev-secret-key-change-me'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///shop.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Datenbank- und Login-Erweiterungen initialisieren
db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login' # Name der Login-Funktion/Route

# Der User Loader wird hier definiert, da er das User-Modell benötigt
from .models import User
@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# Wichtig: Die Routen am Ende importieren, um zirkuläre Importe zu vermeiden
from . import routes