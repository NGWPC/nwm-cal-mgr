# syntax=docker/dockerfile:1.4

############################################################################
# Change/Verify these values when adopting this Dockerfile into another org:
#   GH_ORG, GHCR_ORG, IMAGE_NAMESPACE,
#   EWTS_ORG, EWTS_REF, MSW_MGR_ORG, MSW_MGR_REF,
#   CAL_MGR_INSTALL_EWTS, EWTS_CACHE_BUST
############################################################################

# Ownership / branding overrides
ARG GH_ORG=NGWPC
ARG GHCR_ORG=ngwpc
ARG IMAGE_NAMESPACE=ngwpc

# External repository sources (org and ref/branch overrides)
ARG EWTS_ORG=${GH_ORG}
ARG EWTS_REF=development
ARG CAL_MGR_INSTALL_EWTS=OFF
ARG EWTS_CACHE_BUST=0

ARG MSW_MGR_ORG=${GH_ORG}
ARG MSW_MGR_REF=development

############################################################################
# Image selection
############################################################################

# Use the ngen image as the base.
#
# Default build:
#   docker build -t nwm-cal-mgr .
#
# Build from a different published ngen image:
#   docker build \
#     --build-arg NGEN_IMAGE=ghcr.io/ngwpc/ngen:development \
#     -t nwm-cal-mgr .
#
# Build from a locally built ngen image:
#   docker build \
#     --build-arg NGEN_IMAGE=ngen \
#     -t nwm-cal-mgr .
ARG NGEN_IMAGE=ghcr.io/${GHCR_ORG}/ngen:latest

FROM ${NGEN_IMAGE}

# Re-expose args after FROM for the remaining build stage.
ARG GH_ORG
ARG GHCR_ORG
ARG IMAGE_NAMESPACE
ARG EWTS_ORG
ARG EWTS_REF
ARG CAL_MGR_INSTALL_EWTS
ARG EWTS_CACHE_BUST
ARG MSW_MGR_ORG
ARG MSW_MGR_REF
ARG NGEN_IMAGE

# OCI Metadata Arguments
#
# BASE_IMAGE_* refers to the ngen image this image is built FROM.
ARG BASE_IMAGE_DIGEST="unknown"
ARG BASE_IMAGE_REVISION="unknown"
ARG IMAGE_SOURCE="unknown"
ARG IMAGE_VENDOR="unknown"
ARG IMAGE_VERSION="unknown"
ARG IMAGE_REVISION="unknown"
ARG EWTS_REVISION="unknown"
ARG MSW_MGR_REVISION="unknown"

# Image Labels: OCI-spec annotations followed by custom source-repo metadata.
LABEL org.opencontainers.image.base.name="${NGEN_IMAGE}" \
      org.opencontainers.image.base.digest="${BASE_IMAGE_DIGEST}" \
      org.opencontainers.image.source="${IMAGE_SOURCE}" \
      org.opencontainers.image.vendor="${IMAGE_VENDOR}" \
      org.opencontainers.image.version="${IMAGE_VERSION}" \
      org.opencontainers.image.revision="${IMAGE_REVISION}" \
      org.opencontainers.image.title="NGEN Calibration Manager" \
      org.opencontainers.image.description="Docker image for the NGEN Calibration application" \
      io.${IMAGE_NAMESPACE}.image.base.revision="${BASE_IMAGE_REVISION}" \
      io.${IMAGE_NAMESPACE}.ewts.org="${EWTS_ORG}" \
      io.${IMAGE_NAMESPACE}.ewts.ref="${EWTS_REF}" \
      io.${IMAGE_NAMESPACE}.ewts.revision="${EWTS_REVISION}" \
      io.${IMAGE_NAMESPACE}.msw.mgr.org="${MSW_MGR_ORG}" \
      io.${IMAGE_NAMESPACE}.msw.mgr.ref="${MSW_MGR_REF}" \
      io.${IMAGE_NAMESPACE}.msw.mgr.revision="${MSW_MGR_REVISION}"

# Reuse the Python virtual environment inherited from ngen. The dependency image
# creates the venv; forcing and ngen install their Python packages into that same
# environment. Do not recreate it here.
ENV VIRTUAL_ENV="/ngen-app/ngen-python"
ENV PATH="${VIRTUAL_ENV}/bin:${PATH}"

SHELL ["/bin/bash", "-c"]

COPY . /ngen-app/nwm-cal-mgr/
COPY ./docker/run-nwm-cal-mgr.sh /ngen-app/bin/

WORKDIR /ngen-app/

RUN set -eux; \
    chmod +x /ngen-app/bin/run-nwm-cal-mgr.sh

