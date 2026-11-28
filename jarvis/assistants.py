"""Choose the assistant for a single turn without another model call."""
import re

CHOICES = ("auto", "jarvis", "tuki", "both")
TUKI_NAME = "TUKI"
TUKI_FULL_NAME = "Technical Utility for Knowledge and Insight"

_TUKI_NAME_QUESTION = re.compile(
    r"\b(?:what (?:(?:does|do) (?:the letters in |each letter in )?tuki stand for|tuki stands for|is tuki(?:'s full name)?)|"
    r"tuki(?:'s)? (?:acronym|full name)|(?:your name|tuki) (?:stand|stands) for)\b", re.I
)


def display_name(assistant):
    return TUKI_NAME if assistant == "tuki" else "Jarvis"


def tuki_name_question(text, assistant):
    return bool(_TUKI_NAME_QUESTION.search(text) or (
        assistant == "tuki" and re.fullmatch(r"what (?:does your name|does each letter|do the letters) stand for[.?!]*", text, re.I)
    ))

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
    r"maths?|calculate|solve|equation|derivative|integral|matrix|probability|statistics|"
    r"percent(?:age)?|convert \d|unit conversion|algorithm|big[- ]o|complexity|regex|regular expression|"
    r"sql|api|json|yaml|git|merge conflict|compiler|runtime|dependency|install(?:ing|ation)? error|"
    r"error (?:code|message)|exception|segfault|\w+(?:Error|Exception)\b|"
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
    if mode in ("coding", "research", "cybersecurity") or request.startswith(("/fix", "/test", "/build", "/search ", "/calc ", "/files", "/diff", "/apply", "/undo",
                                               "/check ", "/read ", "/prs", "/git-status")):
        return "tuki", request
    if mode != "talk" and not _EDITING.match(request) and (_TECHNICAL.search(request) or FACT_CHECK.search(request)):
        return "tuki", request
    return "jarvis", request


_CONFIDENCE = re.compile(r"^\s*confidence\s*:", re.I | re.M)
_EVIDENCE_TOOLS = {"web_search", "search_library", "read_source", "check_sources", "search_documents",
                   "calculate", "read_code", "search_files"}


def label_uncertainty(reply, tools_used=()):
    """Make TUKI's answers say what they rest on. Adds a note when the model gave no confidence
    line, and says when no source or tool was checked in this turn."""
    if not reply or reply.startswith(("Preview only.", "Proposed edit for", "Stopped", "Couldn't", "My brain")):
        return reply
    used = sorted(set(tools_used) & _EVIDENCE_TOOLS)
    notes = []
    if not _CONFIDENCE.search(reply):
        notes.append("Confidence: not stated by the model.")
    notes.append("Checked with: " + ", ".join(used) + "." if used else
                 "Checked with: nothing in this turn. This answer comes from the model's own knowledge.")
    return reply.rstrip() + "\n\n" + " ".join(notes)
