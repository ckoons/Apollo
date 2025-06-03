"""Entry point for python -m apollo"""
import os
import sys

# Add Tekton root to path if not already present
tekton_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
if tekton_root not in sys.path:
    sys.path.insert(0, tekton_root)

from shared.utils.socket_server import run_component_server

if __name__ == "__main__":
    # Get port from environment variable
    default_port = int(os.environ.get("APOLLO_PORT"))
    
    run_component_server(
        component_name="apollo",
        app_module="apollo.api.app",
        default_port=default_port,
        reload=False
    )