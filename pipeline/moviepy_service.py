from __future__ import annotations

import math
import os
import re
import shutil
import uuid
from pathlib import Path
from urllib.parse import urlparse

import requests
from PIL import Image, ImageDraw, ImageFont

from pipeline.config import BASE_DIR, OUTPUT_DIR


STORAGE_DIR = Path(BASE_DIR) / "backend" / "storage"
TMP_DIR = STORAGE_DIR / "tmp" / "moviepy"
SUBTITLE_STYLE_PRESETS = {
    "classic": {
        "fill": (255, 255, 255),
        "stroke": (0, 0, 0),
        "bg": (0, 0, 0),
        "bg_alpha": 158,
        "stroke_width": 2,
        "size_scale": 1.0,
    },
    "yellow": {
        "fill": (255, 230, 80),
        "stroke": (0, 0, 0),
        "bg": (0, 0, 0),
        "bg_alpha": 138,
        "stroke_width": 3,
        "size_scale": 1.04,
    },
    "clean": {
        "fill": (255, 255, 255),
        "stroke": (0, 0, 0),
        "bg": (0, 0, 0),
        "bg_alpha": 0,
        "stroke_width": 3,
        "size_scale": 1.0,
    },
    "bold": {
        "fill": (255, 255, 255),
        "stroke": (0, 0, 0),
        "bg": (0, 0, 0),
        "bg_alpha": 190,
        "stroke_width": 3,
        "size_scale": 1.14,
    },
}

TMP_DIR.mkdir(parents=True, exist_ok=True)
Path(OUTPUT_DIR).mkdir(parents=True, exist_ok=True)


def _url_suffix(value: str, fallback: str) -> str:
    parsed = urlparse(value or "")
    suffix = Path(parsed.path).suffix.lower()
    return suffix or fallback


def _resolve_app_url(value: str, base_url: str) -> str:
    value = (value or "").strip()
    if value.startswith("/api/") or value.startswith("/assets/"):
        return f"{base_url.rstrip('/')}{value}"
    return value


