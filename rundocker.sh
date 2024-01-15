#!/usr/bin/env bash
set -eEuo pipefail
IID="$(mktemp)" || { echo "Failed to create temp file"; exit 1; }
trap "rm -f ${IID}" EXIT

cd ${PWD}

[ -f instance/known_hosts ] || ssh-keyscan -p 29418 review.opendev.org > instance/known_host

docker build --iidfile "$IID" .
docker run \
  --env-file .env \
  --rm \
  --mount type=bind,source="${SSH_PRIVATE_KEY_PATH},target=/root/.ssh/id_ed25519" \
  --mount type=bind,source="${PWD}/instance/known_hosts,target=/root/.ssh/known_hosts" \
  -ti \
  $(cat "$IID")
