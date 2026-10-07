"""Product matching and selection (rule-based, no AI, no network).

For one ingredient and the products a store returned, we:
  1. EVALUATE each product: is it the right thing? what pack size? how many packs? what cost?
  2. RANK them: confident matches first, then cheapest total cost to cover the amount needed.
  3. Report a CONFIDENCE (high / medium / low) with short reasons, which the UI shows as flags.

Confidence is the weakest of these rule checks (an optional AI review in report.py can lower
it further, never raise it):
    name doesn't contain the ingredient or a known synonym        -> low
    name looks like a different FORM (drink/biscuit/coconut...)   -> low
    name looks like a different INGREDIENT (brown vs caster sugar)-> low
    pack size couldn't be parsed                                  -> low
    sold by a unit we can't convert (ml vs g)                     -> low
    only a generic one-word synonym matched ("sugar")             -> medium
"""
import math
import re

from app import units
from app.models import Candidate, Confidence, SearchHit, TaskResult
from app.units import PackOption, Quantity, choose_packs, describe_need, format_amount, parse_size, price_per_unit

RANK = {"high": 3, "medium": 2, "low": 1}

# Words that make a product a different thing, unless the ingredient itself contains the word.
# e.g. "cocoa powder" vs "Cocoa Drink Powder", "milk" vs "Coconut Milk", "butter" vs "Butter Cookies".
DIFFERENT_FORM_MARKERS = [
    "drink", "mix", "chip", "biscuit", "cookie", "wafer", "noodle", "popcorn", "snack", "ice cream", "tortilla",
    "wrap", "sweetener", "boba", "syrup", "flavoured", "flavored", "flavour", "flavor", "coconut", "peanut",
    "malt", "pancake", "roll", "condensed", "chocolate", "self raising", "bread", "wholemeal",
    "gluten free", "sugar free", "skim", "low fat",
]


def _stem(w: str) -> str:
    if w.endswith("oes") and len(w) > 4:
        return w[:-2]
    if w.endswith("s") and not w.endswith("ss") and len(w) > 3:
        return w[:-1]
    return w


def _phrase(text: str) -> str:
    """" hello big world " : lower-cased, punctuation-free, plural-insensitive, padded with spaces
    so ' big world ' can be found with a plain `in` and never matches half a word."""
    return " " + " ".join(_stem(t) for t in re.findall(r"[a-z0-9]+", text.lower())) + " "


def _name_phrases(ingredient: str) -> tuple[list[str], list[str]]:
    """(strong, weak) phrases that would identify the ingredient inside a product name.

    strong = the ingredient's own name, its canonical name, and multi-word synonyms
    weak   = other one-word synonyms ("sugar" for "caster sugar"): too generic to trust fully
    """
    name = " ".join(ingredient.lower().split())
    canon = units.canonical_name(name)
    own = {name} | ({canon} if canon else set())
    strong, weak = set(own), set()
    for n in units.known_names(name):
        (strong if len(n.split()) > 1 else weak).add(n)
    weak -= strong
    return sorted(_phrase(p) for p in strong), sorted(_phrase(p) for p in weak)


def _other_ingredient_names(ingredient: str) -> list[str]:
    """Names of OTHER known ingredients (their canonical names and multi-word synonyms)."""
    canon = units.canonical_name(ingredient)
    out = []
    for key, info in units.INGREDIENTS.items():
        if key == canon:
            continue
        out += [key] + [s for s in info.synonyms if len(s.split()) > 1]
    return out


