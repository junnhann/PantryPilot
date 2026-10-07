"""Units: parse messy pack sizes, convert recipe quantities, price per unit, pick packs.

Everything is reduced to ONE of three "standard units" so values can be compared:
    "g"      weight
    "ml"     volume
    "piece"  countable things (eggs, bread rolls...)

Pure functions only (no network, no I/O), so they are easy to unit-test.
"""
import math
import re
from dataclasses import dataclass
from typing import Literal

StdUnit = Literal["g", "ml", "piece"]

CURRENCY = "S$"
LEFTOVER_THRESHOLD = 0.30  # a pack with >30% unused counts as a "significant" leftover


@dataclass(frozen=True)
class Quantity:
    amount: float
    unit: StdUnit


# ============================================================ 1. parsing pack sizes
# Maps every spelling we expect on a shop page -> (standard unit, multiplier).
_UNITS: dict[str, tuple[StdUnit, float]] = {
    # weight
    "kg": ("g", 1000), "kgs": ("g", 1000), "kilogram": ("g", 1000), "kilograms": ("g", 1000),
    "g": ("g", 1), "gm": ("g", 1), "gms": ("g", 1), "gram": ("g", 1), "grams": ("g", 1),
    "mg": ("g", 0.001),
    "oz": ("g", 28.3495), "lb": ("g", 453.592), "lbs": ("g", 453.592),
    # volume
    "l": ("ml", 1000), "ltr": ("ml", 1000), "litre": ("ml", 1000), "litres": ("ml", 1000),
    "liter": ("ml", 1000), "liters": ("ml", 1000),
    "ml": ("ml", 1), "cl": ("ml", 10),
    # counts
    "s": ("piece", 1), "pcs": ("piece", 1), "pc": ("piece", 1), "piece": ("piece", 1),
    "pieces": ("piece", 1), "ct": ("piece", 1), "count": ("piece", 1), "pack": ("piece", 1),
    "packs": ("piece", 1), "unit": ("piece", 1), "units": ("piece", 1), "eggs": ("piece", 1),
}
# Longest names first so "grams" is tried before "g" (regex alternation takes the first match).
_UNIT_RE = "|".join(sorted(map(re.escape, _UNITS), key=len, reverse=True))
_NUM = r"\d+(?:\.\d+)?"

# "6 x 50ml"  (count first)       -> group 1 = count, 2 = amount, 3 = unit
_MULTI_A = re.compile(rf"(?<![\w.])(\d+)\s*x\s*({_NUM})\s*({_UNIT_RE})\b")
# "50ml x 6"  (amount first)      -> group 1 = amount, 2 = unit, 3 = count
_MULTI_B = re.compile(rf"(?<![\w.])({_NUM})\s*({_UNIT_RE})\s*x\s*(\d+)\b")
# "500 g", "1.5l", "12s"
_SIMPLE = re.compile(rf"(?<![\w.])({_NUM})\s*({_UNIT_RE})\b")
# "pack of 12", "box of 6", "tray of 30"
_PACK_OF = re.compile(r"\b(?:pack|box|carton|tray|bag)\s+of\s+(\d+)\b")
_DOZEN = re.compile(rf"(?<![\w.])({_NUM})?\s*dozen\b")


def parse_size(text: str) -> Quantity | None:
    """Turn a pack-size string into a standard Quantity, or None if we can't tell.

    "1kg" -> 1000 g     "6 x 50ml" -> 300 ml     "12s" -> 12 piece     "1.5L" -> 1500 ml

    Returning None (instead of guessing) matters: the matching step marks an
    unparseable size as LOW confidence so the user double-checks it.
    """
    if not text:
        return None
    t = text.lower().replace("×", "x").replace("*", "x")
    t = re.sub(r"(?<=\d),(?=\d{3}(?!\d))", "", t)  # "1,000g" -> "1000g"
    t = re.sub(r"(?<=\d)'s\b", "s", t)  # "12's" -> "12s"

    m = _MULTI_A.search(t)
    if m:
        count, amount, unit = int(m.group(1)), float(m.group(2)), m.group(3)
        return _make(count * amount, unit)
    m = _MULTI_B.search(t)
    if m:
        amount, unit, count = float(m.group(1)), m.group(2), int(m.group(3))
        return _make(count * amount, unit)
    # Several simple sizes? Prefer weight/volume over a count ("1 pack 500g" -> 500 g).
    found = [_make(float(m.group(1)), m.group(2)) for m in _SIMPLE.finditer(t)]
    found = [q for q in found if q]
    if found:
        return next((q for q in found if q.unit != "piece"), found[0])
    m = _PACK_OF.search(t)
    if m:
        return _make(int(m.group(1)), "pcs")
    m = _DOZEN.search(t)
    if m:
        return _make(float(m.group(1) or 1) * 12, "pcs")
    return None


