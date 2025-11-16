# projekt/routes.py

from flask import render_template, request, redirect, url_for, flash, session, abort
from flask_login import login_user, logout_user, login_required, current_user
from decimal import Decimal

# +++ NEW IMPORTS FOR API, SYNC & RETRY LOGIC +++
import requests
from requests.auth import HTTPBasicAuth
# Imports for retry logic
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from datetime import datetime
# +++ END NEW IMPORTS +++

# Imports app, db, and scheduler from __init__.py
from . import app, db, scheduler 
from .models import User, Product


# --- NEW CONFIGURATION FOR REAL-TIME API (RPC) ---
ERP_BASE_URL = 'http://localhost:4004/odata/v4/simple-erp'
ERP_PRODUCTS_URL = f"{ERP_BASE_URL}/Products"
ERP_CUSTOMERS_URL = f"{ERP_BASE_URL}/Customers"
ERP_ORDERS_URL = f"{ERP_BASE_URL}/Orders"

ERP_USERNAME = 'alice'
ERP_PASSWORD = 'alice'
ERP_AUTH = HTTPBasicAuth(ERP_USERNAME, ERP_PASSWORD)
ERP_TIMEOUT = 10 # Timeout of 10 seconds for requests

# +++ NEW: GLOBAL SESSION WITH RETRY LOGIC +++
# 1. Define the retry strategy
retry_strategy = Retry(
    total=3,  # 3 total retries
    backoff_factor=0.5, # Wait time between attempts (0.5s, 1s, 2s)
    status_forcelist=[502, 503, 504], # Retry on these server errors
    # NOTE: Connection errors and timeouts are retried by default
)

# 2. Create an adapter with this strategy
adapter = HTTPAdapter(max_retries=retry_strategy)

# 3. Create a global session
erp_session = requests.Session()

# 4. Assign auth to the session (no longer needs to be passed individually)
erp_session.auth = ERP_AUTH 

# 5. Mount the adapter for all http/https requests
erp_session.mount("http://", adapter)
erp_session.mount("https://", adapter)
# --- END CONFIGURATION ---


# --- HELPER: ERP-API Functions (RPC Calls) ---

def get_erp_stock(product_guid_id):
    """
    Gets the real-time stock for ONE product GUID from the ERP.
    Now uses the global session with retry logic.
    """
    try:
        url = f"{ERP_PRODUCTS_URL}({product_guid_id})" # OData syntax for PK access
        response = erp_session.get(url, timeout=ERP_TIMEOUT) # Uses erp_session
        response.raise_for_status() # Raises errors on 4xx/5xx
        return response.json().get('stock', 0)
    except requests.exceptions.RequestException as e:
        print(f"ERP Stock-Check Error for {product_guid_id}: {e}")
        return 0 # Assume "Out of Stock" in case of error

def get_or_create_erp_customer(user):
    """
    Looks for a customer in the ERP by email. 
    If not present (or local ID is invalid), it will be created.
    Returns the ERP customer GUID.
    Now uses the global session with retry logic.
    """
    erp_id = None

    # 1. Check if we have a local ID AND if it is still valid in the ERP
    if user.erp_customer_id:
        try:
            # Existence check: Does this customer really still exist?
            check_url = f"{ERP_CUSTOMERS_URL}({user.erp_customer_id})"
            check_response = erp_session.get(check_url, timeout=ERP_TIMEOUT)
            
            if check_response.status_code == 200:
                # Yes, still exists -> use it
                return user.erp_customer_id
            else:
                # No (e.g., 404) -> The local ID is outdated (Zombie ID)
                print(f"Local Customer-ID {user.erp_customer_id} not found in ERP. Searching again...")
                # We reset erp_id and continue below
                user.erp_customer_id = None
                db.session.commit()
                
        except requests.exceptions.RequestException:
            # In case of connection errors, we play it safe and abort or try to continue
            print("Connection error during ID check.")
            return None

    try:
        # 2. Search in ERP by email (If we have no ID or it was invalid)
        filter_url = f"{ERP_CUSTOMERS_URL}?$filter=email eq '{user.email}'"
        response = erp_session.get(filter_url, timeout=ERP_TIMEOUT)
        response.raise_for_status()
        
        customers = response.json().get('value', [])
        
        if customers:
            # 3. Case A: Customer found (but we didn't have the ID locally or it was wrong)
            erp_id = customers[0]['ID']
            print(f"Customer found in ERP: {erp_id}")
        else:
            # 4. Case B: Customer not found -> create new
            print(f"Creating new ERP customer for {user.email}...")
            
            payload = {
                "name": user.name,
                "email": user.email,
                "street": user.street,
                "houseNumber": user.house_number, # ERP expects camelCase
                "postalCode": user.zip_code,      # ERP expects 'postalCode'
                "city": user.city,
                "country_code": "DE"
            }
            create_response = erp_session.post(ERP_CUSTOMERS_URL, json=payload, timeout=ERP_TIMEOUT)
            create_response.raise_for_status()
            erp_id = create_response.json()['ID']
            print(f"New customer created: {erp_id}")
            
        # 5. Save new ERP-ID locally
        user.erp_customer_id = erp_id
        db.session.commit()
        return erp_id
        
    except requests.exceptions.RequestException as e:
        print(f"Error while fetching/creating the ERP customer: {e}")
        return None
    except Exception as e:
        print(f"General error in get_or_create_erp_customer: {e}")
        return None

