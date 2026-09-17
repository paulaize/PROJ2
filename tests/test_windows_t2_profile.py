"""A Windows model restriction must survive old studies and direct action calls."""

from pathlib import Path

import pytest

from lys_bbb_app.domain.errors import StudyStateError
from lys_bbb_app.features import FULL_FEATURES, T2_FEATURES, active_features
from lys_bbb_app.services.study_service import StudyService


def test_t2_profile_is_explicit_and_does_not_change_mac_development() -> None:
    assert active_features({}) is FULL_FEATURES
    assert FULL_FEATURES.t1_brain_mask
    assert active_features({"LYS_IRM_FEATURE_PROFILE": "t2-only"}) is T2_FEATURES
    assert not T2_FEATURES.t1_brain_mask
    assert not T2_FEATURES.atlas_mapping


def test_t2_service_rejects_t1_before_loading_any_model(monkeypatch) -> None:
    monkeypatch.setenv("LYS_IRM_FEATURE_PROFILE", "t2-only")

    def unexpected(*args, **kwargs):
        pytest.fail("The disabled T1 model must not be validated or executed")

    service = StudyService(t1_release_validator=unexpected, t1_brain_mask_runner=unexpected)
    with pytest.raises(StudyStateError, match="unavailable in this edition"):
        service.register_t1_brain_mask_release(Path("old-study-model"), actor="QA")
    with pytest.raises(StudyStateError, match="unavailable in this edition"):
        service.t1_brain_mask_readiness(("existing-subject",))
    with pytest.raises(StudyStateError, match="unavailable in this edition"):
        service.run_t1_brain_mask_generation(actor="QA", subject_ids=("existing-subject",))