def _make(amount: float, unit: str) -> Quantity | None:
    std, mult = _UNITS[unit]
    total = amount * mult
    if total <= 0:
        return None
    return Quantity(round(total, 4), std)


# ============================================================ 2. ingredient knowledge
@dataclass(frozen=True)
class IngredientInfo:
    kind: Literal["solid", "liquid", "count"]
    g_per_cup: float | None = None  # solids: grams in one cup (used to convert cups/spoons)
    g_per_piece: float | None = None  # countables: grams in one piece (egg ~ 50 g)
    synonyms: tuple[str, ...] = ()


# Common baking conversions. Keys are the canonical names the AI is asked to use.
# tbsp = cup/16 and tsp = cup/48, so 1 cup flour = 120 g, 1 tbsp butter = 14 g (rounded).
INGREDIENTS: dict[str, IngredientInfo] = {
    "plain flour": IngredientInfo("solid", 120, synonyms=("flour", "all-purpose flour", "all purpose flour", "wheat flour", "cake flour")),
    "caster sugar": IngredientInfo("solid", 200, synonyms=("sugar", "white sugar", "granulated sugar", "fine sugar", "superfine sugar")),
    "brown sugar": IngredientInfo("solid", 210, synonyms=("light brown sugar", "dark brown sugar", "muscovado sugar")),
    "icing sugar": IngredientInfo("solid", 120, synonyms=("powdered sugar", "confectioners sugar", "confectioners' sugar")),
    "cocoa powder": IngredientInfo("solid", 85, synonyms=("cocoa", "unsweetened cocoa powder", "unsweetened cocoa", "baking cocoa")),
    "baking powder": IngredientInfo("solid", 192, synonyms=()),  # 1 tsp = 4 g
    "baking soda": IngredientInfo("solid", 240, synonyms=("bicarbonate of soda", "bicarb soda", "bicarb")),  # 1 tsp = 5 g
    "salt": IngredientInfo("solid", 288, synonyms=("table salt", "fine salt")),  # 1 tsp = 6 g
    "butter": IngredientInfo("solid", 227, synonyms=("unsalted butter", "salted butter")),
    "chocolate chips": IngredientInfo("solid", 170, synonyms=("choc chips", "chocolate chunks", "semi-sweet chocolate chips", "dark chocolate chips")),
    "rolled oats": IngredientInfo("solid", 90, synonyms=("oats", "porridge oats", "old fashioned oats")),
    "cornflour": IngredientInfo("solid", 128, synonyms=("cornstarch", "corn starch")),
    "honey": IngredientInfo("solid", 340, synonyms=()),
    "milk": IngredientInfo("liquid", synonyms=("full cream milk", "whole milk", "fresh milk")),
    "vegetable oil": IngredientInfo("liquid", synonyms=("cooking oil", "canola oil", "sunflower oil", "oil")),
    "vanilla extract": IngredientInfo("liquid", synonyms=("vanilla essence", "vanilla", "pure vanilla extract")),
    "cream": IngredientInfo("liquid", synonyms=("heavy cream", "whipping cream", "double cream", "thickened cream")),
    "egg": IngredientInfo("count", g_per_piece=50, synonyms=("eggs", "large egg", "large eggs", "whole egg")),
    # produce/meat: typical weight of one piece, so "2 onions" can be priced from an "Onions 1kg" bag
    "onion": IngredientInfo("count", g_per_piece=150, synonyms=("onions", "brown onion", "brown onions")),
    "banana": IngredientInfo("count", g_per_piece=120, synonyms=("bananas", "ripe banana", "ripe bananas")),
    "potato": IngredientInfo("count", g_per_piece=200, synonyms=("potatoes",)),
    "lemon": IngredientInfo("count", g_per_piece=100, synonyms=("lemons",)),
    "chicken breast": IngredientInfo("count", g_per_piece=200, synonyms=("chicken breasts", "chicken breast fillet")),
}

