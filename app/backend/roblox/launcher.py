"""Safe local hand-off to the Windows-registered ``roblox://`` protocol."""

from __future__ import annotations

from collections.abc import Callable
import os
import platform
import re
from urllib.parse import urlencode

from app.backend.core.errors import ValidationError

from .errors import RobloxLaunchError
from .types import LaunchResult, LaunchTarget


ProtocolOpener = Callable[[str], object]
ProtocolChecker = Callable[[], bool]
_JOB_ID = re.compile(r"^[A-Za-z0-9-]{1,128}$")


class WindowsRobloxLauncher:
    """Launch a Roblox experience through Windows' registered protocol handler.

    ``os.startfile`` asks Windows to resolve the installed handler for the URI;
    it does not construct a shell command.  No executable path, binary patch,
    account secret, or remote-control channel is involved.
    """

    def __init__(
        self,
        *,
        opener: ProtocolOpener | None = None,
        platform_name: Callable[[], str] = platform.system,
        protocol_checker: ProtocolChecker | None = None,
    ) -> None:
        self._opener = opener
        self._platform_name = platform_name
        self._protocol_checker = protocol_checker or _roblox_protocol_is_registered

    def build_uri(self, target: LaunchTarget) -> str:
        """Build a strictly validated experience URI without session data."""

        if not isinstance(target, LaunchTarget):
            raise ValidationError("La cible de lancement Roblox est invalide.")
        if isinstance(target.place_id, bool) or not isinstance(target.place_id, int) or target.place_id <= 0:
            raise ValidationError("Le PlaceId doit Ãªtre un entier positif.")
        if target.job_id is not None and (
            not isinstance(target.job_id, str) or not _JOB_ID.fullmatch(target.job_id)
        ):
            raise ValidationError("Le JobId doit contenir uniquement des lettres, chiffres ou tirets.")

        parameters = {"placeId": str(target.place_id)}
        if target.job_id:
            parameters["gameInstanceId"] = target.job_id
        return f"roblox://experiences/start?{urlencode(parameters)}"

    def launch(self, target: LaunchTarget) -> LaunchResult:
        """Ask Windows to open a validated Roblox experience URI.

        A clear capability check avoids pretending that a launch succeeded on a
        non-Windows machine or one without a registered Roblox installation.
        """

        uri = self.build_uri(target)
        if self._platform_name().casefold() != "windows":
            raise RobloxLaunchError("Le lancement local Roblox est disponible uniquement sous Windows.")
        if not self._protocol_checker():
            raise RobloxLaunchError("Roblox n'est pas installÃ© ou son protocole Windows est indisponible.")

        opener = self._opener or getattr(os, "startfile", None)
        if not callable(opener):
            raise RobloxLaunchError("Windows ne peut pas ouvrir le protocole Roblox.")
        try:
            opener(uri)
        except OSError:
            raise RobloxLaunchError("Windows n'a pas pu lancer Roblox.") from None
        except Exception:
            # Third-party protocol handlers sometimes attach request details to
            # their exception text.  Keep those diagnostics out of the bridge.
            raise RobloxLaunchError("Windows n'a pas pu lancer Roblox.") from None
        return LaunchResult(uri=uri, launched=True)


def _roblox_protocol_is_registered() -> bool:
    """Return whether Windows currently advertises a ``roblox`` URI handler."""

    if platform.system().casefold() != "windows":
        return False
    try:
        import winreg  # type: ignore[import-not-found]

        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, "roblox"):
            return True
    except (ImportError, OSError):
        return False


__all__ = ["WindowsRobloxLauncher"]

