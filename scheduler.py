import time
import random
import logging
from datetime import datetime, timedelta
import pytz

logger = logging.getLogger(__name__)

# Timezone
ICT = pytz.timezone('Asia/Phnom_Penh')

class SmartScheduler:
    def __init__(self):
        # Configuration
        self.BURST_MODE = False
        self.last_post_time = {} # {platform: timestamp}
        self.last_category_time = {} # {category: timestamp}
        
        # Best Posting Hours (0-23)
        # High engagement: 7-9am, 11am-1pm, 5-8pm
        self.PEAK_HOURS = {7, 8, 9, 11, 12, 13, 17, 18, 19, 20}
        self.OFF_HOURS = {2, 3, 4, 5} # Sleep time
        
        # Spacing Rules (seconds)
        self.MIN_PLATFORM_DELAY = 300 # 5 mins between posts on same platform
        self.MIN_CATEGORY_DELAY = 1800 # 30 mins between same category
        self.BURST_DELAY = 60 # 1 min in burst mode
        
    def is_peak_hour(self) -> bool:
        """Check if current time is high engagement"""
        now = datetime.now(ICT)
        return now.hour in self.PEAK_HOURS

    def is_off_hour(self) -> bool:
        """Check if current time is sleep time"""
        if self.BURST_MODE: return False
        now = datetime.now(ICT)
        return now.hour in self.OFF_HOURS

    def get_jitter(self) -> int:
        """Random delay +/- 5 mins to avoid patterns"""
        return random.randint(-300, 300)

    def can_post(self, platform: str, category: str, priority: int) -> bool:
        """
        Determine if we can post now based on rules.
        Priority: 1 (Normal), 2 (High), 3 (Breaking)
        """
        now = time.time()
        
        # 1. Breaking News overrides all time rules
        if priority >= 3:
            return True
            
        # 2. Burst Mode overrides off-hours
        if self.BURST_MODE:
            pass # Skip off-hour check
        elif self.is_off_hour():
            return False
            
        # 3. Platform Spacing
        last_p = self.last_post_time.get(platform, 0)
        min_delay = self.BURST_DELAY if self.BURST_MODE else self.MIN_PLATFORM_DELAY
        if now - last_p < min_delay:
            return False
            
        # 4. Category Spacing (Avoid 3 tech posts in a row)
        # Only applies to Normal priority
        if priority == 1:
            last_c = self.last_category_time.get(category, 0)
            if now - last_c < self.MIN_CATEGORY_DELAY:
                return False
                
        return True

    def record_post(self, platform: str, category: str):
        """Record that a post was just made"""
        now = time.time()
        self.last_post_time[platform] = now
        self.last_category_time[category] = now

    def set_burst_mode(self, enabled: bool):
        self.BURST_MODE = enabled
        logger.info(f"🔥 Burst Mode: {'ON' if enabled else 'OFF'}")

# Global Instance
scheduler = SmartScheduler()
