#!/usr/bin/env python3
"""
Apollo API Server

This module implements the API server for the Apollo component,
following the Single Port Architecture pattern.
"""

import asyncio
import json
import logging
import os
import sys
import time
import uuid
from typing import Dict, List, Any, Optional, Union
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, APIRouter, WebSocket, WebSocketDisconnect, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

# Add Tekton root to path if not already present
tekton_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
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

# Import shared utilities
from shared.utils.hermes_registration import HermesRegistration, heartbeat_loop
from shared.utils.logging_setup import setup_component_logging
from shared.utils.env_config import get_component_config
from shared.utils.errors import StartupError
from shared.utils.startup import component_startup, StartupMetrics
from shared.utils.shutdown import GracefulShutdown
from shared.utils.health_check import create_health_response
from shared.api import (
    create_standard_routers,
    mount_standard_routers,
    create_ready_endpoint,
    create_discovery_endpoint,
    get_openapi_configuration,
    EndpointInfo
)

# Import core modules
from apollo.core.apollo_manager import ApolloManager
from apollo.core.context_observer import ContextObserver
from apollo.core.token_budget import TokenBudgetManager
from apollo.core.predictive_engine import PredictiveEngine
from apollo.core.action_planner import ActionPlanner
from apollo.core.protocol_enforcer import ProtocolEnforcer
from apollo.core.message_handler import MessageHandler, HermesClient
from apollo.core.interfaces.rhetor import RhetorInterface

# Import API routes
from apollo.api.routes import api_router, ws_router, metrics_router
from apollo.api.endpoints.mcp import mcp_router

# Use shared logger
logger = setup_component_logging("apollo")

# Component configuration
COMPONENT_NAME = "Apollo"
COMPONENT_VERSION = "0.1.0"
COMPONENT_DESCRIPTION = "Local attention and prediction system for LLM orchestration"

