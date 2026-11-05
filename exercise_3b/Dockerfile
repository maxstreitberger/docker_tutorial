# Base image with Python 3.12
FROM python:3.12-slim

# Working directory inside the container
WORKDIR /app

# Copy dependency list
COPY requirements.txt .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY app.py .

# Start Flask
CMD ["flask", "--app", "app", "run", "--host", "0.0.0.0", "--port", "5000"]