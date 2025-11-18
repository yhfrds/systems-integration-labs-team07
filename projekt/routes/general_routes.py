from flask import render_template, session
from ..models import Product

# Helper: cart operations (stored in session)


def get_cart():
    return session.get('cart', {})  # {product_id: quantity}


def save_cart(cart):
    session['cart'] = cart
    session.modified = True


def clear_cart():
    session.pop('cart', None)
    session.modified = True


def register_general_routes(app):
    @app.route('/')
    def index():
        products = Product.query.all()
        return render_template('index.html', products=products, cart=get_cart())
