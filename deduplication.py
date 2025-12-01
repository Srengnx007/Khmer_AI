import re
import math
import hashlib
import unicodedata
import time
import logging
from collections import Counter, defaultdict

logger = logging.getLogger(__name__)

class DuplicateDetector:
    def __init__(self, similarity_threshold=0.75):
        self.threshold = similarity_threshold
        self.cache = {} # Simple cache for vectors
        self.minhash_cache = {}
        self.idf_cache = {}
        self.doc_count = 0
        
        # Khmer Stopwords (Simplified list)
        self.stopwords = {
            "និង", "នៃ", "បាន", "ជា", "គឺ", "ដែល", "ក្នុង", "លើ", "ដោយ", "មាន",
            "មិន", "ថា", "នេះ", "នោះ", "មួយ", "ពីរ", "បី", "សំរាប់", "អំពី"
        }

    def normalize_khmer(self, text: str) -> str:
        """Normalize Khmer text (NFD -> NFC, remove zero-width spaces)"""
        if not text: return ""
        # Normalize Unicode
        text = unicodedata.normalize('NFC', text)
        # Remove zero-width spaces and common noise
        text = text.replace('\u200b', '').replace('\u200c', '').replace('\u200d', '')
        # Remove punctuation
        text = re.sub(r'[។៕៖ៗ,.\?!\'"]', ' ', text)
        return text.strip().lower()

    def tokenize(self, text: str) -> list:
        """Simple whitespace/char tokenizer for Khmer"""
        # Since Khmer doesn't use spaces, we might need character n-grams or simple split if spaces exist
        # For robustness, we'll use character bigrams + trigrams for Khmer
        text = self.normalize_khmer(text)
        tokens = []
        
        # 1. Split by space (if any)
        words = text.split()
        
        # 2. Generate char n-grams (2-3 chars)
        for word in words:
            if word in self.stopwords: continue
            if len(word) < 2: continue
            
            # Add the word itself
            tokens.append(word)
            
            # Add bigrams for better matching
            for i in range(len(word) - 1):
                tokens.append(word[i:i+2])
                
        return tokens

    def compute_tf(self, text: str) -> dict:
        """Compute Term Frequency"""
        tokens = self.tokenize(text)
        if not tokens: return {}
        
        counter = Counter(tokens)
        total = len(tokens)
        return {k: v/total for k, v in counter.items()}

    def get_cosine_similarity(self, text1: str, text2: str) -> float:
        """Compute Cosine Similarity between two texts"""
        # Check cache
        cache_key = f"{hash(text1)}-{hash(text2)}"
        if cache_key in self.cache:
            return self.cache[cache_key]

        tf1 = self.compute_tf(text1)
        tf2 = self.compute_tf(text2)
        
        # Union of terms
        terms = set(tf1.keys()) | set(tf2.keys())
        
        dot_product = 0
        mag1 = 0
        mag2 = 0
        
        for term in terms:
            v1 = tf1.get(term, 0)
            v2 = tf2.get(term, 0)
            
            dot_product += v1 * v2
            mag1 += v1 * v1
            mag2 += v2 * v2
            
        if mag1 == 0 or mag2 == 0:
            return 0.0
            
        similarity = dot_product / (math.sqrt(mag1) * math.sqrt(mag2))
        
        # Cache result
        self.cache[cache_key] = similarity
        return similarity

    def compute_minhash(self, text: str, num_perm=128) -> list:
        """Compute MinHash signature (Simplified)"""
        tokens = self.tokenize(text)
        signature = [float('inf')] * num_perm
        
        for token in tokens:
            # Simulate permutations using different hash seeds
            h = int(hashlib.md5(token.encode()).hexdigest(), 16)
            for i in range(num_perm):
                # Simple linear permutation: (a*h + b) % p
                # Using fixed constants for stability
                ph = (h * (i + 1) + (i * 13)) % (2**32 - 1)
                if ph < signature[i]:
                    signature[i] = ph
                    
        return signature

    def get_jaccard_similarity(self, sig1: list, sig2: list) -> float:
        """Estimate Jaccard similarity from MinHash signatures"""
        if not sig1 or not sig2: return 0.0
        matches = sum(1 for i in range(len(sig1)) if sig1[i] == sig2[i])
        return matches / len(sig1)

    def is_duplicate(self, new_title: str, recent_titles: list, method="cosine") -> tuple:
        """
        Check if new_title is a duplicate of any recent_titles.
        Returns: (is_duplicate, match_title, score)
        """
        start_time = time.time()
        best_score = 0.0
        best_match = None
        
        # 1. Exact Match (Fastest)
        if new_title in recent_titles:
            return True, new_title, 1.0

        # 2. Advanced Matching
        for title in recent_titles:
            score = 0.0
            if method == "cosine":
                score = self.get_cosine_similarity(new_title, title)
            elif method == "minhash":
                # Only compute if not cached
                if new_title not in self.minhash_cache:
                    self.minhash_cache[new_title] = self.compute_minhash(new_title)
                if title not in self.minhash_cache:
                    self.minhash_cache[title] = self.compute_minhash(title)
                    
                score = self.get_jaccard_similarity(
                    self.minhash_cache[new_title], 
                    self.minhash_cache[title]
                )
            
            if score > best_score:
                best_score = score
                best_match = title
                
            if best_score > self.threshold:
                break
        
        duration = (time.time() - start_time) * 1000
        # logger.debug(f"🔎 DupCheck ({method}): {duration:.2f}ms, Score: {best_score:.2f}")
        
        return best_score >= self.threshold, best_match, best_score

# Global Instance
detector = DuplicateDetector(similarity_threshold=0.75)
