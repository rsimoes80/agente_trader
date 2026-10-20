"""Small operator credential boundary for the new observation-session controls."""

import hmac


def authorized(supplied: str, configured: str) -> bool:
    return bool(configured) and hmac.compare_digest(supplied, configured)
