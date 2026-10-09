from time import perf_counter


def elapsed_ms(started_at: float) -> float:
    return (perf_counter() - started_at) * 1_000
