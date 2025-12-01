import asyncio
import unittest
import time
from main import RateLimiter, config

# Mock config for testing
config.RATE_LIMITS = {
    "test_platform": {"calls": 5, "period": 1}
}

class TestRateLimiter(unittest.IsolatedAsyncioTestCase):
    async def test_rate_limit_basic(self):
        limiter = RateLimiter()
        # Should allow 5 calls immediately
        for i in range(5):
            remaining = await limiter.acquire("test_platform")
            self.assertEqual(remaining, 5 - (i + 1))
            
    async def test_rate_limit_wait(self):
        limiter = RateLimiter()
        # Consume all tokens
        for _ in range(5):
            await limiter.acquire("test_platform")
            
        start = time.time()
        # This should wait approx 1s
        remaining = await limiter.acquire("test_platform")
        duration = time.time() - start
        
        self.assertGreater(duration, 0.9)
        self.assertEqual(remaining, 4) # 5 - 1 (new window started)

    async def test_concurrency(self):
        limiter = RateLimiter()
        
        async def worker():
            await limiter.acquire("test_platform")
            
        # Launch 10 workers concurrently (limit is 5/sec)
        start = time.time()
        await asyncio.gather(*[worker() for _ in range(10)])
        duration = time.time() - start
        
        # Should take at least 1 second (to clear first batch)
        self.assertGreater(duration, 0.9)

if __name__ == "__main__":
    unittest.main()
