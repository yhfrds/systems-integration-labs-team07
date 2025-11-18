# projekt/routes/admin_routes.py

from flask import render_template, request, redirect, url_for, flash
from flask_login import login_required
from decimal import Decimal
import requests
import csv
import os
from requests.auth import HTTPBasicAuth
from datetime import datetime

from projekt import db, app
from projekt.models import Product


# ERP Sync Config (from your original file)
ERP_CSV_URL = 'http://localhost:4004/rest/api/getProducts'
ERP_USERNAME = 'alice'
ERP_PASSWORD = 'alice'
ERP_IMPORTS_DIR = 'erp_imports'
CSV_SAVE_FILENAME = 'erp_products_archive.csv'
CSV_DELIMITER = ','
CSV_PRICE_DECIMAL = '.'


def register_admin_routes(app):

    @app.route('/admin/sync', methods=['GET', 'POST'])
    @login_required
    def admin_sync():
        """
        Shows Admin-Sync page (GET) and performs ERP CSV sync (POST).
        """

        if request.method == 'POST':

            print(f"[{datetime.now()}] Starting ERP sync...")

            # ---- 0: Resolve file paths ----
            try:
                # one level above /projekt
                base_dir = os.path.dirname(app.root_path)
                imports_dir_path = os.path.join(base_dir, ERP_IMPORTS_DIR)
                os.makedirs(imports_dir_path, exist_ok=True)
                csv_save_path = os.path.join(
                    imports_dir_path, CSV_SAVE_FILENAME)
            except Exception as e:
                flash(f"Error creating import directory: {e}")
                return redirect(url_for('admin_sync'))

            # ---- 1: Download CSV ----
            try:
                print(f"Downloading from {ERP_CSV_URL} as {ERP_USERNAME}...")
                csv_response = requests.get(
                    ERP_CSV_URL,
                    timeout=10,
                    auth=HTTPBasicAuth(ERP_USERNAME, ERP_PASSWORD)
                )
                csv_response.raise_for_status()

                with open(csv_save_path, 'w', encoding='utf-8', newline='') as f:
                    f.write(csv_response.text)

                print(f"CSV saved to {csv_save_path}")

            except requests.exceptions.ConnectionError:
                flash("Error: Cannot connect to ERP server.")
                return redirect(url_for('admin_sync'))

            except requests.exceptions.RequestException as e:
                if "401" in str(e):
                    flash(
                        "Authentication failed (401). Check ERP_USERNAME and ERP_PASSWORD.")
                else:
                    flash(f"Error downloading CSV: {e}")
                return redirect(url_for('admin_sync'))

            # ---- 2: Read CSV and update DB ----
            created = updated = deleted = errors = 0
            erp_ids_from_sync = set()

            try:
                with open(csv_save_path, 'r', encoding='utf-8') as f:
                    reader = csv.DictReader(f, delimiter=CSV_DELIMITER)

                    for row in reader:
                        try:
                            erp_id = row.get('productID')
                            name = row.get('name')
                            price_raw = row.get('price')
                            desc_raw = row.get('description')

                            if not erp_id or not name or price_raw is None:
                                print("Skipping incomplete row:", row)
                                errors += 1
                                continue

                            # Clean and parse
                            price_str = str(price_raw).replace(
                                ' null', '').strip()
                            price = Decimal(price_str)
                            desc = desc_raw if desc_raw and str(
                                desc_raw) != 'NaN' else ''

                            erp_id_str = str(erp_id)
                            erp_ids_from_sync.add(erp_id_str)

                            # Look in DB
                            product = Product.query.filter_by(
                                erp_id=erp_id_str).first()

                            if product:
                                # Update
                                product.name = name
                                product.description = desc
                                product.price = price
                                updated += 1
                            else:
                                # Create
                                new_p = Product(
                                    erp_id=erp_id_str,
                                    name=name,
                                    description=desc,
                                    price=price
                                )
                                db.session.add(new_p)
                                created += 1

                        except Exception as e:
                            print("Error processing row:", row, e)
                            errors += 1

                # ---- 3: Delete removed products ----
                products_to_check = Product.query.filter(
                    Product.erp_id != None).all()
                for p in products_to_check:
                    if p.erp_id not in erp_ids_from_sync:
                        db.session.delete(p)
                        deleted += 1

                # Commit updates
                db.session.commit()

                flash(
                    f"ERP Sync complete — Created: {created}, Updated: {updated}, "
                    f"Deleted: {deleted}, Errors: {errors}",
                    "success"
                )

            except Exception as e:
                db.session.rollback()
                flash(f"Error processing CSV or updating DB: {e}")

            return redirect(url_for('admin_sync'))

        # GET request → Show admin page
        return render_template('admin_sync.html')
