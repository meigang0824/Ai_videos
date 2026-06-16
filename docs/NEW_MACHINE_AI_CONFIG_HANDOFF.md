# 新电脑部署 AI 配置交接文件

这个文件用于在新电脑部署后，直接发给 AI 或运维人员，让对方按当前系统配置还原环境。本文不包含真实密码、API Key、AccessKey，请在部署时从安全渠道单独填写。

## 0. 敏感配置填写清单

真实密码、API Key、AccessKey 不要写入本文档，也不要提交到 Git。部署时请把下面字段通过 `.env`、后台配置页或服务器环境变量填写。

需要写入 `.env`：

```text
POSTGRES_PASSWORD
DATABASE_URL
SECRET_KEY
ALIYUN_OSS_ACCESS_KEY_ID
ALIYUN_OSS_ACCESS_KEY_SECRET
```

需要进入后台 `/admin` 的“接口配置”填写：

```text
llm.apiKey
```

当前 OSS 配置项：

```text
ALIYUN_OSS_ENDPOINT=https://oss-cn-shanghai.aliyuncs.com
ALIYUN_OSS_BUCKET=letwx
ALIYUN_OSS_PREFIX=cosyvoice
```

如果一定要给部署 AI 提供真实密钥，请通过单独的私密消息发送，不要放进仓库文档。

## 1. 项目仓库

```text
git@github.com:meigang0824/Ai_videos.git
```

推荐使用 Docker Compose 部署。

```bash
git clone git@github.com:meigang0824/Ai_videos.git
cd Ai_videos
cp .env.example .env
```

## 2. .env 推荐配置

把下面内容按新电脑实际 IP、端口和密钥修改后写入 `.env`。

```bash
APP_ENV=production
HOST=0.0.0.0
PORT=8010
HTTP_PORT=8080
PUBLIC_BASE_URL=http://新电脑局域网IP:8080

POSTGRES_DB=cosyvoice
POSTGRES_USER=cosyvoice
POSTGRES_PASSWORD=请填写新的强密码
DATABASE_URL=postgresql+psycopg://cosyvoice:请填写同一个强密码@postgres:5432/cosyvoice

SECRET_KEY=请填写新的长随机字符串
AUTH_REQUIRED=1
AUTH_TOKEN_TTL_SECONDS=604800

CORS_ALLOW_ORIGINS=http://新电脑局域网IP:8080,http://127.0.0.1:8080,http://localhost:8080
DEFAULT_BACKGROUND_VIDEO=
MAX_UPLOAD_BYTES=1073741824

JOB_RUNNER_BACKEND=celery
JOB_MAX_WORKERS=2
CELERY_WORKER_CONCURRENCY=2
CELERY_WORKER_PREFETCH_MULTIPLIER=1

REDIS_URL=redis://redis:6379/0
CELERY_BROKER_URL=redis://redis:6379/0
CELERY_RESULT_BACKEND=redis://redis:6379/0

QUOTA_TASKS=
QUOTA_TTS_CHARS=
QUOTA_VIDEO_SECONDS=
QUOTA_STORAGE_BYTES=

OBJECT_STORAGE_PROVIDER=aliyun_oss
ALIYUN_OSS_ENDPOINT=https://oss-cn-shanghai.aliyuncs.com
ALIYUN_OSS_BUCKET=letwx
ALIYUN_OSS_ACCESS_KEY_ID=请从安全渠道填写
ALIYUN_OSS_ACCESS_KEY_SECRET=请从安全渠道填写
ALIYUN_OSS_PREFIX=cosyvoice
ALIYUN_OSS_SIGNED_URL_TTL=3600
ALIYUN_OSS_PUBLIC_BASE_URL=
```

启动：

```bash
docker-compose up -d --build
```

访问：

```text
前台：http://新电脑局域网IP:8080
后台：http://新电脑局域网IP:8080/admin
API：http://新电脑局域网IP:8010
```

如果使用 `HTTP_PORT=80`，前后台地址去掉 `:8080`。

## 3. 后台接口配置

进入 `/admin` 后，在“接口配置”里按下面配置。API Key 需要单独填写，不要写入代码仓库。

