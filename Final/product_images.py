"""Public product photos stored on the same persistent disk as the shared database."""
import hashlib
import io
import os
import re
import tempfile
import warnings
from pathlib import Path
from PIL import Image, ImageOps, UnidentifiedImageError

MAX_BYTES = 8 * 1024 * 1024
MAX_PIXELS = 20000000

def save(data_dir, raw):
    if not raw or len(raw) > MAX_BYTES:
        raise ValueError('Choose an image under 8 MB.')
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(raw)) as source:
                if source.format not in ('JPEG', 'PNG', 'WEBP'):
                    raise ValueError('Choose a JPG, PNG or WebP image.')
                if source.width * source.height > MAX_PIXELS:
                    raise ValueError('Choose an image smaller than 20 megapixels.')
                source.load()
                image = ImageOps.exif_transpose(source).convert('RGBA' if source.mode in ('RGBA', 'LA', 'P') else 'RGB')
                image.thumbnail((2000, 2000))
                output = io.BytesIO()
                image.save(output, format='WEBP', quality=90, method=4)
                normalized = output.getvalue()
    except (UnidentifiedImageError, OSError, SyntaxError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise ValueError('This image could not be read. Choose a valid JPG, PNG or WebP image.')
    directory = Path(data_dir) / 'product-images'
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    name = hashlib.sha256(normalized).hexdigest() + '.webp'
    # Complete the file before publishing its immutable URL, including simultaneous uploads.
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=directory, delete=False) as file:
            temporary = file.name
            file.write(normalized)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, directory / name)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)
    return {'image': '/media/products/' + name}

def read(data_dir, name):
    if not re.fullmatch(r'[0-9a-f]{64}\.webp', name):
        raise ValueError('Image not found.')
    try:
        return (Path(data_dir) / 'product-images' / name).read_bytes()
    except FileNotFoundError:
        raise ValueError('Image not found.')
