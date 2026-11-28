"""Validate and normalize product photos before saving them."""

from io import BytesIO

from PIL import Image, ImageOps, UnidentifiedImageError

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_PIXELS = 25_000_000
MAX_SIDE = 720
IMAGE_TYPES = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp"}


class InvalidProductImageError(ValueError):
    pass


def _webp_size(content: bytes) -> tuple[int, int] | None:
    """Read the canvas from the first RIFF chunk before libwebp allocates it."""
    chunk = content[12:16]
    if chunk == b"VP8X" and len(content) >= 30:
        return int.from_bytes(content[24:27], "little") + 1, int.from_bytes(content[27:30], "little") + 1
    if chunk == b"VP8L" and len(content) >= 25 and content[20] == 0x2F:
        bits = int.from_bytes(content[21:25], "little")
        return (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
    if chunk == b"VP8 " and len(content) >= 30 and content[23:26] == b"\x9d\x01\x2a":
        return int.from_bytes(content[26:28], "little") & 0x3FFF, int.from_bytes(content[28:30], "little") & 0x3FFF
    return None


def _check_size(width: int, height: int) -> None:
    if width * height > MAX_PIXELS:
        raise InvalidProductImageError("Choose an image with at most 25 megapixels.")


def normalize_product_image(content: bytes, content_type: str | None) -> bytes:
    if len(content) > MAX_UPLOAD_BYTES:
        raise InvalidProductImageError("Choose an image of 10 MB or less.")
    if content.startswith(b"RIFF") and content[8:12] == b"WEBP":
        size = _webp_size(content)
        if size is None:
            raise InvalidProductImageError("Choose a valid JPEG, PNG or WebP image.")
        _check_size(*size)
    try:
        # Pillow selects the decoder by file signature and verifies the image can be decoded.
        with Image.open(BytesIO(content), formats=list(IMAGE_TYPES)) as original:
            if content_type not in {None, "", "application/octet-stream", IMAGE_TYPES[original.format]}:
                raise InvalidProductImageError("The file type does not match the image.")
            _check_size(*original.size)
            if getattr(original, "is_animated", False):
                raise InvalidProductImageError("Choose a still image.")
            original.load()
            oriented = ImageOps.exif_transpose(original)
            mode = "RGBA" if oriented.has_transparency_data else "RGB"
            oriented = oriented.convert(mode)
            oriented.thumbnail((MAX_SIDE, MAX_SIDE), Image.Resampling.LANCZOS)

            # A fresh pixel buffer carries none of the input's EXIF, ICC or text metadata.
            clean = Image.new(mode, oriented.size)
            clean.paste(oriented)
            buffer = BytesIO()
            clean.save(buffer, "WEBP", quality=85)
            return buffer.getvalue()
    except InvalidProductImageError:
        raise
    except (
        UnidentifiedImageError,
        OSError,
        Image.DecompressionBombError,
        SyntaxError,
        OverflowError,
        ValueError,
    ) as exc:
        raise InvalidProductImageError("Choose a valid JPEG, PNG or WebP image.") from exc
