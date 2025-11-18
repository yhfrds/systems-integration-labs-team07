# projekt\routes\order_routes.py
from flask import redirect, url_for, flash, render_template, abort
from flask_login import login_required, current_user
from decimal import Decimal
from ..models import Order, OrderItem, Product
from .. import db
from .general_routes import get_cart, clear_cart


def register_order_routes(app):

    @app.route('/checkout', methods=['POST'])
    @login_required
    def checkout():
        cart = get_cart()
        if not cart:
            flash('Cart is empty')
            return redirect(url_for('index'))

        total = Decimal('0.00')
        items_for_order = []

        for pid_str, qty in cart.items():
            p = Product.query.get(int(pid_str))
            if p:
                subtotal = p.price * qty
                total += subtotal
                items_for_order.append(
                    {'product': p, 'quantity': qty, 'unit_price': p.price})

        o = Order(user_id=current_user.id, total_price=total, status='pending')
        db.session.add(o)
        db.session.commit()

        for it in items_for_order:
            oi = OrderItem(order_id=o.id, product_id=it['product'].id,
                           quantity=it['quantity'], unit_price=it['unit_price'])
            db.session.add(oi)

        db.session.commit()
        clear_cart()
        flash('Order placed')
        return redirect(url_for('orders'))

    @app.route('/orders')
    @login_required
    def orders():
        my_orders = Order.query.filter_by(
            user_id=current_user.id).order_by(Order.created_at.desc()).all()
        return render_template('orders.html', orders=my_orders)

    @app.route('/order/<int:order_id>')
    @login_required
    def order_detail(order_id):
        o = Order.query.get_or_404(order_id)
        if o.user_id != current_user.id:
            abort(403)
        return render_template('order_detail.html', order=o)

    @app.route('/order/<int:order_id>/status', methods=['POST'])
    def change_status(order_id):
        from flask import request
        new_status = request.form.get('status')
        o = Order.query.get_or_404(order_id)

        if new_status not in ('pending', 'shipped', 'completed'):
            flash('Invalid status')
        else:
            o.status = new_status
            db.session.commit()
            flash('Order status updated')

        return redirect(url_for('index'))
