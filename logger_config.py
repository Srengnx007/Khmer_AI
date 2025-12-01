import logging
import sys
import structlog
import uuid
import time
import contextvars
from functools import wraps

# Context variable for correlation ID
correlation_id = contextvars.ContextVar("correlation_id", default=None)

def add_correlation_id(logger, method_name, event_dict):
    """Add correlation ID to log event"""
    cid = correlation_id.get()
    if cid:
        event_dict["correlation_id"] = cid
    return event_dict

def configure_logger():
    """Configure structlog and standard logging"""
    
    # Configure standard logging to capture library logs
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=logging.INFO,
    )

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            add_correlation_id,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.add_log_level,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            structlog.processors.JSONRenderer()
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

def get_logger(name=None):
    return structlog.get_logger(name)

def new_correlation_id():
    """Generate and set a new correlation ID"""
    cid = str(uuid.uuid4())
    correlation_id.set(cid)
    return cid

# Performance Profiler Decorator
def profile(func):
    @wraps(func)
    async def wrapper(*args, **kwargs):
        start_time = time.time()
        log = structlog.get_logger()
        func_name = func.__name__
        
        try:
            result = await func(*args, **kwargs)
            duration = (time.time() - start_time) * 1000
            
            # Log slow operations (>500ms)
            if duration > 500:
                log.info("performance_metric", function=func_name, duration_ms=duration)
                
            return result
        except Exception as e:
            duration = (time.time() - start_time) * 1000
            log.error("function_failed", function=func_name, duration_ms=duration, error=str(e))
            raise e
            
    return wrapper
