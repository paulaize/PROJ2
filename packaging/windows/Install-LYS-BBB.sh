#!/usr/bin/env bash
set -Eeuo pipefail

readonly PAYLOAD_DIRECTORY="${1:?app payload directory is required}"
readonly WINDOWS_PROFILE_DIRECTORY="${2:?Windows profile directory is required}"
readonly SKIP_T1_MODEL="${3:-0}"
readonly INSTALL_ROOT="/opt/lys-bbb"
readonly MINIFORGE_DIRECTORY="${INSTALL_ROOT}/miniforge"
readonly ENVIRONMENT_DIRECTORY="${INSTALL_ROOT}/env"
readonly APPLICATION_DIRECTORY="${INSTALL_ROOT}/app"
readonly SHARE_DIRECTORY="${INSTALL_ROOT}/share"
readonly APP_USER="lysbbb"
readonly APP_USER_DIRECTORY="/home/${APP_USER}"
readonly MINIFORGE_VERSION="26.1.1-3"
readonly MINIFORGE_SHA256="b25b828b702df4dd2a6d24d4eb56cfa912471dd8e3342cde2c3d86fe3dc2d870"
readonly ITKSNAP_ARCHIVE="itksnap-4.4.0-20250909-Linux-x86_64.tar.gz"
readonly ITKSNAP_SHA256="10524c143d329c197a6ce05ac112dcd5686f9c0d4b3b985c2287c02de923948c"
readonly ITKSNAP_DIRECTORY="/opt/itksnap-4.4.0-20250909-Linux-x86_64"

temporary_directory=""
staged_application=""

cleanup() {
    if [[ -n "${temporary_directory}" && -d "${temporary_directory}" ]]; then
        rm -rf -- "${temporary_directory}"
    fi
    if [[ -n "${staged_application}" && -d "${staged_application}" ]]; then
        rm -rf -- "${staged_application}"
    fi
}
trap cleanup EXIT

step() {
    printf '\n==> %s\n' "$1"
}

if [[ "$(id -u)" -ne 0 ]]; then
    printf 'This installer must run as root inside WSL.\n' >&2
    exit 1
fi
if [[ ! -d "${PAYLOAD_DIRECTORY}/src" || ! -f "${PAYLOAD_DIRECTORY}/pyproject.toml" ]]; then
    printf 'Incomplete application payload: %s\n' "${PAYLOAD_DIRECTORY}" >&2
    exit 1
fi

step "Ubuntu runtime libraries"
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install --yes --no-install-recommends \
    ca-certificates \
    curl \
    dbus-x11 \
    fontconfig \
    git \
    libdbus-1-3 \
    libegl1 \
    libfontconfig1 \
    libfreetype6 \
    libgl1 \
    libglib2.0-0 \
    libopengl0 \
    libx11-6 \
    libxcb-cursor0 \
    libxcb-icccm4 \
    libxcb-image0 \
    libxcb-keysyms1 \
    libxcb-randr0 \
    libxcb-render-util0 \
    libxcb-shape0 \
    libxcb-xfixes0 \
    libxcb-xinerama0 \
    libxcb1 \
    libxext6 \
    libxi6 \
    libxkbcommon-x11-0 \
    libxrender1

if ! id "${APP_USER}" >/dev/null 2>&1; then
    useradd --create-home --shell /bin/bash "${APP_USER}"
fi
install -d -o "${APP_USER}" -g "${APP_USER}" "${APP_USER_DIRECTORY}/.local/share"
if [[ -d "${WINDOWS_PROFILE_DIRECTORY}/Downloads" && ! -e "${APP_USER_DIRECTORY}/Downloads" ]]; then
    ln -s "${WINDOWS_PROFILE_DIRECTORY}/Downloads" "${APP_USER_DIRECTORY}/Downloads"
    chown -h "${APP_USER}:${APP_USER}" "${APP_USER_DIRECTORY}/Downloads"
fi

step "Pinned Miniforge ${MINIFORGE_VERSION}"
temporary_directory="$(mktemp -d)"
if [[ ! -x "${MINIFORGE_DIRECTORY}/bin/conda" ]]; then
    miniforge_installer="${temporary_directory}/Miniforge3-${MINIFORGE_VERSION}-Linux-x86_64.sh"
    curl --fail --location --show-error \
        --output "${miniforge_installer}" \
        "https://github.com/conda-forge/miniforge/releases/download/${MINIFORGE_VERSION}/Miniforge3-${MINIFORGE_VERSION}-Linux-x86_64.sh"
    printf '%s  %s\n' "${MINIFORGE_SHA256}" "${miniforge_installer}" | sha256sum --check -
    bash "${miniforge_installer}" -b -p "${MINIFORGE_DIRECTORY}"
