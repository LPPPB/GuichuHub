# 云无关部署

本基线适用于任意 Ubuntu/Debian 主机。云厂商只负责 VM、DNS、防火墙和可选监控；应用不调用云 API。

## 主机布局

将 Git 检出放在 `/srv/kichu/app`，运行态放在检出目录外：

```text
/srv/kichu/config/production.env
/srv/kichu/secrets/write_token
/srv/kichu/data/{db,auth,state,private}
/srv/kichu/logs
/srv/kichu/backups
```

安装 Docker Engine 与 Compose plugin，创建上述目录，并让运行 Docker 的服务账户能读取 `config`、`secrets`，以及读写 `data`、`logs`、`backups`。密钥文件应仅允许其所有者读取。

防火墙与安全组只允许 22、80、443；API、Frontend、Worker、SQLite 均不开放主机端口。DNS 在部署前指向该主机，Caddy 使用 `KICHU_DOMAIN` 自动处理 TLS。

## 首次部署与更新

```bash
git clone <chosen-remote> /srv/kichu/app
cd /srv/kichu/app
git checkout <verified-tag>
cp config/production.example.env /srv/kichu/config/production.env
# 在仓库外填写 production.env，并创建 /srv/kichu/secrets/write_token
docker compose --env-file /srv/kichu/config/production.env -f compose.prod.yml build
docker compose --env-file /srv/kichu/config/production.env -f compose.prod.yml up -d
curl --fail https://<domain>/api/health
```

更新顺序是：测试、提交、创建并推送 tag、服务器检出 tag、创建备份、构建、启动、健康检查。远程仓库和访问模型由部署者选择；本基线不假定任何托管平台。

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
