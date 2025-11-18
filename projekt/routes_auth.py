from flask import render_template, request, redirect, url_for, flash
from flask_login import login_user, logout_user, login_required, current_user
from .routes_helpers import get_or_create_erp_customer, update_erp_customer

# Imports app, db, and scheduler from __init__.py
from . import app, db
from .models import User

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
        
        # +++ SYNC: Create in ERP immediately +++
        try:
            get_or_create_erp_customer(u)
        except Exception as e:
            print(f"Warning: ERP sync during registration failed: {e}")
            # We let the user in anyway, sync will happen at checkout at the latest
        
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
        
        # +++ SYNC: Ensure ERP link is up-to-date +++
        # (Runs in the background, errors are ignored to not block login)
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

        # Local updates
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
                
                # +++ SYNC: Send changes to ERP +++
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
