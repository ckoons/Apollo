#!/bin/bash

# This script starts the Apollo server with the appropriate environment variables

# Ensure the script is run from the Apollo directory
cd "$(dirname "$0")"

# Load environment variables if .env file exists
if [ -f .env ]; then
    set -a
    source .env
    set +a
fi

# Set APOLLO_PORT if not already set in environment
if [ -z "$APOLLO_PORT" ]; then
    export APOLLO_PORT=8012  # Choose appropriate port according to port_assignments.md
fi

# Start Apollo API server
python -m apollo "$@"