```json
{
  "llm": {
    "enabled": true,
    "url": "https://coding.dashscope.aliyuncs.com/v1/chat/completions",
    "apiKey": "请从安全渠道填写",
    "model": "qwen3.6-plus",
    "timeout": 180
  },
  "asr": {
    "enabled": true,
    "url": "http://192.168.1.9:8000/v1/audio/transcribe-url",
    "videoUrl": "http://192.168.1.9:8000/v1/video/transcribe",
    "apiKey": "",
    "model": "base",
    "timeout": 180
  },
  "tts": {
    "enabled": true,
    "url": "http://192.168.1.9:8000/v1/tts/synthesize",
    "cloneUrl": "http://192.168.1.9:8000/v1/tts/clone",
    "apiKey": "",
    "timeout": 900
  },
  "lipSync": {
    "enabled": false,
    "url": "",
    "apiKey": "",
    "timeout": 900
  },
  "videoCompose": {
    "enabled": true,
    "url": "http://192.168.1.9:8000/v1/video/compose",
    "apiKey": "",
    "timeout": 900
  }
}
```

## 4. 外部模型服务检查

新电脑必须能访问模型服务：

```bash
curl http://192.168.1.9:8000/v1/health
```

当前期望：

```text
ok=true
whisper.available=true
tts.available=true
latentsync.available=true
```

注意：如果 `tts.speakers` 为空或 clone 接口很慢，TTS 仍可能可用但生成会非常慢。当前系统实际观察到 `/v1/tts/clone` 可能需要数分钟。

## 5. TTS Clone 调用方式

当前系统调用：

```text
POST http://192.168.1.9:8000/v1/tts/clone
Content-Type: multipart/form-data
```

字段：

```text
text: 要合成的文本
speed: 语速，例如 "1.0"
prompt_audio: 参考音频文件
```

不传：

```text
prompt_text
voice_ref_text
voice_id
model
```

`prompt_text` 不传是当前约定，外部服务会自动转写参考音频。

## 6. 首次部署后的账号配置

注册功能已关闭。需要管理员账号时，可在新环境数据库或后端初始化流程里创建管理员，之后通过 `/admin` 创建普通用户和房产中介用户。

角色说明：

```text
admin：后台管理、接口配置、用户管理
user：普通短视频流程
realtor：房产中介，显示房产文案生成模块
```

## 7. 数据迁移说明

只部署代码时，新电脑是空系统，需要重新配置：

- 管理员和用户
- 后台接口配置
- 导入音色
- 上传素材

如果要迁移旧电脑完整数据，需要同时迁移 Docker volumes：

```text
cosy_postgres：用户、任务、接口配置、音色记录
cosy_voices：音色音频文件
cosy_outputs：生成的音频、视频、字幕
cosy_storage：兼容存储和上传记录
cosy_redis：队列缓存，可不迁移
```

PostgreSQL 备份：

```bash
docker-compose exec -T postgres pg_dump -U cosyvoice -d cosyvoice > cosyvoice.sql
```

PostgreSQL 恢复：

```bash
docker-compose exec -T postgres psql -U cosyvoice -d cosyvoice < cosyvoice.sql
```

## 8. 部署后验证

```bash
docker-compose ps
curl http://127.0.0.1:8010/api/v1/health
curl http://192.168.1.9:8000/v1/health
```

前端构建和后端测试：

```bash
npm --prefix app_ui run build
.venv/bin/python -m pytest -q
```

## 9. 可直接发给 AI 的提示词

```text
你现在要在一台新电脑部署 Ai_videos 项目。请按本文配置执行：

1. 使用仓库 git@github.com:meigang0824/Ai_videos.git。
2. 复制 .env.example 为 .env，按“第 2 节 .env 推荐配置”填写。
3. 不要把任何真实 API Key、AccessKey、数据库密码提交到 Git。
4. 使用 docker-compose up -d --build 启动。
5. 访问 /admin，按“第 3 节 后台接口配置”填写接口。
6. 检查 http://192.168.1.9:8000/v1/health 是否可访问。
7. TTS clone 必须用 multipart/form-data，字段是 text、speed、prompt_audio，不传 prompt_text。
8. 如果要迁移旧数据，请迁移 cosy_postgres、cosy_voices、cosy_outputs、cosy_storage。
9. 部署完成后运行健康检查，确认 queued/running 为 0 或符合当前任务状态。
```
