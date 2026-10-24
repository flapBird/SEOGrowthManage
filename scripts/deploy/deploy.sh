#!/usr/bin/env bash
# 服务器端一键更新：git pull → 重建并启动容器 → 健康检查（失败自动回滚）→ 清理旧镜像。
# GitHub Actions 的 SSH 部署和服务器 cron 轮询共用本脚本；重复执行是安全的
# （没有新提交时直接退出，不会重复重建）。
set -euo pipefail
cd "$(dirname "$0")/.."  # 仓库根目录

BRANCH="${DEPLOY_BRANCH:-main}"
BEFORE=$(git rev-parse HEAD)

git fetch origin "$BRANCH"
LOCAL=$(git rev-parse HEAD)
REMOTE=$(git rev-parse "origin/$BRANCH")
if [ "$LOCAL" = "$REMOTE" ]; then
  echo "[deploy] $(date '+%F %T') 已是最新 ($LOCAL)，无需更新"
  exit 0
fi

echo "[deploy] $(date '+%F %T') 发现新提交：$BEFORE → $REMOTE，开始更新"
git pull --ff-only origin "$BRANCH"
docker compose up -d --build

# 健康检查：默认用 .env 里的 APP_DOMAIN 探测登录页；也可用 DEPLOY_HEALTHCHECK_URL 覆盖
URL="${DEPLOY_HEALTHCHECK_URL:-}"
if [ -z "$URL" ] && [ -f .env ]; then
  APP_DOMAIN=$(grep -E '^APP_DOMAIN=' .env | head -1 | cut -d= -f2- | tr -d '"'"'"'')
  [ -n "$APP_DOMAIN" ] && URL="https://$APP_DOMAIN/login"
fi
if [ -n "$URL" ]; then
  ok=0
  for i in 1 2 3 4 5; do
    sleep 5
    if curl -fsS -m 10 "$URL" >/dev/null 2>&1; then
      echo "[deploy] 健康检查通过：$URL"
      ok=1
      break
    fi
    echo "[deploy] 健康检查第 $i 次未通过，等待重试"
  done
  if [ "$ok" != "1" ]; then
    echo "[deploy] 健康检查连续失败，回滚到 $BEFORE"
    git reset --hard "$BEFORE"
    docker compose up -d --build
    exit 1
  fi
fi

docker image prune -f >/dev/null 2>&1 || true
echo "[deploy] 完成：$BEFORE → $(git rev-parse HEAD)"
