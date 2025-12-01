import io
import asyncio
import logging
import aiohttp
from PIL import Image, ImageDraw, ImageFont, ImageEnhance
import time

# Try importing NSFW detection
try:
    from nudenet import NudeDetector
    NSFW_MODEL_AVAILABLE = True
    nude_detector = NudeDetector()
except ImportError:
    NSFW_MODEL_AVAILABLE = False

logger = logging.getLogger(__name__)

class ImageProcessor:
    def __init__(self):
        self.MIN_WIDTH = 400
        self.MIN_HEIGHT = 300
        self.MAX_DIMENSION = 4096
        self.MAX_SIZE_BYTES = 5 * 1024 * 1024 # 5MB (Telegram limit)
        self.CACHE = {} 
        
    async def process_image(self, url: str) -> tuple:
        """
        Download, check NSFW, watermark, and compress.
        Returns: (processed_bytes, content_type, is_valid)
        """
        if not url: return None, None, False
        if url in self.CACHE: return self.CACHE[url]

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=10) as resp:
                    if resp.status != 200: return None, None, False
                    content = await resp.read()
                    
                    result = await asyncio.to_thread(self._process_cpu_bound, content, url)
                    if result:
                        self.CACHE[url] = result
                        return result
                    return None, None, False

        except Exception as e:
            logger.error(f"❌ Image Processing Error: {e}")
            return None, None, False

    def _process_cpu_bound(self, content: bytes, url: str) -> tuple:
        try:
            img = Image.open(io.BytesIO(content))
            
            # 1. Validation
            w, h = img.size
            if w < self.MIN_WIDTH or h < self.MIN_HEIGHT:
                return None
                
            if img.mode in ("RGBA", "P"):
                img = img.convert("RGB")
            
            # 2. NSFW Check
            if self._is_nsfw(img, url):
                logger.warning(f"🔞 NSFW Detected: {url}")
                return None

            # 3. Resize if too huge
            if w > self.MAX_DIMENSION or h > self.MAX_DIMENSION:
                img.thumbnail((self.MAX_DIMENSION, self.MAX_DIMENSION))

            # 4. Watermark
            self._add_watermark(img)

            # 5. Compression
            output = io.BytesIO()
            img.save(output, format="JPEG", quality=85, optimize=True)
            processed_data = output.getvalue()
            
            # Aggressive compression if still too big
            if len(processed_data) > self.MAX_SIZE_BYTES:
                output = io.BytesIO()
                img.save(output, format="JPEG", quality=65, optimize=True)
                processed_data = output.getvalue()
            
            return (processed_data, "image/jpeg", True)
            
        except Exception as e:
            logger.error(f"Image CPU error: {e}")
            return None

    def _is_nsfw(self, img: Image.Image, url: str) -> bool:
        """Check for NSFW content"""
        if NSFW_MODEL_AVAILABLE:
            try:
                # Save temp file for NudeNet
                temp_path = f"/tmp/nsfw_check_{int(time.time())}.jpg"
                img.save(temp_path)
                detections = nude_detector.detect(temp_path)
                for d in detections:
                    if d['label'] in ['EXPOSED_GENITALIA', 'EXPOSED_BREAST_F', 'EXPOSED_BUTTOCKS'] and d['score'] > 0.7:
                        return True
            except Exception as e:
                logger.error(f"NudeNet failed: {e}")
        
        # Fallback: Skin Tone Heuristic
        small = img.resize((64, 64))
        pixels = list(small.getdata())
        skin_pixels = 0
        for r, g, b in pixels:
            if r > 95 and g > 40 and b > 20 and \
               max(r, g, b) - min(r, g, b) > 15 and \
               abs(r - g) > 15 and r > g and r > b:
                skin_pixels += 1
        return (skin_pixels / len(pixels)) > 0.6

    def _add_watermark(self, img: Image.Image):
        """Add 'Khmer AI News' watermark"""
        try:
            draw = ImageDraw.Draw(img)
            w, h = img.size
            text = "Khmer AI News"
            
            # Calculate size
            fontsize = int(h * 0.03) # 3% of height
            if fontsize < 12: fontsize = 12
            
            # Try to load font, fallback to default
            try:
                font = ImageFont.truetype("arial.ttf", fontsize)
            except:
                font = ImageFont.load_default()

            # Position: Bottom Right
            # Get text bounding box
            bbox = draw.textbbox((0, 0), text, font=font)
            text_w = bbox[2] - bbox[0]
            text_h = bbox[3] - bbox[1]
            
            x = w - text_w - 10
            y = h - text_h - 10
            
            # Draw shadow
            draw.text((x+1, y+1), text, font=font, fill="black")
            # Draw text
            draw.text((x, y), text, font=font, fill=(255, 255, 255, 128)) # Semi-transparent white
            
        except Exception as e:
            logger.warning(f"Watermark failed: {e}")

# Global Instance
image_processor = ImageProcessor()
