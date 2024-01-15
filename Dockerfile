ARG PYVER=3.12
ARG REPO=python

# build stage
FROM ${REPO}:${PYVER} AS builder

ARG PIP_CACHE_DIR=/var/cache/pip
# install PDM
RUN --mount=type=cache,target=${PIP_CACHE_DIR},sharing=locked \
  pip install -U pip setuptools wheel
RUN --mount=type=cache,target=${PIP_CACHE_DIR},sharing=locked \
  pip install pdm

# copy files
COPY pdm.lock pyproject.toml README.md src/ /gerrit-argo-gateway/

# install dependencies and project into the local packages directory
WORKDIR /gerrit-argo-gateway
RUN --mount=type=cache,target=${PIP_CACHE_DIR},sharing=locked \
  mkdir __pypackages__ && pdm install --prod --no-lock --no-editable

# run stage
FROM ${REPO}:${PYVER}-slim
ARG PYVER=3.12
LABEL source_repository=https://github.com/sapcc/gerrit-argo-gateway
# retrieve packages from build stage
ARG CA_CRT=https://aia.pki.co.sap.com/aia/SAPNetCA_G2.crt
ADD ${CA_CRT} /usr/local/share/ca-certificates/
SHELL ["/bin/bash", "-c"]
RUN --mount=type=cache,target=/root/.cache,sharing=locked \
    --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    <<EOF
set -euo pipefail
apt update
apt upgrade -y
pip install -U pip
update-ca-certificates
mkdir -p /root/.ssh
chmod go-rwx /root/.ssh
EOF

ENV PYTHONPATH=/gerrit-argo-gateway/pkgs
COPY --from=builder /gerrit-argo-gateway/__pypackages__/${PYVER}/lib $PYTHONPATH

# set command/entrypoint, adapt to fit your needs
CMD ["python", "-m", "gerrit_argo_gateway"]
