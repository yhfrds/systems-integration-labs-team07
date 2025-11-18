from projekt.models import User  # Now db exists, safe to import
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager

# App und Konfiguration initialisieren
app = Flask(__name__)
app.config['SECRET_KEY'] = 'dev-secret-key-change-me'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///shop.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Datenbank- und Login-Erweiterungen initialisieren
db = SQLAlchemy()
db.init_app(app)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'  # Name der Login-Funktion/Route

# --- Import Models AFTER db is initialized ---

# User Loader


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# --- Import routes AFTER app/db are ready ---


def register_routes(app):
    from projekt.routes.general_routes import register_general_routes
    from projekt.routes.auth_routes import register_auth_routes
    from projekt.routes.product_routes import register_product_routes
    from projekt.routes.cart_routes import register_cart_routes
    from projekt.routes.admin_routes import register_admin_routes
    from projekt.routes.order_routes import register_order_routes

    # Register all routes
    register_general_routes(app)
    register_auth_routes(app)
    register_product_routes(app)
    register_cart_routes(app)
    register_admin_routes(app)
    register_order_routes(app)


register_routes(app)
