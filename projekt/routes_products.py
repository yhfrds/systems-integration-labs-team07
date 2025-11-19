from flask import render_template
from .routes_helpers import get_cart, get_erp_stock, ERP_BASE_URL, ERP_PRODUCTS_URL, ERP_AUTH, requests
import json

# Imports app, db, and scheduler from __init__.py
from . import app
# from .models import Product
from .cache import cache_get, cache_set

ttl_time = 45
  # Cache TTL in seconds

def get_erp_products_cached():
    cache_key = "erp_products_all"
    cached = cache_get(cache_key)

    if cached is not None:
        return cached

    response = requests.get(ERP_PRODUCTS_URL, auth=ERP_AUTH)
    response.raise_for_status()
    data = response.json()["value"]

    cache_set(cache_key, data, ttl_seconds=ttl_time)
    return data


def get_erp_product_cached(product_id):
    cache_key = f"erp_product:{product_id}"
    cached = cache_get(cache_key)

    if cached is not None:
        return cached

    response = requests.get(f"{ERP_PRODUCTS_URL}({product_id})", auth=ERP_AUTH)
    response.raise_for_status()
    data = response.json()

    cache_set(cache_key, data, ttl_seconds=ttl_time)
    return data


# --- General & Product Routes ---
@app.route('/')
def index():
    products = get_erp_products_cached()
    return render_template('index.html', products=products, cart=get_cart())

# +++ NEUE ROUTE FÜR PRODUKTDETAILS +++


@app.route('/product/<string:product_id>')
def product_detail(product_id):
    """
    Zeigt die Detailseite für ein einzelnes Produkt an.
    """
    # 1. Lokale Produktdaten abrufen (Name, Preis, Beschreibung)
    product = get_erp_product_cached(product_id)

    # 2. ECHTZEIT-RPC: Lagerbestand aus dem ERP abrufen
    real_stock = get_erp_stock(product['ID'])

    # 3. Neue Template-Datei rendern und Daten übergeben
    return render_template('product_detail.html', product=product, stock=real_stock)
# +++ ENDE NEUE ROUTE +++