def update_erp_customer(user):
    """
    Sends local changes (Name, Address, Email) to the ERP system.
    Uses PATCH to update the existing record.
    """
    if not user.erp_customer_id:
        # If no ID is present yet, we create it first
        return get_or_create_erp_customer(user)

    try:
        url = f"{ERP_CUSTOMERS_URL}({user.erp_customer_id})"
        
        payload = {
            "name": user.name,
            "email": user.email,
            "street": user.street,
            "houseNumber": user.house_number,
            "postalCode": user.zip_code,
            "city": user.city,
            "country_code": "DE"
        }
        
        # PATCH only updates the sent fields
        response = erp_session.patch(url, json=payload, timeout=ERP_TIMEOUT)
        
        if response.status_code == 404:
            # Customer deleted in ERP? -> remove ID and create new
            user.erp_customer_id = None
            db.session.commit()
            return get_or_create_erp_customer(user)
            
        response.raise_for_status()
        print(f"ERP customer {user.erp_customer_id} updated.")
        return True
        
    except Exception as e:
        print(f"Error while updating the ERP customer: {e}")
        return False

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

# --- product_new AND product_delete WERE REMOVED AS REQUESTED ---


# --- Auth & User Routes ---
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        name = request.form['name'].strip()
        email = request.form['email'].strip().lower()
        password = request.form['password']

        street = request.form.get('street', '').strip()
        house_number = request.form.get('house_number', '').strip()
        zip_code = request.form.get('zip_code', '').strip()
        city = request.form.get('city', '').strip()
        
        if User.query.filter_by(email=email).first():
            flash('Email already registered')
            return redirect(url_for('register'))
            
        u = User(name=name, email=email, street=street, house_number=house_number, zip_code=zip_code, city=city)
        u.set_password(password)
        db.session.add(u)
        db.session.commit()
        
        # +++ SYNC: Create in ERP immediately +++
        try:
            get_or_create_erp_customer(u)
        except Exception as e:
            print(f"Warning: ERP sync during registration failed: {e}")
            # We let the user in anyway, sync will happen at checkout at the latest
        
        login_user(u)
        flash('Registered and logged in (ERP synced)')
        return redirect(url_for('index'))
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email'].strip().lower()
        password = request.form['password']
        user = User.query.filter_by(email=email).first()
        
        if not user or not user.check_password(password):
            flash('Invalid credentials')
            return redirect(url_for('login'))
            
        login_user(user)
        
        # +++ SYNC: Ensure ERP link is up-to-date +++
        # (Runs in the background, errors are ignored to not block login)
        try:
            get_or_create_erp_customer(user)
        except:
            pass 
            
        flash('Logged in')
        return redirect(url_for('index'))
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Logged out')
    return redirect(url_for('index'))

@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    if request.method == 'POST':
        name = request.form['name'].strip()
        email = request.form['email'].strip().lower()
        street = request.form.get('street', '').strip()
        house_number = request.form.get('house_number', '').strip()
        zip_code = request.form.get('zip_code', '').strip()
        city = request.form.get('city', '').strip()
        current_password = request.form['current_password']
        new_password = request.form.get('new_password')

        if not current_user.check_password(current_password):
            flash('Incorrect current password. No changes were made.')
            return redirect(url_for('profile'))

        # Local updates
        current_user.name = name
        current_user.street = street
        current_user.house_number = house_number
        current_user.zip_code = zip_code
        current_user.city = city
        update_made = True

        if current_user.email != email:
            if User.query.filter(User.email == email, User.id != current_user.id).first():
                flash('This email address is already in use.')
                return redirect(url_for('profile'))
            current_user.email = email
            update_made = True

        if new_password:
            current_user.set_password(new_password)
            update_made = True
        
        try:
            if update_made:
                db.session.commit()
                
                # +++ SYNC: Send changes to ERP +++
                if update_erp_customer(current_user):
                    flash('Profile updated successfully (Local & ERP).')
                else:
                    flash('Profile updated locally, but ERP sync failed.', 'warning')
            else:
                flash('No changes detected.')
        except Exception as e:
            db.session.rollback()
            flash(f'Error updating profile: {e}')

        return redirect(url_for('profile'))
        
    return render_template('profile.html')

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

