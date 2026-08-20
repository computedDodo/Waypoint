# Paste this into the WSGI configuration file PythonAnywhere gives you
# under the "Web" tab (e.g. /var/www/yourusername_pythonanywhere_com_wsgi.py).
# Replace 'yourusername' and the project folder name with your real values.

import sys
import os

project_home = '/home/yourusername/waypoint'
if project_home not in sys.path:
    sys.path.insert(0, project_home)

from dotenv import load_dotenv
load_dotenv(os.path.join(project_home, '.env'))

from app import create_app
application = create_app()
