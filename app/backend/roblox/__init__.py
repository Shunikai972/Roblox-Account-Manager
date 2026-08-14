"""Public Roblox metadata, OAuth identity linking, and safe local launching."""

from .auth_tools import RobloxAuthTools
from .batch_launcher import BatchLauncher
from .background import RobloxBackgroundManager
from .authenticated_browser import AuthenticatedBrowserService
from .client import RobloxClient, SessionRobloxClient
from .client_settings import ClientSettingsPatcher
from .launcher import WindowsRobloxLauncher
from .multi_instance import WindowsMultiInstanceController
from .server_region import (
    RegionLookupSettings,
    RequestsRegionTransport,
    ServerRegionResolver,
)
from .oauth import (
    OAuthClientConfiguration,
    OAuthConfigurationError,
    OAuthFlowError,
    OAuthGrant,
    OAuthGrantVault,
    OAuthIdentity,
    OAuthLoginCompletion,
    OAuthLoginCoordinator,
    OAuthLoginSnapshot,
    OAuthLoopbackCallbackServer,
    RobloxOAuthClient,
)
from .types import (
    AuthenticatedUser,
    LaunchResult,
    LaunchTarget,
    PresenceState,
    PublicUserProfile,
    PublicUsernameResolution,
    ServerPage,
    ServerSortOrder,
    UserPresence,
)
from .uwp import UwpLaunchResult, UwpRobloxPackage, WindowsUwpRobloxManager

__all__ = [
    "AuthenticatedUser",
    "BatchLauncher",
    "ClientSettingsPatcher",
    "RobloxAuthTools",
    "RobloxBackgroundManager",
    "AuthenticatedBrowserService",
    "LaunchResult",
    "LaunchTarget",
    "OAuthClientConfiguration",
    "OAuthConfigurationError",
    "OAuthFlowError",
    "OAuthGrant",
    "OAuthGrantVault",
    "OAuthIdentity",
    "OAuthLoginCompletion",
    "OAuthLoginCoordinator",
    "OAuthLoginSnapshot",
    "OAuthLoopbackCallbackServer",
    "PresenceState",
    "PublicUserProfile",
    "PublicUsernameResolution",
    "RegionLookupSettings",
    "RequestsRegionTransport",
    "RobloxClient",
    "RobloxOAuthClient",
    "ServerPage",
    "ServerRegionResolver",
    "ServerSortOrder",
    "SessionRobloxClient",
    "WindowsMultiInstanceController",
    "WindowsRobloxLauncher",
    "WindowsUwpRobloxManager",
    "UwpLaunchResult",
    "UwpRobloxPackage",
    "UserPresence",
]
