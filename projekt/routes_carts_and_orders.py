from flask import render_template, request, redirect, url_for, flash, abort
from flask_login import login_required, current_user
from decimal import Decimal

import requests
from datetime import datetime

from projekt.routes_helpers import ERP_ORDERS_URL, ERP_TIMEOUT, clear_cart, get_cart, get_erp_stock, get_or_create_erp_customer, save_cart, erp_session

# Imports app, db, and scheduler from __init__.py
from . import app, db
from .models import Product

# --- Cart & Order Routes ---
@app.route('/cart/add/<string:product_id>', methods=['POST']) # CHANGED: int -> string
def cart_add(product_id):
    product = Product.query.get_or_404(product_id) # Now searches by GUID
    cart = get_cart()
    qty = int(request.form.get('quantity', 1))
    if qty < 1: qty = 1
    
    # +++ NEW: Real-time stock check on add +++
    current_in_cart = cart.get(product_id, 0)
    total_wanted = current_in_cart + qty
    
    real_stock = get_erp_stock(product.id)
    
    if total_wanted > real_stock:
        flash(f"Error: Not enough stock for '{product.name}'. Available: {real_stock}, You wanted: {total_wanted}")
        return redirect(request.referrer or url_for('index'))
    # +++ END Stock check +++
    
    cart[product_id] = total_wanted # Uses GUID as key
    save_cart(cart)
    flash(f"Added {qty} × {product.name} to cart")
    return redirect(request.referrer or url_for('index'))

@app.route('/cart')
def cart_view():
    cart = get_cart()
    items = []
    total = Decimal('0.00')
    
    cart_changed = False
    for pid_str_guid, qty in list(cart.items()): # list() to create a copy, so pop works
        # pid_str_guid is now the GUID
        p = Product.query.get(pid_str_guid)
        if not p:
            # Product no longer exists in our DB (perhaps removed by sync)
            cart.pop(pid_str_guid, None)
            cart_changed = True
            continue
        
        # +++ NEW: Get real-time stock for the view +++
        real_stock = get_erp_stock(p.id)
        
        subtotal = (p.price * qty)
        items.append({
            'product': p, 
            'quantity': qty, 
            'subtotal': subtotal,
            'real_stock': real_stock # For template
        })
        total += subtotal
    
    if cart_changed:
        save_cart(cart)
        flash("Some items in your cart were no longer available and have been removed.")
        
    return render_template('cart.html', items=items, total=total)

@app.route('/cart/remove/<string:product_id>', methods=['POST']) # CHANGED: int -> string
def cart_remove(product_id):
    cart = get_cart()
    cart.pop(product_id, None) # Uses GUID as key
    save_cart(cart)
    flash('Removed item from cart')
    return redirect(url_for('cart_view'))

@app.route('/checkout', methods=['POST'])
@login_required
def checkout():
    """
    +++ COMPLETELY REWRITTEN FOR REAL-TIME RPC +++
    Replaces local saving with an RPC call to the ERP.
    1. Fetches/Creates ERP customer.
    2. Checks real-time stock for *every* item.
    3. Creates the order in the ERP via "Deep Insert".
    4. Saves a *copy* of the order locally for "My Orders".
    """
    
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
    local_items_for_order = []
    total = Decimal('0.00')

    # --- 2. Validate cart (Price & Real-time Stock) ---
    
    # list(cart.items()) fixes the "RuntimeError: dictionary changed size"
    for pid_guid, qty in list(cart.items()): 
        p = Product.query.get(pid_guid)
        if not p:
            flash(f"A product in the cart is no longer available and has been removed.")
            cart.pop(pid_guid, None) # This line requires list() above
            save_cart(cart)
            return redirect(url_for('cart_view'))

        # --- REAL-TIME STOCK CHECK ---
        real_stock = get_erp_stock(p.id)
        if qty > real_stock:
            flash(f"Stock for '{p.name}' insufficient (Available: {real_stock}). Order canceled.")
            return redirect(url_for('cart_view'))
        
        # +++ PRICE CALCULATION +++
        subtotal = (p.price * qty)
        total += subtotal
        
        # For ERP payload
        erp_items_payload.append({
            "product_ID": p.id, # The product GUID
            "quantity": qty,
            "itemAmount": str(subtotal) # Field added for ERP
        })
        
        # For local DB copy
        local_items_for_order.append({
            'product': p, 
            'quantity': qty, 
            'unit_price': p.price
        })

    if not erp_items_payload:
        flash("Cart is empty after check.")
        return redirect(url_for('cart_view'))

    # --- 3. Send order to ERP (Deep Insert) ---
    order_payload = {
        "customer_ID": erp_customer_id,
        "orderDate": datetime.utcnow().strftime('%Y-%m-%d'),
        "currency_code": "EUR", # Assumption
        "orderAmount": str(total), # Field added for ERP
        "items": erp_items_payload
    }

    try:
        # Now uses the global session with retry logic
        response = erp_session.post(ERP_ORDERS_URL, json=order_payload, timeout=ERP_TIMEOUT)
        
        if response.status_code == 201:
            # --- SUCCESS ---
            # IMPORTANT: We are NOT saving anything locally anymore. The ERP is the single source of truth.
            
            clear_cart()
            flash('Order successfully transmitted to ERP!')
            return redirect(url_for('orders'))
            
        elif response.status_code == 400 or response.status_code == 422:
            # --- ERP Error (e.g., stock problem or validation error) ---
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
            # --- Other server error ---
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
    No local storage.
    """
    my_orders = []
    
    if current_user.erp_customer_id:
        try:
            # Filter by Customer ID in ERP
            url = f"{ERP_ORDERS_URL}?$filter=customer_ID eq {current_user.erp_customer_id}&$orderby=createdAt desc"
            response = erp_session.get(url, timeout=ERP_TIMEOUT)
            
            if response.status_code == 200:
                my_orders = response.json().get('value', [])
            else:
                flash(f"Could not load orders (ERP Status: {response.status_code})", "warning")
                
        except Exception as e:
            flash(f"Connection error to ERP when loading orders: {e}", "danger")

    return render_template('orders.html', orders=my_orders)

@app.route('/order/<string:order_id>') # IMPORTANT: Now string (GUID) instead of int
@login_required
def order_detail(order_id):
    """
    Fetches details of an order LIVE from the ERP.
    Uses $expand to load items and product names in one call.
    """
    order_data = None
    
    try:
        # OData Deep Expand: Order -> Items -> Product
        # We need 'items' and within that 'product' to display the name
        url = f"{ERP_ORDERS_URL}({order_id})?$expand=items($expand=product)"
        
        response = erp_session.get(url, timeout=ERP_TIMEOUT)
        
        if response.status_code == 200:
            order_data = response.json()
            
            # Security check: Does the order really belong to me?
            # We compare the ERP customer ID of the order with that of the user
            if order_data.get('customer_ID') != current_user.erp_customer_id:
                abort(403) # Forbidden
        elif response.status_code == 404:
            abort(404)
        else:
            flash(f"ERP Error: {response.status_code}", "danger")
            return redirect(url_for('orders'))
            
    except Exception as e:
        flash(f"Connection Error: {e}", "danger")
        return redirect(url_for('orders'))

    return render_template('order_detail.html', order=order_data)
