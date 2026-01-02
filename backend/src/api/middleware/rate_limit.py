"""
Rate Limiting Middleware for FastAPI

Provides configurable rate limiting to prevent abuse:
- Brute force attacks on login
- API abuse / DoS
- Resource exhaustion

Uses in-memory storage by default. For production with multiple instances,
configure Redis via REDIS_URL environment variable.
"""

import os
import time
import logging
from typing import Dict, Optional, Tuple
from collections import defaultdict
from fastapi import Request, HTTPException, status
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger(__name__)


class RateLimitStore:
    """
    In-memory rate limit store.

    For production with multiple app instances, extend this to use Redis.
    """

    def __init__(self):
        # Structure: {key: [(timestamp, count), ...]}
        self._requests: Dict[str, list] = defaultdict(list)
        self._cleanup_interval = 60  # seconds
        self._last_cleanup = time.time()

    def _cleanup_old_entries(self, window_seconds: int):
        """Remove entries older than the window"""
        current_time = time.time()

        # Only cleanup periodically to avoid overhead
        if current_time - self._last_cleanup < self._cleanup_interval:
            return

        self._last_cleanup = current_time
        cutoff = current_time - window_seconds

        keys_to_delete = []
        for key, timestamps in self._requests.items():
            # Filter out old timestamps
            self._requests[key] = [ts for ts in timestamps if ts > cutoff]
            if not self._requests[key]:
                keys_to_delete.append(key)

        for key in keys_to_delete:
            del self._requests[key]

    def is_rate_limited(
        self,
        key: str,
        max_requests: int,
        window_seconds: int
    ) -> Tuple[bool, int, int]:
        """
        Check if a key is rate limited.

        Args:
            key: Unique identifier (e.g., IP address, user ID)
            max_requests: Maximum requests allowed in window
            window_seconds: Time window in seconds

        Returns:
            Tuple of (is_limited, current_count, seconds_until_reset)
        """
        current_time = time.time()
        cutoff = current_time - window_seconds

        # Cleanup old entries periodically
        self._cleanup_old_entries(window_seconds)

        # Filter to only recent requests
        recent_requests = [ts for ts in self._requests[key] if ts > cutoff]
        self._requests[key] = recent_requests

        current_count = len(recent_requests)

        if current_count >= max_requests:
            # Calculate time until oldest request expires
            if recent_requests:
                oldest = min(recent_requests)
                seconds_until_reset = int(oldest + window_seconds - current_time) + 1
            else:
                seconds_until_reset = window_seconds
            return True, current_count, seconds_until_reset

        # Record this request
        self._requests[key].append(current_time)
        return False, current_count + 1, 0

    def reset(self, key: str):
        """Reset rate limit for a key (e.g., after successful login)"""
        if key in self._requests:
            del self._requests[key]


# Global rate limit store
_rate_limit_store = RateLimitStore()


def get_rate_limit_store() -> RateLimitStore:
    """Get the global rate limit store"""
    return _rate_limit_store


# Rate limit configurations for different endpoint types
RATE_LIMITS = {
    # Auth endpoints - strict limits to prevent brute force
    'auth': {
        'max_requests': int(os.getenv('RATE_LIMIT_AUTH_MAX', '5')),
        'window_seconds': int(os.getenv('RATE_LIMIT_AUTH_WINDOW', '60')),
    },
    # API endpoints - moderate limits
    'api': {
        'max_requests': int(os.getenv('RATE_LIMIT_API_MAX', '100')),
        'window_seconds': int(os.getenv('RATE_LIMIT_API_WINDOW', '60')),
    },
    # Upload endpoints - strict limits due to resource usage
    'upload': {
        'max_requests': int(os.getenv('RATE_LIMIT_UPLOAD_MAX', '10')),
        'window_seconds': int(os.getenv('RATE_LIMIT_UPLOAD_WINDOW', '60')),
    },
}


def get_client_ip(request: Request) -> str:
    """
    Get client IP address, handling proxies.

    Note: In production behind a load balancer, configure trusted proxies
    and use X-Forwarded-For header appropriately.
    """
    # Check for forwarded header (when behind proxy)
    forwarded = request.headers.get('X-Forwarded-For')
    if forwarded:
        # Take the first IP (original client)
        return forwarded.split(',')[0].strip()

    # Check for real IP header (nginx)
    real_ip = request.headers.get('X-Real-IP')
    if real_ip:
        return real_ip

    # Fall back to direct connection
    if request.client:
        return request.client.host

    return 'unknown'


def get_rate_limit_key(request: Request, endpoint_type: str) -> str:
    """Generate a rate limit key for the request"""
    client_ip = get_client_ip(request)
    return f"{endpoint_type}:{client_ip}"


def check_rate_limit(
    request: Request,
    endpoint_type: str = 'api'
) -> None:
    """
    Check rate limit and raise HTTPException if exceeded.

    Args:
        request: FastAPI request object
        endpoint_type: Type of endpoint ('auth', 'api', 'upload')

    Raises:
        HTTPException: If rate limit exceeded (429 Too Many Requests)
    """
    if endpoint_type not in RATE_LIMITS:
        endpoint_type = 'api'

    config = RATE_LIMITS[endpoint_type]
    key = get_rate_limit_key(request, endpoint_type)
    store = get_rate_limit_store()

    is_limited, count, retry_after = store.is_rate_limited(
        key=key,
        max_requests=config['max_requests'],
        window_seconds=config['window_seconds']
    )

    if is_limited:
        logger.warning(
            f"Rate limit exceeded for {key}: {count} requests in {config['window_seconds']}s"
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Rate limit exceeded. Try again in {retry_after} seconds.",
            headers={
                'Retry-After': str(retry_after),
                'X-RateLimit-Limit': str(config['max_requests']),
                'X-RateLimit-Remaining': '0',
                'X-RateLimit-Reset': str(int(time.time()) + retry_after),
            }
        )


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Middleware to apply rate limiting to all requests.

    Applies different limits based on endpoint path:
    - /api/auth/* -> 'auth' limits (strict)
    - /api/documents/upload -> 'upload' limits
    - /api/* -> 'api' limits (default)
    """

    async def dispatch(self, request: Request, call_next):
        # Skip rate limiting for health checks and static files
        path = request.url.path
        if path in ('/health', '/', '/api/docs', '/api/redoc', '/openapi.json'):
            return await call_next(request)

        # Determine endpoint type based on path
        if '/auth/' in path or path.endswith('/auth'):
            endpoint_type = 'auth'
        elif '/upload' in path:
            endpoint_type = 'upload'
        elif path.startswith('/api/'):
            endpoint_type = 'api'
        else:
            # Don't rate limit non-API paths
            return await call_next(request)

        # Check rate limit
        try:
            check_rate_limit(request, endpoint_type)
        except HTTPException as e:
            from fastapi.responses import JSONResponse
            return JSONResponse(
                status_code=e.status_code,
                content={'detail': e.detail},
                headers=e.headers
            )

        # Add rate limit headers to response
        response = await call_next(request)

        config = RATE_LIMITS.get(endpoint_type, RATE_LIMITS['api'])
        key = get_rate_limit_key(request, endpoint_type)
        store = get_rate_limit_store()

        # Get current count (don't increment)
        recent = [ts for ts in store._requests.get(key, [])
                  if ts > time.time() - config['window_seconds']]
        remaining = max(0, config['max_requests'] - len(recent))

        response.headers['X-RateLimit-Limit'] = str(config['max_requests'])
        response.headers['X-RateLimit-Remaining'] = str(remaining)

        return response
