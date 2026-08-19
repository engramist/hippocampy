"""Hermes Agent Adapter for Campy memory integration.

Hermes is an AI agent orchestration framework. This adapter provides
Hermes with persistent memory capabilities via the Campy MCP server.
"""
from typing import Optional, Dict, Any, Callable
import logging

logger = logging.getLogger(__name__)


class HermesAdapter:
    """Adapter for integrating Campy memory with Hermes agents."""
    
    def __init__(
        self,
        memory_url: str = "http://127.0.0.1:7799",
        async_client_factory: Optional[Callable[[], Any]] = None,
    ):
        """
        Initialize the Hermes adapter.
        
        Args:
            memory_url: URL of the Campy Brain Daemon (default: localhost:7799)
        """
        self.memory_url = memory_url
        self.name = "hermes-campy"
        self.version = "0.1.0"
        self._session_id = None
        self._async_client_factory = async_client_factory

    def _make_async_client(self):
        if self._async_client_factory is not None:
            return self._async_client_factory()
        import httpx

        return httpx.AsyncClient()
    
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
            url = f"{self.memory_url}/api/v1/recall"
            params = {"q": query, "scope": scope, "session_id": self._session_id}

            async with self._make_async_client() as client:
                resp = await client.get(url, params=params)
                if resp.status_code == 200:
                    data = resp.json()
                    return data.get("data")
                else:
                    logger.warning(f"Memory recall failed: {resp.status_code}")
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
            url = f"{self.memory_url}/api/v1/decide"
            payload = {"query": query, "session_id": self._session_id}

            async with self._make_async_client() as client:
                resp = await client.post(url, json=payload)
                if resp.status_code == 200:
                    data = resp.json()
                    return data.get("data")
                else:
                    logger.warning(f"Memory decision failed: {resp.status_code}")
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
            url = f"{self.memory_url}/api/v1/notify"
            payload = {
                "role": role,
                "content": content,
                "session_id": self._session_id,
            }

            async with self._make_async_client() as client:
                resp = await client.post(url, json=payload)
                return resp.status_code == 200
        except Exception as e:
            logger.error(f"Error notifying memory: {e}")
            return False

    async def session_recall(
        self, task_description: str, token_budget: int = 32000, agent_type: str = "generic"
    ) -> Optional[Dict[str, Any]]:
        """
        Retrieve a compiled context bundle (decisions, constraints, tabular data,
        summaries) for a broad or multi-entity task - the compile_context-backed
        counterpart to recall()'s single-fact current_truth lookup.

        Args:
            task_description: What the agent is about to work on
            token_budget: Max tokens the bundle should target
            agent_type: Output formatting hint (e.g. "generic", "claude_code")

        Returns:
            Compiled context bundle or None if failed
        """
        try:
            url = f"{self.memory_url}/api/v1/bundle"
            payload = {
                "query": task_description,
                "token_budget": token_budget,
                "agent_type": agent_type,
            }

            async with self._make_async_client() as client:
                resp = await client.post(url, json=payload)
                if resp.status_code == 200:
                    data = resp.json()
                    return data.get("data")
                else:
                    logger.warning(f"session_recall failed: {resp.status_code}")
                    return None
        except Exception as e:
            logger.error(f"Error in session_recall: {e}")
            return None

    async def spawn_context(
        self, parent_session_id: str, task_description: str, token_budget: int = 8000
    ) -> Optional[Dict[str, Any]]:
        """
        Get a task-scoped context bundle for a Hermes-spawned sub-agent. Same
        compile_context backing as session_recall(), but a smaller default
        token budget since spawned agents work a narrower slice of the task.

        Args:
            parent_session_id: Session ID of the Hermes agent doing the spawning
            task_description: What the spawned agent is being asked to do
            token_budget: Max tokens the bundle should target

        Returns:
            Compiled context bundle or None if failed
        """
        return await self.session_recall(
            task_description, token_budget=token_budget, agent_type="spawned"
        )

    async def capture_turn(
        self, role: str, content: str, session_id: Optional[str] = None
    ) -> bool:
        """
        Forward a message exchange to memory, like notify(), with an optional
        per-call session_id override that does not persist past this call.

        Args:
            role: Message role (user | assistant | system)
            content: Message content
            session_id: Session to attribute this turn to; defaults to the
                adapter's configured session when omitted

        Returns:
            True if notification succeeded
        """
        if session_id is None:
            return await self.notify(role, content)

        prior_session_id = self._session_id
        self._session_id = session_id
        try:
            return await self.notify(role, content)
        finally:
            self._session_id = prior_session_id
    
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
