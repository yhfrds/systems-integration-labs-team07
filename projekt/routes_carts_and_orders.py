from flask import render_template, request, redirect, url_for, flash, abort
from flask_login import login_required, current_user
from decimal import Decimal

import requests
from datetime import datetime

# We import erp_session here to use the global session with retry logic
from projekt.routes_helpers import ERP_ORDERS_URL, ERP_TIMEOUT, clear_cart, get_cart, get_erp_stock, get_or_create_erp_customer, save_cart, erp_session, ERP_PRODUCTS_URL

# Imports app, db, and scheduler from __init__.py
from . import app, db


def get_product(product_id):
    """
    Attempts to load a product from the ERP.
    Returns None if the ERP is unreachable or the product is not found.
    """
    try:
        url = f"{ERP_PRODUCTS_URL}?$filter=ID eq {product_id}"
        # We use erp_session which already has retry logic.
        # We must still catch the final ConnectionError if it fails.
        response = erp_session.get(url, timeout=ERP_TIMEOUT)
        response.raise_for_status()

        data = response.json().get('value', [])
        if not data:
            return None

        return data[0]
    except requests.exceptions.RequestException as e:
        print(f"ERP Connection Error in get_product: {e}")
        return None

# --- Cart & Order Routes ---
@app.route('/cart/add/<string:product_id>', methods=['POST'])
def cart_add(product_id):
    
    product = get_product(product_id)

    # +++ NEW: Check for ERP availability +++
    if not product:
        flash("The ERP system is currently unreachable. The product could not be added to the cart.", "danger")
        return redirect(url_for('index'))
    # +++ END NEW +++

    cart = get_cart()
    qty = int(request.form.get('quantity', 1))
    if qty < 1: qty = 1
    
    # +++ Real-time stock check on add +++
    current_in_cart = cart.get(product_id, 0)
    total_wanted = current_in_cart + qty
    
    real_stock = get_erp_stock(product['ID'])
    
    if total_wanted > real_stock:
        flash(f"Error: Not enough stock for '{product['name']}'. Available: {real_stock}, You wanted: {total_wanted}")
        return redirect(request.referrer or url_for('index'))
    # +++ END Stock check +++
    
    cart[product_id] = total_wanted # Uses GUID as key
    save_cart(cart)
    flash(f"Added {qty} × {product['name']} to cart")
    return redirect(request.referrer or url_for('index'))

@app.route('/cart')
def cart_view():
    cart = get_cart()
    items = []
    total = Decimal('0.00')
    
    cart_changed = False
    
    # Iterate through cart items
    for pid_str_guid, qty in list(cart.items()): 
        p = get_product(pid_str_guid)
        
        if not p:
            # Fail Safe: If get_product returns None, the ERP might be down.
            # We show a warning and stop processing the cart to avoid crashes.
            flash("Cart cannot be loaded at the moment (ERP unreachable).", "danger")
            return render_template('cart.html', items=[], total=0)
        
        # +++ Get real-time stock for the view +++
        real_stock = get_erp_stock(p['ID'])
        
        subtotal = (p['price'] * qty)
        items.append({
            'product': p, 
            'quantity': qty, 
            'subtotal': subtotal,
            'real_stock': real_stock 
        })
        total += subtotal
    
    if cart_changed:
        save_cart(cart)
        flash("Some items in your cart were no longer available and have been removed.")
        
    return render_template('cart.html', items=items, total=total)

@app.route('/cart/remove/<string:product_id>', methods=['POST'])
def cart_remove(product_id):
    cart = get_cart()
    cart.pop(product_id, None) # Uses GUID as key
    save_cart(cart)
    flash('Removed item from cart')
    return redirect(url_for('cart_view'))

