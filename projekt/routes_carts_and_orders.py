# projekt/routes_carts_and_orders.py

from flask import render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from decimal import Decimal
import requests
from datetime import datetime

# Import Helper
from projekt.routes_helpers import (
    get_cart, save_cart, clear_cart, 
    get_erp_stock, get_or_create_erp_customer, 
    send_order_via_mq,  # <--- Wichtig: MQ Helper
    erp_session, ERP_PRODUCTS_URL, ERP_TIMEOUT
)

from . import app

def get_product(product_id):
    """Lädt Produkt per REST (für Warenkorb-Anzeige)."""
    try:
        url = f"{ERP_PRODUCTS_URL}?$filter=ID eq {product_id}"
        response = erp_session.get(url, timeout=ERP_TIMEOUT)
        response.raise_for_status()
        data = response.json().get('value', [])
        if not data:
            return None
        return data[0]
    except Exception:
        return None

# --- Cart Routes ---

@app.route('/cart/add/<string:product_id>', methods=['POST'])
def cart_add(product_id):
    product = get_product(product_id)
    if not product:
        flash("ERP nicht erreichbar oder Produkt nicht gefunden.", "danger")
        return redirect(url_for('index'))

    cart = get_cart()
    qty = int(request.form.get('quantity', 1))
    if qty < 1: qty = 1
    
    # Stock Check (REST)
    current_in_cart = cart.get(product_id, 0)
    real_stock = get_erp_stock(product['ID'])
    
    if (current_in_cart + qty) > real_stock:
        flash(f"Nicht genug Lagerbestand. Verfügbar: {real_stock}", "warning")
        return redirect(request.referrer or url_for('index'))
    
    cart[product_id] = current_in_cart + qty
    save_cart(cart)
    flash(f"{qty} x {product['name']} hinzugefügt.")
    return redirect(request.referrer or url_for('index'))

@app.route('/cart')
def cart_view():
    cart = get_cart()
    items = []
    total = Decimal('0.00')
    
    cart_changed = False
    
    # Wir iterieren über eine Kopie, falls wir löschen müssen
    for pid, qty in list(cart.items()):
        p = get_product(pid)
        if not p:
            flash("Warenkorb kann wegen ERP-Problemen nicht vollständig geladen werden.", "danger")
            return render_template('cart.html', items=[], total=0)
            
        real_stock = get_erp_stock(p['ID'])
        # Optional: Automatisch anpassen wenn Stock < Qty
        
        subtotal = Decimal(str(p['price'])) * qty
        items.append({
            'product': p,
            'quantity': qty,
            'subtotal': subtotal,
            'real_stock': real_stock
        })
        total += subtotal
        
    return render_template('cart.html', items=items, total=total)

@app.route('/cart/remove/<string:product_id>', methods=['POST'])
def cart_remove(product_id):
    cart = get_cart()
    cart.pop(product_id, None)
    save_cart(cart)
    flash('Artikel entfernt.')
    return redirect(url_for('cart_view'))


# --- CHECKOUT (MESSAGING) ---

@app.route('/checkout', methods=['POST'])
@login_required
def checkout():
    cart = get_cart()
    if not cart:
        flash('Warenkorb ist leer.')
        return redirect(url_for('index'))

    # 1. Customer Sync (REST) - Wir brauchen die ID
    try:
        # Gibt die ID als String zurück oder None
        erp_customer_id = get_or_create_erp_customer(current_user)
        if not erp_customer_id:
            flash("Fehler: Kundenkonto konnte im ERP nicht synchronisiert werden.", "danger")
            return redirect(url_for('cart_view'))
    except Exception as e:
        flash(f"Sync-Fehler: {e}", "danger")
        return redirect(url_for('cart_view'))

    # 2. Payload bauen
    erp_items_payload = []
    total = Decimal('0.00')

    for pid, qty in list(cart.items()):
        p = get_product(pid)
        if not p:
            flash("Produktinformationen konnten nicht geladen werden.", "danger")
            return redirect(url_for('cart_view'))
            
        # Optional: Letzter Stock Check hier
        
        subtotal = Decimal(str(p['price'])) * qty
        total += subtotal
        
        erp_items_payload.append({
            "product_ID": p['ID'],
            "quantity": qty,
            "itemAmount": str(subtotal)
        })

    order_payload = {
        "customer_ID": erp_customer_id,
        "orderDate": datetime.utcnow().strftime('%Y-%m-%d'),
        "currency_code": "EUR",
        "orderAmount": str(total),
        "items": erp_items_payload
    }

    # 3. SENDEN AN RABBITMQ (RPC)
    # Hier wird der REST-Aufruf durch den MQ-Aufruf ersetzt
    response_data = send_order_via_mq(order_payload)

    # 4. Antwort prüfen
    if "error" in response_data:
        # Fehlerfall
        err_msg = response_data["error"]
        # Falls es ein komplexes Fehlerobjekt vom ERP ist:
        if isinstance(err_msg, dict):
            err_msg = err_msg.get('message', str(err_msg))
            
        flash(f"Fehler bei der Bestellung (MQ/ERP): {err_msg}", "danger")
        return redirect(url_for('cart_view'))
    
    # Erfolgsfall (z.B. ERP sendet das erstellte Order-Objekt zurück)
    # Wir prüfen grob auf Erfolg (z.B. ID vorhanden oder kein Error Key)
    clear_cart()
    flash('Bestellung erfolgreich an das ERP-System übermittelt (Messaging)!', 'success')
    return redirect(url_for('orders'))


# --- Orders Read (Bleibt REST für Live-Ansicht) ---
# Da die Aufgabe nur das SENDEN per Message forderte, lesen wir weiter per REST.

from projekt.routes_helpers import ERP_ORDERS_URL

@app.route('/orders')
@login_required
def orders():
    my_orders = []
    if current_user.erp_customer_id:
        try:
            url = f"{ERP_ORDERS_URL}?$filter=customer_ID eq {current_user.erp_customer_id}&$orderby=createdAt desc"
            resp = erp_session.get(url, timeout=10)
            if resp.status_code == 200:
                my_orders = resp.json().get('value', [])
        except Exception:
            flash("Bestellliste konnte nicht geladen werden.", "warning")
            
    return render_template('orders.html', orders=my_orders)

@app.route('/order/<string:order_id>')
@login_required
def order_detail(order_id):
    order_data = None
    try:
        url = f"{ERP_ORDERS_URL}({order_id})?$expand=items($expand=product)"
        resp = erp_session.get(url, timeout=10)
        if resp.status_code == 200:
            order_data = resp.json()
    except Exception:
        pass
        
    if not order_data:
        flash("Details nicht verfügbar.", "danger")
        return redirect(url_for('orders'))
        
    return render_template('order_detail.html', order=order_data)