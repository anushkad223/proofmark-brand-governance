"""Proofmark rule engine: exact rules over parsed paragraphs. Every finding cites its rule."""
import re, datetime as dt
from docx import Document

RULE = {
 "claim": "Claims policy 3.2: any superlative or comparative claim must match an entry in the approved claim ledger.",
 "exp": "Claims policy 3.4: a claim may be used only until its valid-until date.",
 "term": "Glossary: write the brand as \u201cBrightloop\u201d, say \u201cemail\u201d not \u201ce-mail\u201d, avoid \u201ccheap\u201d.",
 "a11y": "WCAG 2.2, 1.4.3 Contrast (Minimum): 4.5:1 normal text, 3:1 large text. 1.1.1: images need text alternatives.",
}
def rule_offer(L): return f"Approved offers sheet: the offer ends {L['offer']['end']} and the discount is {L['offer']['disc']}% off."
DEFAULT_LIB = {
 "claims": [{"id": "C-014", "text": "Rated 4.6/5 by 1,200+ customers", "until": "2027-06-30"},
            {"id": "C-021", "text": "Free delivery on orders over \u20b9999", "until": "2027-03-31"},
            {"id": "C-007", "text": "Trusted by 500+ teams", "until": "2026-09-30"}],
 "offer": {"end": "15 Dec", "disc": 20},
 "terms": [["Bright[ -]?loop", "Brightloop"], ["e-mail", "email"], [r"\bcheap\b", "affordable"]],
}
def parse_docx(f):
    out = []
    for p in Document(f).paragraphs:
        runs = [r for r in p.runs if r.text.strip()]
        col = next((str(r.font.color.rgb) for r in p.runs if r.font.color is not None and r.font.color.rgb is not None), None)
        sz = next((int(r.font.size.pt * 2) for r in p.runs if r.font.size), 22)
        dp = p._p.xpath('.//*[local-name()="docPr"]')
        if p.text.strip() or dp:
            out.append({"text": p.text, "color": col, "sz": sz, "bold": any(r.bold for r in runs),
                        "img": bool(dp), "alt": (dp[0].get("descr") or "") if dp else ""})
    return out
def _lum(h):
    c = [int(h[i:i+2], 16) / 255 for i in (0, 2, 4)]
    c = [v / 12.92 if v <= .03928 else ((v + .055) / 1.055) ** 2.4 for v in c]
    return .2126 * c[0] + .7152 * c[1] + .0722 * c[2]
def contrast(a, b="FFFFFF"):
    x, y = _lum(a), _lum(b); return (max(x, y) + .05) / (min(x, y) + .05)
def darken(h):
    c = [int(h[i:i+2], 16) for i in (0, 2, 4)]
    while contrast("%02X%02X%02X" % tuple(c)) < 4.5 and any(c): c = [max(0, v - 8) for v in c]
    return "%02X%02X%02X" % tuple(c)
def check(P, L, today=None):
    today = today or dt.date.today().isoformat(); F = []
    ok = next((c for c in L["claims"] if c["until"] >= today), None)
    def add(**o): F.append({"id": f"F{len(F)+1}", "st": "open", "kind": "text", **o})
    for i, p in enumerate(P):
        t = p["text"]
        m = re.search(r"#1\b|number one|best in class|the best|world-class|guaranteed|unbeatable|market leader", t, re.I)
        if m and not any(c["text"] in t for c in L["claims"]):
            s = next(x for x in re.findall(r"[^.!?]+[.!?]*\s*", t) if m.group(0) in x).strip()
            add(type="Claim", pi=i, match=m.group(0), span=s, fix=ok and ok["text"] + ".", rule=RULE["claim"],
                msg=f"No approved evidence supports \u201c{m.group(0)}\u201d. The claim ledger has no matching entry.")
        for c in L["claims"]:
            if c["until"] < today and c["text"] in t:
                add(type="Expired claim", pi=i, match=c["text"], span=c["text"], fix=ok and ok["text"], rule=RULE["exp"],
                    msg=f"Claim {c['id']} expired on {c['until']}.")
        if re.search(r"ends|until|till|valid|offer", t, re.I):
            for d in re.finditer(r"\b\d{1,2} (?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\b", t):
                if d.group(0) != L["offer"]["end"]:
                    add(type="Offer fact", pi=i, match=d.group(0), span=d.group(0), fix=L["offer"]["end"], rule=rule_offer(L),
                        msg=f"\u201c{d.group(0)}\u201d conflicts with the approved end date, {L['offer']['end']}.")
        pc = re.search(r"(\d+)% off", t, re.I)
        if pc and int(pc.group(1)) != int(L["offer"]["disc"]):
            add(type="Offer fact", pi=i, match=pc.group(0), span=pc.group(0), fix=f"{L['offer']['disc']}% off", rule=rule_offer(L),
                msg=f"\u201c{pc.group(0)}\u201d conflicts with the approved discount, {L['offer']['disc']}% off.")
        for pat, r in L["terms"]:
            x = re.search(pat, t, re.I)
            if x:
                fx = r[0].upper() + r[1:] if x.group(0)[0].isupper() else r
                if x.group(0) != fx:
                    add(type="Terminology", pi=i, match=x.group(0), span=x.group(0), fix=fx, rule=RULE["term"],
                        msg=f"\u201c{x.group(0)}\u201d should be \u201c{fx}\u201d.")
        if p.get("color"):
            need = 3 if (p["bold"] and p["sz"] >= 28) or p["sz"] >= 36 else 4.5; n = contrast(p["color"])
            if n < need:
                add(type="Accessibility", kind="color", pi=i, match="#" + p["color"], span="#" + p["color"], fix="#" + darken(p["color"]),
                    rule=RULE["a11y"], msg=f"Text colour #{p['color']} on white has contrast {n:.1f}:1. The minimum here is {need}:1.")
        if p.get("img") and not p.get("alt"):
            add(type="Accessibility", kind="note", pi=i, match="image", span="", fix=None, rule=RULE["a11y"], msg="This image has no alt text.")
    return F
def apply_fixes(P, F):
    P = [dict(p) for p in P]
    for f in F:
        if f["fix"] and f["st"] in ("accepted", "edited"):
            t = f.get("newText") if f["st"] == "edited" else f["fix"]
            if f["kind"] == "color": P[f["pi"]]["color"] = t.lstrip("#")
            else: P[f["pi"]]["text"] = P[f["pi"]]["text"].replace(f["span"], t, 1)
    return P