@app.route('/checkout', methods=['POST'])
@login_required
def checkout():
    cart = get_cart() 
    
    if not cart:
        flash('Cart is empty')
        return redirect(url_for('index'))

    # --- 1. Get/create ERP customer ID ---
    try:
        erp_customer_id = get_or_create_erp_customer(current_user)
        if not erp_customer_id:
            flash("Critical Error: Your customer account could not be found or created in the ERP system.")
            return redirect(url_for('cart_view'))
    except Exception as e:
        flash(f"Error during customer synchronization: {e}")
        return redirect(url_for('cart_view'))

    erp_items_payload = []
    total = Decimal('0.00')

    # --- 2. Validate cart (Price & Real-time Stock) ---
    
    for pid_guid, qty in list(cart.items()): 
        p = get_product(pid_guid)
        if not p:
            # +++ NEW: Fail Safe +++
            flash(f"Checkout aborted: ERP system unreachable.", "danger")
            return redirect(url_for('cart_view'))
            # +++ END NEW +++

        # --- REAL-TIME STOCK CHECK ---
        real_stock = get_erp_stock(p['ID'])
        if qty > real_stock:
            flash(f"Stock for '{p['name']}' insufficient (Available: {real_stock}). Order canceled.")
            return redirect(url_for('cart_view'))
        
        # +++ PRICE CALCULATION +++
        subtotal = (p['price'] * qty)
        total += subtotal
        
        # For ERP payload
        erp_items_payload.append({
            "product_ID": p['ID'], # The product GUID
            "quantity": qty,
            "itemAmount": str(subtotal)
        })

    if not erp_items_payload:
        flash("Cart is empty after check.")
        return redirect(url_for('cart_view'))

    # --- 3. Send order to ERP (Deep Insert) ---
    cust_id = erp_customer_id['ID'] if isinstance(erp_customer_id, dict) else erp_customer_id

    order_payload = {
        "customer_ID": cust_id,
        "orderDate": datetime.utcnow().strftime('%Y-%m-%d'),
        "currency_code": "EUR",
        "orderAmount": str(total),
        "items": erp_items_payload
    }

    try:
        response = erp_session.post(ERP_ORDERS_URL, json=order_payload, timeout=ERP_TIMEOUT)
        
        if response.status_code == 201:
            clear_cart()
            flash('Order successfully transmitted to ERP!')
            return redirect(url_for('orders'))
            
        elif response.status_code == 400 or response.status_code == 422:
            try:
                error_msg = response.json().get('error', {}).get('message', 'Unknown ERP error')
                details = response.json().get('error', {}).get('details', [])
                if details:
                    detail_messages = [d.get('message') for d in details if d.get('message')]
                    error_msg += ": " + ", ".join(detail_messages)
            except requests.exceptions.JSONDecodeError:
                error_msg = response.text
                
            flash(f"ERP Error: {error_msg}")
            return redirect(url_for('cart_view'))
        else:
            flash(f"Unexpected ERP error: {response.status_code} - {response.text}")
            response.raise_for_status()

    except requests.exceptions.RequestException as e:
        flash(f"Critical connection error to ERP: {e}")
        return redirect(url_for('cart_view'))
    except Exception as e:
        db.session.rollback()
        flash(f"General error during checkout: {e}")
        return redirect(url_for('cart_view'))


@app.route('/orders')
@login_required
def orders():
    """
    Fetches the order list LIVE from the ERP system (RPC).
    Handles ERP connection errors gracefully.
    """
    my_orders = []
    
    if current_user.erp_customer_id:
        try:
            cust_id = current_user.erp_customer_id
            
            url = f"{ERP_ORDERS_URL}?$filter=customer_ID eq {cust_id}&$orderby=createdAt desc"
            response = erp_session.get(url, timeout=ERP_TIMEOUT)
            
            if response.status_code == 200:
                my_orders = response.json().get('value', [])
            else:
                flash(f"Could not load orders (ERP Status: {response.status_code})", "warning")
                
        # +++ CHANGED: Catch connection errors specifically +++
        except requests.exceptions.RequestException:
            flash("The ERP system is currently unreachable. Your orders cannot be loaded at this time.", "danger")
        except Exception as e:
            flash(f"General error loading orders: {e}", "danger")

    return render_template('orders.html', orders=my_orders)

@app.route('/order/<string:order_id>')
@login_required
def order_detail(order_id):
    """
    Fetches details of an order LIVE from the ERP.
    Handles ERP connection errors gracefully.
    """
    order_data = None
    
    try:
        url = f"{ERP_ORDERS_URL}({order_id})?$expand=items($expand=product)"
        response = erp_session.get(url, timeout=ERP_TIMEOUT)
        
        if response.status_code == 200:
            order_data = response.json()
            
            if order_data.get('customer_ID') != current_user.erp_customer_id:
                abort(403) # Forbidden
        elif response.status_code == 404:
            abort(404)
        else:
            flash(f"ERP Error: {response.status_code}", "danger")
            return redirect(url_for('orders'))
    
    # +++ CHANGED: Catch connection errors specifically +++
    except requests.exceptions.RequestException:
        flash("The ERP system is currently unreachable. Order details cannot be loaded.", "danger")
        return redirect(url_for('orders'))
    except Exception as e:
        flash(f"General Error: {e}", "danger")
        return redirect(url_for('orders'))

    return render_template('order_detail.html', order=order_data)