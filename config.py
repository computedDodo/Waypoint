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

    BREVO_API_KEY = os.environ.get('BREVO_API_KEY')
    MAIL_DEFAULT_SENDER = os.environ.get('MAIL_DEFAULT_SENDER')

    MAX_CONTENT_LENGTH = 5 * 1024 * 1024  
    WTF_CSRF_TIME_LIMIT = None

    POINT_VALUE_NGN = float(os.environ.get('POINT_VALUE_NGN', '5'))
