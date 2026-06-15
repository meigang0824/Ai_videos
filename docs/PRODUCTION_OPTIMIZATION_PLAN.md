# 生产版优化实现说明书

本文档用于指导当前 `CosyVoice API Only` 从单机工具版升级为支持多用户、多任务、可部署、可运维的生产系统。

## 1. 当前系统判断

当前项目已经具备完整的短视频生成主流程：

- 文案提取：下载/上传素材后调用外部 ASR 接口。
- AI 改写：调用外部 LLM 接口。
- 语音合成：调用外部 TTS/声音克隆接口。
- 视频成片：本地 MoviePy/ffmpeg 合成。
- 口型同步：调用外部 LipSync 接口。
- 任务记录：本地 JSON 保存。
- 文件管理：本地目录保存上传、临时文件、输出文件。

但当前架构仍然是单机版，主要问题如下：

- 无用户体系，所有人共享同一套任务记录、上传文件、输出文件、接口配置。
- 任务存储使用 `backend/storage/task_store.json`，并发写入和长期数据可靠性不足。
- 上传文件、生成结果、临时文件都在本机磁盘，不适合多实例部署。
- 后台任务已支持 Redis/Celery，API 进程和 worker 进程可拆分部署。
- 接口配置是全局配置，无法支持按用户、按租户、按套餐隔离。
- 缺少权限控制、限流、审计、配额、费用统计、任务重试和失败追踪。
- 缺少生产部署规范、日志、监控、备份和清理策略。

## 2. 生产版目标

生产版应满足以下目标：

- 支持多用户注册、登录、权限隔离。
- 用户只能访问自己的任务、上传文件、音色、输出结果。
- 支持多个用户同时提交任务，任务排队执行，失败可重试。
- 文件存储可迁移到对象存储，后端服务可多实例部署。
- 外部模型接口调用可配置、可追踪、可计费、可限流。
- 管理员可以查看用户、任务、调用日志、失败原因和资源占用。
- 系统具备基本安全能力，包括鉴权、上传校验、访问控制、接口限流。
- 支持 Docker Compose 一键部署，后续可升级到云服务器或 Kubernetes。

## 3. 推荐目标架构

```text
Browser
  |
  v
Frontend React/Vite
  |
  v
API Server FastAPI
  |
  +--> PostgreSQL: users, tasks, files, configs, usage_logs
  |
  +--> Redis: queue broker, cache, rate limit
  |
  +--> Worker: ASR/LLM/TTS/LipSync/video compose job executor
  |
  +--> Object Storage: uploads, voices, outputs, temp artifacts
  |
  +--> External Model APIs: ASR, LLM, TTS, LipSync
```

## 4. 技术选型建议

### 4.1 后端

- Web 框架：继续使用 FastAPI。
- ORM：SQLAlchemy 2.x。
- 数据迁移：Alembic。
- 数据库：PostgreSQL，开发环境可临时使用 SQLite。
- 任务队列：Celery + Redis，或 RQ + Redis。生产更推荐 Celery。
- 配置管理：Pydantic Settings + `.env`。
- 鉴权：JWT Access Token + Refresh Token，或服务端 Session。
- 密码：`passlib[bcrypt]`。
- 文件存储：阿里云 OSS，未配置时保留本地文件缓存。

### 4.2 前端

- 保留现有 React/Vite。
- 增加登录页、用户菜单、任务中心、用量页面、管理员页面。
- 所有 API 请求自动携带 Token。
- 上传、任务状态、下载链接都按当前登录用户隔离。

### 4.3 部署

- 推荐 Docker Compose 起步：
  - `api`
  - `worker`
  - `frontend`
  - `postgres`
  - `redis`
  - `nginx`
- 后续可迁移到云数据库、云 Redis 和 OSS/CDN。

## 5. 数据库设计

### 5.1 users

用户表。

```text
id
email
phone
username
password_hash
role: user/admin
status: active/disabled
plan: free/pro/team
created_at
updated_at
last_login_at
```

