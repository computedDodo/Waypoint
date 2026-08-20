import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY')
    if not SECRET_KEY:
        raise RuntimeError(
            "SECRET_KEY is not set. Create a .env file (see .env.example) "
            "before running the app."
        )

    # 'mysql' (default, native on PythonAnywhere) or 'postgres' (external
    # managed DB like Neon/Supabase — PythonAnywhere's own Postgres is only
    # on paid Custom accounts and is pinned to an old Postgres version).
    DB_ENGINE = os.environ.get('DB_ENGINE', 'mysql').lower()

    DB_USER = os.environ.get('DB_USER')
    DB_PASSWORD = os.environ.get('DB_PASSWORD')
    DB_HOST = os.environ.get('DB_HOST')
    DB_NAME = os.environ.get('DB_NAME')

    if DB_ENGINE == 'postgres':
        DB_PORT = os.environ.get('DB_PORT', '5432')
        SQLALCHEMY_DATABASE_URI = (
            f"postgresql+psycopg2://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
        )
    else:
        SQLALCHEMY_DATABASE_URI = (
            f"mysql+pymysql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}/{DB_NAME}"
        )

    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_recycle": 280, "pool_pre_ping": True}

    MAIL_SERVER = os.environ.get('MAIL_SERVER')
    MAIL_PORT = int(os.environ.get('MAIL_PORT', 587))
    MAIL_USE_TLS = os.environ.get('MAIL_USE_TLS', 'True') == 'True'
    MAIL_USERNAME = os.environ.get('MAIL_USERNAME')
    MAIL_PASSWORD = os.environ.get('MAIL_PASSWORD')
    MAIL_DEFAULT_SENDER = os.environ.get('MAIL_DEFAULT_SENDER')

    MAX_CONTENT_LENGTH = 5 * 1024 * 1024  # 5MB screenshot upload cap
    WTF_CSRF_TIME_LIMIT = None

    # What testers get paid per point when they redeem, platform-wide, in
    # Nigerian Naira. Kept separate from each Campaign.conversion_rate,
    # which is a per-client budget/margin figure for your own accounting —
    # testers shouldn't be paid differently depending on which client's
    # campaign the points happened to come from.
    POINT_VALUE_NGN = float(os.environ.get('POINT_VALUE_NGN', '5'))
