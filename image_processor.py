import io
import asyncio
import logging
import hashlib
import aiohttp
from PIL import Image, ImageOps
import time

logger = logging.getLogger(__name__)

class ImageProcessor:
    def __init__(self):
        self.MIN_WIDTH = 400
        self.MIN_HEIGHT = 300
        self.MAX_DIMENSION = 4096
        self.MAX_SIZE_BYTES = 3 * 1024 * 1024 # 3MB
        self.CACHE = {} # Simple in-memory cache for processed URLs
        
    async def process_image(self, url: str) -> tuple:
        """
        Download and process image.
        Returns: (processed_bytes, content_type, is_valid)
        """
        if not url: return None, None, False
        
        # Check Cache
        if url in self.CACHE:
            return self.CACHE[url]

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=10) as resp:
                    if resp.status != 200:
                        return None, None, False
                    
                    content = await resp.read()
                    
                    # 1. Validate Format & Dimensions using Pillow
                    try:
                        img = Image.open(io.BytesIO(content))
                    except Exception:
                        return None, None, False # Not a valid image
                        
                    # Check dimensions
                    w, h = img.size
                    if w < self.MIN_WIDTH or h < self.MIN_HEIGHT:
                        logger.warning(f"⚠️ Image too small ({w}x{h}): {url}")
                        return None, None, False
                        
                    if w > self.MAX_DIMENSION or h > self.MAX_DIMENSION:
                        img.thumbnail((self.MAX_DIMENSION, self.MAX_DIMENSION))
                        
                    # 2. Auto-crop (Simple center crop to 16:9 if extremely wide/tall)
                    # For now, we just ensure it's RGB
                    if img.mode in ("RGBA", "P"):
                        img = img.convert("RGB")
                        
                    # 3. Strip EXIF (Pillow does this by default unless you copy it)
                    # We are creating a new image bytes, so EXIF is gone.
                    
                    # 4. NSFW Check (Basic Skin Tone Heuristic)
                    if self._is_nsfw(img):
                        logger.warning(f"⚠️ Potential NSFW Image detected: {url}")
                        return None, None, False
                        
                    # 5. Compress if needed
                    output = io.BytesIO()
                    img.save(output, format="JPEG", quality=85, optimize=True, progressive=True)
                    processed_data = output.getvalue()
                    
                    # Check size
                    if len(processed_data) > self.MAX_SIZE_BYTES:
                        # Try harder compression
                        output = io.BytesIO()
                        img.save(output, format="JPEG", quality=65, optimize=True)
                        processed_data = output.getvalue()
                    
                    result = (processed_data, "image/jpeg", True)
                    self.CACHE[url] = result
                    return result

        except Exception as e:
            logger.error(f"❌ Image Processing Error: {e}")
            return None, None, False

    def _is_nsfw(self, img: Image.Image) -> bool:
        """
        Basic heuristic: Check for excessive skin-tone pixels.
        This is NOT a replacement for a real ML model but catches obvious cases.
        """
        try:
            # Resize for speed
            small = img.resize((64, 64))
            pixels = list(small.getdata())
            skin_pixels = 0
            total_pixels = len(pixels)
            
            for r, g, b in pixels:
                # Simple skin tone detection rule (YCbCr-like logic in RGB)
                if r > 95 and g > 40 and b > 20 and \
                   max(r, g, b) - min(r, g, b) > 15 and \
                   abs(r - g) > 15 and r > g and r > b:
                    skin_pixels += 1
                    
            ratio = skin_pixels / total_pixels
            return ratio > 0.6 # If >60% skin, flag as potential NSFW
        except Exception:
            return False

# Global Instance
image_processor = ImageProcessor()
