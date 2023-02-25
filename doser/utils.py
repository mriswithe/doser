import time
from functools import wraps
from typing import NamedTuple, Any


class TimedResult(NamedTuple):
    result: Any
    duration: float


def timer(f):
    @wraps(f)
    def inner(*args, **kwargs):
        start = time.perf_counter()
        ret = f(*args, **kwargs)
        end = time.perf_counter()
        return TimedResult(ret, end - start)

    return inner
