# AI Agent Instructions for Simple Web Shop

## Project Overview
This is a Flask-based simple web shop application that demonstrates core e-commerce functionality. The application uses SQLite for data storage and Flask-SQLAlchemy for ORM.

## Architecture & Components

### Database Models (`app.py`)
- `User`: Handles user authentication and profile management
- `Product`: Manages product catalog
- `Order` & `OrderItem`: Handles order processing with status tracking
- Session-based cart implementation (no database persistence for cart)

### Key Files
- `app.py`: Main application file containing routes, models, and business logic
- `create_db.py`: Database initialization script
- `seed_db.py`: Database seeding utility
- `templates/`: Jinja2 HTML templates for frontend

## Development Workflow


### Environment Setup
```bash
# Python 3.10 or higher is required
pip install -r requirements.txt
python create_db.py  # Initialize database
python seed_db.py    # (Optional) Add sample data
python app.py        # Run development server
```

### Flask Environment Variables
- As of Flask 2.3+, use `FLASK_DEBUG` instead of `FLASK_ENV`.

### Docker/WSL2 Troubleshooting (Windows)
- Ensure WSL2 is installed and Docker Desktop is running with WSL2 integration. If you see errors about the Docker Linux Engine or WSL, install/enable WSL2 and restart Docker Desktop.

### Database Operations
- SQLite database file is created at `instance/shop.db`
- Models are defined using SQLAlchemy in `app.py`
- Database migrations are manual - recreate using `create_db.py`

## Project Conventions

### Authentication
- Uses Flask-Login for session management
- Password hashing via Werkzeug's security utilities
- Login required for order operations (see `@login_required` decorators)

### Data Flow
1. Cart management through session storage (`get_cart()`, `save_cart()`)
2. Orders created from cart data upon checkout
3. Order status progression: pending → shipped → completed

### Security Notes
- Development secret key in `app.config['SECRET_KEY']` - needs production value
- Product creation lacks admin protection (noted in comments)
- CSRF protection via Flask's built-in mechanisms

## Common Tasks

### Adding New Product Fields
1. Update `Product` model in `app.py`
2. Modify `product_form.html` template
3. Update route handler in `app.py` (`product_new()` function)

### Modifying Order Flow
1. Check `Order` model for status values
2. Update order processing in relevant route handlers
3. Modify `order_detail.html` for display changes