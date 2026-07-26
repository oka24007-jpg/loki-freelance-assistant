import re

from app.keywords import (
    HARD_REJECT_KEYWORDS,
    INTEREST_CATEGORIES,
    SOFT_NEGATIVE_KEYWORDS,
)
from app.normalize import normalize


DIRECT_NOTIFY_THRESHOLD = 85
GEMINI_THRESHOLD = 30

SAFE_DIRECT_CATEGORIES = {
    "power_bi",
    "excel",
    "data_analysis",
    "sql",
    "gis",
}

# If the accumulated soft-negative penalties reach this value,
# the project becomes too "tech-heavy" to bypass Gemini.
DIRECT_NOTIFY_SOFT_PENALTY_LIMIT = -60


def _contains_keyword(text: str, keyword: str) -> bool:
    """
    English keywords use word boundaries to avoid false positives
    like 'bot' matching 'robotics'.

    Arabic keywords continue using substring matching because \b
    is unreliable for Arabic.
    """
    if re.search(r"[a-z]", keyword):
        pattern = r"\b" + re.escape(keyword) + r"\b"
        return re.search(pattern, text) is not None

    return keyword in text


def _mask_keyword(text: str, keyword: str) -> str:
    """
    Replace matched keyword with spaces so shorter overlapping
    keywords cannot match afterwards.

    Keeps string length unchanged.
    """
    if re.search(r"[a-z]", keyword):
        pattern = r"\b" + re.escape(keyword) + r"\b"
    else:
        pattern = re.escape(keyword)

    return re.sub(
        pattern,
        lambda m: " " * len(m.group(0)),
        text,
    )


def keyword_filter(text: str):
    normalized = normalize(text)

    score = 0

    matched_categories = set()
    positive_matches = []
    soft_negative_matches = []
    hard_reject_matches = []

    # ------------------------------------------------------------------
    # Build one master keyword list.
    #
    # Duplicate keywords across categories keep only the highest weight.
    # ------------------------------------------------------------------
    keyword_map = {}

    for category, keywords in INTEREST_CATEGORIES.items():
        for keyword, weight in keywords.items():
            normalized_keyword = normalize(keyword)

            existing = keyword_map.get(normalized_keyword)

            if existing is None or weight > existing["weight"]:
                keyword_map[normalized_keyword] = {
                    "keyword": keyword,
                    "weight": weight,
                    "category": category,
                }

    ordered_keywords = sorted(
        keyword_map.values(),
        key=lambda x: len(normalize(x["keyword"])),
        reverse=True,
    )

    remaining_text = normalized

    # ------------------------------------------------------------------
    # Positive keywords
    # ------------------------------------------------------------------

    for item in ordered_keywords:
        keyword = normalize(item["keyword"])

        if _contains_keyword(remaining_text, keyword):
            score += item["weight"]

            matched_categories.add(item["category"])

            positive_matches.append({
                "keyword": item["keyword"],
                "weight": item["weight"],
                "category": item["category"],
            })

            remaining_text = _mask_keyword(
                remaining_text,
                keyword,
            )

    # ------------------------------------------------------------------
    # Soft negatives
    # ------------------------------------------------------------------

    for keyword, penalty in SOFT_NEGATIVE_KEYWORDS.items():
        if _contains_keyword(normalized, normalize(keyword)):
            score += penalty

            soft_negative_matches.append({
                "keyword": keyword,
                "weight": penalty,
            })

    total_soft_penalty = sum(
        match["weight"]
        for match in soft_negative_matches
    )

    has_dangerous_tech = (
        total_soft_penalty <= DIRECT_NOTIFY_SOFT_PENALTY_LIMIT
    )

    # ------------------------------------------------------------------
    # Hard rejects
    # ------------------------------------------------------------------

    for keyword in HARD_REJECT_KEYWORDS:
        if _contains_keyword(normalized, normalize(keyword)):
            hard_reject_matches.append(keyword)

    hard_reject = (
        len(hard_reject_matches) > 0
        and len(positive_matches) == 0
    )

    matched = len(positive_matches) > 0

    categories_are_safe = (
        matched_categories
        and matched_categories.issubset(
            SAFE_DIRECT_CATEGORIES
        )
    )

    # ------------------------------------------------------------------
    # Routing
    # ------------------------------------------------------------------

    notify_directly = (
        matched
        and not hard_reject
        and score >= DIRECT_NOTIFY_THRESHOLD
        and categories_are_safe
        and not has_dangerous_tech
    )

    needs_gemini = (
        matched
        and not hard_reject
        and not notify_directly
        and score >= GEMINI_THRESHOLD
    )

    return {
        "matched": matched,
        "score": score,
        "categories": sorted(matched_categories),
        "positive_matches": positive_matches,
        "soft_negative_matches": soft_negative_matches,
        "hard_reject_matches": hard_reject_matches,
        "hard_reject": hard_reject,

        "total_soft_penalty": total_soft_penalty,
        "has_dangerous_tech": has_dangerous_tech,

        "notify_directly": notify_directly,
        "needs_gemini": needs_gemini,

        "normalized_text": normalized,
    }
