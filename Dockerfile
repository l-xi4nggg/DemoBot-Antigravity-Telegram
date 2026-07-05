FROM python:3.11-slim

# Set environment variables to optimize Python runtime
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install python dependencies
COPY telegram_tracker/requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

# Copy all project files to container working directory
COPY . /app/

# Ensure directory for SQLite database exists
RUN mkdir -p /app/telegram_tracker/database

# Command to run the bot
CMD ["python", "-m", "telegram_tracker.main"]