# Optional development-only EWTS Python override.
#
# Production images should inherit EWTS from ngen. Set CAL_MGR_INSTALL_EWTS=ON
# only when testing a new EWTS Python package without rebuilding forcing/ngen.
#
# Example:
# docker build \
#   --build-arg CAL_MGR_INSTALL_EWTS=ON \
#   --build-arg EWTS_REF=my-ewts-branch \
#   --build-arg EWTS_CACHE_BUST=$(date +%s) \
#   -t nwm-cal-mgr .
RUN --mount=type=cache,target=/root/.cache/pip,id=pip-cache-bookworm \
    set -eux; \
    CAL_MGR_INSTALL_EWTS="${CAL_MGR_INSTALL_EWTS:-OFF}"; \
    echo "CAL_MGR_INSTALL_EWTS=${CAL_MGR_INSTALL_EWTS}; EWTS ref: ${EWTS_REF}; cache bust: ${EWTS_CACHE_BUST}"; \
    CAL_MGR_INSTALL_EWTS_NORMALIZED="$(echo "${CAL_MGR_INSTALL_EWTS}" | tr '[:lower:]' '[:upper:]')"; \
    if [[ "${CAL_MGR_INSTALL_EWTS_NORMALIZED}" =~ ^(ON|YES|TRUE|1)$ ]]; then \
        echo "Installing development EWTS Python override"; \
        rm -rf /tmp/nwm-ewts; \
        (git clone --depth 1 -b "${EWTS_REF}" \
            "https://github.com/${EWTS_ORG}/nwm-ewts.git" /tmp/nwm-ewts \
         || (git clone "https://github.com/${EWTS_ORG}/nwm-ewts.git" /tmp/nwm-ewts && \
             cd /tmp/nwm-ewts && git checkout "${EWTS_REF}")); \
        python -m pip install --force-reinstall --no-deps /tmp/nwm-ewts/runtime/python/ewts; \
        rm -rf /tmp/nwm-ewts; \
    else \
        echo "Using EWTS inherited from ngen"; \
    fi

# Install calibration-specific Python dependencies.
RUN --mount=type=cache,target=/root/.cache/pip,id=pip-cache-bookworm \
    set -eux; \
    python -m pip install "hydrotools.events==1.1.5" "hydrotools.nwis-client==3.3.1"

WORKDIR /ngen-app/

# MSW_MGR_CACHE_BUST is set by CI to the nwm-msw-mgr commit SHA. A new commit
# invalidates this layer so mswm is installed from the requested ref rather
# than being reused from a stale Docker layer.
ARG MSW_MGR_CACHE_BUST=1

RUN --mount=type=cache,target=/root/.cache/pip,id=pip-cache-bookworm \
    set -eux; \
    echo "MSW MGR cache bust: ${MSW_MGR_CACHE_BUST}"; \
    cd /ngen-app/nwm-cal-mgr/python/common; \
    python -m pip install .; \
    cd /ngen-app/nwm-cal-mgr/python/calib; \
    python -m pip install .; \
    python -m pip install \
        "mswm@git+https://github.com/${MSW_MGR_ORG}/nwm-msw-mgr.git@${MSW_MGR_REF}"; \
    cd /ngen-app/nwm-cal-mgr/python/config; \
    python -m pip install .

WORKDIR /ngen-app/nwm-cal-mgr

ARG CI_COMMIT_REF_NAME

RUN set -eux; \
    # Get the remote URL from Git configuration
    repo_url=$(git config --get remote.origin.url); \
    # Extract the repo name (everything after the last slash) and remove any trailing .git
    key=${repo_url##*/}; \
    key=${key%.git}; \
    # Construct the file path using the derived key
    GIT_INFO_PATH="/ngen-app/${key}_git_info.json"; \
    # Determine branch name: use CI_COMMIT_REF_NAME if set; otherwise, use git's current branch
    branch=$( [ -n "${CI_COMMIT_REF_NAME:-}" ] && echo "${CI_COMMIT_REF_NAME}" || git rev-parse --abbrev-ref HEAD ); \
    jq -n \
      --arg commit_hash "$(git rev-parse HEAD)" \
      --arg branch "$branch" \
      --arg tags "$(git tag --points-at HEAD | tr '\n' ' ')" \
      --arg author "$(git log -1 --pretty=format:'%an')" \
      --arg commit_date "$(date -u -d @$(git log -1 --pretty=format:'%ct') +'%Y-%m-%d %H:%M:%S UTC')" \
      --arg message "$(git log -1 --pretty=format:'%s' | tr '\n' ';')" \
      --arg build_date "$(date -u +'%Y-%m-%d %H:%M:%S UTC')" \
      "{\"$key\": {commit_hash: \$commit_hash, branch: \$branch, tags: \$tags, author: \$author, commit_date: \$commit_date, message: \$message, build_date: \$build_date}}" \
      > $GIT_INFO_PATH

WORKDIR /
ENTRYPOINT ["/ngen-app/bin/run-nwm-cal-mgr.sh"]