# Every spelling -> canonical name, e.g. "white sugar" -> "caster sugar".
_CANON: dict[str, str] = {}
for _name, _info in INGREDIENTS.items():
    _CANON[_name] = _name
    for _syn in _info.synonyms:
        _CANON[_syn] = _name


def canonical_name(name: str) -> str | None:
    """Map an ingredient name (or synonym / simple plural) to our canonical name, else None."""
    n = " ".join(name.lower().split())
    if n in _CANON:
        return _CANON[n]
    for plural in ("es", "s"):  # "baking sodas" -> "baking soda"
        if n.endswith(plural) and n[: -len(plural)] in _CANON:
            return _CANON[n[: -len(plural)]]
    return None


def known_names(name: str) -> frozenset[str]:
    """All names that mean the same thing as `name`. Used for product-name matching in step 8.

    Unknown ingredients just return themselves.
    """
    canon = canonical_name(name)
    if canon is None:
        return frozenset({name.lower().strip()})
    return frozenset({canon, *INGREDIENTS[canon].synonyms})


# ============================================================ 3. recipe quantity -> standard
_VOLUME_ML = {"tsp": 5.0, "tbsp": 15.0, "cup": 240.0}
_PINCH_G = 0.3


def to_standard(name: str, quantity: float, unit: str) -> Quantity:
    """Convert a recipe amount ("1 cup", "2 tbsp", "3 piece") into g, ml or piece.

    Uses the ingredient table for density: 1 cup of flour is 120 g but 1 cup of milk is 240 ml.
    Unknown ingredients fall back to ml for cups/spoons.
    """
    canon = canonical_name(name)
    info = INGREDIENTS.get(canon) if canon else None

    if unit == "piece":
        return Quantity(quantity, "piece")
    if unit == "pinch":
        return Quantity(quantity * _PINCH_G, "g")

    if unit in ("g", "kg"):
        grams = quantity * (1000 if unit == "kg" else 1)
        if info and info.kind == "count" and info.g_per_piece:
            return Quantity(grams / info.g_per_piece, "piece")
        if info and info.kind == "liquid":
            return Quantity(grams, "ml")  # treat 1 g ~ 1 ml for water-like liquids
        return Quantity(grams, "g")

    # volume-type units -> millilitres first
    ml = quantity * (1000 if unit == "l" else _VOLUME_ML.get(unit, 1.0))
    if info and info.kind == "solid" and info.g_per_cup:
        return Quantity(ml / 240 * info.g_per_cup, "g")  # cup/spoon of a solid -> grams
    return Quantity(ml, "ml")


def convert_amount(name: str, q: Quantity, target: StdUnit) -> Quantity | None:
    """Express `q` in `target` unit if we can (piece <-> g via typical piece weight), else None.

    "2 piece of onion" -> 300 g;  "200 g of egg" -> 4 piece;  g vs ml -> None (unknown density).
    """
    if q.unit == target:
        return q
    canon = canonical_name(name)
    info = INGREDIENTS.get(canon) if canon else None
    if info and info.g_per_piece:
        if q.unit == "piece" and target == "g":
            return Quantity(q.amount * info.g_per_piece, "g")
        if q.unit == "g" and target == "piece":
            return Quantity(q.amount / info.g_per_piece, "piece")
    return None


def tidy_quantity(quantity: float, unit: str) -> float:
    """Round an amount to something a person would write ("0.88 cup" -> 1 cup).

    Pieces round UP (you can't buy half an egg), g/ml to the nearest 5, spoons/cups to a quarter.
    """
    if unit == "piece":
        return float(max(1, math.ceil(quantity - 1e-9)))
    if unit in ("g", "ml"):
        return float(max(5, round(quantity / 5) * 5))
    if unit == "pinch":
        return 1.0
    return max(0.25, round(quantity * 4) / 4)


# ============================================================ 4. price per unit
@dataclass(frozen=True)
class UnitPrice:
    value: float  # price per 100 g / 100 ml / 1 piece. This is the number we sort by.
    unit: StdUnit

    @property
    def label(self) -> str:
        per = {"g": "100g", "ml": "100ml", "piece": "piece"}[self.unit]
        return f"{CURRENCY}{self.value:.2f} / {per}"


