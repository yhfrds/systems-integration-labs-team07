from decimal import Decimal
from app import app, db, Product, User
with app.app_context():
    # Create sample products
    p1 = Product(name='T-Shirt', description='Cotton tee', price=Decimal('9.99'))
    p2 = Product(name='Mug', description='Ceramic mug', price=Decimal('7.50'))
    db.session.add_all([p1, p2])

    # Create a sample user
    u = User(name='Alice', email='alice@example.com', address='123 Street')
    u.set_password('password')
    db.session.add(u)

    db.session.commit()
    print("Seed data committed.")
