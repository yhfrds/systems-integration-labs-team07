# projekt/routes.py

from flask import render_template, request, redirect, url_for, flash, session, abort
from flask_login import login_user, logout_user, login_required, current_user
from decimal import Decimal

# +++ NEUE IMPORTE FÜR API, SYNC & RETRY-LOGIK +++
import requests
from requests.auth import HTTPBasicAuth
# Imports für Retry-Logik
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from datetime import datetime
# +++ ENDE NEUE IMPORTE +++

# Importiert app, db und scheduler aus __init__.py
from . import app, db, scheduler 
from .models import User, Product


# --- NEUE KONFIGURATION FÜR ECHTZEIT-API (RPC) ---
ERP_BASE_URL = 'http://localhost:4004/odata/v4/simple-erp'
ERP_PRODUCTS_URL = f"{ERP_BASE_URL}/Products"
ERP_CUSTOMERS_URL = f"{ERP_BASE_URL}/Customers"
ERP_ORDERS_URL = f"{ERP_BASE_URL}/Orders"

ERP_USERNAME = 'alice'
ERP_PASSWORD = 'alice'
ERP_AUTH = HTTPBasicAuth(ERP_USERNAME, ERP_PASSWORD)
ERP_TIMEOUT = 10 # Timeout von 10 Sekunden für Anfragen

# +++ NEU: GLOBALE SESSION MIT RETRY-LOGIK +++
# 1. Definiere die Retry-Strategie
retry_strategy = Retry(
    total=3,  # 3 Wiederholungsversuche insgesamt
    backoff_factor=0.5, # Wartezeit zwischen Versuchen (0.5s, 1s, 2s)
    status_forcelist=[502, 503, 504], # Wiederhole bei diesen Server-Fehlern
    # HINWEIS: Verbindungsfehler und Timeouts werden standardmäßig wiederholt
)

# 2. Erstelle einen Adapter mit dieser Strategie
adapter = HTTPAdapter(max_retries=retry_strategy)

# 3. Erstelle eine globale Session
erp_session = requests.Session()

# 4. Weise die Auth der Session zu (muss nicht mehr einzeln übergeben werden)
erp_session.auth = ERP_AUTH 

# 5. Montiere den Adapter für alle http/https-Anfragen
erp_session.mount("http://", adapter)
erp_session.mount("https://", adapter)
# --- ENDE KONFIGURATION ---


# --- HELPER: ERP-API-Funktionen (RPC-Aufrufe) ---

def get_erp_stock(product_guid_id):
    """
    Holt den Echtzeit-Lagerbestand für EINE Produkt-GUID aus dem ERP.
    Verwendet jetzt die globale Session mit Retry-Logik.
    """
    try:
        url = f"{ERP_PRODUCTS_URL}({product_guid_id})" # OData-Syntax für PK-Zugriff
        response = erp_session.get(url, timeout=ERP_TIMEOUT) # Verwendet erp_session
        response.raise_for_status() # Löst Fehler aus bei 4xx/5xx
        return response.json().get('stock', 0)
    except requests.exceptions.RequestException as e:
        print(f"ERP Stock-Check Fehler für {product_guid_id}: {e}")
        return 0 # Im Fehlerfall "Out of Stock" annehmen

