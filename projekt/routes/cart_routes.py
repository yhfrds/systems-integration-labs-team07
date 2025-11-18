from flask import render_template, request, redirect, url_for, flash, session
from decimal import Decimal
from ..models import Product
from .general_routes import get_cart, save_cart, clear_cart


def save_cart(cart):
    session['cart'] = cart
    session.modified = True


def clear_cart():
    session.pop('cart', None)
    session.modified = True


def register_cart_routes(app):

    @app.route('/cart/add/<int:product_id>', methods=['POST'])
    def cart_add(product_id):
        product = Product.query.get_or_404(product_id)
        cart = get_cart()
        qty = int(request.form.get('quantity', 1))
        qty = max(1, qty)
        cart[str(product_id)] = cart.get(str(product_id), 0) + qty
        save_cart(cart)
        flash(f'Added {qty} × {product.name} to cart')
        return redirect(url_for('index'))

    @app.route('/cart')
    def cart_view():
        cart = get_cart()
        items = []
        total = Decimal('0.00')

        for pid_str, qty in cart.items():
            p = Product.query.get(int(pid_str))
            if p:
                subtotal = p.price * qty
                items.append(
                    {'product': p, 'quantity': qty, 'subtotal': subtotal})
                total += subtotal

        return render_template('cart.html', items=items, total=total)

    @app.route('/cart/remove/<int:product_id>', methods=['POST'])
    def cart_remove(product_id):
        cart = get_cart()
        cart.pop(str(product_id), None)
        save_cart(cart)
        flash('Removed item from cart')
        return redirect(url_for('cart_view'))
