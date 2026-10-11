#!/bin/bash
# Build script for Render deployment
# This runs during the build phase

set -e  # Exit on error

echo "==================================="
echo "Starting Render Build Process"
echo "==================================="

# Print Python version
echo "Python version:"
python --version

# Upgrade pip
echo "Upgrading pip..."
pip install --upgrade pip

# Install dependencies
echo "Installing dependencies from requirements.txt..."
pip install -r requirements.txt

# Verify critical packages
echo "Verifying critical packages..."
python -c "import fastapi; print(f'FastAPI: {fastapi.__version__}')"
python -c "import uvicorn; print(f'Uvicorn: {uvicorn.__version__}')"
python -c "import redis; print(f'Redis: {redis.__version__}')"
python -c "import sqlalchemy; print(f'SQLAlchemy: {sqlalchemy.__version__}')"

# Make start script executable
echo "Making start.sh executable..."
chmod +x start.sh

echo "==================================="
echo "Build Complete!"
echo "==================================="
