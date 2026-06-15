# CosyVoice API Only

这是纯外部接口版短视频工作台。项目不包含本地 CosyVoice、Whisper、Wav2Lip、VideoReTalking 模型，也不会在后端加载这些模型。

## 功能边界

- 前端保留 6 个工作模块：输入素材、AI 改写、音色设置、视频剪辑、口型同步、成片预览和任务记录。
- 后端只负责文件上传、任务记录、视频剪辑合成、接口转发和结果文件管理。
- 模型能力全部通过接口调用：ASR 文案提取、LLM 文案改写、TTS 语音合成、口型同步。
- 接口地址、API Key、模型名、返回格式都可以在前端右上角“接口配置”里填写。

## 启动

macOS / Linux：

```bash
cd /Users/apple/CosyVoice_API_Only
chmod +x start_macos.sh
./start_macos.sh
```

Windows PowerShell：

```powershell
cd C:\path\to\CosyVoice_API_Only
.\start_windows.ps1
```

如果系统拦截脚本执行，可以用：

```powershell
powershell -ExecutionPolicy Bypass -File .\start_windows.ps1
```

也可以双击 `start_windows.bat`。

默认访问地址：

```text
http://127.0.0.1:8010/
```

局域网访问时，把 `127.0.0.1` 换成这台电脑的局域网 IP。

可选环境变量：

```bash
DEFAULT_BACKGROUND_VIDEO=/path/to/default.mp4
MAX_UPLOAD_BYTES=1073741824
CORS_ALLOW_ORIGINS=http://127.0.0.1:8010,http://localhost:5173
AUTH_REQUIRED=0
AUTH_TOKEN_TTL_SECONDS=604800
SECRET_KEY=replace-with-a-random-string
JOB_RUNNER_BACKEND=local
JOB_MAX_WORKERS=2
REDIS_URL=redis://127.0.0.1:6379/0
CELERY_BROKER_URL=redis://127.0.0.1:6379/0
CELERY_RESULT_BACKEND=redis://127.0.0.1:6379/0
CELERY_WORKER_CONCURRENCY=2
POSTGRES_DB=cosyvoice
POSTGRES_USER=cosyvoice
POSTGRES_PASSWORD=replace-with-a-strong-postgres-password
DATABASE_URL=postgresql+psycopg://cosyvoice:replace-with-a-strong-postgres-password@postgres:5432/cosyvoice
OBJECT_STORAGE_PROVIDER=aliyun_oss
ALIYUN_OSS_ENDPOINT=https://oss-cn-shanghai.aliyuncs.com
ALIYUN_OSS_BUCKET=letwx
ALIYUN_OSS_ACCESS_KEY_ID=
ALIYUN_OSS_ACCESS_KEY_SECRET=
ALIYUN_OSS_PREFIX=cosyvoice
ALIYUN_OSS_SIGNED_URL_TTL=3600
```

如确实需要恢复跨域全开放，可显式设置 `CORS_ALLOW_ORIGINS=*`。

第一次在页面右上角登录入口注册的用户会自动成为管理员。已有用户后，任务、上传、历史记录和文件访问会按登录用户隔离；保存接口配置和清理存储等敏感操作需要管理员权限。设置 `AUTH_REQUIRED=1` 后，即使还没有注册用户，也会要求按登录态接入。

Docker Compose 部署默认使用 PostgreSQL 保存用户、任务和上传记录，并通过 Alembic 在容器启动时自动执行数据库迁移。本地脚本启动且未设置 `DATABASE_URL` 时，会回落到 `backend/storage/*.sqlite3`，首次启动会把旧的 `backend/storage/task_store.json` 历史迁移进去，旧记录归属为 `local`。

导入音色会写入当前登录用户归属，普通用户只能看到和试听自己的本地音色。升级前已经存在、没有 `user_id` 的旧音色会按 `local` 处理，管理员可以继续使用。

