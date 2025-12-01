import logging
import asyncio
from datetime import datetime

# Try importing Transformers
try:
    from transformers import pipeline
    AI_SCORER_AVAILABLE = True
    # Load zero-shot classifier (lightweight)
    classifier = pipeline("zero-shot-classification", model="facebook/bart-large-mnli", device=-1) # CPU
except ImportError:
    AI_SCORER_AVAILABLE = False

logger = logging.getLogger(__name__)

class QualityScorer:
    def __init__(self):
        self.weights = {
            "title": 15,
            "summary": 20,
            "image": 10,
            "source": 15,
            "ai_score": 30, # New AI component
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

    async def score_article(self, article: dict) -> tuple:
        """
        Score article quality from 0-100.
        Returns: (score, reason_list)
        """
        score = 0
        reasons = []
        
        # 1. Basic Checks
        title = article.get("title", "")
        summary = article.get("summary", "")
        
        if len(title) < 20: reasons.append("Title too short")
        else: score += self.weights["title"]
        
        if len(summary) < 100: reasons.append("Summary too short")
        else: score += self.weights["summary"]
        
        if article.get("image_url"): score += self.weights["image"]
        else: reasons.append("No image")
        
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
            
        # 3. AI Scoring (Zero-Shot)
        ai_score = 0
        if AI_SCORER_AVAILABLE:
            try:
                # Classify into categories
                labels = ["news", "spam", "clickbait", "sensitive"]
                result = await asyncio.to_thread(classifier, title + ". " + summary, labels)
                
                # result['labels'] and result['scores'] are sorted
                top_label = result['labels'][0]
                top_score = result['scores'][0]
                
                if top_label == "news" and top_score > 0.6:
                    ai_score = 30
                elif top_label in ["spam", "clickbait", "sensitive"]:
                    ai_score = 0
                    reasons.append(f"AI detected {top_label} ({top_score:.2f})")
                else:
                    ai_score = 15 # Neutral
            except Exception as e:
                logger.error(f"AI Scorer failed: {e}")
                ai_score = 15 # Fallback
        else:
            ai_score = 30 # Assume good if no AI available to prove otherwise
            
        score += ai_score
        
        return min(score, 100), reasons

# Global Instance
scorer = QualityScorer()