def get_or_create_erp_customer(user):
    """
    Sucht einen Kunden im ERP per E-Mail. 
    Wenn nicht vorhanden (oder lokale ID ungültig ist), wird er erstellt.
    Gibt die ERP-Kunden-GUID zurück.
    Verwendet jetzt die globale Session mit Retry-Logik.
    """
    erp_id = None

    # 1. Prüfen, ob wir eine lokale ID haben UND ob sie im ERP noch gültig ist
    if user.erp_customer_id:
        try:
            # Existenz-Check: Gibt es diesen Kunden wirklich noch?
            check_url = f"{ERP_CUSTOMERS_URL}({user.erp_customer_id})"
            check_response = erp_session.get(check_url, timeout=ERP_TIMEOUT)
            
            if check_response.status_code == 200:
                # Ja, existiert noch -> verwenden
                return user.erp_customer_id
            else:
                # Nein (z.B. 404) -> Die lokale ID ist veraltet (Zombie-ID)
                print(f"Lokale Customer-ID {user.erp_customer_id} im ERP nicht gefunden. Suche neu...")
                # Wir setzen erp_id zurück und machen weiter unten weiter
                user.erp_customer_id = None
                db.session.commit()
                
        except requests.exceptions.RequestException:
            # Bei Verbindungsfehlern gehen wir auf Nummer sicher und brechen ab oder versuchen weiter
            print("Verbindungsfehler beim ID-Check.")
            return None

    try:
        # 2. Im ERP nach E-Mail suchen (Falls wir keine ID haben oder sie ungültig war)
        filter_url = f"{ERP_CUSTOMERS_URL}?$filter=email eq '{user.email}'"
        response = erp_session.get(filter_url, timeout=ERP_TIMEOUT)
        response.raise_for_status()
        
        customers = response.json().get('value', [])
        
        if customers:
            # 3. Fall A: Kunde gefunden (aber wir hatten die ID lokal noch nicht oder falsch)
            erp_id = customers[0]['ID']
            print(f"Kunde im ERP gefunden: {erp_id}")
        else:
            # 4. Fall B: Kunde nicht gefunden -> neu anlegen
            print(f"Erstelle neuen ERP-Kunden für {user.email}...")
            
            payload = {
                "name": user.name,
                "email": user.email,
                "street": user.street,
                "houseNumber": user.house_number, # ERP erwartet camelCase
                "postalCode": user.zip_code,      # ERP erwartet 'postalCode'
                "city": user.city,
                "country_code": "DE"
            }
            create_response = erp_session.post(ERP_CUSTOMERS_URL, json=payload, timeout=ERP_TIMEOUT)
            create_response.raise_for_status()
            erp_id = create_response.json()['ID']
            print(f"Neuer Kunde erstellt: {erp_id}")
            
        # 5. Neue ERP-ID lokal speichern
        user.erp_customer_id = erp_id
        db.session.commit()
        return erp_id
        
    except requests.exceptions.RequestException as e:
        print(f"Fehler beim Abrufen/Erstellen des ERP-Kunden: {e}")
        return None
    except Exception as e:
        print(f"Allgemeiner Fehler in get_or_create_erp_customer: {e}")
        return None

def update_erp_customer(user):
    """
    Sendet lokale Änderungen (Name, Adresse, Email) an das ERP-System.
    Nutzt PATCH um den bestehenden Datensatz zu aktualisieren.
    """
    if not user.erp_customer_id:
        # Wenn noch keine ID da ist, erstellen wir ihn erst einmal
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
        
        # PATCH aktualisiert nur die gesendeten Felder
        response = erp_session.patch(url, json=payload, timeout=ERP_TIMEOUT)
        
        if response.status_code == 404:
            # Kunde im ERP gelöscht? -> ID entfernen und neu anlegen
            user.erp_customer_id = None
            db.session.commit()
            return get_or_create_erp_customer(user)
            
        response.raise_for_status()
        print(f"ERP-Kunde {user.erp_customer_id} aktualisiert.")
        return True
        
    except Exception as e:
        print(f"Fehler beim Aktualisieren des ERP-Kunden: {e}")
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

# --- product_new UND product_delete WURDEN WIE GEWÜNSCHT ENTFERNT ---


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
        
        # +++ SYNC: Sofort im ERP anlegen +++
        try:
            get_or_create_erp_customer(u)
        except Exception as e:
            print(f"Warnung: ERP-Sync bei Registrierung fehlgeschlagen: {e}")
            # Wir lassen den User trotzdem rein, Sync passiert spätestens beim Checkout
        
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
        
        # +++ SYNC: Sicherstellen, dass ERP-Verknüpfung aktuell ist +++
        # (Läuft im Hintergrund, Fehler werden ignoriert, um Login nicht zu blockieren)
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

        # Lokale Updates
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
                
                # +++ SYNC: Änderungen an ERP senden +++
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
@app.route('/cart/add/<string:product_id>', methods=['POST']) # GEÄNDERT: int -> string
def cart_add(product_id):
    product = Product.query.get_or_404(product_id) # Sucht jetzt nach GUID
    cart = get_cart()
    qty = int(request.form.get('quantity', 1))
    if qty < 1: qty = 1
    
    # +++ NEU: Echtzeit-Stock-Prüfung beim Hinzufügen +++
    current_in_cart = cart.get(product_id, 0)
    total_wanted = current_in_cart + qty
    
    real_stock = get_erp_stock(product.id)
    
    if total_wanted > real_stock:
        flash(f"Fehler: Nicht genügend Lagerbestand für '{product.name}'. Verfügbar: {real_stock}, Sie wollten: {total_wanted}")
        return redirect(request.referrer or url_for('index'))
    # +++ ENDE Stock-Prüfung +++
    
    cart[product_id] = total_wanted # Verwendet GUID als Key
    save_cart(cart)
    flash(f"Added {qty} × {product.name} to cart")
    return redirect(request.referrer or url_for('index'))

