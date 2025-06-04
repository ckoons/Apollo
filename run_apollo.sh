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

# APOLLO_PORT must be set in environment - no hardcoded defaults per Single Port Architecture
if [ -z "$APOLLO_PORT" ]; then
    echo "Error: APOLLO_PORT not set in environment"
    echo "Please configure port in ~/.env.tekton or system environment"
    exit 1
fi

# Start Apollo API server
python -m apollo "$@"