def download_or_copy_media(value: str, output_path: Path, base_url: str):
    raw_value = (value or "").strip()
    if not raw_value:
        raise ValueError("media source is required")

    local_path = Path(raw_value).expanduser()
    if local_path.is_absolute() and local_path.exists():
        shutil.copyfile(local_path, output_path)
        return

    source = _resolve_app_url(raw_value, base_url)
    parsed = urlparse(source)

    if parsed.scheme == "file":
        file_path = Path(parsed.path).expanduser()
        if not file_path.exists():
            raise FileNotFoundError(f"Local file not found: {file_path}")
        shutil.copyfile(file_path, output_path)
        return

    if parsed.scheme in ("http", "https"):
        with requests.get(source, stream=True, timeout=120) as response:
            response.raise_for_status()
            with open(output_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        f.write(chunk)
        return

    if local_path.exists():
        shutil.copyfile(local_path, output_path)
        return

    raise ValueError(f"Unsupported media source: {value}")


def _fit_clip(video, target_width: int, target_height: int):
    if not target_width or not target_height:
        return video

    source_w, source_h = video.size
    scale = max(target_width / source_w, target_height / source_h)
    resized = video.resized(scale)
    x_center = resized.w / 2
    y_center = resized.h / 2
    return resized.cropped(
        x_center=x_center,
        y_center=y_center,
        width=target_width,
        height=target_height,
    )


def _segment_start(source_duration: float, segment_duration: float, index: int) -> float:
    if source_duration <= segment_duration + 0.2:
        return 0.0

    usable_duration = max(0.0, source_duration - segment_duration)
    positions = [0.08, 0.32, 0.56, 0.78, 0.18, 0.44, 0.68, 0.88]
    return min(usable_duration, usable_duration * positions[index % len(positions)])


def _make_video_segment(source_clip, target_width: int, target_height: int, segment_seconds: float, index: int):
    source_duration = float(source_clip.duration or 0)
    if source_duration <= 0:
        return None, []

    if segment_seconds > 0:
        segment_duration = min(source_duration, max(0.5, segment_seconds))
        start = _segment_start(source_duration, segment_duration, index)
        working_clip = source_clip.subclipped(start, min(source_duration, start + segment_duration))
    else:
        working_clip = source_clip

    created = []
    if working_clip is not source_clip:
        created.append(working_clip)

    fitted_clip = _fit_clip(working_clip, target_width, target_height)
    if fitted_clip is not working_clip:
        created.append(fitted_clip)

    return fitted_clip, created


def _build_video_segments(source_clips: list, duration: float, target_width: int, target_height: int, segment_seconds: float):
    if not source_clips:
        return [], []

    created_clips = []
    if len(source_clips) == 1:
        segment, created = _make_video_segment(source_clips[0], target_width, target_height, 0, 0)
        return ([segment] if segment else []), created

    video_segments = []
    cursor = 0.0
    index = 0
    max_iterations = max(1, math.ceil(duration / max(segment_seconds or 4, 0.5)) + len(source_clips) + 2)
    while cursor < duration and index < max_iterations:
        source_clip = source_clips[index % len(source_clips)]
        segment, created = _make_video_segment(
            source_clip,
            target_width,
            target_height,
            segment_seconds,
            index,
        )
        created_clips.extend(created)
        if segment:
            video_segments.append(segment)
            cursor += float(segment.duration or 0)
        index += 1

    return video_segments, created_clips


def _ffmpeg_preset(value: str | None) -> str:
    allowed = {"ultrafast", "superfast", "veryfast", "faster", "fast", "medium", "slow", "slower", "veryslow"}
    value = (value or "medium").strip().lower()
    return value if value in allowed else "medium"


def _parse_hex_color(value: str | None, fallback: tuple[int, int, int]) -> tuple[int, int, int]:
    value = (value or "").strip().lstrip("#")
    if len(value) == 3:
        value = "".join(ch * 2 for ch in value)
    if len(value) != 6:
        return fallback
    try:
        return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return fallback


def _subtitle_style(options: dict | None) -> dict:
    options = options or {}
    preset_id = options.get("subtitleStyle") or "classic"
    preset = SUBTITLE_STYLE_PRESETS.get(preset_id, SUBTITLE_STYLE_PRESETS["classic"]).copy()
    size_scale = {"small": 0.88, "normal": 1.0, "large": 1.18}.get(options.get("subtitleSize"), 1.0)
    preset["size_scale"] = preset["size_scale"] * size_scale
    preset["fill"] = _parse_hex_color(options.get("subtitleTextColor"), preset["fill"])
    preset["stroke"] = _parse_hex_color(options.get("subtitleStrokeColor"), preset["stroke"])
    preset["bg"] = _parse_hex_color(options.get("subtitleBgColor"), preset["bg"])
    if options.get("subtitleBackground") is False:
        preset["bg_alpha"] = 0
    if options.get("subtitleBgOpacity") is not None:
        try:
            preset["bg_alpha"] = max(0, min(230, int(options.get("subtitleBgOpacity"))))
        except (TypeError, ValueError):
            pass
    return preset


def _normalize_subtitle_text(text: str) -> str:
    text = re.sub(r"\s+", " ", (text or "")).strip()
    return re.sub(r"(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])", "", text)


def _make_subtitle_image(text: str, width: int, output_path: Path, options: dict | None = None):
    text = _normalize_subtitle_text(text)
    if not text:
        return None

    style = _subtitle_style(options)
    font_path = "/System/Library/Fonts/STHeiti Medium.ttc"
    font_size = max(24, min(58, int(width * 0.052 * style["size_scale"])))
    font = ImageFont.truetype(font_path, font_size)
    max_chars = max(10, int(width / (font_size * 0.66)))
    lines = _split_long_subtitle(text[:160], max_chars)
    lines = lines[:3] or [text[:40]]

    padding_x = int(width * 0.045)
    padding_y = int(font_size * 0.6)
    line_height = int(font_size * 1.35)
    height = padding_y * 2 + line_height * len(lines)

    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    line_widths = []
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font, stroke_width=style["stroke_width"])
        line_widths.append(bbox[2] - bbox[0])

    if style["bg_alpha"] > 0:
        max_line_width = max(line_widths) if line_widths else width
        bg_width = min(width - int(width * 0.06), max_line_width + padding_x * 2)
        bg_left = int((width - bg_width) / 2)
        draw.rounded_rectangle(
            (bg_left, 0, bg_left + bg_width, height),
            radius=max(12, int(font_size * 0.35)),
            fill=(*style["bg"], style["bg_alpha"]),
        )

    y = padding_y
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font, stroke_width=style["stroke_width"])
        text_width = bbox[2] - bbox[0]
        x = max(padding_x, (width - text_width) // 2)
        draw.text(
            (x, y),
            line,
            font=font,
            fill=(*style["fill"], 255),
            stroke_width=style["stroke_width"],
            stroke_fill=(*style["stroke"], 235),
        )
        y += line_height

    image.save(output_path)
    return output_path


def _split_long_subtitle(text: str, max_chars: int) -> list[str]:
    if len(text) <= max_chars:
        return [text]

    parts = re.findall(r"[^，,、]+[，,、]?", text)
    if len(parts) <= 1:
        return [text[i:i + max_chars] for i in range(0, len(text), max_chars)]

    chunks = []
    current = ""
    for part in parts:
        part = part.strip()
        if not part:
            continue
        if current and len(current) + len(part) > max_chars:
            chunks.append(current)
            current = part
        else:
            current += part
    if current:
        chunks.append(current)

    normalized = []
    for chunk in chunks:
        normalized.extend(
            chunk[i:i + max_chars]
            for i in range(0, len(chunk), max_chars)
        )
    return normalized


def _split_subtitle_text(text: str, max_chars: int = 28) -> list[str]:
    text = _normalize_subtitle_text(text)
    if not text:
        return []

    sentences = re.findall(r"[^。！？!?；;\n]+[。！？!?；;]?", text)
    if not sentences:
        sentences = [text]

    chunks = []
    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue
        chunks.extend(_split_long_subtitle(sentence, max_chars))
    return chunks[:120]


def _subtitle_timings(lines: list[str], duration: float) -> list[tuple[str, float, float]]:
    if not lines:
        return []
    if len(lines) == 1:
        return [(lines[0], 0, duration)]

    weights = [max(len(re.sub(r"\s+", "", line)), 1) for line in lines]
    total_weight = sum(weights) or len(lines)
    raw_durations = [max(0.9, duration * weight / total_weight) for weight in weights]
    scale = duration / sum(raw_durations)
    durations = [item * scale for item in raw_durations]

    timings = []
    cursor = 0.0
    for index, line in enumerate(lines):
        if index == len(lines) - 1:
            item_duration = max(0.1, duration - cursor)
        else:
            item_duration = max(0.1, durations[index])
        timings.append((line, cursor, item_duration))
        cursor += item_duration
    return timings


def _timings_for_text_range(text: str, start: float, end: float, max_chars: int) -> list[tuple[str, float, float]]:
    duration = max(0.1, end - start)
    lines = _split_subtitle_text(text, max_chars=max_chars)
    if not lines:
        return []
    return [
        (line, start + rel_start, item_duration)
        for line, rel_start, item_duration in _subtitle_timings(lines, duration)
    ]


def _subtitle_y_position(video_height: int, subtitle_height: int, position: str) -> int:
    position = (position or "bottom").lower()
    if position == "top":
        return max(0, int(video_height * 0.1))
    if position == "middle":
        return max(0, int((video_height - subtitle_height) / 2))
    return max(0, video_height - subtitle_height - int(video_height * 0.08))


def _srt_timestamp(seconds: float) -> str:
    milliseconds = max(0, int(round(seconds * 1000)))
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def _write_srt(timings: list[tuple[str, float, float]], output_path: Path):
    if not timings:
        return None
    lines = []
    for index, (text, start, item_duration) in enumerate(timings, start=1):
        end = start + item_duration
        lines.append(str(index))
        lines.append(f"{_srt_timestamp(start)} --> {_srt_timestamp(end)}")
        lines.append(text)
        lines.append("")
    output_path.write_text("\n".join(lines), encoding="utf-8")
    return output_path


def _make_subtitle_clips(text: str, duration: float, width: int, height: int, work_dir: Path, ImageClip, options: dict):
    mode = options.get("subtitleMode") or "sentence"
    subtitle_position = options.get("subtitlePosition") or "bottom"
    if mode == "full":
        subtitle_image = _make_subtitle_image(text, width, work_dir / "subtitle_full.png", options)
        if not subtitle_image:
            return []
        image_clip = ImageClip(str(subtitle_image))
        return [
            image_clip
            .with_duration(duration)
            .with_position(("center", _subtitle_y_position(height, image_clip.h, subtitle_position)))
        ]

    max_chars = int(options.get("subtitleMaxChars") or 28)
    lines = _split_subtitle_text(text, max_chars=max_chars)
    clips = []
    for index, (line, start, item_duration) in enumerate(_subtitle_timings(lines, duration)):
        subtitle_image = _make_subtitle_image(line, width, work_dir / f"subtitle_{index:03d}.png", options)
        if not subtitle_image:
            continue
        image_clip = ImageClip(str(subtitle_image))
        clips.append(
            image_clip
            .with_start(start)
            .with_duration(item_duration)
            .with_position(("center", _subtitle_y_position(height, image_clip.h, subtitle_position)))
        )
    return clips


def _make_timed_subtitle_clips(timings: list[tuple[str, float, float]], width: int, height: int, work_dir: Path, ImageClip, options: dict):
    subtitle_position = options.get("subtitlePosition") or "bottom"
    clips = []
    for index, (line, start, item_duration) in enumerate(timings):
        subtitle_image = _make_subtitle_image(line, width, work_dir / f"subtitle_timed_{index:03d}.png", options)
        if not subtitle_image:
            continue
        image_clip = ImageClip(str(subtitle_image))
        clips.append(
            image_clip
            .with_start(max(0, start))
            .with_duration(max(0.1, item_duration))
            .with_position(("center", _subtitle_y_position(height, image_clip.h, subtitle_position)))
        )
    return clips


def render_video(payload: dict, base_url: str) -> dict:
    from moviepy import AudioFileClip, CompositeVideoClip, ImageClip, VideoFileClip, concatenate_videoclips

    task_id = (payload.get("taskId") or "").strip() or str(uuid.uuid4())[:8]
    options = payload.get("options") or {}
    work_dir = TMP_DIR / task_id
    if work_dir.exists():
        shutil.rmtree(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)

    output_path = Path(OUTPUT_DIR) / f"{task_id}_moviepy_video.mp4"
    subtitle_output_path = Path(OUTPUT_DIR) / f"{task_id}_subtitles.srt"

    source_video_clips = []
    intermediate_clips = []
    video_clips = []
    audio_clip = None
    sequence_clip = None
    final_clip = None
    subtitle_clips = []
    subtitle_source = "none"
    subtitle_timings_data = []

    try:
        video_sources = payload.get("videoUrls") or payload.get("video_urls") or []
        if isinstance(video_sources, str):
            video_sources = [video_sources]
        video_sources = [source.strip() for source in video_sources if source and source.strip()]
        single_video_source = payload.get("videoUrl") or payload.get("backgroundVideoUrl") or ""
        if single_video_source and single_video_source.strip() and single_video_source.strip() not in video_sources:
            video_sources.insert(0, single_video_source.strip())
        if not video_sources:
            raise ValueError("video source is required")

        audio_source = payload.get("audioUrl") or ""

        raw_audio = work_dir / f"input_audio{_url_suffix(audio_source, '.wav')}"

        download_or_copy_media(audio_source, raw_audio, base_url)

        audio_clip = AudioFileClip(str(raw_audio))
        duration = max(float(audio_clip.duration or 0), 0.1)
        target_width = int(options.get("width") or 0)
        target_height = int(options.get("height") or 0)
        max_clip_seconds = float(options.get("maxClipSeconds") or options.get("clipDuration") or 4)

        for index, video_source in enumerate(video_sources):
            raw_video = work_dir / f"input_video_{index}{_url_suffix(video_source, '.mp4')}"
            download_or_copy_media(video_source, raw_video, base_url)
            clip = VideoFileClip(str(raw_video))
            if not clip.duration:
                clip.close()
                continue
            source_video_clips.append(clip)

        segment_seconds = max_clip_seconds if len(source_video_clips) > 1 else 0
        video_clips, created_clips = _build_video_segments(
            source_video_clips,
            duration,
            target_width,
            target_height,
            segment_seconds,
        )
        intermediate_clips.extend(created_clips)

        if not video_clips:
            raise ValueError("no readable video clips")

        sequence_clip = (
            video_clips[0]
            if len(video_clips) == 1
            else concatenate_videoclips(video_clips, method="compose")
        )

        loop_video = bool(options.get("loopVideo", True))
        if sequence_clip.duration < duration and loop_video:
            repeats = max(1, math.ceil(duration / sequence_clip.duration))
            final_clip = concatenate_videoclips([sequence_clip] * repeats, method="compose").subclipped(0, duration)
        else:
            final_clip = sequence_clip.subclipped(0, min(duration, sequence_clip.duration))

        final_clip = final_clip.with_duration(duration).with_audio(audio_clip)

        subtitle_text = (payload.get("subtitle") or payload.get("script") or "").strip()
        if options.get("addSubtitle"):
            if subtitle_text:
                max_chars = int(options.get("subtitleMaxChars") or 28)
                lines = _split_subtitle_text(subtitle_text, max_chars=max_chars)
                subtitle_timings_data = _subtitle_timings(lines, duration)
                subtitle_clips = _make_timed_subtitle_clips(
                    subtitle_timings_data,
                    final_clip.w,
                    final_clip.h,
                    work_dir,
                    ImageClip,
                    options,
                )
                if subtitle_clips:
                    subtitle_source = "estimated"

            if subtitle_clips:
                final_clip = CompositeVideoClip([final_clip, *subtitle_clips], size=final_clip.size)
                _write_srt(subtitle_timings_data, subtitle_output_path)

        final_clip.write_videofile(
            str(output_path),
            codec="libx264",
            audio_codec="aac",
            fps=float(options.get("fps") or 30),
            preset=_ffmpeg_preset(options.get("ffmpegPreset")),
            ffmpeg_params=["-pix_fmt", "yuv420p", "-crf", str(options.get("crf") or 18)],
            logger=None,
        )

        return {
            "taskId": task_id,
            "video_path": str(output_path),
            "video_url": f"/api/v1/video/{task_id}",
            "duration": round(duration, 2),
            "source_count": len(source_video_clips),
            "segment_count": len(video_clips),
            "clip_seconds": max_clip_seconds if len(source_video_clips) > 1 else None,
            "subtitle_count": len(subtitle_clips),
            "subtitle_position": options.get("subtitlePosition") or "bottom",
            "subtitle_source": subtitle_source,
            "subtitle_style": options.get("subtitleStyle") or "classic",
            "subtitle_size": options.get("subtitleSize") or "normal",
            "subtitle_path": str(subtitle_output_path) if subtitle_output_path.exists() else None,
            "subtitle_url": f"/api/v1/subtitle/{task_id}" if subtitle_output_path.exists() else None,
        }
    finally:
        clips_to_close = [
            *subtitle_clips,
            final_clip,
            audio_clip,
            sequence_clip,
            *video_clips,
            *intermediate_clips,
            *source_video_clips,
        ]
        closed = set()
        for clip in clips_to_close:
            try:
                if clip and id(clip) not in closed:
                    closed.add(id(clip))
                    clip.close()
            except Exception:
                pass
        shutil.rmtree(work_dir, ignore_errors=True)
