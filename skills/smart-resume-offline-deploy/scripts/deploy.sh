#!/usr/bin/env bash
set -Eeuo pipefail

SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PACKAGE_DIR="$(cd "$SKILL_DIR/.." && pwd)"
cd "$PACKAGE_DIR"

PROJECT_NAME="${COMPOSE_PROJECT_NAME:-smart-resume-filter}"
ENV_FILE="${ENV_FILE:-.env}"
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.yml}"
IMAGE_TAR="${IMAGE_TAR:-smart-resume-filter-images-amd64.tar}"

compose() {
  docker compose --project-name "$PROJECT_NAME" --env-file "$ENV_FILE" -f "$COMPOSE_FILE" "$@"
}

choose() {
  local title="$1"
  shift
  local answer index=1 option
  printf '\n[%s]\n' "$title"
  for option in "$@"; do
    printf '%d. %s\n' "$index" "$option"
    ((index++))
  done
  while true; do
    read -r -p "请选择 [1-$#]: " answer || { echo "已取消。"; exit 0; }
    if [[ "$answer" =~ ^[1-9][0-9]*$ ]] && (( answer >= 1 && answer <= $# )); then
      MENU_CHOICE="$answer"
      return
    fi
    echo "仅接受菜单中的编号。"
  done
}

require_value() {
  local key="$1"
  local value
  value="$(sed -n "s/^${key}=//p" "$ENV_FILE" | tail -n 1)"
  [[ -n "$value" && "$value" != change-me* && "$value" != *"你的服务器"* ]] || {
    echo "请先在 ${ENV_FILE} 设置有效的 ${key}。"
    exit 1
  }
}

[[ -f "$COMPOSE_FILE" ]] || { echo "缺少 ${COMPOSE_FILE}。"; exit 1; }
[[ -f "$IMAGE_TAR" ]] || { echo "缺少 ${IMAGE_TAR}。"; exit 1; }
command -v docker >/dev/null || { echo "未找到 docker。"; exit 1; }
docker compose version >/dev/null || { echo "未找到 Docker Compose v2。"; exit 1; }

case "$(uname -m)" in
  x86_64|amd64) ;;
  *) echo "当前 CPU 架构为 $(uname -m)，本离线包仅支持 amd64。"; exit 1 ;;
esac

if [[ ! -f "$ENV_FILE" ]]; then
  choose "未找到环境文件" "创建 .env 模板并退出" "取消"
  [[ "$MENU_CHOICE" == "1" ]] || { echo "已取消，未执行 Docker 变更。"; exit 0; }
  cp .env.example "$ENV_FILE"
  echo "已创建 ${ENV_FILE}。请编辑必填项后重新执行本脚本。"
  exit 0
fi

require_value DJANGO_SECRET_KEY
require_value DJANGO_ALLOWED_HOSTS
require_value POSTGRES_PASSWORD

echo "即将部署项目：${PROJECT_NAME}"
echo "- 导入镜像：${IMAGE_TAR}"
echo "- 使用环境文件：${ENV_FILE}（不会显示其中的密钥）"
echo "- 首次初始化会执行迁移和基础权限数据写入"

if [[ -n "$(compose ps -aq 2>/dev/null || true)" ]]; then
  choose "检测到已有部署" "升级服务并保留数据库和上传文件卷" "仅查看当前服务状态" "取消"
  case "$MENU_CHOICE" in
    1) ;;
    2) compose ps; exit 0 ;;
    3) echo "已取消，未执行 Docker 变更。"; exit 0 ;;
  esac
fi
choose "开始部署" "导入镜像、初始化并启动服务" "取消"
[[ "$MENU_CHOICE" == "1" ]] || { echo "已取消，未执行 Docker 变更。"; exit 0; }

if command -v sha256sum >/dev/null && [[ -f SHA256SUMS ]]; then
  sha256sum -c SHA256SUMS
fi

docker load -i "$IMAGE_TAR"
compose config --images
compose --profile init run --rm init
compose up -d --wait --wait-timeout 180
bash "$SKILL_DIR/scripts/verify.sh"

echo "部署完成。前端地址为：http://服务器IP:${FRONTEND_PORT:-5173}"
