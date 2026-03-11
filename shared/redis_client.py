import redis
import json
from shared.config import settings, get_logger

logger = get_logger("REDIS_CLIENT")

# 1. Initialize 'r' globally so functions can see it
r = None

try:
    r = redis.Redis(
        host=settings.REDIS_HOST,
        port=settings.REDIS_PORT,
        db=0,
        decode_responses=True
    )
except Exception as e:
    logger.critical(f"Redis Connection Failed: {e}")

CHANNEL = settings.REDIS_CHANNEL


def publish_exploit(payload):
    """Red Agent uses this to broadcast attacks."""
    # Safety check: if Redis failed to connect, don't crash the agent
    if r is None:
        logger.error("Cannot publish: Redis connection is missing.")
        return

    try:
        # default=str fixes the "datetime not serializable" crash
        message = json.dumps(payload, default=str)
        r.publish(CHANNEL, message)
        r.rpush("exploits", message) # Keep history for the dashboard count
        logger.debug(f"📡 [PUB] Exploit sent to channel '{CHANNEL}'")
    except Exception as e:
        logger.error(f"Failed to publish to Redis: {e}")


def listen_for_exploits(callback_function):
    """Blue Agent uses this to subscribe to attacks."""
    if r is None:
        logger.error("Cannot listen: Redis connection is missing.")
        return

    pubsub = r.pubsub()
    pubsub.subscribe(CHANNEL)
    logger.info(f"👂 [SUB] Listening for threats on '{CHANNEL}'...")

    for message in pubsub.listen():
        if message['type'] == 'message':
            try:
                data = json.loads(message['data'])
                callback_function(data)
            except json.JSONDecodeError:
                logger.warning("Received invalid JSON from Redis")