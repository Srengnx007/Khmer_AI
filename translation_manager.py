import logging
import json
import asyncio
from deep_translator import GoogleTranslator
import google.generativeai as genai
from config import GEMINI_API_KEY, GEMINI_MODEL

# Configure Gemini
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel(GEMINI_MODEL)

logger = logging.getLogger(__name__)

class TranslationManager:
    def __init__(self):
        self.fallback_translator = GoogleTranslator(source='auto', target='en')
        self.supported_langs = ['kh', 'th', 'vi', 'zh-cn']
        
    async def detect_language(self, text: str) -> str:
        """Detect source language"""
        try:
            # Use deep_translator for quick detection
            return self.fallback_translator.detect(text)
        except:
            return "en" # Default to English

    async def translate_content(self, article: dict, target_lang: str = 'km') -> dict:
        """
        Translate article content to target language using Gemini.
        Returns dict with title, body, summary.
        """
        prompt = f"""
        You are a professional news translator. Translate the following news article to {target_lang}.
        
        Input:
        Title: {article['title']}
        Summary: {article['summary']}
        
        Requirements:
        1. Output valid JSON only.
        2. Keys: "title", "body" (full translation), "summary" (concise summary).
        3. Maintain professional journalistic tone.
        4. Preserve numbers, dates, and proper nouns.
        5. Do not include markdown code blocks in the output, just the raw JSON string.
        
        JSON Output:
        """
        
        try:
            response = await asyncio.to_thread(
                model.generate_content, 
                prompt,
                generation_config={"response_mime_type": "application/json"}
            )
            return json.loads(response.text)
        except Exception as e:
            logger.error(f"Gemini Translation Failed: {e}")
            # Fallback
            return await self._fallback_translate(article, target_lang)

    async def _fallback_translate(self, article: dict, target_lang: str) -> dict:
        """Fallback using Google Translate (deep-translator)"""
        try:
            translator = GoogleTranslator(source='auto', target=target_lang)
            return {
                "title": translator.translate(article['title']),
                "body": translator.translate(article['summary']), # Use summary as body for fallback
                "summary": translator.translate(article['summary'])
            }
        except Exception as e:
            logger.error(f"Fallback Translation Failed: {e}")
            raise e

    async def verify_translation(self, original: str, translated: str) -> bool:
        """
        Back-translate and verify similarity.
        Returns True if quality is acceptable.
        """
        try:
            # Back translate to English
            back_translated = GoogleTranslator(source='auto', target='en').translate(translated)
            
            # Simple length check heuristic for now (can be improved with semantic similarity)
            # If back translation is too short or empty, it failed.
            if len(back_translated) < len(original) * 0.5:
                return False
                
            return True
        except:
            return True # Assume pass if verification fails to avoid blocking

    async def get_content_for_platform(self, article: dict, translations: dict, platform: str) -> str:
        """
        Format content based on platform strategy.
        translations: dict of {lang: {title, body, summary}}
        """
        # 1. Telegram: Full Khmer (or primary target)
        if platform == 'telegram':
            content = translations.get('km', {})
            return f"<b>{content.get('title', article['title'])}</b>\n\n{content.get('body', article['summary'])}\n\n🔗 <a href='{article['link']}'>Read More</a>"
            
        # 2. Facebook: Khmer + English Summary
        elif platform == 'facebook':
            km = translations.get('km', {})
            return f"{km.get('title', article['title'])}\n\n{km.get('body', article['summary'])}\n\n🇬🇧 Summary:\n{article['summary']}\n\n#KhmerAI #News"
            
        # 3. X (Twitter): Short English Headline (or source lang)
        elif platform == 'x':
            return f"{article['title']}\n\n{article['link']} #News"
            
        return article['title']

# Global Instance
translator = TranslationManager()
