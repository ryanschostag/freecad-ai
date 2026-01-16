from redis import Redis
from rq import Queue, Worker
from worker.settings import settings

def main():
    redis = Redis.from_url(settings.redis_url)
    q = Queue("freecad", connection=redis)
    Worker([q], connection=redis).work()

if __name__ == "__main__":
    main()
