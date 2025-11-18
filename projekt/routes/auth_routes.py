from flask import render_template, request, redirect, url_for, flash
from flask_login import login_user, logout_user, login_required, current_user
from ..models import User
from .. import db


def register_auth_routes(app):

    @app.route('/register', methods=['GET', 'POST'])
    def register():
        if request.method == 'POST':
            name = request.form['name'].strip()
            email = request.form['email'].strip().lower()
            address = request.form.get('address', '').strip()
            password = request.form['password']

            if User.query.filter_by(email=email).first():
                flash('Email already registered')
                return redirect(url_for('register'))

            u = User(name=name, email=email, address=address)
            u.set_password(password)
            db.session.add(u)
            db.session.commit()

            login_user(u)
            flash('Registered and logged in')
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
            address = request.form.get('address', '').strip()
            email = request.form['email'].strip().lower()
            current_password = request.form['current_password']
            new_password = request.form.get('new_password')

            if not current_user.check_password(current_password):
                flash('Incorrect current password. No changes were made.')
                return redirect(url_for('profile'))

            current_user.name = name
            current_user.address = address

            if current_user.email != email:
                if User.query.filter(User.email == email, User.id != current_user.id).first():
                    flash('This email address is already in use by another account.')
                    return redirect(url_for('profile'))
                current_user.email = email

            if new_password:
                current_user.set_password(new_password)

            db.session.commit()
            flash('Profile updated successfully.')
            return redirect(url_for('profile'))

        return render_template('profile.html')
