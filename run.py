from app import create_app, db

app = create_app()

if __name__ == '__main__':
    # Schema is managed with Flask-Migrate now (see README) — db.create_all()
    # only creates missing tables, it won't apply column-level changes to
    # tables that already exist, so it's no longer run here automatically.
    app.run(host='0.0.0.0', port=5001, debug=True)
