# Simple Web Shop Project

A lightweight e-commerce application built with Flask, demonstrating core online shopping functionality including user authentication, product management, and order processing.

## 🚀 Getting Started

### Prerequisites (Docker Only)

**Docker is the recommended and supported way to run this project.**

**What is Docker?** Docker lets you run this app without worrying about installing all the right software. It works the same on Windows, Mac, and Linux.

**Install Docker Desktop:**
- [Download for Windows](https://www.docker.com/products/docker-desktop/)
- [Download for Mac](https://www.docker.com/products/docker-desktop/)
- [Download for Linux](https://docs.docker.com/desktop/install/linux-install/)

  - **Windows users:** During installation, if asked, enable WSL2 (Windows Subsystem for Linux). This is required for Docker to work on Windows. [WSL2 install guide](https://aka.ms/wslinstall)
  - **Mac users:** No WSL2 needed. Just install Docker Desktop for Mac.
  - **Linux users:** Follow the Linux instructions above.

After installing Docker Desktop, restart your computer if prompted, then open Docker Desktop to make sure it is running (look for the whale icon in your system tray or menu bar).

---
### Quick Setup with Docker (Recommended)

1. Clone the repository:
   ```bash
   git clone https://github.com/yhfrds/systems-integration-labs-team07.git
   cd systems-integration-labs-team07
   ```

2. Build and start the application:
   ```bash
   docker-compose up --build
   ```

The application will be available at `http://localhost:5000`

**Note:** If you are on Windows, ensure WSL2 is installed and Docker Desktop is running with WSL2 integration enabled. If you see errors about the Docker Linux Engine or WSL, follow the prompts to install or enable WSL2, then restart Docker Desktop.

Visit `http://localhost:5000` in your browser to see the application.

#### Using Sample Data with Docker
To add sample data to your Docker container:
```bash
docker-compose exec web python seed_db.py
```
---
## Advanced/Alternative: Local Python Setup (Not Recommended)

If you are an advanced user and prefer to run the app without Docker, you need Python 3.10 or higher. [Download Python](https://www.python.org/downloads/)

See the end of this README for alternative setup instructions.

### Alternative: Local Setup without Docker

1. Create and activate a virtual environment:
   ```bash
   # Windows
   python -m venv venv
   .\venv\Scripts\activate

   # Linux/MacOS
   python -m venv venv
   source venv/bin/activate
   ```

2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

3. Initialize the database:
   ```bash
   python create_db.py
   ```

4. (Optional) Add sample data:
   ```bash
   python seed_db.py
   ```

5. Run the development server:
   ```bash
   python app.py
   ```


## 📱 Features

- **User Management**: Registration, login, and profile management
- **Product Catalog**: Browse and add products
- **Shopping Cart**: Session-based cart management
- **Order Processing**: Complete purchase flow with order status tracking

## 🏗 Project Structure

```
├── app.py              # Main application file (routes, models, business logic)
├── create_db.py        # Database initialization script
├── seed_db.py         # Sample data population script
├── requirements.txt    # Project dependencies
├── Dockerfile         # Docker image configuration
├── docker-compose.yml # Docker service orchestration
├── instance/          # Database file location
│   └── shop.db       # SQLite database file
└── templates/         # Jinja2 HTML templates
    ├── base.html     # Base template with common layout
    ├── index.html    # Home page/product listing
    ├── cart.html     # Shopping cart view
    └── ...           # Other template files
```

## 💻 Development Guide

### Flask Environment Variables

- As of Flask 2.3+, `FLASK_ENV` is deprecated. This project uses `FLASK_DEBUG=0` for production mode in Docker. You may set `FLASK_DEBUG=1` for development mode.

### Database Models

- **User**: Account management and authentication
  - Fields: id, name, email, address, password_hash
  - Relationships: One-to-many with Order

- **Product**: Product catalog items
  - Fields: id, name, description, price

- **Order**: Customer purchase records
  - Fields: id, user_id, total_price, status, created_at
  - Status flow: pending → shipped → completed

- **OrderItem**: Individual items in an order
  - Fields: id, order_id, product_id, quantity, unit_price

### Common Development Tasks

#### Adding a New Product Field
1. Update the `Product` model in `app.py`
2. Modify `templates/product_form.html`
3. Update the `product_new()` route handler

#### Implementing a New Order Status
1. Add the status to the Order model's status column comments
2. Update order processing logic in relevant route handlers
3. Update status display in `order_detail.html`

## 🔒 Security Notes

- **Development Mode**: The current `SECRET_KEY` is for development only. Change it in production.
- **Admin Access**: Product creation currently has no admin protection - implement role-based access in production.
- **Password Security**: Passwords are hashed using Werkzeug's security utilities.
- **Docker Security**: The provided Docker configuration is for development. For production:
  - Use a non-root user in the container
  - Change the `SECRET_KEY`
  - Configure proper logging
  - Consider using a production-grade database

## 🤝 Contributing

1. Create a feature branch
2. Make your changes
3. Test thoroughly
4. Submit a pull request

## 🐳 Docker Development

### Troubleshooting Docker on Windows

- If you encounter errors related to WSL2 or the Docker Linux Engine, ensure:
  - WSL2 is installed (`wsl -l -v` should show a running distro)
  - Docker Desktop is running and set to use WSL2
  - Restart Docker Desktop after any WSL2 changes

### Common Docker Commands

- Start the application: `docker-compose up`
- Rebuild and start: `docker-compose up --build`
- Run in background: `docker-compose up -d`
- Stop containers: `docker-compose down`
- View logs: `docker-compose logs -f`
- Execute command in container: `docker-compose exec web <command>`
- Reset database: 
  ```bash
  docker-compose down -v  # Remove volume
  docker-compose up --build  # Rebuild with fresh DB
  ```

### Data Persistence
- The SQLite database is stored in a Docker volume (`db-data`)
- Data persists between container restarts
- To reset data, remove the volume with `docker-compose down -v`

<!-- This is irrelevant for now
## ❗ Known Issues / TODOs

- Product management needs admin role implementation
- Cart data is session-based (not persistent)
- No automated tests yet
- Manual database migrations -->

## 📚 Additional Resources

- [Flask Documentation](https://flask.palletsprojects.com/)
- [Flask-SQLAlchemy Documentation](https://flask-sqlalchemy.palletsprojects.com/)
- [Flask-Login Documentation](https://flask-login.readthedocs.io/)

--Generated by Github Copilot