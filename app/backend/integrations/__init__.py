"""Optional local desktop integrations."""

from .discord_rpc import DiscordPresenceManager, DiscordRpcError

__all__ = ["DiscordPresenceManager", "DiscordRpcError"]
