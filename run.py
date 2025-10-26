# run.py

from projekt import app, db

if __name__ == '__main__':
    # Erstellt die Datenbanktabellen, falls sie noch nicht existieren
    with app.app_context():
        db.create_all()
    app.run(debug=True)