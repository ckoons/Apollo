"""
Apollo Manager Module.

This module provides a high-level manager that coordinates the Context Observer,
Predictive Engine, and Action Planner components. It integrates their functionality
and provides a simplified interface for the Apollo API.
"""

import os
import json
import logging
import asyncio
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Union, Callable

from apollo.models.context import (
    ContextState,
    ContextPrediction,
    ContextAction,
    ContextHealth
)
from apollo.core.context_observer import ContextObserver
from apollo.core.predictive_engine import PredictiveEngine
from apollo.core.action_planner import ActionPlanner
from apollo.core.interfaces.rhetor import RhetorInterface

# Configure logging
logger = logging.getLogger(__name__)


class ApolloManager:
    """
    High-level manager for Apollo components.
    
    This class coordinates the Context Observer, Predictive Engine, and Action
    Planner components, providing a simplified interface for the Apollo API.
    """
    
    def __init__(
        self,
        rhetor_interface: Optional[RhetorInterface] = None,
        data_dir: Optional[str] = None,
        enable_predictive: bool = True,
        enable_actions: bool = True
    ):
        """
        Initialize the Apollo Manager.
        
        Args:
            rhetor_interface: Interface for communicating with Rhetor
            data_dir: Root directory for storing data
            enable_predictive: Whether to enable the predictive engine
            enable_actions: Whether to enable the action planner
        """
        # Set up data directory
        self.data_dir = data_dir or os.path.expanduser("~/.tekton/apollo")
        os.makedirs(self.data_dir, exist_ok=True)
        
        # Sub-directories for component data
        context_data_dir = os.path.join(self.data_dir, "context_data")
        prediction_data_dir = os.path.join(self.data_dir, "prediction_data")
        action_data_dir = os.path.join(self.data_dir, "action_data")
        
        # Create rhetor interface if not provided
        self.rhetor_interface = rhetor_interface or RhetorInterface()
        
        # Initialize components
        self.context_observer = ContextObserver(
            rhetor_interface=self.rhetor_interface,
            data_dir=context_data_dir
        )
        
        self.predictive_engine = PredictiveEngine(
            context_observer=self.context_observer,
            data_dir=prediction_data_dir
        ) if enable_predictive else None
        
        self.action_planner = ActionPlanner(
            context_observer=self.context_observer,
            predictive_engine=self.predictive_engine,
            data_dir=action_data_dir
        ) if enable_actions else None
        
        # For task management
        self.is_running = False
        
        # Set up component connections
        self._connect_components()
    
    def _connect_components(self):
        """Set up connections between components."""
        # Connect context observer to predictive engine
        if self.context_observer and self.predictive_engine:
            # Register callbacks for health changes
            self.context_observer.register_callback(
                "on_health_change",
                self._on_context_health_change
            )
        
        # Connect predictive engine to action planner
        if self.predictive_engine and self.action_planner:
            # No specific callbacks needed currently
            pass
    
    async def _on_context_health_change(self, context_state: ContextState, previous_health: ContextHealth):
        """
        Handle context health change events.
        
        Args:
            context_state: Current context state
            previous_health: Previous health status
        """
        # If health degraded significantly, trigger immediate prediction and action planning
        if (previous_health in [ContextHealth.EXCELLENT, ContextHealth.GOOD] and 
            context_state.health in [ContextHealth.POOR, ContextHealth.CRITICAL]):
            
            logger.info(f"Context {context_state.context_id} health degraded from {previous_health} to {context_state.health}")
            
            # Immediate action planning happens in action planner's own loop
            pass
    
    async def start(self):
        """Start all Apollo components."""
        if self.is_running:
            logger.warning("Apollo Manager is already running")
            return
            
        self.is_running = True
        
        # Start context observer
        await self.context_observer.start()
        
        # Start predictive engine if enabled
        if self.predictive_engine:
            await self.predictive_engine.start()
            
        # Start action planner if enabled
        if self.action_planner:
            await self.action_planner.start()
            
        logger.info("Apollo Manager started")
    
    async def stop(self):
        """Stop all Apollo components."""
        if not self.is_running:
            logger.warning("Apollo Manager is not running")
            return
            
        self.is_running = False
        
        # Stop components in reverse order
        if self.action_planner:
            await self.action_planner.stop()
            
        if self.predictive_engine:
            await self.predictive_engine.stop()
            
        await self.context_observer.stop()
        
        logger.info("Apollo Manager stopped")
    
    # Context Observer Proxy Methods
    
    def get_context_state(self, context_id: str) -> Optional[ContextState]:
        """
        Get the current state of a context.
        
        Args:
            context_id: Context identifier
            
        Returns:
            ContextState or None if not found
        """
        return self.context_observer.get_context_state(context_id)
    
    def get_all_context_states(self) -> List[ContextState]:
        """
        Get states for all active contexts.
        
        Returns:
            List of ContextState objects
        """
        return self.context_observer.get_all_context_states()
    
    def get_context_history(self, context_id: str, limit: int = None) -> List[Any]:
        """
        Get history for a specific context.
        
        Args:
            context_id: Context identifier
            limit: Maximum number of records to return
            
        Returns:
            List of context history records
        """
        return self.context_observer.get_context_history(context_id, limit)
    
    def get_health_distribution(self) -> Dict[ContextHealth, int]:
        """
        Get distribution of context health across all active contexts.
        
        Returns:
            Dictionary mapping health status to count
        """
        return self.context_observer.get_health_distribution()
    
    def get_critical_contexts(self) -> List[ContextState]:
        """
        Get contexts with critical health status.
        
        Returns:
            List of ContextState objects with critical health
        """
        return self.context_observer.get_critical_contexts()
    
    async def suggest_action(self, context_id: str) -> Optional[ContextAction]:
        """
        Suggest an action for a context based on its health.
        
        Args:
            context_id: Context identifier
            
        Returns:
            Suggested ContextAction or None
        """
        return await self.context_observer.suggest_action(context_id)
    
    # Predictive Engine Proxy Methods
    
    def get_prediction(self, context_id: str) -> Optional[ContextPrediction]:
        """
        Get the latest prediction for a specific context.
        
        Args:
            context_id: Context identifier
            
        Returns:
            Latest prediction or None if no predictions exist
        """
        if not self.predictive_engine:
            return None
            
        return self.predictive_engine.get_prediction(context_id)
    
    def get_all_predictions(self) -> Dict[str, ContextPrediction]:
        """
        Get the latest prediction for all contexts.
        
        Returns:
            Dictionary mapping context IDs to their latest predictions
        """
        if not self.predictive_engine:
            return {}
            
        return self.predictive_engine.get_all_predictions()
    
    def get_predictions_by_health(self, health: ContextHealth) -> List[ContextPrediction]:
        """
        Get all predictions with a specific predicted health status.
        
        Args:
            health: Health status to filter by
            
        Returns:
            List of predictions with the specified health status
        """
        if not self.predictive_engine:
            return []
            
        return self.predictive_engine.get_predictions_by_health(health)
    
    def get_critical_predictions(self) -> List[ContextPrediction]:
        """
        Get predictions that indicate critical future issues.
        
        Returns:
            List of predictions with critical health status
        """
        if not self.predictive_engine:
            return []
            
        return self.predictive_engine.get_critical_predictions()
    
    # Action Planner Proxy Methods
    
    def get_actions(self, context_id: str) -> List[ContextAction]:
        """
        Get all actions for a specific context.
        
        Args:
            context_id: Context identifier
            
        Returns:
            List of actions for the context
        """
        if not self.action_planner:
            return []
            
        return self.action_planner.get_actions(context_id)
    
    def get_highest_priority_action(self, context_id: str) -> Optional[ContextAction]:
        """
        Get the highest priority action for a context.
        
        Args:
            context_id: Context identifier
            
        Returns:
            Highest priority action or None
        """
        if not self.action_planner:
            return None
            
        return self.action_planner.get_highest_priority_action(context_id)
    
    def get_all_actions(self) -> Dict[str, List[ContextAction]]:
        """
        Get all actions for all contexts.
        
        Returns:
            Dictionary mapping context IDs to lists of actions
        """
        if not self.action_planner:
            return {}
            
        return self.action_planner.get_all_actions()
    
    def get_critical_actions(self) -> List[ContextAction]:
        """
        Get all critical priority actions.
        
        Returns:
            List of critical actions
        """
        if not self.action_planner:
            return []
            
        return self.action_planner.get_critical_actions()
    
    def get_actionable_now(self) -> List[ContextAction]:
        """
        Get actions that should be taken now.
        
        Returns:
            List of actions that should be taken now
        """
        if not self.action_planner:
            return []
            
        return self.action_planner.get_actionable_now()
    
    async def mark_action_applied(self, action_id: str):
        """
        Mark an action as having been applied.
        
        Args:
            action_id: Action identifier
        """
        if not self.action_planner:
            return
            
        await self.action_planner.mark_action_applied(action_id)
    
    # High-Level Dashboard Methods
    
    def get_system_status(self) -> Dict[str, Any]:
        """
        Get overall system status summary.
        
        Returns:
            Dictionary with system status information
        """
        # Get context health distribution
        health_distribution = self.get_health_distribution()
        
        # Get counts
        active_contexts = len(self.get_all_context_states())
        critical_contexts = len(self.get_critical_contexts())
        
        # Predictive data
        critical_predictions = len(self.get_critical_predictions()) if self.predictive_engine else 0
        
        # Action data
        pending_actions = sum(len(actions) for actions in self.get_all_actions().values()) if self.action_planner else 0
        critical_actions = len(self.get_critical_actions()) if self.action_planner else 0
        actionable_now = len(self.get_actionable_now()) if self.action_planner else 0
        
        # Component status
        components_status = {
            "context_observer": self.context_observer.is_running,
            "predictive_engine": self.predictive_engine.is_running if self.predictive_engine else False,
            "action_planner": self.action_planner.is_running if self.action_planner else False
        }
        
        return {
            "timestamp": datetime.now(),
            "active_contexts": active_contexts,
            "health_distribution": {str(k): v for k, v in health_distribution.items()},
            "critical_contexts": critical_contexts,
            "critical_predictions": critical_predictions,
            "pending_actions": pending_actions,
            "critical_actions": critical_actions,
            "actionable_now": actionable_now,
            "components_status": components_status,
            "system_running": self.is_running
        }
    
    def get_context_dashboard(self, context_id: str) -> Dict[str, Any]:
        """
        Get comprehensive dashboard data for a specific context.
        
        Args:
            context_id: Context identifier
            
        Returns:
            Dictionary with context dashboard information
        """
        # Get current state
        state = self.get_context_state(context_id)
        if not state:
            return {"error": f"Context {context_id} not found"}
        
        # Get recent history (last 10 records)
        history = self.get_context_history(context_id, 10)
        
        # Get prediction
        prediction = self.get_prediction(context_id)
        
        # Get actions
        actions = self.get_actions(context_id)
        
        # Additional health metrics
        health_trend = "stable"
        if len(history) >= 2:
            last_score = history[-1].health_score
            prev_score = history[-2].health_score
            if last_score - prev_score > 0.1:
                health_trend = "improving"
            elif prev_score - last_score > 0.1:
                health_trend = "degrading"
        
        return {
            "timestamp": datetime.now(),
            "context_id": context_id,
            "state": state.dict() if state else None,
            "history": [h.dict() for h in history],
            "prediction": prediction.dict() if prediction else None,
            "actions": [a.dict() for a in actions],
            "health_trend": health_trend,
            "summary": {
                "health": str(state.health),
                "health_score": state.health_score,
                "token_utilization": state.metrics.token_utilization,
                "repetition_score": state.metrics.repetition_score,
                "age_minutes": (datetime.now() - state.creation_time).total_seconds() / 60.0
            }
        }