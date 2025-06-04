"""Entry point for python -m apollo"""
import os
import sys

# Add Tekton root to path if not already present
tekton_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
if tekton_root not in sys.path:
    sys.path.insert(0, tekton_root)

# Initialize Tekton environment before other imports
try:
    from shared.utils.tekton_startup import tekton_component_startup
    # Load environment variables from Tekton's three-tier system
    tekton_component_startup("apollo")
except ImportError as e:
    print(f"[APOLLO] Could not load Tekton environment manager: {e}")
    print(f"[APOLLO] Continuing with system environment variables")

from shared.utils.socket_server import run_component_server

if __name__ == "__main__":
    # Get port from environment variable
    # The run_component_server will look for APOLLO_PORT in environment
    # We pass None as default_port to force it to use environment
    port_str = os.environ.get("APOLLO_PORT")
    if not port_str:
        print("Error: APOLLO_PORT not set in environment")
        sys.exit(1)
    
    default_port = int(port_str)
    
    run_component_server(
        component_name="apollo",
        app_module="apollo.api.app",
        default_port=default_port,
        reload=False
    )