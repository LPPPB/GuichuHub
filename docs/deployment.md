# 云无关部署

本基线适用于任意 Ubuntu/Debian 主机。云厂商只负责 VM、DNS、防火墙和可选监控；应用不调用云 API。

PostgreSQL 16 是唯一运行态持久层。API/Worker 只接收各自的 PostgreSQL URL secret 以及必要的 Cookie/日志路径，不配置或挂载 SQLite、dashboard JSON、tracked-UP JSON 或应用内备份目录。首次离线导入是独立的维护操作，不是服务启动步骤。

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
sudo install -m 0640 -o root -g 10001 /dev/null /srv/kichu/secrets/write_token
```

在仓库外填写 `production.env`，并以安全方式写入 `write_token`。`production.env` 应只对部署操作员可读。文件型 Compose secret 是绑定挂载，需按读取进程设置权限：`write_token` 和四个 `*_database_url` 文件使用 `root:10001`、`0640`；四个 `postgres_*_password` 角色文件使用 `root:70`、`0640`，供 PostgreSQL 初始化进程读取；`postgres_superuser_password` 使用 `root:root`、`0600`。密钥目录本身保持 `root:root`、`0700`。不要将密钥文件所有者改为容器 UID。运行 Docker 的操作员仍需能调用 Docker Compose。

四个 `*_DATABASE_URL_FILE` 都是 Docker secret 文件路径；每个文件只能有一行、不带引号的 SQLAlchemy URL，密码必须进行 URL percent-encoding，且绝不能写入 `production.env`、日志或 Compose 命令行。按 `config/production.example.env` 中的文件名创建它们：

```text
api_database_url       = postgresql+psycopg://kichu_api:<api-password>@postgres:5432/kichu
worker_database_url    = postgresql+psycopg://kichu_worker:<worker-password>@postgres:5432/kichu
migration_database_url = postgresql+psycopg://kichu_migration:<migration-password>@postgres:5432/kichu
backup_database_url    = postgresql+psycopg://kichu_backup:<backup-password>@postgres:5432/kichu
```

API、Worker、backup 均没有 DDL 权限；只有 `kichu_migration` 执行 Alembic。角色密码放在对应的 `postgres_*_password` secret 文件中，仅供 PostgreSQL 初始化使用，URL secret 由相应服务单独挂载。

防火墙与安全组只允许 22、80、443；API、Frontend、Worker、PostgreSQL 均不开放生产主机端口。DNS 在部署前指向该主机，Caddy 使用 `KICHU_DOMAIN` 自动处理 TLS。

构建主机如果无法下载官方软件包，可在仓库外的 `production.env` 设置 `KICHU_PIP_INDEX_URL`、`KICHU_DEBIAN_MIRROR_HOST`、`KICHU_PGDG_APT_URL` 和 `KICHU_NPM_REGISTRY`。默认值仍是官方源；这些变量仅用于构建，不参与应用运行。镜像 URL 不应包含账号或密码。后端从 `uv.lock` 导出带哈希的精确依赖清单，再通过所选 PyPI 镜像安装。

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
