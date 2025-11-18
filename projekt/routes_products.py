from flask import render_template
from .routes import get_cart, get_erp_stock

# Imports app, db, and scheduler from __init__.py
from . import app
from .models import Product 

# --- General & Product Routes ---
@app.route('/')
def index():
    products = Product.query.all()
    return render_template('index.html', products=products, cart=get_cart())

# +++ NEUE ROUTE FÜR PRODUKTDETAILS +++
@app.route('/product/<string:product_id>')
def product_detail(product_id):
    """
    Zeigt die Detailseite für ein einzelnes Produkt an.
    """
    # 1. Lokale Produktdaten abrufen (Name, Preis, Beschreibung)
    product = Product.query.get_or_404(product_id)
    
    # 2. ECHTZEIT-RPC: Lagerbestand aus dem ERP abrufen
    real_stock = get_erp_stock(product.id)
    
    # 3. Neue Template-Datei rendern und Daten übergeben
    return render_template('product_detail.html', product=product, stock=real_stock)
# +++ ENDE NEUE ROUTE +++
