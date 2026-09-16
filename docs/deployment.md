# 云无关部署

本基线适用于任意 Ubuntu/Debian 主机。云厂商只负责 VM、DNS、防火墙和可选监控；应用不调用云 API。

## 主机布局

将 Git 检出放在 `/srv/kichu/app`，运行态放在检出目录外：

```text
/srv/kichu/config/production.env
/srv/kichu/secrets/write_token
/srv/kichu/postgres
/srv/kichu/private
/srv/kichu/logs
/srv/kichu/backups
```

安装 Docker Engine 与 Compose plugin 后，先创建目录。API、Worker 与备份镜像固定以 UID/GID `10001` 运行，因此这些可写 bind mount 必须由该 UID/GID 拥有；仅让 Docker 命令执行者有权限并不足够：

```bash
sudo install -d -m 0750 /srv/kichu/config
sudo install -d -m 0700 /srv/kichu/secrets
sudo install -d -m 0700 /srv/kichu/postgres
sudo install -d -o 10001 -g 10001 -m 0750 \
  /srv/kichu/private /srv/kichu/logs /srv/kichu/backups
sudo install -m 0600 -o root -g root /dev/null /srv/kichu/secrets/write_token
```

在仓库外填写 `production.env`，并以安全方式写入 `write_token`。`production.env` 应只对部署操作员可读；`write_token` 保持 `root:root`、`0600`，由 Docker daemon 读取并挂载为容器 secret，**不要**为此将宿主机密钥文件改为 UID `10001`。运行 Docker 的操作员仍需能调用 Docker Compose。

防火墙与安全组只允许 22、80、443；API、Frontend、Worker、PostgreSQL 均不开放生产主机端口。DNS 在部署前指向该主机，Caddy 使用 `KICHU_DOMAIN` 自动处理 TLS。

## 首次部署与更新

```bash
git clone <chosen-remote> /srv/kichu/app
cd /srv/kichu/app
git checkout <verified-tag>
cp config/production.example.env /srv/kichu/config/production.env
# 在仓库外填写 production.env，并创建 /srv/kichu/secrets/write_token
docker compose --env-file /srv/kichu/config/production.env -f compose.prod.yml build
docker compose --env-file /srv/kichu/config/production.env -f compose.prod.yml up -d postgres
docker compose --env-file /srv/kichu/config/production.env -f compose.prod.yml --profile maintenance run --rm migrate
docker compose --env-file /srv/kichu/config/production.env -f compose.prod.yml up -d
curl --fail https://<domain>/api/health/ready
```

更新顺序是：测试、提交、创建并推送 tag、服务器检出 tag、创建 PostgreSQL 备份、构建、停止写入、运行 migration、启动、readiness/heartbeat 检查。首次数据切换请遵循 [PostgreSQL 切换 Runbook](postgresql-cutover.md)。远程仓库和访问模型由部署者选择；本基线不假定任何托管平台。

## 定时备份

仓库提供可选的 systemd timer，而不是绑定任何云厂商的定时任务。复制 `ops/systemd/kichiku-backup.service` 和 `ops/systemd/kichiku-backup.timer` 到 `/etc/systemd/system/` 后执行：

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now kichiku-backup.timer
systemctl list-timers kichiku-backup.timer
```

该单元固定使用 `/srv/kichu/app` 与 `/srv/kichu/config/production.env`，每天调用一次 Compose 的维护备份服务。若主机目录不同，请在安装前修改单元文件；不要在应用代码中加入云平台路径或 SDK。

## 回滚

代码回滚只能检出上一个已验证 tag 并重新构建/启动。先保留当前日志和备份，绝不自动回滚数据库；数据库恢复只能按恢复演练中明确确认的步骤执行。
