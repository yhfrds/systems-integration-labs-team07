from flask import flash, render_template, redirect, url_for
# +++ GEÄNDERT: erp_session importieren +++
from .routes_helpers import get_cart, get_erp_stock, ERP_BASE_URL, ERP_PRODUCTS_URL, ERP_AUTH, requests, erp_session, ERP_TIMEOUT
import time
import requests
import json

# Imports app, db, and scheduler from __init__.py
from . import app

from .cache import cache_get, cache_set

ttl_time = 10 * 60
# Cache TTL in seconds


def get_erp_products_cached(retries=3, delay=2):
    cache_key = "erp_products_all"
    cached = cache_get(cache_key)

    if cached is not None:
        return cached

    for attempt in range(retries):
        try:
            # Wir nutzen die globale Session
            response = erp_session.get(ERP_PRODUCTS_URL, timeout=ERP_TIMEOUT)
            response.raise_for_status()
            data = response.json()["value"]
            cache_set(cache_key, data, ttl_seconds=ttl_time)
            return data
        except (requests.RequestException, ValueError) as e:
            if attempt < retries - 1:
                time.sleep(delay)
            else:
                print(f"ERP unavailable: {e}")
                return []


def get_erp_product_cached(product_id):
    """
    Lädt ein einzelnes Produkt.
    Gibt None zurück bei Fehler (kein Crash).
    """
    cache_key = f"erp_product:{product_id}"
    cached = cache_get(cache_key)

    if cached is not None:
        return cached

    try:
        # +++ GEÄNDERT: Fehlerbehandlung +++
        response = erp_session.get(f"{ERP_PRODUCTS_URL}({product_id})", timeout=ERP_TIMEOUT)
        response.raise_for_status()
        data = response.json()

        cache_set(cache_key, data, ttl_seconds=ttl_time)
        return data
    except requests.exceptions.RequestException:
        # Bei Verbindungsfehler geben wir None zurück, damit der Aufrufer umleiten kann
        return None


# --- General & Product Routes ---
@app.route('/')
def index():
    products = get_erp_products_cached()  # retries are handled inside
    if not products:
        flash("The ERP system is currently unavailable. No products can be loaded.", "danger")
    return render_template('index.html', products=products, cart=get_cart())


@app.route('/product/<string:product_id>')
def product_detail(product_id):
    """
    Displays the detail page for a single product.
    """
    # 1. Lokale Produktdaten abrufen
    product = get_erp_product_cached(product_id)

    # +++ NEU: Prüfung +++
    if not product:
        flash("The ERP system is currently unavailable. Product details cannot be loaded.", "danger")
        return redirect(url_for('index'))
    # +++ ENDE NEU +++

    # 2. ECHTZEIT-RPC: Lagerbestand aus dem ERP abrufen
    real_stock = get_erp_stock(product['ID'])

    # 3. Neue Template-Datei rendern und Daten übergeben
    return render_template('product_detail.html', product=product, stock=real_stock)