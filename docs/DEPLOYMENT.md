# 部署说明

## 本机 Docker Compose

1. 复制环境变量：

```bash
cp .env.example .env
```

2. 修改 `.env`：

- `SECRET_KEY` 必须替换为长随机字符串。
- `AUTH_REQUIRED=1` 建议生产开启。
- `CORS_ALLOW_ORIGINS` 改成实际域名。
- `POSTGRES_PASSWORD` 和 `DATABASE_URL` 里的密码必须保持一致。
- 如果宿主机 80 端口已被占用，把 `HTTP_PORT` 改成 `8080` 或其他空闲端口。
- `MAX_UPLOAD_BYTES` 按机器磁盘和业务需求调整。
- 如使用阿里云 OSS，配置 `ALIYUN_OSS_*`，AccessKey 只放在部署环境变量里。

3. 启动：

```bash
docker-compose up -d --build
```

4. 打开：

```text
http://127.0.0.1
```

后台管理页地址是 `/admin`，用于配置接口、新增用户和删除用户。注册入口已关闭，普通用户账号由管理员创建；创建“房产中介”角色后，该账号工作台会把前两个模块合并为房产文案生成模块。

应用容器仍会暴露 `PORT`，Nginx 使用 `HTTP_PORT` 对外提供反向代理入口。
如果设置了 `HTTP_PORT=8080`，访问地址就是 `http://127.0.0.1:8080`。API 直连地址仍是 `http://127.0.0.1:8010`。

## 发布前验证

```bash
.venv/bin/pytest -q
.venv/bin/python -m compileall api_server.py api_clients.py pipeline scripts tests
npm --prefix app_ui run build
```

Docker Compose 配置验证：

```bash
cp .env.example .env
docker-compose config
rm .env
```

## 数据持久化

Compose 使用以下 volume：

- `cosy_postgres`：PostgreSQL 数据库，保存用户、任务、上传记录、音色记录和接口配置。
- `cosy_storage`：服务配置兼容备份和兼容本地 SQLite 回落文件。
- `cosy_outputs`：音频、视频、字幕输出。
- `cosy_voices`：本地音色录音和兼容 JSON 元数据；音色名称、归属、OSS key 等结构化信息会写入数据库。
- `cosy_redis`：Celery broker / result backend 数据。

Docker 部署会在 `app` 和 `worker` 容器启动时执行 `alembic upgrade head`，自动创建或升级 PostgreSQL 表结构。未设置 `DATABASE_URL` 的本地开发模式会回落到 SQLite。

## 当前队列说明

生产部署推荐使用 Redis/Celery：

```bash
JOB_RUNNER_BACKEND=celery
REDIS_URL=redis://redis:6379/0
CELERY_BROKER_URL=redis://redis:6379/0
CELERY_RESULT_BACKEND=redis://redis:6379/0
CELERY_WORKER_CONCURRENCY=2
CELERY_WORKER_PREFETCH_MULTIPLIER=1
```

Compose 会启动 `app`、`worker` 和 `redis`。`app` 只创建任务、写入数据库并投递队列；`worker` 从 Redis 取任务，根据任务数据库里的 payload 执行 ASR、改写、TTS、剪辑、口型同步和 OSS 上传。开发环境没有 Redis 时，可以设置 `JOB_RUNNER_BACKEND=local` 继续使用本地线程池，`JOB_MAX_WORKERS` 控制本地并发数。

## 当前对象存储说明

对象存储是可选能力。未配置时，上传和输出文件仍在应用 volume 中；配置阿里云 OSS 后，以下文件会自动补传到 OSS：

- 上传视频素材。
- 上传提取文案的原始媒体文件。
- 导入的本地音色音频和对应 JSON 元数据；音色记录同时入库。
- TTS 输出音频。
- 视频剪辑输出 MP4 和字幕 SRT。
- 口型同步输出 MP4。

推荐 `.env` 配置：

