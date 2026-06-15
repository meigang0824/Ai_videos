# 视频剪辑成片外部接口

新项目已经把 MoviePy 自动合成能力开放为外部异步接口。

## 服务地址

本机：

```text
http://127.0.0.1:8010
```

局域网：

```text
http://你的电脑局域网IP:8010
```

健康检查：

```bash
curl http://127.0.0.1:8010/api/v1/health
```

## 1. 上传视频素材

```bash
curl -X POST http://127.0.0.1:8010/api/v1/upload-video \
  -F "file=@/path/to/video.mp4"
```

返回里的 `video_url` 可作为合成接口的 `videoUrl` 或 `videoUrls`。

## 2. 准备配音音频

配音可以来自：

- 本项目 `/api/v1/tts/start` 生成后的 `audio_url`
- 外部可访问的 `http/https` 音频地址
- 本机绝对路径，比如 `/Users/apple/Downloads/demo.wav`

## 3. 创建剪辑任务

推荐外部系统使用：

```text
POST /api/v1/video-compose/start
```

前端兼容入口仍保留：

```text
POST /api/v1/edit-video/start
```

请求示例：

```bash
curl -X POST http://127.0.0.1:8010/api/v1/video-compose/start \
  -H "Content-Type: application/json" \
  -d '{
    "taskId": "compose_demo_001",
    "videoUrl": "/api/v1/uploads/your_video.mp4",
    "audioUrl": "/api/v1/audio/your_tts_task",
    "subtitle": "第一句口播文案\n第二句口播文案\n第三句口播文案",
    "options": {
      "loop_video": true,
      "add_subtitle": true,
      "subtitle_position": "bottom",
      "subtitle_max_chars": 12,
      "fps": 30,
      "width": 720,
      "height": 1280,
      "max_clip_seconds": 4,
      "crf": 18,
      "ffmpegPreset": "medium"
    }
  }'
```

前端仍使用 camelCase 选项；后端调用外部 `/v1/video/compose` 时会自动转换为新文档要求的 snake_case 字段。

返回：

```json
{
  "task_id": "compose_demo_001",
  "status": "queued"
}
```

## 4. 轮询任务状态

```bash
curl http://127.0.0.1:8010/api/v1/jobs/compose_demo_001
```

成功后会返回：

```json
{
  "status": "success",
  "progress": 100,
  "result": {
    "video_url": "/api/v1/video/compose_demo_001",
    "subtitle_url": "/api/v1/subtitle/compose_demo_001"
  }
}
```

## 5. 下载结果

下载视频：

```bash
curl -L -o result.mp4 http://127.0.0.1:8010/api/v1/video/compose_demo_001
```

下载字幕：

```bash
curl -L -o result.srt http://127.0.0.1:8010/api/v1/subtitle/compose_demo_001
```

## 常用参数

| 参数 | 说明 |
| --- | --- |
| `videoUrl` | 单个视频地址、上传后地址或本机绝对路径 |
| `videoUrls` | 多个视频素材，会按顺序自动取段铺满配音时长 |
| `audioUrl` | 配音音频地址或本机绝对路径 |
| `subtitle` | 字幕文案，建议每句一行 |
| `width` / `height` | 输出画幅，竖屏常用 `720x1280` |
| `maxClipSeconds` | 多视频轮播时每段秒数 |
| `subtitleMaxChars` | 每句字幕最大字数 |
| `subtitlePosition` | `top`、`middle`、`bottom` |
| `subtitleStyle` | `classic`、`yellow`、`clean`、`bold` |
| `crf` | 画质参数，越低越清晰，文件越大 |
| `ffmpegPreset` | 编码速度，常用 `veryfast`、`medium`、`slow` |

## 说明

这个接口不调用模型，不需要显卡。它只使用本机 MoviePy/ffmpeg 做视频合成，适合作为内部服务给其他系统调用。
