#!/bin/bash
# Setup and run the Docling Document Processing API

# Create virtual environment
python -m venv venv

# Activate virtual environment
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Create upload directory
mkdir -p uploads

# Run application
uvicorn app.main:app --reload --port 8000