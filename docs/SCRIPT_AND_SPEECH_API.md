# 提取文案与音色语音外部接口

这些接口都是异步任务接口。创建任务后先拿 `task_id`，再轮询任务状态，最后读取结果。

## 1. 健康检查

```bash
curl http://127.0.0.1:8010/api/v1/health
```

## 2. 配置模型服务

页面右上角“接口配置”里需要先配置：

- `文案提取 ASR`
- `语音合成 TTS`

如果使用“短视频本地模型服务”这类 FastAPI 服务，ASR 推荐配置：

```text
主接口：http://192.168.1.9:8000/v1/audio/transcribe
文件字段：file
视频字段：video
链接字段：url
链接转写接口：http://192.168.1.9:8000/v1/audio/transcribe-url
视频转写接口：http://192.168.1.9:8000/v1/video/transcribe
文本路径：text
分段路径：segments
```

`链接转写接口` 和 `视频转写接口` 可以留空；当主接口是 `/v1/audio/transcribe` 时，后端会自动推导 `/v1/audio/transcribe-url` 和 `/v1/video/transcribe`。

也可以直接调用：

```text
GET /api/v1/service-config
PUT /api/v1/service-config
```

## 3. 通过视频链接提取文案

外部推荐入口：

```text
POST /api/v1/script-extract/start
```

前端兼容入口：

```text
POST /api/v1/extract/start
```

请求：

```bash
curl -X POST http://127.0.0.1:8010/api/v1/script-extract/start \
  -H "Content-Type: application/json" \
  -d '{
    "taskId": "extract_demo_001",
    "reference_url": "https://example.com/video.mp4",
    "model": "base"
  }'
```

返回：

```json
{
  "task_id": "extract_demo_001",
  "status": "queued"
}
```

说明：这个接口会优先调用 ASR 服务的链接转写接口，例如 `/v1/audio/transcribe-url`。如果该接口失败，才会回落到 `yt-dlp` 下载音频后再调用音频转写接口。

## 4. 上传文件提取文案

支持音频或视频文件。上传视频时后端会优先调用 ASR 服务的视频转写接口，例如 `/v1/video/transcribe`；如果该接口失败，才会回落到 ffmpeg 抽音频后再调用音频转写接口。

```text
POST /api/v1/script-extract/upload
```

请求：

```bash
curl -X POST http://127.0.0.1:8010/api/v1/script-extract/upload \
  -F "taskId=extract_upload_001" \
  -F "model=base" \
  -F "file=@/path/to/audio_or_video.mp4"
```

成功后的任务结果：

```json
{
  "extracted_script": "识别出来的文案",
  "segments": [],
  "transcribe_method": "video_transcribe"
}
```

## 5. 视频剪辑成片

当配置了外部视频合成接口后，视频剪辑成片会使用下面链路：

```text
上传视频 -> 上传到 OSS -> 生成 OSS 签名 URL -> 调用 /v1/video/compose
```

推荐配置：

```text
视频剪辑成片接口：http://192.168.1.9:8000/v1/video/compose
返回模式：JSON 地址
URL 路径：video_url
```

外部接口请求体：

```json
{
  "video_urls": ["https://...oss.../background.mp4?..."],
  "audio_url": "https://...oss.../audio.wav?...",
  "subtitle": "字幕文本",
  "options": {
    "width": 1080,
    "height": 1920,
    "max_clip_seconds": 4,
    "add_subtitle": true,
    "subtitle_position": "bottom",
    "subtitle_max_chars": 28,
    "loop_video": true
  }
}
```

注意：外部视频合成服务访问不到本机容器内的 `/api/v1/uploads/...` 或 `/api/v1/audio/...` 地址，所以必须启用 OSS。上传视频和生成配音成功后，后端会优先使用对应的 OSS object key 生成签名 URL，再调用外部视频合成接口。未启用 OSS 时，外部视频合成会报错提示先配置 OSS。

## 6. 导入音色录音

```text
POST /api/v1/upload-voice
```

请求：

```bash
curl -X POST http://127.0.0.1:8010/api/v1/upload-voice \
  -F "file=@/path/to/voice.wav"
```

返回：

```json
{
  "voice": {
    "id": "1718000000000_ab12cd",
    "name": "音色 0615-1050",
    "ref_wav": "/Users/apple/CosyVoice_API_Only/voices/xxx.wav",
    "ref_text": "ASR 识别出的参考文本"
  }
}
```

注意：导入音色不会覆盖旧音色，会生成新的音色记录。音色名称、归属、参考音频路径、OSS key 和参考文本会写入 `voices` 数据表，同时保留 `voices/*.json` 作为兼容备份。

## 7. 查询音色列表

```bash
curl http://127.0.0.1:8010/api/v1/voices
```

## 7. 按音色生成语音

外部推荐入口：

```text
POST /api/v1/speech/start
```

兼容入口：

```text
POST /api/v1/tts/start
POST /api/v1/voice-tts/start
```

试听样音使用缓存入口：

```text
POST /api/v1/tts/sample/start
```

该入口会先按 `taskId` 查询任务表。已有成功任务且音频仍可用时直接返回历史结果，不会再次调用 TTS/clone 接口；没有可用记录时才创建新任务并入库。

请求：

```bash
curl -X POST http://127.0.0.1:8010/api/v1/speech/start \
  -H "Content-Type: application/json" \
  -d '{
    "taskId": "speech_demo_001",
    "text": "这是要生成的口播内容",
    "voice_id": "1718000000000_ab12cd",
    "voice_ref_wav": "/Users/apple/CosyVoice_API_Only/voices/xxx.wav",
    "speed": 1.0
  }'
```

当前模型服务配置：

```text
内置音色接口：http://192.168.1.9:8000/v1/tts/synthesize
字段：text / speaker / speed

声音克隆接口：http://192.168.1.9:8000/v1/tts/clone
multipart 字段：text / prompt_audio / speed
说明：后端不传 prompt_text，让模型服务自行处理参考音频。
```

返回：

```json
{
  "task_id": "speech_demo_001",
  "status": "queued"
}
```

成功后的任务结果：

```json
{
  "audio_url": "/api/v1/audio/speech_demo_001",
  "audio_path": "/Users/apple/CosyVoice_API_Only/outputs/speech_demo_001.wav"
}
```

## 8. 轮询任务状态

```bash
curl http://127.0.0.1:8010/api/v1/jobs/speech_demo_001
```

状态值：

- `queued`
- `running`
- `success`
- `failed`

## 9. 下载语音

```bash
curl -L -o speech.wav http://127.0.0.1:8010/api/v1/audio/speech_demo_001
```

## 10. 典型流程

1. `POST /api/v1/upload-voice` 导入参考录音，拿到 `voice.ref_wav` 和 `voice.ref_text`
2. `POST /api/v1/script-extract/start` 或 `/upload` 提取文案
3. `GET /api/v1/jobs/{task_id}` 拿到 `extracted_script`
4. `POST /api/v1/speech/start` 生成语音
5. `GET /api/v1/audio/{task_id}` 下载音频
