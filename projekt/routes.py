# projekt/routes.py

from flask import render_template, request, redirect, url_for, flash, session, abort
from flask_login import login_user, logout_user, login_required, current_user
from decimal import Decimal

# +++ NEUE IMPORTE FÜR ON-DEMAND-SYNC HINZUFÜGEN +++
import requests
import csv
import os
from requests.auth import HTTPBasicAuth
from datetime import datetime
# +++ ENDE NEUE IMPORTE +++

from . import app, db  # Importiert app und db aus __init__.py
from .models import User, Product, Order, OrderItem


# --- KONFIGURATION FÜR ON-DEMAND-SYNC ---
ERP_CSV_URL = 'http://localhost:4004/rest/api/getProducts'
ERP_USERNAME = 'alice'  # Hier Anmeldedaten eintragen
ERP_PASSWORD = 'alice'      # Hier Anmeldedaten eintragen
ERP_IMPORTS_DIR = 'erp_imports'
CSV_SAVE_FILENAME = 'erp_products_archive.csv'
CSV_DELIMITER = ','
CSV_PRICE_DECIMAL = '.'
# --- ENDE KONFIGURATION ---


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
    if request.method == 'POST':
        # Formulardaten abrufen
        name = request.form['name'].strip()
        address = request.form.get('address', '').strip()
        email = request.form['email'].strip().lower()
        current_password = request.form['current_password']
        new_password = request.form.get('new_password')

        # 1. Aktuelles Passwort überprüfen
        if not current_user.check_password(current_password):
            flash('Incorrect current password. No changes were made.')
            return redirect(url_for('profile'))

        # 2. Allgemeine Informationen aktualisieren
        current_user.name = name
        current_user.address = address
        update_made = True

        # 3. E-Mail-Adresse aktualisieren (falls geändert)
        if current_user.email != email:
            # Prüfen, ob die neue E-Mail bereits vergeben ist
            if User.query.filter(User.email == email, User.id != current_user.id).first():
                flash('This email address is already in use by another account.')
                return redirect(url_for('profile'))
            current_user.email = email
            update_made = True

        # 4. Passwort aktualisieren (falls ein neues eingegeben wurde)
        if new_password:
            current_user.set_password(new_password)
            update_made = True

        # 5. Änderungen in der Datenbank speichern
        if update_made:
            db.session.commit()
            flash('Profile updated successfully.')
        else:
            flash('No changes detected.')

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


# +++ NEUE ON-DEMAND SYNC ROUTE +++
@app.route('/admin/sync', methods=['GET', 'POST'])
@login_required
def admin_sync():
    """
    Zeigt die Admin-Sync-Seite (GET) und führt den
    On-Demand-Sync (POST) aus.
    Geschützt durch @login_required (jeder eingeloggte Benutzer).
    """

    if request.method == 'POST':
        # --- START SYNC-LOGIK ---
        print(f"[{datetime.now()}] Starte manuellen ERP-CSV-Sync...")

        # --- TEIL 0: SPEICHERPFAD DEFINIEREN ---
        try:
            # app.root_path ist der 'projekt' Ordner
            base_dir = os.path.dirname(app.root_path)  # Geht eine Ebene hoch
            imports_dir_path = os.path.join(base_dir, ERP_IMPORTS_DIR)
            os.makedirs(imports_dir_path, exist_ok=True)
            csv_save_path = os.path.join(imports_dir_path, CSV_SAVE_FILENAME)
        except Exception as e:
            flash(f"Fehler beim Erstellen des Ordner-Pfads: {e}")
            return redirect(url_for('admin_sync'))

        # --- TEIL 1: CSV-Datei herunterladen und speichern ---
        try:
            print(
                f"Versuche Download von {ERP_CSV_URL} mit Benutzer: {ERP_USERNAME}...")
            csv_response = requests.get(
                ERP_CSV_URL,
                timeout=10,
                auth=HTTPBasicAuth(ERP_USERNAME, ERP_PASSWORD)
            )
            csv_response.raise_for_status()
            with open(csv_save_path, 'w', encoding='utf-8', newline='') as f:
                f.write(csv_response.text)
            print(f"Erfolgreich: CSV-Archiv gespeichert unter {csv_save_path}")

        except requests.exceptions.ConnectionError:
            flash("Fehler (CSV): Konnte keine Verbindung zum ERP-Server herstellen.")
            return redirect(url_for('admin_sync'))
        except requests.exceptions.RequestException as e:
            if "401" in str(e):
                flash(
                    f"Fehler (CSV): Authentifizierung fehlgeschlagen (401). Bitte ERP_USERNAME und ERP_PASSWORD im Skript prüfen.")
            else:
                flash(f"Fehler (CSV): Beim Download der CSV-Datei: {e}.")
            return redirect(url_for('admin_sync'))
        except IOError as e:
            flash(
                f"Fehler (CSV): Beim Schreiben der Datei auf die Festplatte: {e}.")
            return redirect(url_for('admin_sync'))

        # --- TEIL 2: Gespeicherte CSV einlesen & DB aktualisieren ---
        created_count = 0
        updated_count = 0
        errors_count = 0
        deleted_count = 0
        erp_ids_from_sync = set()

        try:
            with open(csv_save_path, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f, delimiter=CSV_DELIMITER)

                for row in reader:
                    try:
                        # Angepasst an die Spaltennamen Ihrer CSV
                        erp_id = row.get('productID')
                        name = row.get('name')
                        price_raw = row.get('price')
                        description_raw = row.get('description')

                        if not erp_id or not name or price_raw is None:
                            print(
                                f"Übersprungen: Unvollständige Daten in Zeile: {row}")
                            errors_count += 1
                            continue

                        # Datenbereinigung
                        price_str_clean = str(price_raw).replace(
                            ' null', '').strip()
                        price = Decimal(price_str_clean)
                        description = description_raw if description_raw and str(
                            description_raw) != 'NaN' else ''
                        erp_id_str = str(erp_id)
                        erp_ids_from_sync.add(erp_id_str)

                        # Produkt in DB suchen
                        product = Product.query.filter_by(
                            erp_id=erp_id_str).first()

                        if product:
                            product.name = name
                            product.description = description
                            product.price = price
                            updated_count += 1
                        else:
                            product = Product(
                                erp_id=erp_id_str, name=name, description=description, price=price)
                            db.session.add(product)
                            created_count += 1

                    except Exception as e:
                        print(f"Fehler bei Verarbeitung der Zeile {row}: {e}")
                        errors_count += 1

            # --- TEIL 3: Produkte löschen ---
            products_to_check = Product.query.filter(
                Product.erp_id != None).all()
            for prod in products_to_check:
                if prod.erp_id not in erp_ids_from_sync:
                    db.session.delete(prod)
                    deleted_count += 1

            # --- TEIL 4: Änderungen in die DB schreiben ---
            db.session.commit()
            flash(
                f"ERP-Sync erfolgreich! Erstellt: {created_count}, Aktualisiert: {updated_count}, Gelöscht: {deleted_count}, Fehler: {errors_count}", 'success')

        except FileNotFoundError:
            flash(f"Fehler: Die Datei {csv_save_path} wurde nicht gefunden.")
        except Exception as e:
            db.session.rollback()
            flash(f"Fehler (CSV) beim Einlesen der Datei oder DB-Update: {e}")

        # --- ENDE SYNC-LOGIK ---

        return redirect(url_for('admin_sync'))

    # GET Request: Zeige einfach die Admin-Seite mit dem Button an
    return render_template('admin_sync.html')
