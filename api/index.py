import sys
import os

# Add the project root to sys.path to allow imports
project_home = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(project_home, ".."))

# Import the Flask application from telegram_tracker
from telegram_tracker.webapp import app
