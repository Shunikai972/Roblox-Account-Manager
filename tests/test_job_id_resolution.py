"""Regression tests for safe Roblox server Job ID handling."""

from types import SimpleNamespace

import pytest

from app.backend.core.errors import ValidationError
from app.backend.services.application_service import ApplicationService


FULL_JOB_ID = "043de6fd-f85b-43d7-b3cf-2a521c9b0501"
PLACE_ID = 107778070777162


class _Repository:
    def get_setting(self, key):
        assert key == "fleet.server_history"
        return []


def _service(*, instances=(), events=()):
    service = ApplicationService.__new__(ApplicationService)
    service.monitor = SimpleNamespace(current_instances=lambda: tuple(instances))
    service._log_runtime = SimpleNamespace(history=lambda: tuple(events))
    service.repository = _Repository()
    return service


def test_unique_job_id_fragment_expands_from_active_instance() -> None:
    instance = SimpleNamespace(job_id=FULL_JOB_ID, place_id=PLACE_ID)
    service = _service(instances=[instance])

    assert service._resolve_job_id_reference("f85b-43d7", PLACE_ID) == FULL_JOB_ID


def test_unique_job_id_fragment_expands_from_recent_player_log() -> None:
    event = SimpleNamespace(job_id=FULL_JOB_ID, place_id=PLACE_ID)
    service = _service(events=[event])

    assert service._resolve_job_id_reference("f85b-43d7", PLACE_ID) == FULL_JOB_ID


def test_unknown_job_id_fragment_is_rejected_before_roblox_opens() -> None:
    service = _service()

    with pytest.raises(ValidationError, match="only part"):
        service._resolve_job_id_reference("f85b-43d7", PLACE_ID)


def test_full_job_id_is_accepted_without_local_history() -> None:
    service = _service()

    assert service._resolve_job_id_reference(FULL_JOB_ID, PLACE_ID) == FULL_JOB_ID
