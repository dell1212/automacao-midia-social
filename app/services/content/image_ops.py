import io
from typing import Optional

from loguru import logger
from PIL import Image

# Ratios the catalog can request. Values are width / height.
RATIO_FRACTIONS: dict[str, float] = {
    "9:16": 9 / 16,
    "16:9": 16 / 9,
    "1:1": 1.0,
    "4:5": 4 / 5,
    "5:4": 5 / 4,
    "3:4": 3 / 4,
    "4:3": 4 / 3,
}

# Above this much cropping the subject (usually a face) starts leaving the
# frame, so pad instead of cutting.
CROP_TOLERANCE = 0.15

_PAD_COLOR = (18, 18, 18)


def parse_ratio(ratio: Optional[str]) -> Optional[float]:
    if not ratio:
        return None
    known = RATIO_FRACTIONS.get(ratio)
    if known is not None:
        return known
    if ":" in ratio:
        width, _, height = ratio.partition(":")
        try:
            return float(width) / float(height)
        except (TypeError, ValueError, ZeroDivisionError):
            return None
    return None


def normalize_to_ratio(data: bytes, target_ratio: Optional[str]) -> tuple[bytes, int, int]:
    """Reshape an image to `target_ratio` without distorting it.

    An avatar's reference image is registered once and reused across output
    formats, so a 1:1 portrait feeding a 9:16 video is the common case. Sending
    it raw makes image-to-video providers stretch or reject the frame. Small
    mismatches are center-cropped; larger ones are padded, which keeps the
    subject intact at the cost of neutral bars.

    Returns (image_bytes, width, height). Input is returned untouched when the
    ratio already matches or cannot be parsed.
    """
    target = parse_ratio(target_ratio)
    if target is None:
        return data, 0, 0

    with Image.open(io.BytesIO(data)) as image:
        image = image.convert("RGB")
        width, height = image.size
        current = width / height

        if abs(current - target) < 0.01:
            return data, width, height

        crop_loss = abs(current - target) / max(current, target)

        if crop_loss <= CROP_TOLERANCE:
            if current > target:
                new_width = int(round(height * target))
                left = (width - new_width) // 2
                box = (left, 0, left + new_width, height)
            else:
                new_height = int(round(width / target))
                top = (height - new_height) // 2
                box = (0, top, width, top + new_height)
            result = image.crop(box)
            logger.info(
                f"normalized base image by cropping to {target_ratio}: "
                f"{width}x{height} -> {result.size[0]}x{result.size[1]}"
            )
        else:
            if current > target:
                canvas_width, canvas_height = width, int(round(width / target))
            else:
                canvas_width, canvas_height = int(round(height * target)), height
            result = Image.new("RGB", (canvas_width, canvas_height), _PAD_COLOR)
            result.paste(
                image,
                ((canvas_width - width) // 2, (canvas_height - height) // 2),
            )
            logger.info(
                f"normalized base image by padding to {target_ratio}: "
                f"{width}x{height} -> {canvas_width}x{canvas_height}"
            )

        buffer = io.BytesIO()
        result.save(buffer, format="PNG")
        return buffer.getvalue(), result.size[0], result.size[1]
