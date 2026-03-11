import logging
import colorlog
import redis
import json
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    TARGET_URL: str = "http://localhost:8000"
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_CHANNEL: str = "events"
    APP_ENV: str = "development"

    class Config:
        env_file = ".env"

settings = Settings()

class RedisHandler(logging.Handler):
    """Custom logging handler to push logs into a Redis list for the Streamlit dashboard."""
    def __init__(self, redis_client, list_key):
        super().__init__()
        self.redis_client = redis_client
        self.list_key = list_key

    def emit(self, record):
        try:
            log_entry = self.format(record)
            self.redis_client.rpush(self.list_key, log_entry)
            # Keep only the last 50 logs to avoid bloating Redis
            self.redis_client.ltrim(self.list_key, -50, -1)
        except Exception:
            pass # Avoid crashing the app if Redis logging fails

# Setup Enterprise Logging
def get_logger(name: str):
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    
    # Avoid duplicate handlers if get_logger is called multiple times
    if not logger.handlers:
        # 1. Console Handler (Colored)
        console_handler = colorlog.StreamHandler()
        console_handler.setFormatter(colorlog.ColoredFormatter(
            '%(log_color)s[%(asctime)s] [%(name)s] [%(levelname)s] %(message)s',
            datefmt='%H:%M:%S',
            log_colors={
                'DEBUG': 'cyan',
                'INFO': 'green',
                'WARNING': 'yellow',
                'ERROR': 'red',
                'CRITICAL': 'bold_red',
            }
        ))
        logger.addHandler(console_handler)

        # 2. Redis Handler (For Dashboard)
        try:
            r = redis.Redis(host=settings.REDIS_HOST, port=settings.REDIS_PORT, decode_responses=True)
            redis_list = "red_logs" if "RED" in name.upper() else "blue_logs"
            redis_handler = RedisHandler(r, redis_list)
            redis_handler.setFormatter(logging.Formatter('[%(asctime)s] [%(levelname)s] %(message)s', datefmt='%H:%M:%S'))
            logger.addHandler(redis_handler)
        except:
            pass

    return logger