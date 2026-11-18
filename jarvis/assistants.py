"""Choose the assistant for a single turn without another model call."""
import re

CHOICES = ("auto", "jarvis", "tuki")

_TUKI_PREFIX = re.compile(r"^(?:hey\s+)?tuki\b[\s,:.!?-]*", re.I)
_TUKI_SUFFIX = re.compile(r",\s*tuki[.!?]*$", re.I)
_JARVIS_PREFIX = re.compile(r"^jarvis:\s*", re.I)
_WAKE_PREFIX = re.compile(r"^(?:hey\s+)?(?:jarvis|jarvus|jervis|travis)\b[\s,]+", re.I)
_EDITING = re.compile(
    r"^(?:(?:can|could|would|will) you\s+|please\s+)*"
    r"(?:fix (?:my |the |this )?(?:spelling|grammar)|proofread|spell[- ]?check|"
    r"(?:correct|check) (?:my |the |this )?(?:spelling|grammar|punctuation)|"
    r"rewrite|rephrase|polish my|read (?:this|that) aloud|summari[sz]e (?:this|that)\b)", re.I
)
FACT_CHECK = re.compile(r"\b(?:fact[- ]?check|check (?:that|this)\b|verify (?:that|this|these|the claim|the facts))", re.I)
_TECHNICAL = re.compile(
    r"\b(?:fact[- ]?check|verify (?:that|this|these|the claim|the facts)|"
    r"check (?:that|this|these) (?:claim|statements?|facts?|against sources)|"
    r"look (?:this|that) up|web search|search (?:the )?(?:web|internet)|research|"
    r"debug|stack trace|traceback|unit tests?|refactor|compile|source code|"
    r"script|programming|write (?:some |the |a )?code|"
    r"maths?|calculate|solve|equation|derivative|integral|matrix|"
    r"(?:list|find|read|manage|sort|rename|move|copy|organi[sz]e) (?:my |the |these |local )?"
    r"(?:files?|folders?|documents?)|compare (?:these|the) sources)\b", re.I
)


def route(text, preference="auto", mode="everyday"):
    """Return the assistant name and the addressed request."""
    for pattern, assistant in ((_TUKI_PREFIX, "tuki"), (_TUKI_SUFFIX, "tuki"),
                               (_JARVIS_PREFIX, "jarvis")):
        match = pattern.search(text)
        if match:
            return assistant, (text[:match.start()] + text[match.end():]).strip()
    request = _WAKE_PREFIX.sub("", text)
    if preference in ("jarvis", "tuki"):
        return preference, request
    if mode == "coding" or request.startswith(("/fix ", "/search ", "/diff", "/apply", "/undo")):
        return "tuki", request
    if mode != "talk" and not _EDITING.match(request) and (_TECHNICAL.search(request) or FACT_CHECK.search(request)):
        return "tuki", request
    return "jarvis", request
