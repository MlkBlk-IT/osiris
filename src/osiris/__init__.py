"""OSIRIS — context engine cache-aware pour agents IA.

Serveur MCP standard, local-first, independant de tout provider.
"""

from osiris.config import settings

__version__ = settings.version
__all__ = ["settings", "__version__"]
