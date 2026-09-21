"""Reject recognizable publisher branding and placeholder images by URL."""
import re
from urllib.parse import unquote, urlsplit

# Do not reject generic hero/banner/og names: they also identify article artwork.
_COMMON_IMAGE = re.compile(
    r'(?<![a-z0-9])(?:logos?|favicons?|apple[-_ ]touch[-_ ]icon|'
    r'placeholders?|no[-_ ]?image|'
    r'(?:default|fallback)[-_ ](?:og|opengraph|social|share|image|thumbnail)(?:[-_ ]image)?)'
    r'(?![a-z0-9])', re.IGNORECASE,
)


def article_image_url(value, favicon_url=None):
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = urlsplit(value)
        if parsed.scheme not in ('http', 'https') or not parsed.hostname:
            return None
        path = unquote(parsed.path)
        if _COMMON_IMAGE.search(path) or _COMMON_IMAGE.search(unquote(parsed.query)):
            return None
        if favicon_url:
            favicon = urlsplit(favicon_url)
            if (parsed.hostname, parsed.path) == (favicon.hostname, favicon.path):
                return None
    except ValueError:
        return None
    return value
