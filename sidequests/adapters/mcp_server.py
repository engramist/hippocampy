"""Shim for sidequests.adapters.mcp_server -> campy.adapters.mcp_server."""
import asyncio
from campy.adapters.mcp_server import *

if __name__ == "__main__":
    from campy.adapters.mcp_server import main
    asyncio.run(main())