fi

step "Application dependencies and CPU-only ML runtime"
staged_application="$(mktemp -d "${INSTALL_ROOT}/.app-new-XXXXXX")"
cp -a "${PAYLOAD_DIRECTORY}/." "${staged_application}/"
environment_file="${staged_application}/packaging/windows/environment-wsl.yml"
if [[ -x "${ENVIRONMENT_DIRECTORY}/bin/python" ]]; then
    "${MINIFORGE_DIRECTORY}/bin/conda" env update \
        --prefix "${ENVIRONMENT_DIRECTORY}" \
        --file "${environment_file}" \
        --prune
else
    "${MINIFORGE_DIRECTORY}/bin/conda" env create \
        --prefix "${ENVIRONMENT_DIRECTORY}" \
        --file "${environment_file}"
fi

previous_application=""
if [[ -d "${APPLICATION_DIRECTORY}" ]]; then
    previous_application="${INSTALL_ROOT}/app.previous.$(date -u +%Y%m%dT%H%M%SZ)"
    mv "${APPLICATION_DIRECTORY}" "${previous_application}"
fi
mv "${staged_application}" "${APPLICATION_DIRECTORY}"
staged_application=""
chmod -R a+rX "${APPLICATION_DIRECTORY}"
if ! "${ENVIRONMENT_DIRECTORY}/bin/python" -m pip install \
    --no-deps \
    --editable "${APPLICATION_DIRECTORY}"; then
    rm -rf -- "${APPLICATION_DIRECTORY}"
    if [[ -n "${previous_application}" ]]; then
        mv "${previous_application}" "${APPLICATION_DIRECTORY}"
    fi
    exit 1
fi

step "Pinned ITK-SNAP 4.4.0"
if [[ ! -x "${ITKSNAP_DIRECTORY}/bin/itksnap" ]]; then
    itksnap_path="${temporary_directory}/${ITKSNAP_ARCHIVE}"
    curl --fail --location --show-error \
        --output "${itksnap_path}" \
        "https://downloads.sourceforge.net/project/itk-snap/itk-snap/4.4.0/${ITKSNAP_ARCHIVE}"
    printf '%s  %s\n' "${ITKSNAP_SHA256}" "${itksnap_path}" | sha256sum --check -
    tar -xzf "${itksnap_path}" -C /opt
fi
ln -sfn "${ITKSNAP_DIRECTORY}" /opt/itksnap
ln -sfn /opt/itksnap/bin/itksnap /usr/local/bin/itksnap

install -d "${SHARE_DIRECTORY}"
bundle_icon="$(dirname "$0")/lys-bbb.ico"
if [[ -f "${bundle_icon}" ]]; then
    install -m 0644 "${bundle_icon}" "${SHARE_DIRECTORY}/lys-bbb.ico"
fi

if [[ "${SKIP_T1_MODEL}" != "1" ]]; then
    step "Reviewed T1 brain-mask model"
    t1_model_directory="${APP_USER_DIRECTORY}/.local/share/lys-bbb/models/rs2net-m-seam-v1"
    if [[ ! -d "${t1_model_directory}" ]]; then
        install -d -o "${APP_USER}" -g "${APP_USER}" "$(dirname "${t1_model_directory}")"
        if ! runuser -u "${APP_USER}" -- \
            "${ENVIRONMENT_DIRECTORY}/bin/python" \
            -m lys_bbb.t1_brain_mask_setup_cli \
            --destination "${t1_model_directory}"; then
            printf '\nWARNING: T1 model download failed. The app is installed; retry with\n'
            printf '  /opt/lys-bbb/env/bin/lys-bbb-t1-mask-setup --destination %s\n' \
                "${t1_model_directory}"
        fi
    fi
fi

step "Installation smoke test"
"${ENVIRONMENT_DIRECTORY}/bin/antsRegistration" --version 2>&1 | grep -F "ANTs Version: 2.6.5"
runuser -u "${APP_USER}" -- \
    env QT_QPA_PLATFORM=offscreen \
    "${ENVIRONMENT_DIRECTORY}/bin/python" \
    -c "from PySide6.QtCore import QTimer; from PySide6.QtWidgets import QApplication; from lys_bbb_app.ui.main_window import MainWindow; app=QApplication([]); window=MainWindow(); window.show(); QTimer.singleShot(100, app.quit); raise SystemExit(app.exec())"

printf '\nLYS BBB installation completed successfully.\n'
