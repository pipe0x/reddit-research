"""Phrase patterns (English + German) that indicate demand or competition."""
import re

SIGNALS = {
    # Someone is actively looking for a solution.
    "seeking": [
        r"\bis there (?:a|an|any) (?:app|tool|software|service|site|website|platform|way|product|plugin|extension)\b",
        r"\b(?:looking|searching) for (?:a|an|some) (?:app|tool|software|service|solution|platform|website|plugin)\b",
        r"\bany (?:recommendations?|suggestions?|tips) (?:for|on)\b",
        r"\bwhat (?:app|tool|software|service|platform|program)s? (?:do|does|should|would|can) (?:you|i|people)\b",
        r"\bcan (?:anyone|someone|you) recommend\b",
        r"\bdoes (?:anyone|anybody) know (?:of )?(?:a|an|any)\b",
        r"\balternatives? (?:to|for)\b",
        r"\bhow do (?:you|y'all|people) (?:track|manage|handle|keep track|organi[sz]e|deal with)\b",
        r"\bgibt es (?:eine|ein|irgendeine) (?:app|tool|software|lösung|möglichkeit|plattform)\b",
        r"\bsuche (?:eine|ein|nach einer?) (?:app|tool|software|lösung|plattform)\b",
        r"\bkennt (?:jemand|ihr) (?:eine|ein)\b",
    ],
    # The problem hurts.
    "pain": [
        r"\bi (?:really )?hate\b", r"\bfrustrat\w*", r"\bpain in the\b", r"\bnightmare\b", r"\bdrives? me (?:crazy|nuts)\b",
        r"\bwast(?:e|es|ed|ing) (?:so much|hours|time|days)\b", r"\bstruggl\w*", r"\btedious\b", r"\btakes? forever\b",
        r"\bhours? (?:every|each|a|per) (?:week|day|month)\b", r"\bsick of\b", r"\bfed up\b", r"\bhead ?ache\b",
        r"\bnervt\b", r"\balbtraum\b", r"\bzeitaufw[äa]ndig\b", r"\bkostet mich\b", r"\bkein bock\b",
    ],
    # Explicit willingness to pay.
    "wtp": [
        r"\b(?:would|i'?d|i would|happily|gladly|definitely) pay\b", r"\bwilling to pay\b", r"\btake my money\b",
        r"\bworth paying\b", r"\bshut up and take\b", r"\bpay (?:good )?money for\b",
        r"[$€£]\s?\d+(?:\.\d+)?\s?(?:/|per |a )\s?(?:month|mo|year|yr|user)\b",
        r"\bw[üu]rde (?:dafür |gerne |sofort )?(?:zahlen|bezahlen)\b", r"\bzahlen w[üu]rde\b",
    ],
    # People cobble together their own solution.
    "workaround": [
        r"\bspreadsheets?\b", r"\bexcel\b", r"\bgoogle sheets?\b", r"\bmanually\b", r"\bby hand\b",
        r"\bnotion template\b", r"\bwrote (?:a|my own) script\b", r"\bbuilt (?:my own|a little|a small)\b",
        r"\bworkaround\b", r"\bcopy(?:ing)? and past(?:e|ing)\b", r"\bpen and paper\b",
        r"\btabelle\b", r"\bh[äa]ndisch\b", r"\bmanuell\b", r"\bzettel\b",
    ],
    # Dissatisfaction with existing products (= gap in the market).
    "complaint": [
        r"\btoo expensive\b", r"\boverpriced\b", r"\bclunky\b", r"\bbloated\b", r"\bbuggy\b", r"\bmissing (?:a )?feature",
        r"\bdoesn'?t (?:support|have|let|allow|integrate)\b", r"\bswitched (?:away )?from\b", r"\bcancel+ed (?:my|our)\b",
        r"\bprice (?:hike|increase)\b", r"\bterrible (?:support|ux|ui)\b", r"\bzu teuer\b", r"\bumständlich\b",
    ],
    # Someone answers with an existing product (= the need is already served).
    "recommendation": [
        r"\bi (?:use|used|recommend|love|switched to)\b", r"\bwe (?:use|used|switched to)\b", r"\bcheck out\b",
        r"\bbeen using\b", r"\bworks (?:great|well|perfectly)\b", r"\bhighly recommend\b", r"\bgive \w+ a try\b",
        r"\bich (?:nutze|benutze|empfehle)\b", r"\bwir (?:nutzen|benutzen)\b",
    ],
}

COMPILED = {name: [re.compile(p, re.I) for p in patterns] for name, patterns in SIGNALS.items()}

# Capitalized product-like names right after "use X", "alternative to X", ...
CANDIDATE = re.compile(
    r"(?:alternatives? (?:to|for)|switched (?:from|to)|moved (?:from|to)|\b[Ii] use|\b[Ww]e use|been using|check out|"
    r"\btried|recommend|using|[Ii]ch nutze|[Ww]ir nutzen|like|than|vs\.?|versus)\s+"
    r"([A-Z][A-Za-z0-9]*(?:[.\-][A-Za-z0-9]+)*(?:\s[A-Z][A-Za-z0-9]+)?)")

NOT_PRODUCTS = {
    "I", "It", "The", "This", "That", "They", "We", "You", "My", "A", "An", "And", "But", "So", "If", "In", "On", "For",
    "Reddit", "Google", "Amazon", "Facebook", "Instagram", "YouTube", "TikTok", "ChatGPT", "AI", "US", "USA", "UK", "EU",
    "Excel", "Sheets", "Google Sheets", "Notion", "Word", "Windows", "Mac", "iPhone", "Android", "Apple", "Microsoft",
    "Edit", "Update", "Yes", "No", "OP", "Thanks", "Also", "Just", "What", "When", "Why", "How", "There", "Here",
    "Is", "Do", "Not", "All", "Any", "Some", "Most", "One", "Me", "He", "She", "His", "Her", "Our", "Your", "Their",
    "Ich", "Wir", "Die", "Der", "Das", "Und", "Aber", "Es", "Ein", "Eine", "Monday", "Friday", "January",
}


def signals(text):
    return {name: True for name, patterns in COMPILED.items() if any(p.search(text) for p in patterns)}


SWITCH = re.compile(r"\bfrom [A-Z][\w.\-]* to ([A-Z][A-Za-z0-9]*(?:[.\-][A-Za-z0-9]+)*)")


def candidates(text):
    found = set()
    for match in list(CANDIDATE.finditer(text)) + list(SWITCH.finditer(text)):
        name = match.group(1).strip(" .-")
        if name in NOT_PRODUCTS or name.split()[0] in NOT_PRODUCTS or len(name) < 3:
            continue
        found.add(name)
    return found
