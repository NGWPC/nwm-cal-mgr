#!/bin/bash
set -euo pipefail

IMAGE_NAME="nwm-cal-mgr"
TAG="latest"

# Defaults (match Dockerfile defaults)
GH_ORG="${GH_ORG:-NGWPC}"
GHCR_ORG="${GHCR_ORG:-ngwpc}"
IMAGE_NAMESPACE="${IMAGE_NAMESPACE:-ngwpc}"

EWTS_ORG="${EWTS_ORG:-$GH_ORG}"
EWTS_REF="${EWTS_REF:-development}"

MSW_MGR_ORG="${MSW_MGR_ORG:-$GH_ORG}"
MSW_MGR_REF="${MSW_MGR_REF:-development}"

EVAL_MGR_ORG="${EVAL_MGR_ORG:-$GH_ORG}"
EVAL_MGR_REF="${EVAL_MGR_REF:-development}"

NGEN_IMAGE="${NGEN_IMAGE:-ghcr.io/${GHCR_ORG}/ngen:latest}"

# Optional common ref for EWTS / MSW / EVAL
REF=""

usage() {
  cat <<EOF
Usage:
  $0 [options]

Options:
  --tag TAG                Docker image tag (default: latest)

  --gh-org ORG             GitHub org (default: NGWPC)
  --ghcr-org ORG           GHCR org (default: ngwpc)
  --image-namespace NS     OCI label namespace (default: ngwpc)

  --ref REF                Common ref to use for EWTS, MSW, and EVAL
                           unless overridden by a repo-specific --*-ref

  --ewts-org ORG           EWTS repo org (default: GH_ORG)
  --ewts-ref REF           EWTS branch/tag/sha (default: development, or --ref if provided)

  --msw-org ORG            MSW repo org (default: GH_ORG)
  --msw-ref REF            MSW branch/tag/sha (default: development, or --ref if provided)

  --eval-org ORG           Eval repo org (default: GH_ORG)
  --eval-ref REF           Eval branch/tag/sha (default: development, or --ref if provided)

  --ngen-image IMAGE       Base ngen image (default: ghcr.io/<ghcr-org>/ngen:latest)

Examples:
  $0
  $0 --tag v1.0.0
  $0 --ref development
  $0 --ref v1.2.0
  $0 --ref feature-x --eval-ref hotfix-branch
  $0 --gh-org NGWPC --ngen-image ghcr.io/ngwpc/ngen:development
EOF
}

# Track whether repo-specific refs were explicitly set
EWTS_REF_SET=0
MSW_MGR_REF_SET=0
EVAL_MGR_REF_SET=0

# Parse args
while [[ $# -gt 0 ]]; do
  case "$1" in
    --tag) TAG="$2"; shift 2;;

    --gh-org) GH_ORG="$2"; shift 2;;
    --ghcr-org) GHCR_ORG="$2"; shift 2;;
    --image-namespace) IMAGE_NAMESPACE="$2"; shift 2;;

    --ref) REF="$2"; shift 2;;

    --ewts-org) EWTS_ORG="$2"; shift 2;;
    --ewts-ref) EWTS_REF="$2"; EWTS_REF_SET=1; shift 2;;

    --msw-org) MSW_MGR_ORG="$2"; shift 2;;
    --msw-ref) MSW_MGR_REF="$2"; MSW_MGR_REF_SET=1; shift 2;;

    --eval-org) EVAL_MGR_ORG="$2"; shift 2;;
    --eval-ref) EVAL_MGR_REF="$2"; EVAL_MGR_REF_SET=1; shift 2;;

    --ngen-image) NGEN_IMAGE="$2"; shift 2;;

    -h|--help) usage; exit 0;;

    *)
      echo "Unknown option: $1"
      usage
      exit 1
      ;;
  esac
done

# Apply common REF only to repos that did not get an explicit repo-specific ref
if [[ -n "$REF" ]]; then
  [[ $EWTS_REF_SET -eq 0 ]] && EWTS_REF="$REF"
  [[ $MSW_MGR_REF_SET -eq 0 ]] && MSW_MGR_REF="$REF"
  [[ $EVAL_MGR_REF_SET -eq 0 ]] && EVAL_MGR_REF="$REF"
fi

# Git metadata
echo "[build] collecting git metadata..."

IMAGE_SOURCE=$(git config --get remote.origin.url || echo "unknown")
IMAGE_REVISION=$(git rev-parse HEAD)
IMAGE_BRANCH=$( [ -n "${CI_COMMIT_REF_NAME:-}" ] && echo "${CI_COMMIT_REF_NAME}" || git rev-parse --abbrev-ref HEAD )
IMAGE_AUTHOR=$(git log -1 --pretty=format:'%an')
IMAGE_COMMIT_DATE=$(date -u -d @$(git log -1 --pretty=format:'%ct') +'%Y-%m-%d %H:%M:%S UTC')
IMAGE_COMMIT_MESSAGE=$(git log -1 --pretty=format:'%s' | tr '\n' ' ')
IMAGE_TAGS=$(git tag --points-at HEAD | tr '\n' ' ')

# Build
echo "[build] building image ${IMAGE_NAME}:${TAG}"
echo "[build] refs: EWTS=${EWTS_REF}, MSW=${MSW_MGR_REF}, EVAL=${EVAL_MGR_REF}"

docker build \
  -t "${IMAGE_NAME}:${TAG}" \
  \
  --build-arg GH_ORG="${GH_ORG}" \
  --build-arg GHCR_ORG="${GHCR_ORG}" \
  --build-arg IMAGE_NAMESPACE="${IMAGE_NAMESPACE}" \
  \
  --build-arg EWTS_ORG="${EWTS_ORG}" \
  --build-arg EWTS_REF="${EWTS_REF}" \
  \
  --build-arg MSW_MGR_ORG="${MSW_MGR_ORG}" \
  --build-arg MSW_MGR_REF="${MSW_MGR_REF}" \
  \
  --build-arg EVAL_MGR_ORG="${EVAL_MGR_ORG}" \
  --build-arg EVAL_MGR_REF="${EVAL_MGR_REF}" \
  \
  --build-arg NGEN_IMAGE="${NGEN_IMAGE}" \
  \
  --build-arg IMAGE_SOURCE="${IMAGE_SOURCE}" \
  --build-arg IMAGE_REVISION="${IMAGE_REVISION}" \
  --build-arg IMAGE_BRANCH="${IMAGE_BRANCH}" \
  --build-arg IMAGE_AUTHOR="${IMAGE_AUTHOR}" \
  --build-arg IMAGE_COMMIT_DATE="${IMAGE_COMMIT_DATE}" \
  --build-arg IMAGE_COMMIT_MESSAGE="${IMAGE_COMMIT_MESSAGE}" \
  --build-arg IMAGE_TAGS="${IMAGE_TAGS}" \
  \
  .