@app.route('/cart')
def cart_view():
    cart = get_cart()
    items = []
    total = Decimal('0.00')
    
    cart_changed = False
    for pid_str_guid, qty in list(cart.items()): # list() zur Kopieerstellung, damit pop funktioniert
        # pid_str_guid ist jetzt die GUID
        p = Product.query.get(pid_str_guid)
        if not p:
            # Produkt existiert nicht mehr in unserer DB (vielleicht durch Sync entfernt)
            cart.pop(pid_str_guid, None)
            cart_changed = True
            continue
        
        # +++ NEU: Echtzeit-Stock für die Ansicht holen +++
        real_stock = get_erp_stock(p.id)
        
        subtotal = (p.price * qty)
        items.append({
            'product': p, 
            'quantity': qty, 
            'subtotal': subtotal,
            'real_stock': real_stock # Für Template
        })
        total += subtotal
    
    if cart_changed:
        save_cart(cart)
        flash("Einige Artikel in Ihrem Warenkorb waren nicht mehr verfügbar und wurden entfernt.")
        
    return render_template('cart.html', items=items, total=total)

@app.route('/cart/remove/<string:product_id>', methods=['POST']) # GEÄNDERT: int -> string
def cart_remove(product_id):
    cart = get_cart()
    cart.pop(product_id, None) # Verwendet GUID als Key
    save_cart(cart)
    flash('Removed item from cart')
    return redirect(url_for('cart_view'))

@app.route('/checkout', methods=['POST'])
@login_required
def checkout():
    """
    +++ KOMPLETT NEU GESCHRIEBEN FÜR ECHTZEIT-RPC +++
    Ersetzt das lokale Speichern durch einen RPC-Call an das ERP.
    1. Holt/Erstellt ERP-Kunden.
    2. Prüft Echtzeit-Lagerbestand für *jeden* Artikel.
    3. Erstellt die Bestellung im ERP via "Deep Insert".
    4. Speichert eine *Kopie* der Bestellung lokal für "My Orders".
    """
    
    cart = get_cart() 
    
    if not cart:
        flash('Cart is empty')
        return redirect(url_for('index'))

    # --- 1. ERP-Kunden-ID holen/erstellen ---
    try:
        erp_customer_id = get_or_create_erp_customer(current_user)
        if not erp_customer_id:
            flash("Kritischer Fehler: Ihr Kundenkonto konnte nicht im ERP-System gefunden oder erstellt werden.")
            return redirect(url_for('cart_view'))
    except Exception as e:
        flash(f"Fehler bei der Kunden-Synchronisierung: {e}")
        return redirect(url_for('cart_view'))

    erp_items_payload = []
    local_items_for_order = []
    total = Decimal('0.00')

    # --- 2. Warenkorb validieren (Preis & Echtzeit-Stock) ---
    
    # list(cart.items()) behebt den "RuntimeError: dictionary changed size"
    for pid_guid, qty in list(cart.items()): 
        p = Product.query.get(pid_guid)
        if not p:
            flash(f"Ein Produkt im Warenkorb ist nicht mehr verfügbar und wurde entfernt.")
            cart.pop(pid_guid, None) # Diese Zeile erfordert list() oben
            save_cart(cart)
            return redirect(url_for('cart_view'))

        # --- ECHTZEIT-STOCK-PRÜFUNG ---
        real_stock = get_erp_stock(p.id)
        if qty > real_stock:
            flash(f"Bestand für '{p.name}' nicht ausreichend (Verfügbar: {real_stock}). Bestellung abgebrochen.")
            return redirect(url_for('cart_view'))
        
        # +++ BERECHNUNG DES PREISES +++
        subtotal = (p.price * qty)
        total += subtotal
        
        # Für ERP-Payload
        erp_items_payload.append({
            "product_ID": p.id, # Die Produkt-GUID
            "quantity": qty,
            "itemAmount": str(subtotal) # Feld für ERP hinzugefügt
        })
        
        # Für lokale DB-Kopie
        local_items_for_order.append({
            'product': p, 
            'quantity': qty, 
            'unit_price': p.price
        })

    if not erp_items_payload:
        flash("Warenkorb ist nach Prüfung leer.")
        return redirect(url_for('cart_view'))

    # --- 3. Bestellung an ERP senden (Deep Insert) ---
    order_payload = {
        "customer_ID": erp_customer_id,
        "orderDate": datetime.utcnow().strftime('%Y-%m-%d'),
        "currency_code": "EUR", # Annahme
        "orderAmount": str(total), # Feld für ERP hinzugefügt
        "items": erp_items_payload
    }

    try:
        # Verwendet jetzt die globale Session mit Retry-Logik
        response = erp_session.post(ERP_ORDERS_URL, json=order_payload, timeout=ERP_TIMEOUT)
        
        if response.status_code == 201:
            # --- ERFOLG ---
            # WICHTIG: Wir speichern NICHTS mehr lokal. Das ERP ist die einzige Wahrheit.
            
            clear_cart()
            flash('Bestellung erfolgreich an ERP übermittelt!')
            return redirect(url_for('orders'))
            
        elif response.status_code == 400 or response.status_code == 422:
            # --- ERP-Fehler (z.B. Stock-Problem oder Validierungsfehler) ---
            try:
                error_msg = response.json().get('error', {}).get('message', 'Unbekannter ERP-Fehler')
                details = response.json().get('error', {}).get('details', [])
                if details:
                    detail_messages = [d.get('message') for d in details if d.get('message')]
                    error_msg += ": " + ", ".join(detail_messages)
            except requests.exceptions.JSONDecodeError:
                error_msg = response.text
                
            flash(f"ERP-Fehler: {error_msg}")
            return redirect(url_for('cart_view'))
        else:
            # --- Anderer Server-Fehler ---
            flash(f"Unerwarteter ERP-Fehler: {response.status_code} - {response.text}")
            response.raise_for_status()

    except requests.exceptions.RequestException as e:
        flash(f"Kritischer Verbindungsfehler zum ERP: {e}")
        return redirect(url_for('cart_view'))
    except Exception as e:
        db.session.rollback()
        flash(f"Allgemeiner Fehler beim Checkout: {e}")
        return redirect(url_for('cart_view'))


