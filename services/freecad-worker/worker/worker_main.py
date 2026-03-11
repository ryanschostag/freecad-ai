from redis import Redis
from rq import Queue, Worker
from rq.job import Job
from rq.utils import import_attribute

from worker.settings import settings


class CompatJob(Job):
    """
    Make RQ function resolution tolerant to different func_name encodings that can
    arise across RQ versions / enqueue patterns / containers.

    Normalizes:
      - worker.jobs.run_repair_loop_job
      - worker.jobs:run_repair_loop_job
      - worker:jobs.run_repair_loop_job
      - run_repair_loop_job   -> assumed worker.jobs.run_repair_loop_job
    """

    @property
    def func(self):
        fn = (self.func_name or "").strip()

        # Convert colon forms into dotted module paths
        # e.g. "worker.jobs:run_repair_loop_job" -> "worker.jobs.run_repair_loop_job"
        # e.g. "worker:jobs.run_repair_loop_job" -> "worker.jobs.run_repair_loop_job"
        if ":" in fn:
            fn = fn.replace(":", ".")

        # Clean up accidental double dots / trailing dots
        while ".." in fn:
            fn = fn.replace("..", ".")
        fn = fn.strip(".")

        # If somehow only a bare function name is present, assume it's in worker.jobs
        if "." not in fn and fn:
            fn = f"worker.jobs.{fn}"

        return import_attribute(fn)


def main():
    redis = Redis.from_url(settings.redis_url)
    q = Queue("freecad", connection=redis)
    Worker([q], connection=redis, job_class=CompatJob).work()


if __name__ == "__main__":
    main()
