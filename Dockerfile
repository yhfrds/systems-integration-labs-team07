FROM python:3.10-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first to leverage Docker cache
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create volume mount point for database
RUN mkdir -p /app/instance
VOLUME /app/instance

# Set environment variables
ENV FLASK_APP=app.py
ENV FLASK_DEBUG=0
ENV SECRET_KEY="change-me-in-production"

# Initialize the database
RUN python create_db.py

# Expose the port the app runs on
EXPOSE 5000

# Command to run the application
CMD ["python", "app.py"]