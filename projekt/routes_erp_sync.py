from flask import render_template, request, redirect, url_for, flash, abort
from flask_login import login_required
from decimal import Decimal

import requests
from datetime import datetime

from projekt.routes import erp_session, ERP_PRODUCTS_URL, ERP_TIMEOUT


# Imports app, db, and scheduler from __init__.py
from . import app, db, scheduler
from .models import Product


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
        products_to_check = Product.query.filter(
            Product.id.like('________-____-____-____-____________')).all()

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
