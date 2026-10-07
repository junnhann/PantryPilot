"""Prepare user photos for the AI: fix rotation, resize to ~1000px wide, re-encode as JPEG.

Smaller images = faster, cheaper, fewer rate-limit problems, and it strips
location metadata (EXIF) from phone photos before anything leaves the server.
"""
import io

from PIL import Image, ImageOps

MAX_WIDTH = 1000
MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB


def prepare_image(data: bytes) -> bytes:
    from app.ai import AIError  # imported here to avoid a circular import

    if not data:
        raise AIError("The uploaded file is empty.", status=400)
    if len(data) > MAX_UPLOAD_BYTES:
        raise AIError("That image is too large (max 10 MB).", status=400)
    try:
        img = Image.open(io.BytesIO(data))
        img = ImageOps.exif_transpose(img)  # phones store rotation in metadata; apply it
        img = img.convert("RGB")  # drops alpha/palette so JPEG saving always works
    except Exception:
        raise AIError("Couldn't read that image. Please upload a JPG or PNG photo.", status=400)

    if img.width > MAX_WIDTH:
        img = img.resize((MAX_WIDTH, round(img.height * MAX_WIDTH / img.width)), Image.LANCZOS)

    out = io.BytesIO()
    img.save(out, format="JPEG", quality=85)
    return out.getvalue()
