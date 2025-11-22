# projekt/routes.py

from flask import session

import requests
from requests.auth import HTTPBasicAuth

# Imports for retry logic
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# Imports app, db, and scheduler from __init__.py
from . import db 


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
    Always checks ERP directly by email.
    If customer exists → return ERP customer data.
    If not → create it and return the new data.
    """

    try:
        # 1. Search ERP by email
        filter_url = f"{ERP_CUSTOMERS_URL}?$filter=email eq '{user.email}'"
        response = requests.get(filter_url, auth=ERP_AUTH, timeout=ERP_TIMEOUT)
        response.raise_for_status()
        customers = response.json().get('value', [])

        if customers:
            # Customer exists
            user.erp_customer_id = customers[0]['ID']
            db.session.commit()
            return customers[0]

        # Customer not found → create
        payload = {
            "name": user.name,
            "email": user.email,
            "street": user.street,
            "houseNumber": user.house_number,
            "postalCode": user.zip_code,
            "city": user.city,
            "country_code": "DE"
        }

        create_res = requests.post(ERP_CUSTOMERS_URL, json=payload, auth=ERP_AUTH, timeout=ERP_TIMEOUT)
        create_res.raise_for_status()
        return create_res.json()

    except Exception as e:
        print(f"ERP error in get_or_create_erp_customer: {e}")
        return None


def update_erp_customer(user):
    """
    Always updates ERP by email.
    If not found → creates new record.
    Returns ERP customer data if successful, None on error.
    """

    try:
        # Search ERP by email
        erp_customer = get_or_create_erp_customer(user)
        if not erp_customer:
            return None

        erp_id = erp_customer["ID"]
        url = f"{ERP_CUSTOMERS_URL}({erp_id})"

        payload = {
            "name": user.name,
            "email": user.email,
            "street": user.street,
            "houseNumber": user.house_number,
            "postalCode": user.zip_code,
            "city": user.city,
            "country_code": "DE"
        }

        response = requests.patch(url, json=payload, auth=ERP_AUTH, timeout=ERP_TIMEOUT)
        response.raise_for_status()
        return response.json()

    except Exception as e:
        print(f"ERP error in update_erp_customer: {e}")
        return None

'''
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
'''
        
# Helper: cart operations (stored in session)
def get_cart():
    return session.get('cart', {})  # {product_id: quantity}

def save_cart(cart):
    session['cart'] = cart
    session.modified = True

def clear_cart():
    session.pop('cart', None)
    session.modified = True
