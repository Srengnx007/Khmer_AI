import logging
import asyncio
import json
from datetime import datetime
import google.generativeai as genai
from config import GEMINI_API_KEY, GEMINI_MODEL

# Configure Gemini
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel(GEMINI_MODEL)

logger = logging.getLogger(__name__)

class QualityScorer:
    def __init__(self):
        self.weights = {
            "title": 15,
            "summary": 20,
            "image": 10,
            "source": 15,
            "ai_score": 30,  # AI component using Gemini
            "language": 10
        }
        
        self.SPAM_KEYWORDS = ["buy now", "click here", "subscribe", "free money", "winner", "lottery", "casino"]
        self.SENSITIVE_KEYWORDS = ["sex", "porn", "xxx", "gambling"]
        
        self.source_weights = {
            "Fresh News": 1.1,
            "Koh Santepheap": 1.0,
            "Phnom Penh Post": 1.2,
            "Cambodia Daily": 1.1,
            "Khmer Times": 1.1,
            "BBC News": 1.3
        }

    async def _gemini_classify(self, text: str) -> str:
        """
        Use Gemini to classify news text into quality categories.
        Returns: 'High Quality News', 'Clickbait', 'Spam', or 'Sensitive'
        """
        prompt = f"""Classify the following news article text into exactly ONE of these categories:
- High Quality News (factual, informative, well-written journalism)
- Clickbait (sensationalized, misleading headlines designed to get clicks)
- Spam (promotional content, advertisements, irrelevant content)
- Sensitive (adult content, offensive material, inappropriate topics)

News Text:
{text[:1000]}

Respond with a JSON object containing a single key "classification" with the category name.
Example: {{"classification": "High Quality News"}}"""

        try:
            response = await asyncio.to_thread(
                model.generate_content,
                prompt,
                generation_config={"response_mime_type": "application/json"}
            )
            
            # Clean response text (strip Markdown if present)
            text = response.text.strip()
            if text.startswith("```json"):
                text = text[7:]
            elif text.startswith("```"):
                text = text[3:]
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()
            
            parsed = json.loads(text)
            classification = parsed.get("classification", "High Quality News")
            
            # Validate response
            valid_labels = ['High Quality News', 'Clickbait', 'Spam', 'Sensitive']
            for label in valid_labels:
                if label.lower() in classification.lower():
                    return label
            
            # Fallback if unclear
            logger.warning(f"Gemini returned unclear classification: {classification}")
            return "High Quality News"  # Neutral fallback
            
        except Exception as e:
            logger.error(f"Gemini classification failed: {e}")
            return "High Quality News"  # Neutral fallback on error

    async def score_article(self, article: dict) -> tuple:
        """
        Score article quality from 0-100 using Gemini AI classification.
        Returns: (score, reason_list)
        """
        score = 0
        reasons = []
        
        # 1. Basic Checks
        title = article.get("title", "")
        summary = article.get("summary", "")
        
        if len(title) < 20:
            reasons.append("Title too short")
        else:
            score += self.weights["title"]
        
        if len(summary) < 100:
            reasons.append("Summary too short")
        else:
            score += self.weights["summary"]
        
        if article.get("image_url"):
            score += self.weights["image"]
        else:
            reasons.append("No image")
        
        # Source Weight
        source = article.get("source", "Unknown")
        w = self.source_weights.get(source, 1.0)
        score += min(int(self.weights["source"] * w), 20)
        
        # 2. Keyword Safety Check
        text = (title + " " + summary).lower()
        if any(kw in text for kw in self.SENSITIVE_KEYWORDS):
            return 0, ["Sensitive content detected"]
            
        if any(kw in text for kw in self.SPAM_KEYWORDS):
            reasons.append("Spam keywords")
        else:
            score += self.weights["language"]
            
        # 3. Gemini AI Scoring (Zero-Shot Classification)
        ai_score = 0
        try:
            classification = await self._gemini_classify(title + ". " + summary)
            
            if classification == "High Quality News":
                ai_score = 30
                logger.debug(f"✅ Gemini: High Quality - {title[:30]}...")
            elif classification == "Clickbait":
                ai_score = 0
                reasons.append("AI detected clickbait")
                logger.debug(f"⚠️ Gemini: Clickbait - {title[:30]}...")
            elif classification in ["Spam", "Sensitive"]:
                # Reject immediately
                logger.warning(f"❌ Gemini: {classification} - {title[:30]}...")
                return 0, [f"AI detected {classification.lower()}"]
            else:
                ai_score = 15  # Neutral fallback
                
        except Exception as e:
            logger.error(f"Gemini scoring failed: {e}")
            ai_score = 15  # Neutral fallback on error
            
        score += ai_score
        
        return min(score, 100), reasons

# Global Instance
scorer = QualityScorer()
