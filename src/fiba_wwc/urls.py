"""URL hygiene: strip tracking and referral cruft before storing or rendering."""

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

# Exact param names to drop. Anything starting with "utm_" goes too.
TRACKING_PARAMS = frozenset(
    {
        "fbclid",
        "gclid",
        "dclid",
        "msclkid",
        "twclid",
        "igshid",
        "yclid",
        "mc_cid",
        "mc_eid",
        "_hsenc",
        "_hsmi",
        "vero_id",
        "wickedid",
        "ref",
        "referrer",
        "referral",
        "source",
        "campaign",
        "affiliate",
        "partner",
        "cmpid",
        "cid",
        "s_kwcid",
    }
)


def clean_url(url: str | None) -> str | None:
    """Drop tracking params and empty fragments, keeping everything meaningful.

    The FIBA payload hands out broadcaster links like
    ``https://www.dazn.com/en-CH/competition/Competition:66byt...?utm_source=fibaweb
    &utm_medium=referral&utm_campaign=u17wwc&utm_content=gamelinks`` -- the path
    segment is the content, the query is pure referral tagging.
    """
    if not url:
        return url
    parts = urlsplit(url.strip())
    kept = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if not (k.lower().startswith("utm_") or k.lower() in TRACKING_PARAMS)
    ]
    return urlunsplit(
        (
            parts.scheme,
            parts.netloc,
            parts.path,
            urlencode(kept),
            "",  # fragments on these links are never meaningful
        )
    )
