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

import uvicorn
from fastapi import FastAPI, APIRouter, WebSocket, WebSocketDisconnect, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

# Initialize Tekton environment before other imports
try:
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "shared", "utils"))
    from tekton_startup import tekton_component_startup
    # Load environment variables from Tekton's three-tier system
    tekton_component_startup("apollo")
except ImportError as e:
    print(f"[APOLLO] Could not load Tekton environment manager: {e}")
    print(f"[APOLLO] Continuing with system environment variables")

# Import utilities
# from tekton.utils.port_config import get_apollo_port

# Import Hermes registration utility
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "shared", "utils"))
from hermes_registration import HermesRegistration, heartbeat_loop

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

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("apollo.api")

# Create FastAPI application
app = FastAPI(
    title="Apollo Executive Coordinator API",
    description="API for the Apollo executive coordinator for Tekton LLM operations",
    version="0.1.0",
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Root endpoint
@app.get("/")
async def root():
    """Root endpoint for the Apollo API."""
    port = 8012
    
    return {
        "name": "Apollo Executive Coordinator",
        "version": "0.1.0",
        "status": "running",
        "documentation": f"http://localhost:{port}/docs"
    }

# Health check endpoint
@app.get("/health")
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
    
    # Format response according to Tekton standards
    standardized_health = {
        "status": health_status,
        "component": "apollo",
        "version": "0.1.0",
        "port": 8012,
        "message": message
    }
    
    return JSONResponse(
        content=standardized_health,
        status_code=status_code
    )


@app.on_event("startup")
async def startup_event():
    """Initialize Apollo components on startup."""
    try:
        logger.info("Initializing Apollo components...")
        
        # Register with Hermes
        port = 8012
        hermes_registration = HermesRegistration()
        await hermes_registration.register_component(
            component_name="apollo",
            port=port,
            version="0.1.0",
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
        app.state.hermes_registration = hermes_registration
        
        # Start heartbeat task
        if hermes_registration.is_registered:
            asyncio.create_task(heartbeat_loop(hermes_registration, "apollo"))
        
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
        
        # Start components
        logger.info("Starting Apollo components...")
        await message_handler.start()
        await context_observer.start()
        await predictive_engine.start()
        await action_planner.start()
        await apollo_manager.start()
        
        logger.info("Apollo initialized successfully")
        
    except Exception as e:
        logger.error(f"Error initializing Apollo: {e}")
        # Don't re-raise the exception to allow the API to start even if initialization fails


@app.on_event("shutdown")
async def shutdown_event():
    """Shutdown Apollo components gracefully."""
    try:
        logger.info("Shutting down Apollo components...")
        
        # Deregister from Hermes
        if hasattr(app.state, "hermes_registration") and app.state.hermes_registration:
            await app.state.hermes_registration.deregister("apollo")
        
        # Get Apollo manager from app state
        if hasattr(app.state, "apollo_manager") and app.state.apollo_manager:
            apollo_manager = app.state.apollo_manager
            
            # Stop components in reverse order
            await apollo_manager.stop()
            
            if apollo_manager.action_planner:
                await apollo_manager.action_planner.stop()
                
            if apollo_manager.predictive_engine:
                await apollo_manager.predictive_engine.stop()
                
            if apollo_manager.context_observer:
                await apollo_manager.context_observer.stop()
                
            if apollo_manager.message_handler:
                await apollo_manager.message_handler.stop()
            
        logger.info("Apollo shutdown complete")
        
    except Exception as e:
        logger.error(f"Error shutting down Apollo: {e}")


# Include routers in app
app.include_router(api_router)
app.include_router(ws_router)
app.include_router(metrics_router)
app.include_router(mcp_router)

# Main entry point
if __name__ == "__main__":
    import uvicorn
    
    # Get port from environment variable or use default
    port = 8012
    
    uvicorn.run(app, host="0.0.0.0", port=port)