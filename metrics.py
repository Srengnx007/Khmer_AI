import time
import psutil
import logging
from collections import deque, defaultdict
from prometheus_client import Counter, Gauge, Histogram, generate_latest, CONTENT_TYPE_LATEST

logger = logging.getLogger(__name__)

class MetricsCollector:
    def __init__(self):
        # 1. Counters
        self.posts_total = Counter('posts_total', 'Total posts created', ['platform', 'status'])
        self.errors_total = Counter('errors_total', 'Total errors encountered', ['type'])
        self.api_calls_total = Counter('api_calls_total', 'Total API calls', ['platform'])
        self.rate_limits_total = Counter('rate_limits_total', 'Total rate limits hit', ['platform'])
        
        # 2. Gauges
        self.queue_size = Gauge('queue_size', 'Current items in processing queue')
        self.memory_usage = Gauge('memory_usage_mb', 'Memory usage in MB')
        self.uptime_seconds = Gauge('uptime_seconds', 'Bot uptime in seconds')
        self.source_health = Gauge('source_health', 'Source health score (0-100)', ['source'])
        
        # 3. Histograms
        self.request_duration = Histogram('request_duration_seconds', 'Request duration', ['operation'])
        self.article_process_time = Histogram('article_process_time_seconds', 'Time to process one article')
        
        # Internal State for Alerting
        self.start_time = time.time()
        self.error_window = deque(maxlen=100) # Store timestamps of errors
        self.last_post_time = time.time()
        self.rate_limit_window = defaultdict(list)
        
        # Alert Thresholds
        self.ALERT_ERROR_RATE = 0.10 # 10%
        self.ALERT_NO_POSTS = 1800 # 30 mins
        self.ALERT_MEMORY = 800 # 800MB (assuming 1GB limit approx)
        
    def increment_post(self, platform: str, status: str = "success"):
        self.posts_total.labels(platform=platform, status=status).inc()
        if status == "success":
            self.last_post_time = time.time()
            
    def increment_error(self, error_type: str):
        self.errors_total.labels(type=error_type).inc()
        self.error_window.append(time.time())
        
    def track_api_call(self, platform: str):
        self.api_calls_total.labels(platform=platform).inc()
        
    def track_rate_limit(self, platform: str):
        self.rate_limits_total.labels(platform=platform).inc()
        now = time.time()
        # Clean old
        self.rate_limit_window[platform] = [t for t in self.rate_limit_window[platform] if now - t < 3600]
        self.rate_limit_window[platform].append(now)
        
    def update_system_metrics(self):
        """Update system-level metrics (memory, uptime)"""
        process = psutil.Process()
        mem = process.memory_info().rss / 1024 / 1024 # MB
        self.memory_usage.set(mem)
        self.uptime_seconds.set(time.time() - self.start_time)
        
    def check_alerts(self) -> list:
        """Check for alert conditions"""
        alerts = []
        now = time.time()
        
        # 1. Error Rate (Errors in last 5 mins)
        recent_errors = [t for t in self.error_window if now - t < 300]
        if len(recent_errors) > 10: # Minimum threshold to avoid noise
            # This is a simple count check, for rate we'd need total ops. 
            # For now, >10 errors in 5 mins is alarming enough.
            alerts.append(f"High Error Rate: {len(recent_errors)} errors in last 5m")
            
        # 2. Zero Posts
        if now - self.last_post_time > self.ALERT_NO_POSTS:
            alerts.append(f"No posts for {int((now - self.last_post_time)/60)} minutes")
            
        # 3. Memory Usage
        process = psutil.Process()
        mem = process.memory_info().rss / 1024 / 1024
        if mem > self.ALERT_MEMORY:
            alerts.append(f"High Memory Usage: {mem:.1f}MB")
            
        # 4. Rate Limits
        for platform, times in self.rate_limit_window.items():
            if len(times) >= 3:
                alerts.append(f"Rate Limit Warning: {platform} hit {len(times)} times in 1h")
                
        return alerts

    def get_metrics_data(self):
        """Return Prometheus formatted metrics"""
        self.update_system_metrics()
        return generate_latest(), CONTENT_TYPE_LATEST

# Global Instance
metrics = MetricsCollector()
