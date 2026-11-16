#!/usr/bin/env bash
# Build the API image from api/Dockerfile and ship it as a new Cloud Run revision.
#
# The tag is the git SHA, so a deployed revision can always be traced back to a commit, and two
# builds of the same commit collide instead of piling up. Re-running this is the whole update
# procedure: Cloud Run creates a new revision and moves traffic to it only once it is healthy, and
# the previous revision stays available for `gcloud run services update-traffic`.
set -euo pipefail

PROJECT="${PROJECT:-zenith-squad-2026}"
REGION="${REGION:-us-central1}"
SERVICE="${SERVICE:-spherex-api}"

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO"

if ! git diff --quiet || ! git diff --cached --quiet; then
  echo "warning: uncommitted changes are being deployed" >&2
fi

TAG="$(git rev-parse --short HEAD)"
IMAGE="$REGION-docker.pkg.dev/$PROJECT/api/api:$TAG"

echo "==> building $IMAGE"
gcloud builds submit --config scripts/cloudbuild.yaml --substitutions="_IMAGE=$IMAGE" . --quiet

echo "==> deploying $SERVICE in $REGION"
gcloud run deploy "$SERVICE" \
  --image "$IMAGE" \
  --region "$REGION" \
  --allow-unauthenticated \
  --port 8080 \
  --memory 4Gi --cpu 1 --concurrency 4 --timeout 600 \
  --max-instances 1 \
  --no-cpu-throttling \
  --env-vars-file scripts/api.env.yaml \
  --quiet

echo "==> $SERVICE is live"
gcloud run services describe "$SERVICE" --region "$REGION" --format='value(status.url)'
