# syntax=docker/dockerfile:1.4

############################################################################
# Change/Verify these values when adopting this Dockerfile into another org:
#   GH_ORG, GHCR_ORG, IMAGE_NAMESPACE,
#   EWTS_ORG, EWTS_REF, MSW_MGR_ORG, MSW_MGR_REF
############################################################################

# Ownership / branding overrides
ARG GH_ORG=NGWPC
ARG GHCR_ORG=ngwpc
ARG IMAGE_NAMESPACE=ngwpc

# External repository sources (org and ref/branch overrides)
ARG EWTS_ORG=${GH_ORG}
ARG EWTS_REF=development
ARG MSW_MGR_ORG=${GH_ORG}
ARG MSW_MGR_REF=development
ARG NWM_EVAL_ORG=${GH_ORG}
ARG NWM_EVAL_REF=development

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
ARG MSW_MGR_ORG
ARG MSW_MGR_REF
ARG EVAL_MGR_ORG
ARG EVAL_MGR_REF
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
ARG EVAL_MGR_REVISION="unknown"

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
    io.${IMAGE_NAMESPACE}.msw.mgr.revision="${MSW_MGR_REVISION}" \
    io.${IMAGE_NAMESPACE}.nwm.eval.org="${EVAL_MGR_ORG}" \
    io.${IMAGE_NAMESPACE}.nwm.eval.ref="${EVAL_MGR_REF}" \
    io.${IMAGE_NAMESPACE}.nwm.eval.revision="${EVAL_MGR_REVISION}"

COPY . /ngen-app/nwm-cal-mgr/

COPY ./docker/run-nwm-cal-mgr.sh /ngen-app/bin/

WORKDIR /ngen-app/

RUN set -eux; \
    chmod +x /ngen-app/bin/run-nwm-cal-mgr.sh

# Re-expose the Python virtual environment inherited from ngen.
# The dependency image creates the venv and the unversioned `python` symlink.
# ngen-bmi-forcing and ngen install their Python packages into that venv.
# cal-mgr should reuse it rather than recreating it.
ENV VIRTUAL_ENV="/ngen-app/ngen-python" \
    PATH="${VIRTUAL_ENV}/bin:${PATH}" \
    PYTHONPATH="${VIRTUAL_ENV}/lib/python3.11/site-packages:/usr/local/lib64/python3.11/site-packages:${PYTHONPATH}"

# Install numpy, netcdf4, hydrotools events, and nwis-client
RUN --mount=type=cache,target=/root/.cache/pip,id=pip-cache-rocky \
    python -m pip install --upgrade pip && \
    python -m pip install "numpy==1.26.4" "netcdf4<=1.6.3" && \
    python -m pip install "hydrotools.events==1.1.5" "hydrotools.nwis-client==3.3.1"

WORKDIR /ngen-app/
# MSW_MGR_CACHE_BUST = nwm-msw-mgr commit SHA from CI; a new commit busts this layer so mswm is reinstalled from the requested ref, not a stale cache.
ARG MSW_MGR_CACHE_BUST=1
RUN set -eux; \
    echo "Calib cache bust: ${CALIB_CACHE_BUST}" && \
    # install nwm-cal-mgr packages (common, calib, config)
    python -m pip install /ngen-app/nwm-cal-mgr && \
    # Install mswm package
    python -m pip install mswm@git+https://github.com/${MSW_MGR_ORG}/nwm-msw-mgr.git@${MSW_MGR_REF} ; \
    # Install nwm_metrics package
    python -m pip install nwm_metrics@git+https://github.com/${NWM_EVAL_ORG}/nwm-eval-mgr.git@${NWM_EVAL_REF}#subdirectory=nwm_metrics ; \
    python -m pip cache purge && \
    rm --force /root/.gitconfig

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

ENTRYPOINT [ "/ngen-app/bin/run-nwm-cal-mgr.sh" ]