def evaluate(ingredient: str, need: Quantity | None, hit: SearchHit) -> Candidate:
    """Judge one product for one ingredient. Pure function, easy to test."""
    text = _phrase(hit.name)
    conf: Confidence = "high"
    reasons: list[str] = []

    def lower_to(level: Confidence, reason: str):
        nonlocal conf
        if RANK[level] < RANK[conf]:
            conf = level
        if reason not in reasons:
            reasons.append(reason)

    # --- 1. does the name contain the ingredient (or a synonym)?
    strong, weak = _name_phrases(ingredient)
    if any(p in text for p in strong):
        pass
    elif any(p in text for p in weak):
        lower_to("medium", f"Matched loosely on '{next(p for p in weak if p in text).strip()}'")
    else:
        lower_to("low", f"Name doesn't mention '{ingredient}'")

    # --- 2. does it look like a different form or a different ingredient?
    own_words = _phrase(" ".join(units.known_names(ingredient) | {ingredient.lower()}))
    for marker in DIFFERENT_FORM_MARKERS:
        mp = _phrase(marker)
        if mp in text and mp not in own_words:
            lower_to("low", f"Might be a different product (name has '{marker}')")
            break
    # Other known ingredients named in the product ("Soft Brown Sugar" for caster sugar, "Full Cream Milk"
    # for cream)? Cut their names out of the text; if our own name no longer appears, it was a false match.
    remaining, seen = text, None
    for other in sorted(_other_ingredient_names(ingredient), key=len, reverse=True):  # longest first
        op = _phrase(other)
        if any(op in sp for sp in strong):  # "milk" inside our own "condensed milk" is not a rival
            continue
        if op in remaining:
            remaining, seen = remaining.replace(op, " "), seen or other
    if seen and not any(p in remaining for p in strong):
        lower_to("low", f"Looks like a different ingredient ('{seen}')")

    # --- 3. size and units
    size = parse_size(hit.size)
    unit_price = None
    count, total, leftover, leftover_pct, leftover_unit, need_text = 1, hit.price, 0.0, 0.0, "", ""
    if size is None:
        lower_to("low", "Size unclear")
    else:
        unit_price = price_per_unit(hit.price, size)
        converted = units.convert_amount(ingredient, need, size.unit) if need else None
        if need and converted is None and {need.unit, size.unit} == {"g", "ml"}:
            # No density known: assume water-like (1 g ~ 1 ml) but tell the user it's an estimate.
            converted = Quantity(need.amount, size.unit)
            lower_to("medium", "Estimated: assumed 1 g ≈ 1 ml")
        if need and converted is None:
            lower_to("low", f"Sold by {size.unit}, recipe needs {need.unit}")
        elif converted:
            pc = choose_packs(converted.amount, [PackOption(hit.product_id, size.amount, hit.price, hit.size)])
            if pc:
                count, total = pc.count, pc.total_cost
                leftover, leftover_pct, leftover_unit = pc.leftover, pc.leftover_pct, size.unit
                need_text = describe_need(converted.amount, size.unit, pc)

    return Candidate(
        store=hit.store, product_id=hit.product_id, name=hit.name, size=hit.size, price=hit.price,
        url=hit.url, in_stock=hit.in_stock, pack_count=count, total_cost=round(total, 2),
        unit_price=round(unit_price.value, 4) if unit_price else None,
        unit_price_label=unit_price.label if unit_price else "", need_text=need_text,
        leftover_amount=round(leftover, 2), leftover_unit=leftover_unit, leftover_pct=round(leftover_pct, 4),
        significant_leftover=leftover_pct > units.LEFTOVER_THRESHOLD,
        leftover_text=f"{format_amount(leftover, size.unit)} left over" if size and leftover > 0 else "",
        confidence=conf, reasons=reasons,
    )


def sort_key(c: Candidate):
    """Confident matches first, then the cheapest way to cover the need, then least waste, then best value."""
    return (-RANK[c.confidence], c.total_cost, c.leftover_pct, c.unit_price if c.unit_price is not None else math.inf)


def rank(candidates: list[Candidate]) -> list[Candidate]:
    return sorted((c for c in candidates if c.in_stock), key=sort_key)


class Selector:
    """Plugs into the agent: chooses which product to open, and remembers every evaluated option.

    needs: ingredient name -> amount needed in standard units (from units.to_standard).
    """

    def __init__(self, needs: dict[str, Quantity], keep: int = 6):
        self.needs = needs
        self.keep = keep
        self._ranked: dict[tuple[str, str], list[Candidate]] = {}

    def choose(self, ingredient: str, hits: list[SearchHit]) -> SearchHit | None:
        """The agent's `chooser`: returns the hit whose page should be opened (or None)."""
        need = self.needs.get(ingredient)
        ranked = rank([evaluate(ingredient, need, h) for h in hits])
        self._ranked[(hits[0].store, ingredient)] = ranked[: self.keep]
        if not ranked:
            return None
        return next(h for h in hits if h.product_id == ranked[0].product_id)

    def enrich(self, result: TaskResult) -> None:
        """The agent's `enricher`: attach the ranked options to a result, and sanity-check the
        product page we actually opened against what the search result claimed."""
        cands = self._ranked.get((result.store, result.ingredient), [])
        result.candidates = cands
        d = result.chosen
        if d and cands and cands[0].product_id == d.product_id:
            top = cands[0]
            if abs(d.price - top.price) > 0.001 or not d.in_stock:
                top.confidence = "low"
                top.reasons.append("Price or stock on the product page differs from the search result")
