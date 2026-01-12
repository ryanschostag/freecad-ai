from redis import Redis
from rq import Queue
from app.settings import settings
def get_queue(name: str = "freecad"):
    return Queue(name, connection=Redis.from_url(settings.redis_url))
