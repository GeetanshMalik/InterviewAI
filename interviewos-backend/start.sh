#!/bin/bash
# Startup script for Render deployment

# Create necessary directories
mkdir -p chroma_db
mkdir -p uploads
mkdir -p data/code_execution

# Run database migrations if enabled
if [ "$POSTGRES_PERSISTENCE_ENABLED" = "true" ]; then
    echo "Running database migrations..."
    alembic upgrade head || echo "Migration failed or no migrations needed"
fi

# Start the application
exec "$@"
