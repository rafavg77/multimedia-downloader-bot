#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Uso:
  ./scripts/build-and-push.sh [REPO] [TAG]

Ejemplos:
  DOCKERHUB_USER=rafavg77 ./scripts/build-and-push.sh
  ./scripts/build-and-push.sh rafavg77/collibot4fun 1.0.1
  PLATFORM=linux/amd64,linux/arm64 USE_BUILDX=1 ./scripts/build-and-push.sh rafavg77/collibot4fun 1.0.1

Variables (opcionales):
  DOCKERHUB_USER   Usuario Docker Hub (si no pasas REPO)
  DOCKER_REPO      Repo completo (override a DOCKERHUB_USER), ej: rafavg77/collibot4fun
  TAG              Tag (override si no pasas TAG)
  NO_LATEST=1      No taggear/pushear :latest
  DOCKERFILE       Ruta Dockerfile (default: ./Dockerfile)
  CONTEXT          Contexto build (default: .)
  USE_BUILDX=1     Usa docker buildx
  PLATFORM         Plataformas buildx, ej: linux/amd64,linux/arm64
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

command -v docker >/dev/null 2>&1 || { echo "Error: docker no está instalado/en PATH" >&2; exit 1; }

DOCKERFILE="${DOCKERFILE:-./Dockerfile}"
CONTEXT="${CONTEXT:-.}"

REPO="${1:-${DOCKER_REPO:-}}"
if [[ -z "$REPO" ]]; then
  if [[ -n "${DOCKERHUB_USER:-}" ]]; then
    REPO="${DOCKERHUB_USER}/collibot4fun"
  else
    echo "Error: especifica REPO (arg1) o DOCKER_REPO o DOCKERHUB_USER" >&2
    usage
    exit 2
  fi
fi

TAG="${2:-${TAG:-}}"
if [[ -z "$TAG" ]]; then
  if command -v node >/dev/null 2>&1; then
    TAG="$(node -p "require('./package.json').version" 2>/dev/null || true)"
  fi
fi
if [[ -z "$TAG" ]]; then
  echo "Error: no se pudo determinar TAG (pasa arg2 o TAG=...)" >&2
  exit 2
fi

TAGS=("${REPO}:${TAG}")
if [[ "${NO_LATEST:-0}" != "1" && "$TAG" != "latest" ]]; then
  TAGS+=("${REPO}:latest")
fi

if [[ "${USE_BUILDX:-0}" == "1" || -n "${PLATFORM:-}" ]]; then
  # buildx: construye y pushea en un solo comando
  PLATFORM_ARG=()
  if [[ -n "${PLATFORM:-}" ]]; then
    PLATFORM_ARG=(--platform "$PLATFORM")
  fi

  BUILD_TAG_ARGS=()
  for t in "${TAGS[@]}"; do
    BUILD_TAG_ARGS+=( -t "$t" )
  done

  echo "==> buildx build --push: ${TAGS[*]}"
  docker buildx build \
    --push \
    "${PLATFORM_ARG[@]}" \
    -f "$DOCKERFILE" \
    "${BUILD_TAG_ARGS[@]}" \
    "$CONTEXT"
else
  # docker build + push
  BUILD_TAG_ARGS=()
  for t in "${TAGS[@]}"; do
    BUILD_TAG_ARGS+=( -t "$t" )
  done

  echo "==> docker build: ${TAGS[*]}"
  docker build -f "$DOCKERFILE" "${BUILD_TAG_ARGS[@]}" "$CONTEXT"

  for t in "${TAGS[@]}"; do
    echo "==> docker push: $t"
    docker push "$t"
  done
fi

echo "OK: publicado ${TAGS[*]}"