@app.route('/orders')
@login_required
def orders():
    """
    Holt die Bestellliste LIVE aus dem ERP-System (RPC).
    Keine lokale Speicherung.
    """
    my_orders = []
    
    if current_user.erp_customer_id:
        try:
            # Filter nach Customer ID im ERP
            url = f"{ERP_ORDERS_URL}?$filter=customer_ID eq {current_user.erp_customer_id}&$orderby=createdAt desc"
            response = erp_session.get(url, timeout=ERP_TIMEOUT)
            
            if response.status_code == 200:
                my_orders = response.json().get('value', [])
            else:
                flash(f"Konnte Bestellungen nicht laden (ERP Status: {response.status_code})", "warning")
                
        except Exception as e:
            flash(f"Verbindungsfehler zum ERP beim Laden der Bestellungen: {e}", "danger")

    return render_template('orders.html', orders=my_orders)

@app.route('/order/<string:order_id>') # WICHTIG: Jetzt string (GUID) statt int
@login_required
def order_detail(order_id):
    """
    Holt Details einer Bestellung LIVE aus dem ERP.
    Nutzt $expand, um Items und Produktnamen in einem Call zu laden.
    """
    order_data = None
    
    try:
        # OData Deep Expand: Order -> Items -> Product
        # Wir brauchen 'items' und darin das 'product', um den Namen anzuzeigen
        url = f"{ERP_ORDERS_URL}({order_id})?$expand=items($expand=product)"
        
        response = erp_session.get(url, timeout=ERP_TIMEOUT)
        
        if response.status_code == 200:
            order_data = response.json()
            
            # Sicherheitscheck: Gehört die Bestellung wirklich mir?
            # Wir vergleichen die ERP-Customer-ID der Bestellung mit der des Users
            if order_data.get('customer_ID') != current_user.erp_customer_id:
                abort(403) # Forbidden
        elif response.status_code == 404:
            abort(404)
        else:
            flash(f"ERP Fehler: {response.status_code}", "danger")
            return redirect(url_for('orders'))
            
    except Exception as e:
        flash(f"Verbindungsfehler: {e}", "danger")
        return redirect(url_for('orders'))

    return render_template('order_detail.html', order=order_data)

