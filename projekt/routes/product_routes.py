from flask import render_template, request, redirect, url_for, flash
from decimal import Decimal
from ..models import Product
from .. import db
from .general_routes import get_cart


def register_product_routes(app):

    @app.route('/product/new', methods=['GET', 'POST'])
    def product_new():
        if request.method == 'POST':
            name = request.form['name'].strip()
            desc = request.form.get('description', '').strip()
            price_raw = request.form['price']
            try:
                price = Decimal(price_raw)
            except:
                flash('Invalid price format')
                return redirect(url_for('product_new'))
            p = Product(name=name, description=desc, price=price)
            db.session.add(p)
            db.session.commit()
            flash('Product added')
            return redirect(url_for('index'))
        return render_template('product_form.html')

    @app.route('/product/<int:product_id>/delete', methods=['POST'])
    def product_delete(product_id):
        p = Product.query.get_or_404(product_id)
        db.session.delete(p)
        db.session.commit()
        flash('Product removed')
        return redirect(url_for('index'))
