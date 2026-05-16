from collections.abc import Callable, Mapping


def configured_value(
    key: str,
    *,
    env: Mapping[str, str],
    secret_getter: Callable[[str], str | None],
    missing_secret_errors: tuple[type[Exception], ...],
) -> str:
    try:
        secret_value = secret_getter(key)
    except missing_secret_errors:
        secret_value = None
    return str(secret_value or env.get(key) or "")


def slider_bounds(min_value: int, max_value: int) -> tuple[int, int] | None:
    if min_value >= max_value:
        return None
    return min_value, max_value
