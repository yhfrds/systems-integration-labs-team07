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