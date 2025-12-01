import time
import random
import logging
from datetime import datetime, timedelta
import config

logger = logging.getLogger(__name__)

class SmartScheduler:
    def __init__(self):
        self.BURST_MODE = config.BURST_MODE_DEFAULT
        self.last_post_time = {} # {platform: timestamp}
        self.last_category_time = {} # {category: timestamp}
        
        # Best Posting Hours (ICT)
        self.PEAK_HOURS = {7, 8, 9, 11, 12, 13, 17, 18, 19, 20}
        self.OFF_HOURS = {2, 3, 4, 5}
        
        # Spacing Rules (seconds)
        self.MIN_PLATFORM_DELAY = 300 # 5 mins
        self.MIN_CATEGORY_DELAY = 1800 # 30 mins
        self.BURST_DELAY = 60 # 1 min
        
    def is_peak_hour(self) -> bool:
        now = datetime.now(config.ICT)
        return now.hour in self.PEAK_HOURS

    def is_off_hour(self) -> bool:
        if self.BURST_MODE: return False
        now = datetime.now(config.ICT)
        return now.hour in self.OFF_HOURS

    def get_jitter(self) -> int:
        """Random delay +/- 5 mins"""
        return random.randint(-300, 300)

    def can_post(self, platform: str, category: str, priority: int) -> bool:
        """
        Determine if we can post now.
        Priority: 1 (Normal), 2 (High), 3 (Breaking)
        """
        now = time.time()
        
        # 1. Breaking News overrides all
        if priority >= 3: return True
            
        # 2. Burst Mode overrides off-hours
        if self.BURST_MODE: pass
        elif self.is_off_hour(): return False
            
        # 3. Platform Spacing
        last_p = self.last_post_time.get(platform, 0)
        min_delay = self.BURST_DELAY if self.BURST_MODE else self.MIN_PLATFORM_DELAY
        
        # Reduce delay during peak hours
        if self.is_peak_hour() and not self.BURST_MODE:
            min_delay = min_delay / 2
            
        if now - last_p < min_delay: return False
            
        # 4. Category Spacing
        if priority == 1:
            last_c = self.last_category_time.get(category, 0)
            if now - last_c < self.MIN_CATEGORY_DELAY: return False
                
        return True

    def record_post(self, platform: str, category: str):
        now = time.time()
        self.last_post_time[platform] = now
        self.last_category_time[category] = now

    def set_burst_mode(self, enabled: bool):
        self.BURST_MODE = enabled
        logger.info(f"🔥 Burst Mode: {'ON' if enabled else 'OFF'}")

# Global Instance
scheduler = SmartScheduler()
