#!/usr/bin/env bash
set -Eeuo pipefail

SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PACKAGE_DIR="$(cd "$SKILL_DIR/.." && pwd)"
cd "$PACKAGE_DIR"

PROJECT_NAME="${COMPOSE_PROJECT_NAME:-smart-resume-filter}"
ENV_FILE="${ENV_FILE:-.env}"
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.yml}"

[[ -f "$ENV_FILE" ]] || { echo "缺少 ${ENV_FILE}。"; exit 1; }

compose() {
  docker compose --project-name "$PROJECT_NAME" --env-file "$ENV_FILE" -f "$COMPOSE_FILE" "$@"
}

compose ps
compose exec -T backend python manage.py check
compose exec -T frontend nginx -t
echo "部署验证通过。"
