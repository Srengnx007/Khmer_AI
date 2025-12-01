import re
import math
import hashlib
import unicodedata
import time
import logging
from collections import Counter

# Try importing Khmer NLP libraries
try:
    from khmer_nltk import word_tokenize
    KHMER_NLP_AVAILABLE = True
except ImportError:
    KHMER_NLP_AVAILABLE = False

logger = logging.getLogger(__name__)

class DuplicateDetector:
    def __init__(self, similarity_threshold=0.85):
        self.threshold = similarity_threshold
        self.cache = {}
        self.minhash_cache = {}
        
        # Enhanced Khmer Stopwords
        self.stopwords = {
            "និង", "នៃ", "បាន", "ជា", "គឺ", "ដែល", "ក្នុង", "លើ", "ដោយ", "មាន",
            "មិន", "ថា", "នេះ", "នោះ", "មួយ", "ពីរ", "បី", "សំរាប់", "អំពី",
            "នៅ", "ក៏", "តែ", "នូវ", "ហើយ", "ឬ", "ឯ", "ផង", "ដែរ", "ចំពោះ",
            "ដើម្បី", "ដូច", "គ្នា", "អ្វី", "យ៉ាង", "ណា", "បន្ទាប់", "មក"
        }

    def normalize_khmer(self, text: str) -> str:
        """Normalize Khmer text (NFD -> NFC, remove zero-width spaces)"""
        if not text: return ""
        text = unicodedata.normalize('NFC', text)
        text = text.replace('\u200b', '').replace('\u200c', '').replace('\u200d', '')
        text = re.sub(r'[។៕៖ៗ,.\?!\'"]', ' ', text)
        return text.strip().lower()

    def tokenize(self, text: str) -> list:
        """Smart Tokenizer: Uses khmer-nltk if available, else char n-grams"""
        text = self.normalize_khmer(text)
        
        if KHMER_NLP_AVAILABLE:
            try:
                words = word_tokenize(text)
                return [w for w in words if w not in self.stopwords and len(w) > 1]
            except Exception:
                pass # Fallback
        
        # Fallback: Character Trigrams & Quadgrams
        tokens = []
        words = text.split() # Split by existing spaces first
        
        for word in words:
            if word in self.stopwords: continue
            if len(word) < 3: 
                tokens.append(word)
                continue
            
            # Add full word
            tokens.append(word)
            
            # Trigrams
            for i in range(len(word) - 2):
                tokens.append(word[i:i+3])
                
        return tokens

    def compute_tf(self, text: str) -> dict:
        tokens = self.tokenize(text)
        if not tokens: return {}
        counter = Counter(tokens)
        total = len(tokens)
        return {k: v/total for k, v in counter.items()}

    def get_cosine_similarity(self, text1: str, text2: str) -> float:
        cache_key = f"{hash(text1)}-{hash(text2)}"
        if cache_key in self.cache:
            return self.cache[cache_key]

        tf1 = self.compute_tf(text1)
        tf2 = self.compute_tf(text2)
        
        terms = set(tf1.keys()) | set(tf2.keys())
        dot_product = sum(tf1.get(t, 0) * tf2.get(t, 0) for t in terms)
        mag1 = math.sqrt(sum(v**2 for v in tf1.values()))
        mag2 = math.sqrt(sum(v**2 for v in tf2.values()))
        
        if mag1 == 0 or mag2 == 0:
            return 0.0
            
        similarity = dot_product / (mag1 * mag2)
        self.cache[cache_key] = similarity
        return similarity

    def is_duplicate(self, new_title: str, recent_titles: list) -> tuple:
        """
        Check if new_title is a duplicate.
        Returns: (is_duplicate, match_title, score)
        """
        if new_title in recent_titles:
            return True, new_title, 1.0

        best_score = 0.0
        best_match = None
        
        for title in recent_titles:
            score = self.get_cosine_similarity(new_title, title)
            if score > best_score:
                best_score = score
                best_match = title
            
            if best_score > self.threshold:
                break
        
        return best_score >= self.threshold, best_match, best_score

# Global Instance
detector = DuplicateDetector(similarity_threshold=0.85)
