# projekt/models.py

from . import db
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime

class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    erp_customer_id = db.Column(db.String(36), unique=True, nullable=True, index=True)
    
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(200), unique=True, nullable=False)
    
    # Getrennte Adressfelder
    street = db.Column(db.String(100), default='')
    house_number = db.Column(db.String(20), default='')
    zip_code = db.Column(db.String(20), default='')
    city = db.Column(db.String(100), default='')
    
    password_hash = db.Column(db.String(300), nullable=False)
    
    # LÖSCHEN: orders = db.relationship('Order', ...)  <-- Diese Zeile entfernen!

    def set_password(self, pw):
        self.password_hash = generate_password_hash(pw)

    def check_password(self, pw):
        return check_password_hash(self.password_hash, pw)


class Product(db.Model):
    id = db.Column(db.String(36), primary_key=True) 
    product_str_id = db.Column(db.String(100), unique=True, nullable=True, index=True)
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, default='')
    price = db.Column(db.Numeric(10, 2), nullable=False)

# LÖSCHEN: Class Order ... <-- Die ganze Klasse entfernen!
# LÖSCHEN: Class OrderItem ... <-- Die ganze Klasse entfernen!