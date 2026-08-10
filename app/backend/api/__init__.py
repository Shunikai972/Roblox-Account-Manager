"""Desktop bridge and opt-in local API adapters."""

from .bridge import DesktopBridge
from .loopback import LoopbackApiError, LoopbackApiServer, LoopbackApiStatus

__all__ = ["DesktopBridge", "LoopbackApiError", "LoopbackApiServer", "LoopbackApiStatus"]