### 5.2 user_profiles

用户资料表。

```text
user_id
display_name
avatar_url
company
timezone
```

### 5.3 tasks

任务主表，替代当前 `task_store.json`。

```text
id
user_id
kind: extract/rewrite/tts/video/wav2lip
title
status: queued/running/succeeded/failed/canceled
progress
message
payload_json
result_json
error_code
error_message
retry_count
created_at
started_at
finished_at
updated_at
```

索引：

```text
user_id, created_at
user_id, kind, created_at
status, created_at
```

### 5.4 files

文件表，替代本地散落文件记录。

```text
id
user_id
task_id
purpose: upload/voice/audio/video/subtitle/temp/output
original_name
object_key
public_url
content_type
size_bytes
checksum
status: active/deleted/expired
created_at
expires_at
```

### 5.5 service_configs

外部接口配置表。

```text
id
scope: system/user/team
owner_id
service_type: llm/asr/tts/lipSync/videoCompose
enabled
provider
url
model
headers_json
fields_json
timeout_seconds
encrypted_api_key
created_at
updated_at
```

说明：

- 系统默认配置由管理员维护。
- 用户可选择使用系统配置，也可配置自己的接口。
- API Key 必须加密保存，不能明文写入 JSON。

### 5.6 usage_logs

外部接口调用和用量记录。

```text
id
user_id
task_id
service_type
provider
request_id
status_code
duration_ms
input_units
output_units
cost_amount
error_message
created_at
```

### 5.7 quotas

用户额度表。

```text
user_id
period: daily/monthly
extract_limit
tts_chars_limit
video_minutes_limit
storage_bytes_limit
used_extract_count
used_tts_chars
used_video_seconds
used_storage_bytes
reset_at
```

## 6. 后端模块改造

### 6.1 目录建议

```text
backend/
  app/
    main.py
    core/
      config.py
      security.py
      database.py
      storage.py
      rate_limit.py
    models/
      user.py
      task.py
      file.py
      service_config.py
      usage_log.py
    schemas/
      auth.py
      task.py
      file.py
      service_config.py
    api/
      auth.py
      users.py
      tasks.py
      files.py
      service_config.py
      workflow.py
      admin.py
    services/
      asr_client.py
      llm_client.py
      tts_client.py
      lipsync_client.py
      video_compose.py
      task_service.py
      usage_service.py
    workers/
      celery_app.py
      jobs.py
```

当前 `api_server.py` 可以逐步拆分，而不是一次性大重写。

### 6.2 鉴权中间件

新增：

- `POST /api/v1/auth/register`
- `POST /api/v1/auth/login`
- `POST /api/v1/auth/refresh`
- `POST /api/v1/auth/logout`
- `GET /api/v1/auth/me`

所有业务接口默认需要登录，管理员接口需要 `role=admin`。

### 6.3 用户隔离

所有任务接口都必须从登录态获取 `user_id`：

- 创建任务时写入 `user_id`。
- 查询历史时只查当前用户。
- 获取文件时校验文件归属。
- 删除任务/文件时校验归属。
- 管理员接口才允许跨用户查询。

### 6.4 任务队列

当前 `_enqueue()` 已改为任务入库后投递执行器。生产部署使用：

```text
API 创建任务 -> 写入 DB -> 投递 Redis 队列 -> Worker 读取任务 payload -> 执行 -> 更新 DB -> 上传结果文件
```

任务状态流转：

```text
queued -> running -> succeeded
queued -> running -> failed
failed -> queued  // retry
queued/running -> canceled
```

### 6.5 文件存储

文件路径应从本地路径改成对象存储 Key：

```text
users/{user_id}/uploads/{file_id}.mp4
users/{user_id}/voices/{file_id}.wav
users/{user_id}/outputs/{task_id}/audio.wav
users/{user_id}/outputs/{task_id}/video.mp4
users/{user_id}/temp/{task_id}/source.wav
```

