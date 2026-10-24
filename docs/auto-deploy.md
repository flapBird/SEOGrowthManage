# 自动部署：GitHub 变动自动更新服务器

两种方案二选一（都基于 `scripts/deploy/deploy.sh`：git pull → 重建容器 → 健康检查失败自动回滚 → 清理旧镜像）。
脚本重复执行是安全的：没有新提交时直接退出。

## 方案 A：GitHub Actions（推荐，push 即上线）

流程：push 到 main → GitHub 通过 SSH 登录服务器 → 执行仓库里的部署脚本。
执行日志在仓库 Actions 页可查，失败会标红。

一次性配置：

1. 服务器上生成专用密钥对（在服务器执行）：

   ```bash
   ssh-keygen -t ed25519 -f deploy_key -N "" -C "github-deploy"
   cat deploy_key.pub >> ~/.ssh/authorized_keys
   chmod 600 ~/.ssh/authorized_keys
   ```

2. 服务器确保安装了 docker / docker compose 插件，且执行用户能跑 `docker compose`
   （把用户加入 docker 组：`sudo usermod -aG docker <用户>`，重新登录生效）。
   注意：docker 组权限约等于 root，部署用户不要做他用。

3. GitHub 仓库 → Settings → Secrets and variables → Actions → New repository secret，
   添加四个：

   | Secret | 值 |
   | --- | --- |
   | `DEPLOY_HOST` | 服务器公网 IP |
   | `DEPLOY_USER` | 服务器 SSH 用户名 |
   | `DEPLOY_SSH_KEY` | `deploy_key` 私钥文件全文（含 BEGIN/END 行） |
   | `DEPLOY_DIR` | 服务器上仓库绝对路径（如 `/opt/SEOGrowthManage`） |

4. 服务器安全组/防火墙放行自己的常用出口即可（SSH 22 不对公网开放也行——
   GitHub Actions 的出口 IP 段很多，最简单的做法是 22 端口对 0.0.0.0/0 开放但
   禁用密码登录只留密钥：`/etc/ssh/sshd_config` 里 `PasswordAuthentication no`）。

5. 之后每次 `git push`（main 分支）自动部署；也可以在 Actions 页手动触发
   （workflow_dispatch）。未配置 Secrets 前该 workflow 会失败，属正常现象。

## 方案 B：服务器 cron 轮询（极简，无需给 GitHub 任何凭据）

服务器每 5 分钟自己检查一次远程仓库，有新提交才拉取重建：

```bash
crontab -e
# 加入一行（路径按实际仓库位置改）：
*/5 * * * * cd /opt/SEOGrowthManage && flock -n /tmp/seogrowth-deploy.lock bash scripts/deploy/deploy.sh >> /var/log/seogrowth-deploy.log 2>&1
```

- 仓库用 HTTPS 或 deploy key（只读 SSH key）拉取即可，服务器无需暴露任何端口。
- `flock` 防止上一轮还没跑完下一轮又启动。
- 部署日志在 `/var/log/seogrowth-deploy.log`。

## 共同说明

- **健康检查与回滚**：脚本默认用 `.env` 的 `APP_DOMAIN` 探测 `https://<域名>/login`，
  连续 5 次（约 25 秒）失败会自动 `git reset` 回上一个提交并重启容器。也可用环境变量
  `DEPLOY_HEALTHCHECK_URL` 覆盖探测地址。
- **二选一**：A 和 B 同时启用也不会出错（脚本幂等），但没必要，选一个即可。
- **国内 VPS 注意**：如果服务器在国内，`git pull` 访问 GitHub 可能超时，需要给 git
  配代理（`git config --global http.https://github.com.proxy http://127.0.0.1:7890`），
  或改用方案 B + 镜像加速。
- **数据安全**：`.env` 与 `data/` 都不在 git 里，pull 和重建不会触碰数据库与密钥。
- **手动兜底**：任何时候都可以在服务器上手动执行
  `bash scripts/deploy/deploy.sh`，与自动行为完全一致。
