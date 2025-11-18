# run.py

# Importiert die Instanzen, die in projekt/__init__.py erstellt wurden
from projekt import app, db, scheduler 

if __name__ == '__main__':
    # Erstellt die Datenbanktabellen, falls sie noch nicht existieren
    with app.app_context():
        db.create_all()
    
    # Scheduler initialisieren und starten
    scheduler.init_app(app)
    scheduler.start()
    
    # Wichtiger Hinweis für den Debug-Modus
    if app.debug:
        print("--- WARNUNG: DEBUG-MODUS ---")
        print("Der automatische Scheduler wird wegen des Flask-Reloaders")
        print("ggf. zweimal ausgeführt. Das ist im Debug-Modus normal.")
        print("Nutzen Sie für stabile Tests den manuellen 'Sync ERP'-Button.")

    app.run(debug=True)