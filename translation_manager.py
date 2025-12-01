import logging
import json
import asyncio
import time
import re
import backoff
from deep_translator import GoogleTranslator
import google.generativeai as genai
from config import GEMINI_API_KEY, GEMINI_MODEL
import db

# Configure Gemini
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel(GEMINI_MODEL)

logger = logging.getLogger(__name__)

class CircuitBreaker:
    def __init__(self, failure_threshold=5, recovery_timeout=600):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.failures = 0
        self.last_failure_time = 0
        self.state = "CLOSED"

    def record_failure(self):
        self.failures += 1
        self.last_failure_time = time.time()
        if self.failures >= self.failure_threshold:
            self.state = "OPEN"
            logger.warning(f"🔌 Circuit Breaker OPENED: Too many failures ({self.failures})")

    def record_success(self):
        self.failures = 0
        self.state = "CLOSED"

    def allow_request(self):
        if self.state == "CLOSED": return True
        if self.state == "OPEN":
            if time.time() - self.last_failure_time > self.recovery_timeout:
                self.state = "HALF-OPEN"
                return True
            return False
        return True

class TranslationManager:
    def __init__(self):
        self.fallback_translator = GoogleTranslator(source='auto', target='en')
        self.circuit_breaker = CircuitBreaker()
        
    async def detect_language(self, text: str) -> str:
        try:
            return self.fallback_translator.detect(text)
        except:
            return "en"

    @backoff.on_exception(backoff.expo, Exception, max_tries=3)
    async def translate_content(self, article: dict, target_lang: str = 'km') -> dict:
        """
        Translate article content to target language using Gemini.
        Checks DB cache first.
        """
        # 1. Check Cache
        cached = await db.get_translation(article['article_id'], target_lang)
        if cached:
            logger.info(f"♻️ Translation Cache Hit: {article['title'][:20]}")
            return cached

        # 2. Circuit Breaker
        if not self.circuit_breaker.allow_request():
            logger.warning("Translation skipped (Circuit Breaker)")
            return await self._fallback_translate(article, target_lang)

        # 3. Gemini Translation
        prompt = self._get_prompt(article, target_lang)
        
        try:
            response = await asyncio.to_thread(
                model.generate_content, 
                prompt,
                generation_config={"response_mime_type": "application/json"}
            )
            
            # Parse JSON response
            parsed = json.loads(response.text)
            
            # Handle both dict and list responses
            if isinstance(parsed, list):
                # If it's a list, take the first element
                if len(parsed) > 0 and isinstance(parsed[0], dict):
                    result = parsed[0]
                else:
                    raise ValueError(f"Invalid list response from Gemini: {parsed}")
            elif isinstance(parsed, dict):
                result = parsed
            else:
                raise ValueError(f"Unexpected response type from Gemini: {type(parsed)}")
            
            # Verify result has required fields
            if not result.get('title') or not result.get('body'):
                raise ValueError("Translation missing required fields (title, body)")
            
            # 4. Verify
            if not await self.verify_translation(article['summary'], result.get('summary', result.get('body', ''))):
                raise ValueError("Verification failed")
                
            self.circuit_breaker.record_success()
            
            # 5. Save to Cache
            await db.save_translation(article['article_id'], target_lang, result)
            
            return result
            
        except Exception as e:
            logger.error(f"Gemini Translation Failed: {e}")
            self.circuit_breaker.record_failure()
            return await self._fallback_translate(article, target_lang)

    def _get_prompt(self, article, target_lang):
        lang_map = {'km': 'Khmer', 'th': 'Thai', 'vi': 'Vietnamese', 'zh-cn': 'Chinese (Simplified)'}
        lang_name = lang_map.get(target_lang, 'Khmer')
        
        return f"""
        Translate this news article to {lang_name}.
        
        Input:
        Title: {article['title']}
        Summary: {article['summary']}
        
        Output JSON:
        {{
            "title": "Translated Headline",
            "body": "Translated Full Summary",
            "summary": "Short social media blurb (1-2 sentences)"
        }}
        """

    async def _fallback_translate(self, article: dict, target_lang: str) -> dict:
        try:
            translator = GoogleTranslator(source='auto', target=target_lang)
            return {
                "title": translator.translate(article['title']),
                "body": translator.translate(article['summary']),
                "summary": translator.translate(article['summary'])
            }
        except Exception as e:
            logger.error(f"Fallback Translation Failed: {e}")
            # Return original if all else fails
            return {"title": article['title'], "body": article['summary'], "summary": article['summary']}

    async def verify_translation(self, original: str, translated: str) -> bool:
        """Back-translation verification"""
        try:
            if not translated: return False
            # Simple length check
            if len(translated) < len(original) * 0.2: return False
            return True
        except:
            return True

# Global Instance
translator = TranslationManager()
