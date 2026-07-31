"""Runtime feature profiles for deliberately scoped application releases."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping

from lys_bbb.registration_runtime import ANTSPYX_BACKEND


FEATURE_PROFILE_ENVIRONMENT_VARIABLE = "LYS_IRM_FEATURE_PROFILE"
FULL_FEATURE_PROFILE = "full"


@dataclass(frozen=True, slots=True)
class AppFeatures:
    """Features that a particular application distribution is allowed to expose."""

    profile: str
    atlas_mapping: bool
    ants_backend: str = ANTSPYX_BACKEND
    window_title_suffix: str = ""
    runtime_notice: str = ""


FULL_FEATURES = AppFeatures(
    profile=FULL_FEATURE_PROFILE,
    # Atlas mapping is deliberately not product-exposed. No currently tested
    # atlas method has sufficient validated regional accuracy.
    atlas_mapping=False,
)


def features_for_profile(profile: str) -> AppFeatures:
    """Resolve a named release profile or fail before exposing the wrong workflow."""

    normalised = profile.strip().casefold()
    if normalised in {"", FULL_FEATURE_PROFILE}:
        return FULL_FEATURES
    raise ValueError(f"Unknown LYS IRM feature profile: {profile!r}")


def active_features(environ: Mapping[str, str] | None = None) -> AppFeatures:
    """Resolve the active profile from the process environment."""

    source = os.environ if environ is None else environ
    return features_for_profile(
        source.get(FEATURE_PROFILE_ENVIRONMENT_VARIABLE, FULL_FEATURE_PROFILE)
    )