# --- DIESE FUNKTION WURDE ENTFERNT ---
# @app.route('/order/<int:order_id>/status', methods=['POST'])
# def change_status(order_id):
# ... (CODE ENTFERNT) ...


# --- AUTOMATED SYNC LOGIC ---

def perform_erp_sync():
    """
    The actual sync logic.
    Can be called manually or automatically.
    Returns a status string.
    
    IMPORTANT: This function requires an active app context!
    The caller (Route or Job) must provide 'with app.app_context():'.
    """
    
    print(f"[{datetime.now()}] Starting ERP-API-Sync...")
    
    try:
        # --- 1. Fetch products from ERP endpoint ---
        # Now uses the global session with retry logic
        response = erp_session.get(ERP_PRODUCTS_URL, timeout=ERP_TIMEOUT)
        response.raise_for_status()
        erp_products = response.json().get('value', [])
        if not erp_products:
            return "ERP-Sync: Could not receive products from ERP (empty list)."
            
    except requests.exceptions.RequestException as e:
        return f"Error (API): During download of product data: {e}"

    # --- 2. Reconcile local DB with ERP data ---
    created_count = 0
    updated_count = 0
    errors_count = 0
    deleted_count = 0
    erp_ids_from_sync = set()

    try:
        for item in erp_products:
            try:
                # Logic for parsing 'item'
                prod_guid = item.get('ID')
                prod_str_id = item.get('productID')
                name = item.get('name')
                price_raw = item.get('price')
                
                if not prod_guid or not name or price_raw is None:
                    print(f"Skipped: Incomplete data in row: {item}")
                    errors_count += 1
                    continue
                
                erp_ids_from_sync.add(prod_guid)
                price = Decimal(str(price_raw))
                description = item.get('description') or ''

                # Search for product in local DB (by GUID)
                product = Product.query.get(prod_guid)

                if product:
                    # Update
                    product.name = name
                    product.description = description
                    product.price = price
                    product.product_str_id = prod_str_id
                    updated_count += 1
                else:
                    # Create
                    product = Product(
                        id=prod_guid,
                        name=name,
                        description=description,
                        price=price,
                        product_str_id=prod_str_id
                    )
                    db.session.add(product)
                    created_count += 1
            
            except Exception as e:
                print(f"Error processing product {item.get('ID')}: {e}")
                errors_count += 1
        
        # --- 3. Delete local products that are no longer in the ERP ---
        products_to_check = Product.query.filter(Product.id.like('________-____-____-____-____________')).all()
        
        for prod in products_to_check:
            if prod.id not in erp_ids_from_sync:
                db.session.delete(prod)
                deleted_count += 1

        # --- 4. Write changes to the DB ---
        db.session.commit()
        return f"ERP-API-Sync successful! Created: {created_count}, Updated: {updated_count}, Deleted: {deleted_count}, Errors: {errors_count}"

    except Exception as e:
        db.session.rollback()
        return f"Error (DB) during import or DB-Update: {e}"


# +++ NEW BACKGROUND JOB +++
@scheduler.task('interval', id='erp_sync_job', minutes=5, misfire_grace_time=900)
def scheduled_sync_job():
    """
    Executes the automatic ERP product sync every hour in the background.
    """
    # Provide app context for the sync function and DB access
    with app.app_context():
        status_message = perform_erp_sync()
        # Logs the result to the console (since no user can see a flash message)
        print(f"Automatic sync job finished: {status_message}")


# +++ ADJUSTED MANUAL ROUTE +++
@app.route('/admin/sync', methods=['GET', 'POST'])
@login_required
def admin_sync():
    """
    GET: Redirects.
    POST: Triggers the sync manually and shows the result as a flash message.
    """
    if request.method == 'GET':
        flash("Sync is triggered via POST (Button in the nav bar).")
        return redirect(url_for('index'))

    # The route already provides an app context
    try:
        status_message = perform_erp_sync()
        flash(status_message, 'success')
    except Exception as e:
        flash(f"Error during manual sync: {e}", 'danger')
    
    return redirect(url_for('index'))