访问文件时由后端生成短期签名 URL，避免公开暴露真实存储地址。

### 6.6 外部接口调用

外部 ASR、LLM、TTS、LipSync 调用需要统一封装：

- 读取用户可用配置。
- 注入 API Key。
- 记录调用日志。
- 捕获错误并转换为统一错误码。
- 支持超时、重试、熔断。
- 统计输入/输出用量。

统一错误格式：

```json
{
  "code": "TTS_PROVIDER_TIMEOUT",
  "message": "语音合成服务超时",
  "detail": "provider response timeout after 240 seconds"
}
```

## 7. API 调整建议

### 7.1 保留当前业务接口

为了前端少改，以下接口路径可以保留：

```text
POST /api/v1/extract/start
POST /api/v1/rewrite/start
POST /api/v1/tts/start
POST /api/v1/upload-voice
POST /api/v1/upload-video
POST /api/v1/edit-video/start
POST /api/v1/wav2lip/start
GET  /api/v1/jobs/{task_id}
GET  /api/v1/history
DELETE /api/v1/history/{task_id}
GET  /api/v1/storage
```

但返回值应增加：

```json
{
  "task_id": "...",
  "status": "queued",
  "kind": "tts",
  "poll_url": "/api/v1/jobs/..."
}
```

### 7.2 新增生产接口

```text
GET  /api/v1/tasks
GET  /api/v1/tasks/{task_id}
POST /api/v1/tasks/{task_id}/retry
POST /api/v1/tasks/{task_id}/cancel
GET  /api/v1/files
GET  /api/v1/files/{file_id}/download-url
DELETE /api/v1/files/{file_id}
GET  /api/v1/usage/me
GET  /api/v1/quota/me
```

管理员接口：

```text
GET  /api/v1/admin/users
GET  /api/v1/admin/tasks
GET  /api/v1/admin/usage
GET  /api/v1/admin/service-configs
PUT  /api/v1/admin/service-configs/{id}
```

## 8. 前端改造

### 8.1 页面结构

生产版建议增加：

- 登录页。
- 注册页。
- 工作台首页。
- 任务记录页。
- 文件库页。
- 接口配置页。
- 个人用量页。
- 管理员后台。

### 8.2 当前工作台改造

当前 6 个模块可以继续保留，但需要：

- 所有请求加 `Authorization: Bearer <token>`。
- 任务记录只展示当前用户数据。
- 文件上传后保存 `file_id`，不要只依赖 `filename`。
- 下载视频/音频时请求短期下载 URL。
- 任务执行中支持刷新、取消、失败重试。
- AI 改写不要直连外部模型地址，应统一调用 `/api/v1/rewrite/start`。

### 8.3 管理员后台

管理员需要看到：

- 用户列表。
- 用户任务数量。
- 今日外部接口调用次数。
- 失败任务列表。
- 存储占用排行。
- 外部服务健康状态。

## 9. 安全要求

### 9.1 上传安全

- 限制文件类型和大小。
- 后端重新探测 MIME 类型。
- 文件名只保存原名展示，实际存储使用 UUID。
- 上传文件不能直接作为本地路径拼接使用。
- 定期清理临时文件。

### 9.2 接口安全

- 业务接口必须鉴权。
- 下载接口必须校验文件归属。
- 管理接口必须校验管理员角色。
- 登录接口限流。
- 上传接口限流。
- 外部接口配置中的 API Key 加密保存。

### 9.3 多租户隔离

所有核心表都必须有 `user_id` 或明确的 `owner_id`。

禁止通过前端传入的 `user_id` 决定数据归属，必须以后端登录态为准。

## 10. 运维与监控

### 10.1 日志

建议使用结构化日志，至少包含：

```text
request_id
user_id
task_id
service_type
duration_ms
status
error_code
```

### 10.2 监控指标

需要监控：

- API 请求量、错误率、延迟。
- 队列长度。
- Worker 执行耗时。
- 外部接口成功率。
- 外部接口超时率。
- 存储占用。
- 用户用量。

