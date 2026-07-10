#!/usr/bin/env bash
set -Eeuo pipefail

SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PACKAGE_DIR="$(cd "$SKILL_DIR/.." && pwd)"
cd "$PACKAGE_DIR"

PROJECT_NAME="${COMPOSE_PROJECT_NAME:-smart-resume-filter}"
ENV_FILE="${ENV_FILE:-.env}"
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.yml}"

[[ -f "$ENV_FILE" ]] || { echo "缺少 $ENV_FILE，无法确认目标部署。"; exit 1; }

compose() {
  docker compose --project-name "$PROJECT_NAME" --env-file "$ENV_FILE" -f "$COMPOSE_FILE" "$@"
}

confirm_yes() {
  local prompt="$1"
  local answer
  read -r -p "$prompt 输入 yes 继续: " answer
  [[ "$answer" == "yes" ]] || { echo "已取消，未执行卸载。"; exit 0; }
}

confirm_phrase() {
  local prompt="$1"
  local phrase="$2"
  local answer
  read -r -p "$prompt 输入 ${phrase} 确认: " answer
  [[ "$answer" == "$phrase" ]] || { echo "未确认，跳过此清理项。"; return 1; }
}

echo "目标项目：$PROJECT_NAME"
compose ps -a || true
echo "默认操作：删除容器和网络，保留 PostgreSQL 数据卷与上传文件卷。"
confirm_yes "确认执行常规卸载"
compose down --remove-orphans
echo "常规卸载完成，业务数据已保留。"

if confirm_phrase "是否永久删除数据库和上传文件卷？此操作不可恢复。" DELETE_DATA; then
  compose down --volumes --remove-orphans
  echo "数据卷已删除。"
fi

if confirm_phrase "是否删除本项目 Docker 镜像？再次部署需要重新 docker load。" REMOVE_IMAGES; then
  mapfile -t images < <(compose config --images)
  if [[ "${#images[@]}" -gt 0 ]]; then
    docker image rm "${images[@]}" || echo "部分镜像仍被其它容器使用，未能删除。"
  fi
fi

echo "卸载流程结束。"
