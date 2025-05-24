"""
Rhetor Interface for Apollo.

This module provides an interface for communicating with the Rhetor component
to monitor LLM context usage and metrics.
"""

import os
import logging
import json
import asyncio
import aiohttp
from typing import Dict, List, Any, Optional, Union
from datetime import datetime

from tekton.utils.port_config import get_component_port, get_component_url

# Configure logging
logger = logging.getLogger(__name__)


class RhetorInterface:
    """
    Interface for communicating with the Rhetor component.
    
    This class handles API calls to Rhetor for retrieving metrics, context information,
    and sending directives for context management.
    """
    
    def __init__(
        self, 
        base_url: Optional[str] = None,
        retry_count: int = 3,
        retry_delay: float = 1.0,
        timeout: float = 10.0
    ):
        """
        Initialize the Rhetor Interface.
        
        Args:
            base_url: Base URL for the Rhetor API (default: use port_config)
            retry_count: Number of retries for failed requests
            retry_delay: Delay between retries (seconds)
            timeout: Request timeout (seconds)
        """
        self.base_url = base_url or get_component_url("rhetor")
        self.ws_url = get_component_url("rhetor", protocol="ws")
        self.retry_count = retry_count
        self.retry_delay = retry_delay
        self.timeout = timeout
        
        # Session for HTTP requests
        self._session = None
        self._ws = None
        self._ws_connected = False
    
    async def _get_session(self) -> aiohttp.ClientSession:
        """
        Get or create an HTTP session.
        
        Returns:
            aiohttp.ClientSession
        """
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=self.timeout))
        return self._session
    
    async def _request(
        self, 
        method: str, 
        endpoint: str, 
        **kwargs
    ) -> Any:
        """
        Make an HTTP request to the Rhetor API with retries.
        
        Args:
            method: HTTP method
            endpoint: API endpoint (without base URL)
            **kwargs: Additional arguments for the request
            
        Returns:
            Response data
            
        Raises:
            Exception: If the request fails after retries
        """
        session = await self._get_session()
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        
        for attempt in range(self.retry_count):
            try:
                async with session.request(method, url, **kwargs) as response:
                    if response.status >= 400:
                        text = await response.text()
                        logger.error(f"Rhetor API error: {response.status} - {text}")
                        raise Exception(f"Rhetor API error: {response.status} - {text}")
                    
                    return await response.json()
                    
            except asyncio.TimeoutError:
                logger.warning(f"Request to Rhetor API timed out (attempt {attempt + 1}/{self.retry_count})")
                
            except Exception as e:
                logger.warning(f"Error in request to Rhetor API (attempt {attempt + 1}/{self.retry_count}): {e}")
                
            # Last attempt failed
            if attempt == self.retry_count - 1:
                logger.error(f"Request to Rhetor API failed after {self.retry_count} attempts")
                raise
                
            # Wait before retrying
            await asyncio.sleep(self.retry_delay)
    
    async def get_active_sessions(self) -> List[Dict[str, Any]]:
        """
        Get information about all active LLM sessions from Rhetor.
        
        Returns:
            List of session information dictionaries
        """
        try:
            response = await self._request("GET", "/contexts")
            return response.get("contexts", [])
        except Exception as e:
            logger.error(f"Error getting active sessions from Rhetor: {e}")
            return []
    
    async def get_session_metrics(self, context_id: str) -> Dict[str, Any]:
        """
        Get detailed metrics for a specific LLM session.
        
        Args:
            context_id: Context identifier
            
        Returns:
            Dictionary of session metrics
        """
        try:
            response = await self._request("GET", f"/contexts/{context_id}")
            return response
        except Exception as e:
            logger.error(f"Error getting session metrics for {context_id}: {e}")
            return {}
    
    async def compress_context(
        self, 
        context_id: str,
        level: str = "moderate",
        max_tokens: Optional[int] = None
    ) -> bool:
        """
        Request context compression for an LLM session.
        
        Args:
            context_id: Context identifier
            level: Compression level (light, moderate, aggressive)
            max_tokens: Maximum tokens to retain after compression
            
        Returns:
            True if the request was successful
        """
        try:
            data = {
                "operation": "compress",
                "context_id": context_id,
                "parameters": {
                    "level": level
                }
            }
            
            if max_tokens is not None:
                data["parameters"]["max_tokens"] = max_tokens
                
            response = await self._request("POST", "/contexts/operations", json=data)
            return response.get("success", False)
            
        except Exception as e:
            logger.error(f"Error requesting context compression for {context_id}: {e}")
            return False
    
    async def reset_context(self, context_id: str) -> bool:
        """
        Request a context reset for an LLM session.
        
        Args:
            context_id: Context identifier
            
        Returns:
            True if the request was successful
        """
        try:
            data = {
                "operation": "reset",
                "context_id": context_id,
                "parameters": {}
            }
            
            response = await self._request("POST", "/contexts/operations", json=data)
            return response.get("success", False)
            
        except Exception as e:
            logger.error(f"Error requesting context reset for {context_id}: {e}")
            return False
    
    async def inject_system_message(
        self, 
        context_id: str,
        message: str,
        priority: int = 5
    ) -> bool:
        """
        Inject a system message into an LLM context.
        
        Args:
            context_id: Context identifier
            message: System message to inject
            priority: Message priority (0-10)
            
        Returns:
            True if the request was successful
        """
        try:
            data = {
                "operation": "inject_system_message",
                "context_id": context_id,
                "parameters": {
                    "message": message,
                    "priority": priority
                }
            }
            
            response = await self._request("POST", "/contexts/operations", json=data)
            return response.get("success", False)
            
        except Exception as e:
            logger.error(f"Error injecting system message for {context_id}: {e}")
            return False
    
    async def connect_websocket(self) -> bool:
        """
        Connect to the Rhetor WebSocket for real-time updates.
        
        Returns:
            True if connection was successful
        """
        if self._ws_connected:
            return True
            
        try:
            session = await self._get_session()
            self._ws = await session.ws_connect(self.ws_url)
            self._ws_connected = True
            
            # Send registration message
            await self._ws.send_json({
                "type": "REGISTER",
                "source": "APOLLO"
            })
            
            logger.info("Connected to Rhetor WebSocket")
            return True
            
        except Exception as e:
            logger.error(f"Error connecting to Rhetor WebSocket: {e}")
            self._ws_connected = False
            return False
    
    async def disconnect_websocket(self):
        """Disconnect from the Rhetor WebSocket."""
        if not self._ws_connected or self._ws is None:
            return
            
        try:
            await self._ws.close()
        except Exception as e:
            logger.error(f"Error disconnecting from Rhetor WebSocket: {e}")
        finally:
            self._ws_connected = False
            self._ws = None
    
    async def subscribe_to_context_updates(
        self, 
        context_id: Optional[str] = None,
        callback = None
    ):
        """
        Subscribe to real-time context updates via WebSocket.
        
        Args:
            context_id: Optional context ID to filter updates
            callback: Callback function for updates
            
        Note: This is a placeholder for future implementation.
        """
        # This would be implemented in a future version
        pass
        
    async def close(self):
        """Close all connections."""
        await self.disconnect_websocket()
        
        if self._session and not self._session.closed:
            await self._session.close()