后台任务支持两种执行器：`JOB_RUNNER_BACKEND=local` 使用本地线程池，适合单机开发；`JOB_RUNNER_BACKEND=celery` 使用 Redis/Celery，适合 Docker/生产部署。`GET /api/v1/job-runner` 可查看当前执行器状态。Docker Compose 默认启动 `app`、`worker` 和 `redis`，API 进程只负责任务入库和投递，Celery worker 负责实际执行。

任务记录里支持取消和重试：`POST /api/v1/tasks/{task_id}/cancel` 可取消尚未开始执行的任务，已开始运行的任务不会被强制中断；`POST /api/v1/tasks/{task_id}/retry` 会基于原 payload 创建一个新的重试任务，上传文件提取任务会优先复用本地临时文件或 OSS 源文件。

配置阿里云 OSS 后，上传视频、导入音色、TTS 音频、剪辑成片、字幕和口型同步视频会自动补传到 OSS；前端仍访问原来的 `/api/v1/...` 地址，后端会按权限校验后重定向到临时签名 URL。不要把 AccessKey 写入仓库，生产环境请通过 `.env`、容器 secret 或部署平台环境变量注入。已有本地媒体文件可用下面脚本补传：

```bash
OBJECT_STORAGE_PROVIDER=aliyun_oss \
ALIYUN_OSS_ENDPOINT=https://oss-cn-shanghai.aliyuncs.com \
ALIYUN_OSS_BUCKET=letwx \
ALIYUN_OSS_ACCESS_KEY_ID=你的AccessKeyId \
ALIYUN_OSS_ACCESS_KEY_SECRET=你的AccessKeySecret \
python scripts/upload_to_aliyun_oss.py
```

已提供 Docker Compose 部署文件和环境变量样例，见 `docs/DEPLOYMENT.md`。当前管理和用量接口包括 `/api/v1/usage/me`、`/api/v1/quota/me`、`/api/v1/admin/users`、`/api/v1/admin/tasks`、`/api/v1/admin/usage`。

## 测试

后端基础自动化测试覆盖登录注册、Token 校验和任务分发执行路径：

```bash
.venv/bin/pytest -q
```

前端生产构建验证：

```bash
npm --prefix app_ui run build
```

## 接口配置说明

打开页面后点击右上角“接口配置”，按你的服务填写：

- `文案改写 LLM`：支持 OpenAI Chat Compatible 或 Anthropic Messages Compatible。
- `文案提取 ASR`：支持链接转写、音频文件转写和视频文件转写；主接口填 `/v1/audio/transcribe` 时，会自动推导 `/v1/audio/transcribe-url` 和 `/v1/video/transcribe`。
- `语音合成 TTS`：可返回二进制音频、JSON 音频地址或 JSON base64。
- `口型同步`：后端会把人物视频和音频用 multipart 上传给该接口。

API Key 保存在本机 `backend/storage/service_config.json`，前端读取时会显示为掩码。再次保存时留空或保持掩码，后端会沿用旧 Key。

## 迁移到新电脑

复制整个 `CosyVoice_API_Only` 目录即可。新电脑只需要安装：

- Python 3.11+
- Node.js 18+
- ffmpeg
- yt-dlp 依赖由 `requirements.txt` 安装

然后执行启动命令，并在前端重新填写各模型服务接口。

## 注意

- 这个版本不下载模型，也不打包模型。
- 视频剪辑仍在本机用 MoviePy/ffmpeg 完成，这不是模型调用。
- 视频剪辑成片能力已开放为外部接口，见 `docs/VIDEO_COMPOSE_API.md`。
- 提取文案和音色生成语音能力已开放为外部接口，见 `docs/SCRIPT_AND_SPEECH_API.md`。
- 如果“提取文案”使用视频链接，机器需要能访问该链接，并且 `yt-dlp` 能正常下载音频。
- 如果某个模型接口未配置，对应模块会直接报错提示先配置接口。
