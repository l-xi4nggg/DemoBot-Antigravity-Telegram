import sys
import os

# -------------------------------------------------------------
# PythonAnywhere WSGI Configuration Template
# Copy the entire contents of this file and paste it into the 
# WSGI configuration file link on the PythonAnywhere 'Web' tab.
# -------------------------------------------------------------

# Add your project directory to the sys.path
project_home = '/home/Puloda/DemoBot-Antigravity-Telegram'
if project_home not in sys.path:
    sys.path.insert(0, project_home)

# Load environment variables from the .env file
from dotenv import load_dotenv
load_dotenv(os.path.join(project_home, 'telegram_tracker', '.env'))

# Import the Flask application (webapp.py)
from telegram_tracker.webapp import app as application
