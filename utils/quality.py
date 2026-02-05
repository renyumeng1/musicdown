QUALITY_BEST_TO_WORST: list[str] = [
    "MASTER",
    "ATMOS_2",
    "ATMOS_51",
    "flac",
    "320",
    "128",
    "m4a",
]


_ALIASES: dict[str, str] = {
    "aac": "m4a",
    "m4a": "m4a",
    "mp3_128": "128",
    "mp3_320": "320",
    "flac": "flac",
    "master": "MASTER",
    "sq": "MASTER",
    "atmos_2": "ATMOS_2",
    "dolby": "ATMOS_2",
    "atmos_51": "ATMOS_51",
    "hi": "ATMOS_51",
}


def canonical_quality(quality: str) -> str:
    q = (quality or "").strip()
    if not q:
        return ""

    q = q.replace("-", "_")
    upper = q.upper()
    if upper in {"MASTER", "ATMOS_2", "ATMOS_51"}:
        return upper

    lower = q.lower()
    if lower in {"flac", "m4a"}:
        return lower
    if lower in {"128", "320", "ogg"}:
        return lower

    return _ALIASES.get(lower, q)


def best_available_fallback_qualities(preferred: str) -> list[str]:
    """Fallback by exploring the highest available quality.

    Order:
    1) preferred
    2) then from best → worst (excluding preferred)
    """
    preferred_q = canonical_quality(preferred)
    if not preferred_q:
        return []

    candidates = [preferred_q]
    for q in QUALITY_BEST_TO_WORST:
        if q != preferred_q:
            candidates.append(q)

    seen: set[str] = set()
    out: list[str] = []
    for c in candidates:
        if c and c not in seen:
            seen.add(c)
            out.append(c)
    return out
