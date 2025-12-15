# projekt/routes_helpers.py

from flask import session
import requests
import pika
import json
import uuid
import time
from requests.auth import HTTPBasicAuth

# Imports für Retry-Logik
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# Import app, db von __init__.py
from . import db 

# --- KONFIGURATION ---
ERP_BASE_URL = 'http://localhost:4004/odata/v4/simple-erp'
ERP_PRODUCTS_URL = f"{ERP_BASE_URL}/Products"
ERP_CUSTOMERS_URL = f"{ERP_BASE_URL}/Customers"
ERP_ORDERS_URL = f"{ERP_BASE_URL}/Orders"

ERP_USERNAME = 'alice'
ERP_PASSWORD = 'alice'
ERP_AUTH = HTTPBasicAuth(ERP_USERNAME, ERP_PASSWORD)
ERP_TIMEOUT = 10 

# RabbitMQ Konfiguration
RABBITMQ_HOST = 'localhost'
RABBITMQ_PORT = 5672
QUEUE_ORDERS = 'order_queue'
QUEUE_RESPONSES = 'order_response_queue'

# --- GLOBALE SESSION (REST) ---
retry_strategy = Retry(
    total=3,
    backoff_factor=0.5,
    status_forcelist=[502, 503, 504],
)
adapter = HTTPAdapter(max_retries=retry_strategy)
erp_session = requests.Session()
erp_session.auth = ERP_AUTH 
erp_session.mount("http://", adapter)
erp_session.mount("https://", adapter)


# --- HELPER: Cart ---
def get_cart():
    return session.get('cart', {})

def save_cart(cart):
    session['cart'] = cart
    session.modified = True

def clear_cart():
    session.pop('cart', None)
    session.modified = True


# --- HELPER: ERP REST (Kunden & Stock) ---

def get_erp_stock(product_guid_id):
    """
    Holt den Echtzeit-Lagerbestand per REST (bleibt synchron).
    """
    try:
        url = f"{ERP_PRODUCTS_URL}({product_guid_id})"
        response = erp_session.get(url, timeout=ERP_TIMEOUT)
        response.raise_for_status()
        return response.json().get('stock', 0)
    except Exception as e:
        print(f"ERP Stock-Check Error für {product_guid_id}: {e}")
        return 0

def get_or_create_erp_customer(user):
    """
    Prüft/Erstellt Kunden im ERP per REST (bleibt synchron, damit wir die ID haben).
    """
    # 1. Haben wir lokal schon eine ID? Prüfen ob valide.
    if user.erp_customer_id:
        try:
            check_url = f"{ERP_CUSTOMERS_URL}({user.erp_customer_id})"
            check_res = erp_session.get(check_url, timeout=ERP_TIMEOUT)
            if check_res.status_code == 200:
                return user.erp_customer_id
            else:
                # Ungültig -> Reset
                user.erp_customer_id = None
                db.session.commit()
        except:
            return None

    try:
        # 2. Suchen per Email
        filter_url = f"{ERP_CUSTOMERS_URL}?$filter=email eq '{user.email}'"
        response = erp_session.get(filter_url, timeout=ERP_TIMEOUT)
        response.raise_for_status()
        customers = response.json().get('value', [])

        if customers:
            erp_id = customers[0]['ID']
        else:
            # 3. Anlegen
            payload = {
                "name": user.name,
                "email": user.email,
                "street": user.street,
                "houseNumber": user.house_number,
                "postalCode": user.zip_code,
                "city": user.city,
                "country_code": "DE"
            }
            create_res = erp_session.post(ERP_CUSTOMERS_URL, json=payload, timeout=ERP_TIMEOUT)
            create_res.raise_for_status()
            erp_id = create_res.json()['ID']

        user.erp_customer_id = erp_id
        db.session.commit()
        return erp_id

    except Exception as e:
        print(f"Fehler in get_or_create_erp_customer: {e}")
        return None

def update_erp_customer(user):
    """Update Kundendaten per PATCH."""
    if not user.erp_customer_id:
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
        response = erp_session.patch(url, json=payload, timeout=ERP_TIMEOUT)
        if response.status_code == 404:
            user.erp_customer_id = None
            db.session.commit()
            return get_or_create_erp_customer(user)
        response.raise_for_status()
        return True
    except Exception as e:
        print(f"Fehler bei update_erp_customer: {e}")
        return False


# --- HELPER: Messaging (RabbitMQ) ---

def send_order_via_mq(order_data):
    """
    Sendet Bestellung an RabbitMQ und wartet auf Antwort (RPC Pattern).
    """
    connection = None
    try:
        # 1. Verbindung
        connection = pika.BlockingConnection(
            pika.ConnectionParameters(host=RABBITMQ_HOST, port=RABBITMQ_PORT))
        channel = connection.channel()

        # 2. Queue deklarieren (Ziel)
        channel.queue_declare(queue=QUEUE_ORDERS, durable=True)

        # 3. Antwort-Queue deklarieren
        channel.queue_declare(queue=QUEUE_RESPONSES, durable=True)

        corr_id = str(uuid.uuid4())
        response = None

        def on_response(ch, method, props, body):
            nonlocal response
            # Wir prüfen, ob die ID passt
            if corr_id == props.correlation_id:
                response = body

        # Consumer starten
        # WICHTIG: auto_ack=False sorgt dafür, dass die Nachricht NICHT gelöscht wird.
        # Da wir im Code kein manuelles Ack senden, wird die Nachricht nach dem Schließen
        # der Verbindung wieder in den Status "Ready" zurückgesetzt.
        channel.basic_consume(
            queue=QUEUE_RESPONSES,
            on_message_callback=on_response,
            auto_ack=False  # <--- HIER GEÄNDERT VON True AUF False
        )

        print(f"Sende Order {corr_id} an RabbitMQ...")

        # Nachricht senden
        channel.basic_publish(
            exchange='',
            routing_key=QUEUE_ORDERS,
            properties=pika.BasicProperties(
                reply_to=QUEUE_RESPONSES,
                correlation_id=corr_id,
                content_type='application/json'
            ),
            body=json.dumps(order_data)
        )

        # Warten auf Antwort (mit Timeout)
        start_time = time.time()
        while response is None:
            connection.process_data_events()
            if time.time() - start_time > 15: # 15 Sekunden Timeout
                raise TimeoutError("Keine Antwort vom ERP/Karavan erhalten.")

        print("Antwort erhalten.")
        return json.loads(response)

    except Exception as e:
        print(f"Messaging Error: {e}")
        return {"error": str(e)}
    finally:
        if connection:
            try:
                # Schließen der Verbindung setzt unbestätigte Nachrichten zurück in die Queue
                connection.close()
            except:
                pass