# projekt/routes.py

from flask import render_template, request, redirect, url_for, flash, session, abort
from flask_login import login_user, logout_user, login_required, current_user
from decimal import Decimal

from . import app, db  # Importiert app und db aus __init__.py
from .models import User, Product, Order, OrderItem


# Helper: cart operations (stored in session)
def get_cart():
    return session.get('cart', {})  # {product_id: quantity}

def save_cart(cart):
    session['cart'] = cart
    session.modified = True

def clear_cart():
    session.pop('cart', None)
    session.modified = True

# --- General & Product Routes ---
@app.route('/')
def index():
    products = Product.query.all()
    return render_template('index.html', products=products, cart=get_cart())

@app.route('/product/new', methods=['GET', 'POST'])
def product_new():
    # ... (Code für product_new kopieren)
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
    # ... (Code für product_delete kopieren)
    p = Product.query.get_or_404(product_id)
    db.session.delete(p)
    db.session.commit()
    flash('Product removed')
    return redirect(url_for('index'))

# --- Auth & User Routes ---
@app.route('/register', methods=['GET', 'POST'])
def register():
    # ... (Code für register kopieren)
    if request.method == 'POST':
        name = request.form['name'].strip()
        email = request.form['email'].strip().lower()
        address = request.form.get('address', '').strip()
        password = request.form['password']
        if User.query.filter_by(email=email).first():
            flash('Email already registered')
            return redirect(url_for('register'))
        u = User(name=name, email=email, address=address)
        u.set_password(password)
        db.session.add(u)
        db.session.commit()
        login_user(u)
        flash('Registered and logged in')
        return redirect(url_for('index'))
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    # ... (Code für login kopieren)
    if request.method == 'POST':
        email = request.form['email'].strip().lower()
        password = request.form['password']
        user = User.query.filter_by(email=email).first()
        if not user or not user.check_password(password):
            flash('Invalid credentials')
            return redirect(url_for('login'))
        login_user(user)
        flash('Logged in')
        return redirect(url_for('index'))
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    # ... (Code für logout kopieren)
    logout_user()
    flash('Logged out')
    return redirect(url_for('index'))

@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    # ... (Code für profile kopieren)
    if request.method == 'POST':
        current_user.name = request.form['name'].strip()
        current_user.address = request.form.get('address', '').strip()
        db.session.commit()
        flash('Profile updated')
        return redirect(url_for('profile'))
    return render_template('profile.html')

# --- Cart & Order Routes ---
@app.route('/cart/add/<int:product_id>', methods=['POST'])
def cart_add(product_id):
    # ... (Code für cart_add kopieren)
    product = Product.query.get_or_404(product_id)
    cart = get_cart()
    qty = int(request.form.get('quantity', 1))
    if qty < 1:
        qty = 1
    cart[str(product_id)] = cart.get(str(product_id), 0) + qty
    save_cart(cart)
    flash(f'Added {qty} × {product.name} to cart')
    return redirect(url_for('index'))

@app.route('/cart')
def cart_view():
    # ... (Code für cart_view kopieren)
    cart = get_cart()
    items = []
    total = Decimal('0.00')
    for pid_str, qty in cart.items():
        pid = int(pid_str)
        p = Product.query.get(pid)
        if not p:
            continue
        subtotal = (p.price * qty)
        items.append({'product': p, 'quantity': qty, 'subtotal': subtotal})
        total += subtotal
    return render_template('cart.html', items=items, total=total)

@app.route('/cart/remove/<int:product_id>', methods=['POST'])
def cart_remove(product_id):
    # ... (Code für cart_remove kopieren)
    cart = get_cart()
    cart.pop(str(product_id), None)
    save_cart(cart)
    flash('Removed item from cart')
    return redirect(url_for('cart_view'))

@app.route('/checkout', methods=['POST'])
@login_required
def checkout():
    # ... (Code für checkout kopieren)
    cart = get_cart()
    if not cart:
        flash('Cart is empty')
        return redirect(url_for('index'))
    total = Decimal('0.00')
    items_for_order = []
    for pid_str, qty in cart.items():
        pid = int(pid_str)
        p = Product.query.get(pid)
        if not p:
            continue
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
    # ... (Code für orders kopieren)
    my_orders = Order.query.filter_by(
        user_id=current_user.id).order_by(Order.created_at.desc()).all()
    return render_template('orders.html', orders=my_orders)

@app.route('/order/<int:order_id>')
@login_required
def order_detail(order_id):
    # ... (Code für order_detail kopieren)
    o = Order.query.get_or_404(order_id)
    if o.user_id != current_user.id:
        abort(403)
    return render_template('order_detail.html', order=o)

@app.route('/order/<int:order_id>/status', methods=['POST'])
def change_status(order_id):
    # ... (Code für change_status kopieren)
    new_status = request.form.get('status')
    o = Order.query.get_or_404(order_id)
    if new_status not in ('pending', 'shipped', 'completed'):
        flash('Invalid status')
    else:
        o.status = new_status
        db.session.commit()
        flash('Order status updated')
    return redirect(url_for('index'))