# Global state for Hermes registration
hermes_registration = None
heartbeat_task = None
start_time = None
is_registered_with_hermes = False
mcp_bridge = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for Apollo"""
    global hermes_registration, heartbeat_task, start_time, is_registered_with_hermes
    
    # Track startup time
    start_time = time.time()
    
    # Startup
    logger.info("Starting Apollo Executive Coordinator API")
    
    async def apollo_startup():
        """Apollo-specific startup logic"""
        try:
            # Get configuration
            config = get_component_config()
            port = config.apollo.port if hasattr(config, 'apollo') else int(os.environ.get("APOLLO_PORT"))
            
            # Register with Hermes
            global hermes_registration, heartbeat_task
            hermes_registration = HermesRegistration()
            
            logger.info(f"Attempting to register Apollo with Hermes on port {port}")
            is_registered_with_hermes = await hermes_registration.register_component(
                component_name="apollo",
                port=port,
                version=COMPONENT_VERSION,
                capabilities=[
                    "llm_orchestration",
                    "context_observation",
                    "token_budget_management",
                    "predictive_planning",
                    "protocol_enforcement"
                ],
                metadata={
                    "description": "Local attention and prediction system",
                    "category": "ai"
                }
            )
            
            if is_registered_with_hermes:
                logger.info("Successfully registered with Hermes")
                # Start heartbeat task
                heartbeat_task = asyncio.create_task(
                    heartbeat_loop(hermes_registration, "apollo", interval=30)
                )
                logger.info("Started Hermes heartbeat task")
            else:
                logger.warning("Failed to register with Hermes - continuing without registration")
            
            # Create data directories
            data_dir = os.environ.get("APOLLO_DATA_DIR", os.path.expanduser("~/.tekton/apollo"))
            os.makedirs(data_dir, exist_ok=True)
            
            # Sub-directories for component data
            context_data_dir = os.path.join(data_dir, "context_data")
            budget_data_dir = os.path.join(data_dir, "budget_data")
            prediction_data_dir = os.path.join(data_dir, "prediction_data")
            action_data_dir = os.path.join(data_dir, "action_data")
            protocol_data_dir = os.path.join(data_dir, "protocol_data")
            message_data_dir = os.path.join(data_dir, "message_data")
            
            # Create Rhetor interface
            rhetor_interface = RhetorInterface()
            
            # Create message handler with Hermes client
            hermes_client = HermesClient()
            message_handler = MessageHandler(
                component_name="apollo",
                hermes_client=hermes_client,
                data_dir=message_data_dir
            )
            
            # Create context observer
            context_observer = ContextObserver(
                rhetor_interface=rhetor_interface,
                data_dir=context_data_dir
            )
            
            # Create token budget manager
            token_budget_manager = TokenBudgetManager(
                data_dir=budget_data_dir
            )
            
            # Create protocol enforcer
            protocol_enforcer = ProtocolEnforcer(
                data_dir=protocol_data_dir,
                load_defaults=True
            )
            
            # Create predictive engine
            predictive_engine = PredictiveEngine(
                context_observer=context_observer,
                data_dir=prediction_data_dir
            )
            
            # Create action planner
            action_planner = ActionPlanner(
                context_observer=context_observer,
                predictive_engine=predictive_engine,
                data_dir=action_data_dir
            )
            
            # Create Apollo manager
            apollo_manager = ApolloManager(
                rhetor_interface=rhetor_interface,
                data_dir=data_dir
            )
            
            # Register components with Apollo manager
            apollo_manager.context_observer = context_observer
            apollo_manager.token_budget_manager = token_budget_manager
            apollo_manager.protocol_enforcer = protocol_enforcer
            apollo_manager.predictive_engine = predictive_engine
            apollo_manager.action_planner = action_planner
            apollo_manager.message_handler = message_handler
            
            # Store in app state
            app.state.apollo_manager = apollo_manager
            app.state.hermes_registration = hermes_registration
            
            # Start components that have start methods
            logger.info("Starting Apollo components...")
            await message_handler.start()
            await context_observer.start()
            await predictive_engine.start()
            await action_planner.start()
            
            # Mark as running without calling apollo_manager.start() 
            # which tries to start components that don't have start methods
            apollo_manager.is_running = True
            
            # Initialize Hermes MCP Bridge
            try:
                from apollo.core.mcp.hermes_bridge import ApolloMCPBridge
                global mcp_bridge
                mcp_bridge = ApolloMCPBridge(apollo_manager)
                await mcp_bridge.initialize()
                logger.info("Initialized Hermes MCP Bridge for FastMCP tools")
            except Exception as e:
                logger.warning(f"Failed to initialize MCP Bridge: {e}")
            
            logger.info("Apollo initialized successfully")
            
        except Exception as e:
            logger.error(f"Error during Apollo startup: {e}", exc_info=True)
            raise StartupError(str(e), "apollo", "STARTUP_FAILED")
    
    # Execute startup with metrics
    try:
        metrics = await component_startup("apollo", apollo_startup, timeout=30)
        logger.info(f"Apollo started successfully in {metrics.total_time:.2f}s")
    except Exception as e:
        logger.error(f"Failed to start Apollo: {e}")
        raise
    
    # Create shutdown handler
    shutdown = GracefulShutdown("apollo")
    
    # Register cleanup tasks
    async def cleanup_hermes():
        """Cleanup Hermes registration"""
        if heartbeat_task:
            heartbeat_task.cancel()
            try:
                await heartbeat_task
            except asyncio.CancelledError:
                pass
        
        if hermes_registration and hermes_registration.is_registered:
            await hermes_registration.deregister("apollo")
            logger.info("Deregistered from Hermes")
    
    async def cleanup_components():
        """Cleanup Apollo components"""
        try:
            if hasattr(app.state, "apollo_manager") and app.state.apollo_manager:
                apollo_manager = app.state.apollo_manager
                
                # Stop components in reverse order
                # Don't call apollo_manager.stop() as it tries to stop components without stop methods
                apollo_manager.is_running = False
                
                if apollo_manager.action_planner:
                    await apollo_manager.action_planner.stop()
                if apollo_manager.predictive_engine:
                    await apollo_manager.predictive_engine.stop()
                if apollo_manager.context_observer:
                    await apollo_manager.context_observer.stop()
                if apollo_manager.message_handler:
                    await apollo_manager.message_handler.stop()
                
                logger.info("Apollo components shut down successfully")
        except Exception as e:
            logger.warning(f"Error cleaning up Apollo components: {e}")
    
    async def cleanup_mcp_bridge():
        """Cleanup MCP bridge"""
        global mcp_bridge
        if mcp_bridge:
            try:
                await mcp_bridge.shutdown()
                logger.info("MCP bridge cleaned up")
            except Exception as e:
                logger.warning(f"Error cleaning up MCP bridge: {e}")
    
    shutdown.register_cleanup(cleanup_hermes)
    shutdown.register_cleanup(cleanup_components)
    shutdown.register_cleanup(cleanup_mcp_bridge)
    
    yield
    
    # Shutdown
    logger.info("Shutting down Apollo Executive Coordinator API")
    await shutdown.shutdown_sequence(timeout=10)
    
    # Socket release delay for macOS
    await asyncio.sleep(0.5)

# Create FastAPI application with standard configuration
app = FastAPI(
    **get_openapi_configuration(
        component_name=COMPONENT_NAME,
        component_version=COMPONENT_VERSION,
        component_description=COMPONENT_DESCRIPTION
    ),
    lifespan=lifespan
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Create standard routers
routers = create_standard_routers(COMPONENT_NAME)


# Root endpoint
@routers.root.get("/")
async def root():
    """Root endpoint for the Apollo API."""
    return {
        "name": f"{COMPONENT_NAME} Executive Coordinator",
        "version": COMPONENT_VERSION,
        "status": "running",
        "description": COMPONENT_DESCRIPTION,
        "documentation": "/api/v1/docs"
    }

# Health check endpoint
@routers.root.get("/health")
async def health_check():
    """Check the health of the Apollo component following Tekton standards."""
    try:
        if hasattr(app.state, "apollo_manager") and app.state.apollo_manager:
            # Component exists, get proper health info
            system_status = app.state.apollo_manager.get_system_status()
            
            # Set status code based on health
            status_code = 200
            components_status = system_status.get("components_status", {})
            
            if not system_status.get("system_running", False):
                status_code = 500
                health_status = "error"
                message = "Apollo is not running"
            elif not all(components_status.values()):
                status_code = 429
                health_status = "degraded"
                offline_components = [c for c, status in components_status.items() if not status]
                message = f"Apollo is running in degraded state (inactive components: {', '.join(offline_components)})"
            else:
                health_status = "healthy"
                message = "Apollo is running normally"
        else:
            # Component not initialized but app is responding
            status_code = 200
            health_status = "healthy"
            message = "Apollo API is running (component not fully initialized)"
    except Exception as e:
        # Something went wrong in health check
        status_code = 200
        health_status = "healthy"
        message = f"Apollo API is running (basic health check only)"
        logger.warning(f"Error in health check, using basic response: {e}")
    
    # Use standardized health response
    # Get port from config or environment
    config = get_component_config()
    port = config.apollo.port if hasattr(config, 'apollo') else int(os.environ.get("APOLLO_PORT"))
    
    return create_health_response(
        component_name="apollo",
        port=port,
        version=COMPONENT_VERSION,
        status=health_status,
        registered=is_registered_with_hermes,
        details={"message": message}
    )




# Add ready endpoint
routers.root.add_api_route(
    "/ready",
    create_ready_endpoint(
        component_name=COMPONENT_NAME,
        component_version=COMPONENT_VERSION,
        start_time=start_time or 0,
        readiness_check=lambda: hasattr(app.state, "apollo_manager") and app.state.apollo_manager is not None
    ),
    methods=["GET"]
)

# Add discovery endpoint to v1 router
routers.v1.add_api_route(
    "/discovery",
    create_discovery_endpoint(
        component_name=COMPONENT_NAME,
        component_version=COMPONENT_VERSION,
        component_description=COMPONENT_DESCRIPTION,
        endpoints=[
            EndpointInfo(
                path="/api/v1/predict",
                method="POST",
                description="Get predictions for next user actions"
            ),
            EndpointInfo(
                path="/api/v1/context",
                method="GET",
                description="Get current context summary"
            ),
            EndpointInfo(
                path="/api/v1/budget",
                method="GET",
                description="Get token budget status"
            ),
            EndpointInfo(
                path="/api/v1/protocol/validate",
                method="POST",
                description="Validate protocol compliance"
            ),
            EndpointInfo(
                path="/ws",
                method="WEBSOCKET",
                description="WebSocket for real-time events"
            ),
            EndpointInfo(
                path="/api/v1/metrics",
                method="GET",
                description="Get system metrics"
            )
        ],
        capabilities=[
            "llm_orchestration",
            "context_observation",
            "token_budget_management",
            "predictive_planning",
            "protocol_enforcement"
        ],
        dependencies={
            "hermes": "http://localhost:8001",
            "rhetor": "http://localhost:8003"
        },
        metadata={
            "websocket_endpoint": "/ws",
            "documentation": "/api/v1/docs"
        }
    ),
    methods=["GET"]
)

# Mount standard routers
mount_standard_routers(app, routers)

# Include existing routers - these should be updated to use v1 prefix
app.include_router(api_router, prefix="/api/v1")
app.include_router(ws_router)
app.include_router(metrics_router, prefix="/api/v1")
app.include_router(mcp_router)

# Main entry point
if __name__ == "__main__":
    from shared.utils.socket_server import run_component_server
    
    # Get port from environment - NEVER hardcode
    port = int(os.environ.get("APOLLO_PORT"))
    
    run_component_server(
        component_name="apollo",
        app_module="apollo.api.app",
        default_port=port,
        reload=False
    )