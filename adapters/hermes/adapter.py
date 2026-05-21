"""Hermes Agent Adapter for Campy memory integration.

Hermes is an AI agent orchestration framework. This adapter provides
Hermes with persistent memory capabilities via the Campy MCP server.
"""
from typing import Optional, Dict, Any
import logging

logger = logging.getLogger(__name__)


class HermesAdapter:
    """Adapter for integrating Campy memory with Hermes agents."""
    
    def __init__(self, memory_url: str = "http://127.0.0.1:7799"):
        """
        Initialize the Hermes adapter.
        
        Args:
            memory_url: URL of the Campy Brain Daemon (default: localhost:7799)
        """
        self.memory_url = memory_url
        self.name = "hermes-campy"
        self.version = "0.1.0"
        self._session_id = None
    
    def configure(self, config: Dict[str, Any]) -> bool:
        """
        Configure the adapter with Hermes runtime settings.
        
        Args:
            config: Configuration dict (may include session_id, etc.)
        
        Returns:
            True if configuration succeeded
        """
        try:
            self._session_id = config.get("session_id", "hermes-default")
            logger.info(f"Hermes adapter configured with session {self._session_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to configure Hermes adapter: {e}")
            return False
    
    async def recall(self, query: str, scope: str = "both") -> Optional[Dict[str, Any]]:
        """
        Recall from memory using the query.
        
        Args:
            query: What to search for
            scope: Search scope (both | lessons | timeline)
        
        Returns:
            Memory recall result or None if failed
        """
        try:
            import aiohttp
            url = f"{self.memory_url}/api/v1/recall"
            params = {"q": query, "scope": scope, "session_id": self._session_id}
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return data.get("data")
                    else:
                        logger.warning(f"Memory recall failed: {resp.status}")
                        return None
        except Exception as e:
            logger.error(f"Error recalling memory: {e}")
            return None
    
    async def decide(self, query: str) -> Optional[Dict[str, Any]]:
        """
        Ask the memory router which tool to use.
        
        Args:
            query: Decision question
        
        Returns:
            Router recommendation or None
        """
        try:
            import aiohttp
            url = f"{self.memory_url}/api/v1/decide"
            payload = {"query": query, "session_id": self._session_id}
            
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return data.get("data")
                    else:
                        logger.warning(f"Memory decision failed: {resp.status}")
                        return None
        except Exception as e:
            logger.error(f"Error making memory decision: {e}")
            return None
    
    async def notify(self, role: str, content: str) -> bool:
        """
        Notify the memory system of a message exchange.
        
        Args:
            role: Message role (user | assistant | system)
            content: Message content
        
        Returns:
            True if notification succeeded
        """
        try:
            import aiohttp
            url = f"{self.memory_url}/api/v1/notify"
            payload = {
                "role": role,
                "content": content,
                "session_id": self._session_id,
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload) as resp:
                    return resp.status == 200
        except Exception as e:
            logger.error(f"Error notifying memory: {e}")
            return False
    
    def health_check(self) -> bool:
        """
        Check if the memory daemon is running.
        
        Returns:
            True if daemon is healthy
        """
        try:
            import requests
            resp = requests.get(f"{self.memory_url}/health", timeout=2)
            return resp.status_code == 200
        except Exception:
            return False


def get_adapter(config: Optional[Dict[str, Any]] = None) -> Optional[HermesAdapter]:
    """
    Factory function to create and configure a Hermes adapter.
    
    Args:
        config: Optional configuration dict
    
    Returns:
        Configured HermesAdapter or None if creation failed
    """
    try:
        config = config or {}
        memory_url = config.get("memory_url", "http://127.0.0.1:7799")
        adapter = HermesAdapter(memory_url=memory_url)
        
        if not adapter.configure(config):
            return None
        
        return adapter
    except Exception as e:
        logger.error(f"Failed to create Hermes adapter: {e}")
        return None