@app.route('/order/<int:order_id>/status', methods=['POST'])
def change_status(order_id):
    # Ändert nur den Status der *lokalen Kopie*
    # (Keine Verbindung zum ERP in dieser alten Funktion)
    new_status = request.form.get('status')
    o = Order.query.get_or_404(order_id)
    if new_status not in ('pending', 'shipped', 'completed'):
        flash('Invalid status')
    else:
        o.status = new_status
        db.session.commit()
        flash('Order status updated (local only)')
    return redirect(url_for('index'))


# --- AUTOMATISIERTE SYNC-LOGIK ---

def perform_erp_sync():
    """
    Die eigentliche Sync-Logik.
    Kann manuell oder automatisch aufgerufen werden.
    Gibt einen Status-String zurück.
    
    WICHTIG: Diese Funktion benötigt einen aktiven App-Kontext!
    Der Aufrufer (Route oder Job) muss 'with app.app_context():' bereitstellen.
    """
    
    print(f"[{datetime.now()}] Starte ERP-API-Sync...")
    
    try:
        # --- 1. Produkte vom ERP-Endpunkt abrufen ---
        # Verwendet jetzt die globale Session mit Retry-Logik
        response = erp_session.get(ERP_PRODUCTS_URL, timeout=ERP_TIMEOUT)
        response.raise_for_status()
        erp_products = response.json().get('value', [])
        if not erp_products:
            return "ERP-Sync: Konnte keine Produkte vom ERP empfangen (leere Liste)."
            
    except requests.exceptions.RequestException as e:
        return f"Fehler (API): Beim Download der Produktdaten: {e}"

    # --- 2. Lokale DB mit ERP-Daten abgleichen ---
    created_count = 0
    updated_count = 0
    errors_count = 0
    deleted_count = 0
    erp_ids_from_sync = set()

    try:
        for item in erp_products:
            try:
                # Logik zum Parsen von 'item'
                prod_guid = item.get('ID')
                prod_str_id = item.get('productID')
                name = item.get('name')
                price_raw = item.get('price')
                
                if not prod_guid or not name or price_raw is None:
                    print(f"Übersprungen: Unvollständige Daten in Zeile: {item}")
                    errors_count += 1
                    continue
                
                erp_ids_from_sync.add(prod_guid)
                price = Decimal(str(price_raw))
                description = item.get('description') or ''

                # Produkt in lokaler DB suchen (über GUID)
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
                print(f"Fehler bei Verarbeitung von Produkt {item.get('ID')}: {e}")
                errors_count += 1
        
        # --- 3. Lokale Produkte löschen, die nicht mehr im ERP sind ---
        products_to_check = Product.query.filter(Product.id.like('________-____-____-____-____________')).all()
        
        for prod in products_to_check:
            if prod.id not in erp_ids_from_sync:
                db.session.delete(prod)
                deleted_count += 1

        # --- 4. Änderungen in die DB schreiben ---
        db.session.commit()
        return f"ERP-API-Sync erfolgreich! Erstellt: {created_count}, Aktualisiert: {updated_count}, Gelöscht: {deleted_count}, Fehler: {errors_count}"

    except Exception as e:
        db.session.rollback()
        return f"Fehler (DB) beim Einlesen oder DB-Update: {e}"


# +++ NEUER HINTERGRUND-JOB +++
@scheduler.task('interval', id='erp_sync_job', minutes=5, misfire_grace_time=900)
def scheduled_sync_job():
    """
    Führt den automatischen ERP-Produktsync jede Stunde im Hintergrund aus.
    """
    # App-Kontext für die Sync-Funktion und DB-Zugriff bereitstellen
    with app.app_context():
        status_message = perform_erp_sync()
        # Loggt das Ergebnis in die Konsole (da kein Benutzer eine flash-Nachricht sehen kann)
        print(f"Automatischer Sync-Job beendet: {status_message}")


# +++ ANGEPASSTE MANUELLE ROUTE +++
@app.route('/admin/sync', methods=['GET', 'POST'])
@login_required
def admin_sync():
    """
    GET: Leitet um.
    POST: Löst den Sync manuell aus und zeigt das Ergebnis als Flash-Nachricht an.
    """
    if request.method == 'GET':
        flash("Sync wird über POST ausgelöst (Button in der Navi-Leiste).")
        return redirect(url_for('index'))

    # Die Route stellt bereits einen App-Kontext bereit
    try:
        status_message = perform_erp_sync()
        flash(status_message, 'success')
    except Exception as e:
        flash(f"Fehler beim manuellen Sync: {e}", 'danger')
    
    return redirect(url_for('index'))