### 10.3 备份

- PostgreSQL 每日备份。
- 对象存储开启生命周期策略。
- 关键配置定期备份。
- API Key 不进入日志和前端明文。

## 11. 部署方案

### 11.1 Docker Compose 服务

```text
api
worker
frontend
postgres
redis
nginx
```

### 11.2 环境变量

```text
APP_ENV=production
SECRET_KEY=
DATABASE_URL=
REDIS_URL=
OBJECT_STORAGE_PROVIDER=aliyun_oss
ALIYUN_OSS_ENDPOINT=
ALIYUN_OSS_BUCKET=
ALIYUN_OSS_ACCESS_KEY_ID=
ALIYUN_OSS_ACCESS_KEY_SECRET=
ALIYUN_OSS_PREFIX=
PUBLIC_BASE_URL=
```

### 11.3 Nginx

Nginx 负责：

- 静态前端。
- API 反向代理。
- 上传大小限制。
- HTTPS。
- 请求超时配置。

## 12. 实施阶段

### 阶段一：基础生产化

目标：先让系统支持多用户数据隔离。

- 新增数据库、ORM、迁移工具。
- 新增用户注册/登录/JWT。
- 任务记录从 JSON 迁移到数据库。
- 上传文件、输出文件增加用户归属。
- 前端增加登录页和 Token 请求封装。
- 历史记录按用户隔离。

验收标准：

- A 用户看不到 B 用户任务。
- A 用户不能下载 B 用户文件。
- 重启后任务记录仍在数据库中。

### 阶段二：队列化和稳定性

目标：任务执行可靠，支持并发和重试。

- 已引入 Redis。
- 已引入 Celery Worker。
- 已替换 FastAPI `BackgroundTasks` 闭包执行方式。
- 任务支持重试、取消、失败原因。
- 任务状态轮询标准化。

验收标准：

- API 重启不影响已排队任务。
- Worker 重启后失败任务可重试。
- 多个用户可同时提交任务。

### 阶段三：对象存储

目标：文件不再依赖 API 本机磁盘。

- 接入阿里云 OSS。
- 上传文件进入对象存储。
- 输出结果上传对象存储。
- 下载使用短期签名 URL。
- 建立文件表和清理策略。

验收标准：

- API 多实例部署时文件仍可访问。
- 用户只能访问自己的文件。
- 过期临时文件可自动清理。

### 阶段四：用量、配额和管理后台

目标：支持商业化和运营。

- 增加用量统计。
- 增加用户额度。
- 增加接口调用日志。
- 增加管理员后台。
- 增加服务健康检查。

验收标准：

- 管理员可查看用户、任务、失败记录。
- 用户达到额度后无法继续提交对应任务。
- 每次外部模型调用都有日志。

### 阶段五：部署和运维

目标：可稳定部署到服务器。

- 编写 Dockerfile。
- 编写 docker-compose.yml。
- 增加 `.env.example`。
- 增加 Nginx 配置。
- 增加备份脚本。
- 增加生产部署文档。

验收标准：

- 新服务器可以按文档部署。
- 支持 HTTPS 域名访问。
- 服务重启后数据和文件不丢失。

## 13. 优先级建议

优先级从高到低：

1. 用户登录和用户隔离。
2. 任务记录迁移数据库。
3. 文件表和文件归属校验。
4. AI 改写接口统一走后端，不再前端直连外部接口。
5. 队列化任务执行。
6. 对象存储。
7. 配额、用量、管理后台。
8. Docker Compose 生产部署。

## 14. 不建议一次性做的内容

以下内容可以后置：

- 复杂组织/团队体系。
- 在线支付。
- Kubernetes。
- 多区域部署。
- 实时 WebSocket 推送。
- 高级素材库和模板市场。

先把用户隔离、数据库、队列、对象存储做好，系统就已经从单机工具进入可多人使用的生产基础版。
