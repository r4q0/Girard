"""Quick check of the line filter on typical call lines. Run: uv run check_filter.py"""
from girard_audio.filter import LineFilter

f = LineFilter(["Zapier", "Flowbase", "Exact", "Koref", "Salesforce"])
cases = [
    "Yeah.", "Mm-hmm, okay.", "Yeah, sure, got it.", "No.", "How much?", "€50k.", "HubSpot.",
    "Right now we use Zap here for some of it, but it keeps breaking.",
    "We're also talking to Flow Base, they said about forty cents per document.",
    "So um we we we basically need, like, you know, a way to get orders into exact.",
    "I mean, the thing is,", "our planner quit two months ago.",
    "Maybe.",
    "What's your hourly rate?", "What's your hourly rate?",
    "It's kind of a mess honestly.",
    "Probably.",
]
t = 0.0
for raw in cases:
    r = f.process(raw, now=t)
    print(f"{r.rule:8} | {raw:75} -> {r.text}")
    t += 1.0
t += 5
print("flush    |", f.flush_due(now=t))
