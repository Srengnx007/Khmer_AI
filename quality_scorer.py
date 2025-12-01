import re
import time
import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

class QualityScorer:
    def __init__(self):
        # Scoring Weights (Total = 100)
        self.weights = {
            "title": 15,
            "summary": 20,
            "image": 10,
            "source": 15,
            "freshness": 20,
            "spam": 10,
            "language": 10
        }
        
        # Thresholds
        self.MIN_TITLE_LEN = 20
        self.MAX_TITLE_LEN = 200
        self.MIN_SUMMARY_LEN = 100
        self.SPAM_KEYWORDS = ["buy now", "click here", "subscribe", "free money", "winner", "lottery"]
        self.SENSITIVE_KEYWORDS = ["sex", "porn", "xxx", "gambling", "casino"] # Simple list, expand as needed
        
        # Source Reliability (1.0 = standard, <1.0 = penalty, >1.0 = boost)
        self.source_weights = {
            "Fresh News": 1.1,
            "Koh Santepheap": 1.0,
            "Phnom Penh Post": 1.2,
            "Cambodia Daily": 1.1,
            # Add others as needed
        }

    def score_article(self, article: dict) -> tuple:
        """
        Score article quality from 0-100.
        Returns: (score, reason_list)
        """
        score = 0
        reasons = []
        
        # 1. Title Quality (15 pts)
        title = article.get("title", "")
        if self.MIN_TITLE_LEN <= len(title) <= self.MAX_TITLE_LEN:
            score += self.weights["title"]
        else:
            reasons.append(f"Title length {len(title)} out of range")
            
        # 2. Summary Completeness (20 pts)
        summary = article.get("summary", "")
        if len(summary) >= self.MIN_SUMMARY_LEN:
            score += self.weights["summary"]
        else:
            # Partial score
            ratio = len(summary) / self.MIN_SUMMARY_LEN
            points = int(self.weights["summary"] * ratio)
            score += points
            reasons.append(f"Summary too short ({len(summary)} chars)")
            
        # 3. Image Quality (10 pts)
        # Assuming image_url presence implies validation passed (since we validate before scoring usually, or we check here)
        if article.get("image_url"):
            score += self.weights["image"]
        else:
            reasons.append("No image")
            
        # 4. Source Reliability (15 pts)
        source = article.get("source", "Unknown")
        weight = self.source_weights.get(source, 1.0)
        points = int(self.weights["source"] * weight)
        # Cap at 15
        points = min(points, self.weights["source"])
        score += points
        
        # 5. Freshness (20 pts)
        # Assuming article has 'published_parsed' or we estimate
        # If not present, we assume it's fresh enough if it was just fetched, but let's check if available
        # For RSS, we usually have it. If not, give full points (benefit of doubt)
        # Here we'll use a placeholder logic if published date isn't passed explicitly, 
        # but usually we process fresh feeds.
        # Let's assume 'freshness' is high for now unless we parse date.
        score += self.weights["freshness"] 
        
        # 6. Spam/Clickbait Detection (10 pts)
        text = (title + " " + summary).lower()
        if any(kw in text for kw in self.SPAM_KEYWORDS):
            reasons.append("Spam keywords detected")
        elif title.isupper() and len(title) > 10:
            reasons.append("Excessive CAPS in title")
        else:
            score += self.weights["spam"]
            
        # 7. Language/Sensitivity (10 pts)
        if any(kw in text for kw in self.SENSITIVE_KEYWORDS):
            score = 0 # Immediate fail
            reasons.append("Sensitive/Profane content detected")
        else:
            score += self.weights["language"]
            
        return score, reasons

# Global Instance
scorer = QualityScorer()
