# projekt/models.py

from . import db
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime


class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    # +++ NEUES FELD für die ERP-Kunden-GUID +++
    erp_customer_id = db.Column(db.String(36), unique=True, nullable=True, index=True)
    
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(200), unique=True, nullable=False)
    address = db.Column(db.String(300), default='')
    password_hash = db.Column(db.String(300), nullable=False)
    orders = db.relationship('Order', backref='user', lazy=True)

    def set_password(self, pw):
        self.password_hash = generate_password_hash(pw)

    def check_password(self, pw):
        return check_password_hash(self.password_hash, pw)


class Product(db.Model):
    # --- GEÄNDERT: ID ist jetzt die String-GUID aus dem ERP ---
    id = db.Column(db.String(36), primary_key=True) 
    
    # --- GEÄNDERT: Altes 'erp_id' umbenannt, um die lesbare ID zu speichern ---
    product_str_id = db.Column(db.String(100), unique=True, nullable=True, index=True) # z.B. 'GRVL1000'
    
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, default='')
    price = db.Column(db.Numeric(10, 2), nullable=False)
    # WICHTIG: 'stock' wird hier *nicht* gespeichert, da es in Echtzeit gelesen wird.


class Order(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    
    # +++ NEUES FELD für die ERP-Bestell-GUID +++
    erp_order_id = db.Column(db.String(36), unique=True, nullable=True, index=True)

    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    total_price = db.Column(db.Numeric(12, 2), nullable=False)
    status = db.Column(db.String(50), default='pending') # Status aus dem Webshop (z.B. "Submitted to ERP")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    items = db.relationship('OrderItem', backref='order', lazy=True, cascade="all, delete-orphan")


class OrderItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey('order.id'), nullable=False)
    
    # --- GEÄNDERT: Verknüpft jetzt mit der String-GUID des Produkts ---
    product_id = db.Column(db.String(36), db.ForeignKey('product.id'), nullable=False)
    
    product = db.relationship('Product')
    quantity = db.Column(db.Integer, nullable=False)
    unit_price = db.Column(db.Numeric(10, 2), nullable=False)