```bash
OBJECT_STORAGE_PROVIDER=aliyun_oss
ALIYUN_OSS_ENDPOINT=https://oss-cn-shanghai.aliyuncs.com
ALIYUN_OSS_BUCKET=letwx
ALIYUN_OSS_ACCESS_KEY_ID=
ALIYUN_OSS_ACCESS_KEY_SECRET=
ALIYUN_OSS_PREFIX=cosyvoice
ALIYUN_OSS_SIGNED_URL_TTL=3600
ALIYUN_OSS_PUBLIC_BASE_URL=
```

`ALIYUN_OSS_PUBLIC_BASE_URL` 留空时，后端会生成临时签名 URL；如果 bucket 前面有 CDN 或公开读域名，可填对应 base URL。不要把 AccessKey 写入 Git、README、镜像层或前端代码。若密钥曾经通过聊天、日志或截图暴露，建议在阿里云控制台轮换 AccessKey。

已有本地媒体文件可执行补传：

```bash
OBJECT_STORAGE_PROVIDER=aliyun_oss \
ALIYUN_OSS_ENDPOINT=https://oss-cn-shanghai.aliyuncs.com \
ALIYUN_OSS_BUCKET=letwx \
ALIYUN_OSS_ACCESS_KEY_ID=你的AccessKeyId \
ALIYUN_OSS_ACCESS_KEY_SECRET=你的AccessKeySecret \
python scripts/upload_to_aliyun_oss.py
```

先预览不上传：

```bash
python scripts/upload_to_aliyun_oss.py --dry-run
```

## 备份

本机目录部署可以执行：

```bash
chmod +x scripts/backup_storage.sh
./scripts/backup_storage.sh
```

脚本会打包 `backend/storage`、`outputs`、`voices` 到 `backups/`。Docker volume 部署时，建议在宿主机使用 volume 级备份或把 volume 挂载到固定宿主目录后再执行备份。

## 迁移说明

代码和运行数据分开迁移：

- 代码：复制项目目录，但不要把 `.env`、真实 `backend/storage/service_config.json`、SQLite 文件和密钥文件提交到代码仓库。
- 运行配置：接口配置和 API Key 以数据库 `service_configs` 表为准；旧 `backend/storage/service_config.json` 会自动迁入数据库，迁入后不再继续写 JSON 备份。
- Docker 数据：当前 Docker Compose 使用 named volumes，PostgreSQL 数据在 `cosy_postgres`，音色音频在 `cosy_voices`，上传文件在 `cosy_storage`。只复制代码不会带走这些 volume。
- 配置样例：`backend/storage/service_config.example.json` 只放无密钥示例，可用于新环境参考。

迁移到新服务器时，推荐流程：

```bash
# 旧机器备份运行数据
./scripts/backup_storage.sh

# 新机器部署代码后恢复运行数据
tar -xzf backups/cosyvoice_backup_YYYYmmdd_HHMMSS.tar.gz -C /opt/cosyvoice
```

如果是 Docker named volume 生产部署，还需要额外备份/恢复 PostgreSQL。接口配置在 `service_configs` 表，音色名称和归属在 `voices` 表，音色音频文件仍需从 `cosy_voices` 或 OSS 恢复：

```bash
docker-compose exec -T postgres pg_dump -U cosyvoice -d cosyvoice > cosyvoice.sql
docker-compose exec -T postgres psql -U cosyvoice -d cosyvoice < cosyvoice.sql
```

## 管理接口

- `GET /api/v1/job-runner`：查看任务执行器状态。
- `GET /api/v1/admin/users`：查看用户。
- `POST /api/v1/admin/users`：新增用户。
- `DELETE /api/v1/admin/users/{user_id}`：删除用户。
- `GET /api/v1/admin/tasks`：查看任务。
- `GET /api/v1/admin/usage`：查看用量汇总。
- `GET /api/v1/admin/storage`：查看本地存储和 OSS 配置状态。
- `GET /api/v1/admin/service-configs`：查看接口配置。
- `PUT /api/v1/admin/service-configs`：保存接口配置。

以上接口需要管理员 token。