def price_per_unit(price: float, size: Quantity) -> UnitPrice:
    """Price per 100 g, per 100 ml, or per piece. Lower is better value."""
    if size.amount <= 0:
        raise ValueError("size must be positive")
    scale = 1 if size.unit == "piece" else 100
    return UnitPrice(value=price / size.amount * scale, unit=size.unit)


# ============================================================ 5. smart pack selection
@dataclass(frozen=True)
class PackOption:
    key: str  # whatever the caller wants back: a product id, URL...
    amount: float  # pack size in the standard unit
    price: float
    label: str = ""  # original size text for display, e.g. "6 x 50ml"


@dataclass(frozen=True)
class PackChoice:
    option: PackOption
    count: int  # how many of this pack to buy
    total_cost: float
    total_amount: float
    leftover: float
    leftover_pct: float  # leftover / total_amount, 0..1

    @property
    def significant_leftover(self) -> bool:
        return self.leftover_pct > LEFTOVER_THRESHOLD


def choose_packs(needed: float, options: list[PackOption], max_packs: int = 20) -> PackChoice | None:
    """Pick the cheapest way to cover `needed` using ONE kind of pack (bought 1 or more times).

    For every option: count = ceil(needed / pack size); cost = count * price. We take the lowest
    total cost, so "2 x 250g" beats "1 x 1kg" when it's cheaper, and a small pack beats a big one
    when it already covers the need. Ties go to the least waste, then the best price per unit.
    Returns None if nothing is usable.
    """
    if needed <= 0:
        return None
    best: PackChoice | None = None
    best_key = None
    for opt in options:
        if opt.amount <= 0 or opt.price < 0:
            continue
        count = max(1, math.ceil(needed / opt.amount - 1e-9))  # epsilon: 500 needs 1 x 500, not 2
        if count > max_packs:
            continue
        total_amount = count * opt.amount
        leftover = total_amount - needed
        choice = PackChoice(opt, count, round(count * opt.price, 2), total_amount,
                            max(0.0, leftover), max(0.0, leftover) / total_amount)
        key = (choice.total_cost, choice.leftover, opt.price / opt.amount)
        if best_key is None or key < best_key:
            best, best_key = choice, key
    return best


# ============================================================ 6. display helpers
def _num(x: float) -> str:
    return f"{x:.1f}".rstrip("0").rstrip(".")


def format_amount(amount: float, unit: StdUnit) -> str:
    """200 g -> "200g", 1500 g -> "1.5kg", 3 piece -> "3 pcs". Amounts of 10+ are rounded to whole numbers."""
    if amount >= 10:
        amount = round(amount)  # "999.7g" reads better as "1kg"
    if unit == "g":
        return f"{_num(amount / 1000)}kg" if amount >= 1000 else f"{_num(amount)}g"
    if unit == "ml":
        return f"{_num(amount / 1000)}L" if amount >= 1000 else f"{_num(amount)}ml"
    n = round(amount)
    return f"{n} pc" if n == 1 else f"{n} pcs"


def describe_need(needed: float, unit: StdUnit, choice: PackChoice) -> str:
    """"Need 200g -> 1 x 500g pack"."""
    pack = choice.option.label or format_amount(choice.option.amount, unit)
    plural = "packs" if choice.count > 1 else "pack"
    return f"Need {format_amount(needed, unit)} → {choice.count} x {pack} {plural}"


# ============================================================ 7. substitutes
# Shown when no store stocks an item. Deliberately short and conservative.
SUBSTITUTES: dict[str, str] = {
    "vanilla extract": "vanilla essence",
    "caster sugar": "granulated sugar (blitz it in a blender for a finer texture)",
    "brown sugar": "caster sugar plus a spoon of honey",
    "icing sugar": "caster sugar blitzed to a fine powder",
    "butter": "margarine",
    "milk": "any plant milk, or water plus a little extra butter",
    "plain flour": "self-raising flour (skip the baking powder)",
    "baking powder": "baking soda plus lemon juice",
    "cocoa powder": "dark chocolate, melted",
    "chocolate chips": "a chopped dark chocolate bar",
    "cream": "milk plus a little butter",
    "cornflour": "plain flour (use twice as much)",
    "honey": "maple syrup",
    "vegetable oil": "any neutral oil, or melted butter",
}


def suggest_substitute(name: str) -> str:
    canon = canonical_name(name) or name.lower().strip()
    return SUBSTITUTES.get(canon, "")
