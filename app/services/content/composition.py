import os
import tempfile
from typing import Optional

from loguru import logger


def mux_narration(video_bytes: bytes, audio_bytes: bytes) -> Optional[bytes]:
    """Replace a generated video's audio track with the narration.

    Duration mismatch is resolved by trimming to the shorter of the two: a
    video that outlasts the narration ends in silence, and narration that
    outlasts the video is cut. Extending either one is a creative decision the
    generation engine has no basis to make.

    Returns None on any failure — the caller keeps the silent video rather
    than failing the whole piece.
    """
    from moviepy import AudioFileClip, VideoFileClip

    video_path = audio_path = output_path = None
    video_clip = audio_clip = composed = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as handle:
            handle.write(video_bytes)
            video_path = handle.name
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as handle:
            handle.write(audio_bytes)
            audio_path = handle.name
        output_path = tempfile.mktemp(suffix=".mp4")

        video_clip = VideoFileClip(video_path)
        audio_clip = AudioFileClip(audio_path)
        duration = min(video_clip.duration, audio_clip.duration)

        composed = video_clip.subclipped(0, duration).with_audio(
            audio_clip.subclipped(0, duration)
        )
        composed.write_videofile(
            output_path, codec="libx264", audio_codec="aac", logger=None
        )

        with open(output_path, "rb") as handle:
            return handle.read()
    except Exception as exc:  # noqa: BLE001 - composition is best-effort
        logger.warning(f"could not mux narration into generated video: {exc}")
        return None
    finally:
        for clip in (composed, audio_clip, video_clip):
            if clip is not None:
                try:
                    clip.close()
                except Exception:  # noqa: BLE001
                    pass
        for path in (video_path, audio_path, output_path):
            if path and os.path.exists(path):
                try:
                    os.unlink(path)
                except OSError:
                    pass
