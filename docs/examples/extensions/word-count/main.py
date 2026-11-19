"""Example Jarvis extension. Each tool is a function that takes the declared inputs as keyword
arguments and returns a JSON-serialisable dict with the declared outputs."""


def count_words(text):
    return {"words": len(text.split()), "characters": len(text)}
