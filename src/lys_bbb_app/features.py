"""Runtime feature profiles for deliberately scoped application releases."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping


FEATURE_PROFILE_ENVIRONMENT_VARIABLE = "LYS_BBB_FEATURE_PROFILE"
FULL_FEATURE_PROFILE = "full"
WINDOWS_NATIVE_NO_ANTS_V1_PROFILE = "windows_native_no_ants_v1"
WINDOWS_NATIVE_ANTSPYX_PREVIEW_V1_PROFILE = "windows_native_antspyx_preview_v1"


@dataclass(frozen=True, slots=True)
class AppFeatures:
    """Features that a particular application distribution is allowed to expose."""

    profile: str
    atlas_mapping: bool
    ants_backend: str = "cli"
    window_title_suffix: str = ""
    runtime_notice: str = ""


FULL_FEATURES = AppFeatures(
    profile=FULL_FEATURE_PROFILE,
    atlas_mapping=True,
)

WINDOWS_NATIVE_NO_ANTS_V1_FEATURES = AppFeatures(
    profile=WINDOWS_NATIVE_NO_ANTS_V1_PROFILE,
    atlas_mapping=False,
    ants_backend="disabled",
    window_title_suffix="Native Windows test",
    runtime_notice=(
        "NATIVE WINDOWS TEST BUILD — Atlas mapping is disabled in this version. "
        "T1 pre/post registration uses SimpleITK; native-space T1 and T2 workflows "
        "do not require ANTs, Ubuntu, or WSL2."
    ),
)

WINDOWS_NATIVE_ANTSPYX_PREVIEW_V1_FEATURES = AppFeatures(
    profile=WINDOWS_NATIVE_ANTSPYX_PREVIEW_V1_PROFILE,
    atlas_mapping=True,
    ants_backend="antspyx",
    window_title_suffix="Native Windows ANTsPyx preview",
    runtime_notice=(
        "NATIVE WINDOWS ANTSPYX PREVIEW — Registration outputs remain provisional "
        "and require the existing candidate and all-slice human reviews."
    ),
)


def features_for_profile(profile: str) -> AppFeatures:
    """Resolve a named release profile or fail before exposing the wrong workflow."""

    normalised = profile.strip().casefold()
    if normalised in {"", FULL_FEATURE_PROFILE}:
        return FULL_FEATURES
    if normalised == WINDOWS_NATIVE_NO_ANTS_V1_PROFILE:
        return WINDOWS_NATIVE_NO_ANTS_V1_FEATURES
    if normalised == WINDOWS_NATIVE_ANTSPYX_PREVIEW_V1_PROFILE:
        return WINDOWS_NATIVE_ANTSPYX_PREVIEW_V1_FEATURES
    raise ValueError(f"Unknown MRI Tool feature profile: {profile!r}")


def active_features(environ: Mapping[str, str] | None = None) -> AppFeatures:
    """Resolve the active profile from the process environment."""

    source = os.environ if environ is None else environ
    return features_for_profile(
        source.get(FEATURE_PROFILE_ENVIRONMENT_VARIABLE, FULL_FEATURE_PROFILE)
    )
