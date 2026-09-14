# 鬼畜热度看板 V3

V3 是一个单仓库的 React/Vite + Flask + SQLite 应用。生产环境由 Caddy、Frontend、API 与 Worker 组成；只有 Caddy 对外提供 80/443。

代码仓库只保存源码、测试、配置模板和部署定义。真实配置、密钥、SQLite 数据、Cookie、日志与备份必须保存在检出目录之外。

## 本地开发

从仓库根目录运行：

```powershell
docker compose -f compose.dev.yml up --build
```

开发 Compose 仅绑定本机回环地址，且将运行态放在被忽略的 `runtime/dev`。`config/development.example.env` 仅供直接运行后端进程时复制到被忽略的本地 `.env`；Compose 开发模式不读取它。运行路径和完整说明见 [部署指南](docs/deployment.md)、[备份与恢复](docs/backup-restore.md) 和 [安全边界](docs/security.md)。

## 发布原则

发布使用经过验证的 Git tag。服务器检出该 tag、先创建 SQLite 一致性备份，再用 Compose 重建服务；不要上传整个本地项目，也不要把 V2 运行数据提交到 Git。
