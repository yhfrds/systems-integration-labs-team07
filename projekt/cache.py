import time

_cache = {}  # key → (value, expire_timestamp)

def cache_get(key):
    """Return cached value if not expired, else None."""
    if key in _cache:
        value, expires = _cache[key]
        if time.time() < expires:
            return value
        else:
            # expired → remove
            del _cache[key]
    return None

def cache_set(key, value, ttl_seconds=60):
    """Store value in cache with TTL."""
    expires = time.time() + ttl_seconds
    _cache[key] = (value, expires)

