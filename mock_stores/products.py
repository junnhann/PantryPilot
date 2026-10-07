"""Catalogue for the three mock grocery stores.

~41 everyday items ("keys") are sold by the stores with DIFFERENT brands, pack sizes, prices
and stock. Brands are made up. Sizes are deliberately messy ("500 g", "6 x 50ml", "12's",
"1 litre", "Pack of 6") so the size parser gets a real workout.

Also included:
  * look-alike DECOYS (key=None), e.g. "Cocoa Drink Powder" for "cocoa powder", "Coconut Milk"
    for "milk". They test the product-matching rules.
  * one listing with an unparseable size, one item a store doesn't stock at all, and a few
    out-of-stock listings, to test the "not found / low confidence / substitute" paths.

Nothing here is random, so the demo behaves identically every time.
"""
import re
from dataclasses import dataclass

FM, VG, QB = "freshmart", "valuegrocer", "quickbasket"


@dataclass(frozen=True)
class Store:
    slug: str
    name: str
    tagline: str


STORES: dict[str, Store] = {
    FM: Store(FM, "FreshMart", "Fresh. Local. Delivered."),
    VG: Store(VG, "ValueGrocer", "Big savings, every day."),
    QB: Store(QB, "QuickBasket", "Groceries in 30 minutes."),
}


@dataclass(frozen=True)
class Product:
    id: str
    store: str
    key: str | None  # shared catalogue key ("plain flour"); None for decoys
    category: str
    brand: str
    name: str
    size: str  # raw text exactly as the shop shows it
    price: float  # SGD
    in_stock: bool
    decoy_of: str | None = None  # test-only: which ingredient this looks like (never shown on pages)

    @property
    def description(self) -> str:
        return f"{self.name} by {self.brand}. Pack size: {self.size or 'see label'}."

    @property
    def emoji(self) -> str:
        return CATEGORY_EMOJI.get(self.category, "🛒")


CATEGORY_EMOJI = {
    "flour": "🌾", "sugar": "🍬", "baking": "🧁", "dairy": "🥛", "eggs": "🥚", "chocolate": "🍫",
    "oil": "🫒", "pantry": "🥫", "produce": "🥬", "meat": "🍗", "grains": "🍚", "drinks": "🥤",
    "snacks": "🍪",
}

# ------------------------------------------------------------------ raw listings
# (key, category, store, brand, name, size, price[, in_stock])
_RAW: list[tuple] = [
    # --- flours
    ("plain flour", "flour", FM, "Golden Wheat", "Plain Flour", "1kg", 2.60),
    ("plain flour", "flour", FM, "Golden Wheat", "Plain Flour", "500 g", 1.60),
    ("plain flour", "flour", VG, "ValuePick", "Plain Flour", "1kg", 1.85),
    ("plain flour", "flour", VG, "ValuePick", "Plain Flour", "2 x 1kg", 3.40),
    ("plain flour", "flour", QB, "Daily", "Plain Flour", "500 g", 1.50),
    ("self-raising flour", "flour", FM, "Golden Wheat", "Self-Raising Flour", "1kg", 2.80),
    ("self-raising flour", "flour", VG, "ValuePick", "Self Raising Flour", "1kg", 1.95, False),
    ("bread flour", "flour", FM, "Golden Wheat", "High Protein Bread Flour", "1kg", 3.20),
    ("bread flour", "flour", VG, "ValuePick", "Bread Flour", "1kg", 2.40),
    # --- sugars
    ("caster sugar", "sugar", FM, "Pure Farm", "Caster Sugar", "500g", 2.20),
    ("caster sugar", "sugar", FM, "Pure Farm", "Caster Sugar", "1kg", 3.90),
    ("caster sugar", "sugar", VG, "ValuePick", "Caster Sugar", "1kg", 2.50),
    ("caster sugar", "sugar", VG, "ValuePick", "Caster Sugar", "500 g", 1.40),
    ("caster sugar", "sugar", QB, "Daily", "Caster Sugar", "500g", 1.90),
    ("caster sugar", "sugar", QB, "Daily", "Caster Sugar", "1kg", 3.40, False),
    ("brown sugar", "sugar", FM, "Pure Farm", "Soft Brown Sugar", "500g", 2.60),
    ("brown sugar", "sugar", VG, "ValuePick", "Brown Sugar", "1kg", 2.80),
    ("brown sugar", "sugar", QB, "Daily", "Brown Sugar", "500 g", 2.30),
    ("icing sugar", "sugar", FM, "Pure Farm", "Icing Sugar", "500g", 2.40),
    ("icing sugar", "sugar", VG, "ValuePick", "Icing Sugar", "500g", 1.60),
    ("icing sugar", "sugar", QB, "Daily", "Icing Sugar", "250g", 1.50),
    # --- baking basics
    ("cocoa powder", "baking", FM, "Harvest Gold", "Cocoa Powder", "100g", 3.90),
    ("cocoa powder", "baking", FM, "Harvest Gold", "Cocoa Powder", "250g", 7.80),
    ("cocoa powder", "baking", VG, "ValuePick", "Cocoa Powder", "200g", 3.20),
    ("cocoa powder", "baking", QB, "Quick Choice", "Cocoa Powder", "150g", 3.60),
    ("baking powder", "baking", FM, "Baker's Choice", "Baking Powder", "110g", 2.20),
    ("baking powder", "baking", VG, "ValuePick", "Baking Powder", "Value Tin", 1.20),  # size unparseable on purpose
    ("baking powder", "baking", VG, "ValuePick", "Baking Powder", "100 g", 1.50),
    ("baking powder", "baking", QB, "Daily", "Baking Powder", "50g", 1.60),
    ("baking soda", "baking", FM, "Baker's Choice", "Baking Soda", "200g", 1.90),
    ("baking soda", "baking", VG, "ValuePick", "Bicarbonate of Soda", "250g", 1.30),
    ("salt", "pantry", FM, "Sea Crystal", "Fine Salt", "500g", 1.50),
    ("salt", "pantry", VG, "ValuePick", "Table Salt", "1kg", 0.90),
    ("salt", "pantry", QB, "Daily", "Table Salt", "500g", 1.10),
    ("cornflour", "baking", FM, "Baker's Choice", "Cornflour", "400g", 2.10),
    ("cornflour", "baking", VG, "ValuePick", "Corn Flour", "500g", 1.30),
    ("vanilla extract", "baking", FM, "Baker's Choice", "Pure Vanilla Extract", "50ml", 8.90),
    ("vanilla extract", "baking", VG, "ValuePick", "Vanilla Essence", "28ml", 2.20),  # QuickBasket doesn't stock it
    ("yeast", "baking", FM, "Baker's Choice", "Instant Dry Yeast", "3 x 7g", 2.50),
    ("yeast", "baking", VG, "ValuePick", "Instant Yeast", "5 x 7g", 2.20),
    ("chocolate chips", "chocolate", FM, "Harvest Gold", "Dark Chocolate Chips", "200g", 4.50),
    ("chocolate chips", "chocolate", VG, "ValuePick", "Chocolate Chips", "250g", 3.90),
    ("chocolate chips", "chocolate", QB, "Quick Choice", "Choc Chips", "150g", 3.80),
    ("dark chocolate", "chocolate", FM, "Harvest Gold", "Dark Chocolate Bar", "100g", 3.50),
    ("dark chocolate", "chocolate", VG, "ValuePick", "Dark Chocolate Block", "200g", 3.40),
    ("dark chocolate", "chocolate", QB, "Quick Choice", "Dark Chocolate", "100 g", 3.20),
    # --- dairy & eggs
    ("butter", "dairy", FM, "Misty Valley", "Unsalted Butter", "250g", 4.80),
    ("butter", "dairy", FM, "Misty Valley", "Unsalted Butter", "500g", 8.90, False),
    ("butter", "dairy", VG, "ValuePick", "Salted Butter", "250g", 3.60),
    ("butter", "dairy", VG, "ValuePick", "Salted Butter", "500g", 6.80),
    ("butter", "dairy", QB, "Daily", "Butter", "200g", 3.90),
    ("margarine", "dairy", FM, "Baker's Choice", "Margarine", "500g", 3.20),
    ("margarine", "dairy", VG, "ValuePick", "Margarine", "500g", 2.20),
    ("milk", "dairy", FM, "Moo Fresh", "Full Cream Milk", "1L", 3.20),
    ("milk", "dairy", FM, "Moo Fresh", "Full Cream Milk", "1.5L", 4.60),
    ("milk", "dairy", VG, "ValuePick", "Full Cream Milk", "1 litre", 2.60),
    ("milk", "dairy", VG, "ValuePick", "Full Cream Milk", "2L", 4.90),
    ("milk", "dairy", QB, "Daily", "Fresh Milk", "1L", 3.00),
    ("milk", "dairy", QB, "Daily", "Fresh Milk", "250ml", 1.20),
    ("condensed milk", "dairy", FM, "Moo Fresh", "Sweetened Condensed Milk", "390g", 3.10),
    ("condensed milk", "dairy", VG, "ValuePick", "Sweetened Condensed Milk", "397g", 2.40),
    ("cream", "dairy", FM, "Misty Valley", "Whipping Cream", "250ml", 4.50),
    ("cream", "dairy", VG, "ValuePick", "UHT Cooking Cream", "6 x 50ml", 4.80),
    ("cream", "dairy", QB, "Daily", "Cooking Cream", "250ml", 4.20),
    ("yogurt", "dairy", FM, "Misty Valley", "Plain Yogurt", "500g", 4.20),
    ("yogurt", "dairy", VG, "ValuePick", "Natural Yoghurt", "4 x 125g", 3.20),
    ("yogurt", "dairy", QB, "Daily", "Plain Yogurt", "150g", 1.60),
    ("cheddar cheese", "dairy", FM, "Misty Valley", "Mature Cheddar", "200g", 5.90),
    ("cheddar cheese", "dairy", VG, "ValuePick", "Cheddar Cheese", "250g", 4.50),
    ("cheddar cheese", "dairy", QB, "Daily", "Cheddar Cheese", "170g", 4.20),
    ("egg", "eggs", FM, "Happy Hen", "Fresh Eggs", "10s", 3.90),
    ("egg", "eggs", FM, "Happy Hen", "Fresh Eggs", "Pack of 6", 2.40),
    ("egg", "eggs", VG, "ValuePick", "Eggs", "12's", 3.30),
    ("egg", "eggs", VG, "ValuePick", "Eggs", "Tray of 30", 7.90, False),
    ("egg", "eggs", QB, "Daily", "Fresh Eggs", "6s", 2.30),
    ("egg", "eggs", QB, "Daily", "Fresh Eggs", "10 pcs", 3.70),
    # --- oils, spreads, pantry
    ("vegetable oil", "oil", FM, "Sun Gold", "Vegetable Oil", "1L", 4.90),
    ("vegetable oil", "oil", FM, "Sun Gold", "Vegetable Oil", "2L", 8.90),
    ("vegetable oil", "oil", VG, "ValuePick", "Vegetable Oil", "2L", 6.90),
    ("vegetable oil", "oil", VG, "ValuePick", "Vegetable Oil", "1L", 3.80),
    ("olive oil", "oil", FM, "Olio Verde", "Extra Virgin Olive Oil", "500ml", 11.90),
    ("olive oil", "oil", VG, "ValuePick", "Olive Oil", "500ml", 8.50),
    ("olive oil", "oil", QB, "Quick Choice", "Olive Oil", "250ml", 6.50),
    ("honey", "pantry", FM, "Bluebird", "Pure Honey", "500g", 9.50),
    ("honey", "pantry", VG, "ValuePick", "Honey", "500g", 6.50),
    ("honey", "pantry", QB, "Daily", "Honey", "350g", 6.90),
    ("maple syrup", "pantry", FM, "Maple Ridge", "Pure Maple Syrup", "250ml", 8.90),
    ("maple syrup", "pantry", QB, "Quick Choice", "Maple Flavoured Syrup", "355ml", 4.50),
    ("peanut butter", "pantry", FM, "Bluebird", "Crunchy Peanut Butter", "340g", 4.50),
    ("peanut butter", "pantry", VG, "ValuePick", "Peanut Butter", "500 g", 3.50),
    ("peanut butter", "pantry", QB, "Daily", "Peanut Butter", "340g", 4.20),
    ("rolled oats", "grains", FM, "Sunrise", "Rolled Oats", "800g", 4.20),
    ("rolled oats", "grains", VG, "ValuePick", "Rolled Oats", "1kg", 3.30),
    ("rolled oats", "grains", QB, "Daily", "Oats", "500 g", 2.90),
    ("raisins", "pantry", FM, "Sunrise", "Raisins", "250g", 3.20),
    ("raisins", "pantry", VG, "ValuePick", "Raisins", "500g", 3.80),
    ("raisins", "pantry", QB, "Daily", "Raisins", "200g", 2.80),
    ("ground almonds", "baking", FM, "Sunrise", "Ground Almonds", "200g", 6.90),
    ("ground almonds", "baking", VG, "ValuePick", "Almond Meal", "200g", 5.50),
    ("cinnamon", "pantry", FM, "Spice Route", "Ground Cinnamon", "40g", 3.20),
    ("cinnamon", "pantry", VG, "ValuePick", "Cinnamon Powder", "30g", 1.90),
    ("cinnamon", "pantry", QB, "Daily", "Cinnamon Powder", "25 g", 2.10),
    ("rice", "grains", FM, "Golden Grain", "Jasmine Rice", "2kg", 7.90),
    ("rice", "grains", VG, "ValuePick", "Jasmine Rice", "5kg", 12.90),
    ("rice", "grains", QB, "Daily", "Jasmine Rice", "1kg", 3.80),
    ("pasta", "grains", FM, "Pasta Bella", "Spaghetti", "500g", 2.60),
    ("pasta", "grains", VG, "ValuePick", "Spaghetti", "500 g", 1.40),
    ("pasta", "grains", QB, "Daily", "Spaghetti", "400g", 1.90),
    ("tomato paste", "pantry", FM, "Casa Tomate", "Tomato Paste", "140g", 1.80),
    ("tomato paste", "pantry", VG, "ValuePick", "Tomato Paste", "2 x 70g", 1.60),
    ("tomato paste", "pantry", QB, "Daily", "Tomato Paste", "140 g", 1.90),
    # --- fresh produce & meat
    ("lemon", "produce", FM, "Fresh Farm", "Lemons", "4s", 3.20),
    ("lemon", "produce", VG, "ValuePick", "Lemons", "6 pcs", 3.50),
    ("lemon", "produce", QB, "Daily", "Lemon", "2s", 1.80),
    ("banana", "produce", FM, "Fresh Farm", "Cavendish Bananas", "1kg", 2.20),
    ("banana", "produce", VG, "ValuePick", "Bananas", "1kg", 1.80),
    ("banana", "produce", QB, "Daily", "Bananas", "4s", 1.60),
    ("onion", "produce", FM, "Fresh Farm", "Brown Onions", "1kg", 2.50),
    ("onion", "produce", VG, "ValuePick", "Onions", "1kg", 1.90),
    ("onion", "produce", QB, "Daily", "Onions", "500g", 1.40),
    ("garlic", "produce", FM, "Fresh Farm", "Garlic", "200g", 2.20),
    ("garlic", "produce", VG, "ValuePick", "Garlic", "250g", 2.30),
    ("garlic", "produce", QB, "Daily", "Garlic", "100g", 1.60),
    ("potato", "produce", FM, "Fresh Farm", "Potatoes", "1kg", 3.20),
    ("potato", "produce", VG, "ValuePick", "Potatoes", "2kg", 4.20),
    ("potato", "produce", QB, "Daily", "Potatoes", "1 kg", 3.50),
    ("chicken breast", "meat", FM, "Farm Fresh", "Chicken Breast", "500g", 7.50),
    ("chicken breast", "meat", VG, "ValuePick", "Chicken Breast", "600g", 7.20),
    ("chicken breast", "meat", QB, "Daily", "Chicken Breast", "400g", 6.20),
]

# ------------------------------------------------------------------ look-alike decoys
# (decoy_of, category, store, brand, name, size, price)
_DECOYS: list[tuple] = [
    # QuickBasket's decoy is listed BEFORE its real cocoa powder and contains the exact phrase
    # "cocoa powder", so a naive "take the first search result" agent picks the wrong product.
    ("cocoa powder", "drinks", QB, "Quick Choice", "Cocoa Powder Drink Mix", "400g", 4.90),
    ("cocoa powder", "drinks", FM, "Maltie", "Cocoa Drink Powder", "1kg", 8.90),
    ("cocoa powder", "drinks", VG, "ValuePick", "Hot Chocolate Cocoa Drink Powder", "500g", 3.60),
    ("milk", "drinks", FM, "Moo Fresh", "Chocolate Milk Drink", "1L", 3.80),
    ("milk", "dairy", VG, "ValuePick", "Coconut Milk", "400ml", 1.90),
    ("milk", "dairy", QB, "Daily", "Coconut Milk", "400ml", 2.40),
    ("butter", "snacks", FM, "Misty Valley", "Butter Cookies", "454g", 6.50),
    ("butter", "snacks", VG, "ValuePick", "Butter Cookies", "200g", 2.50),
    ("butter", "snacks", QB, "Daily", "Butter Popcorn", "100g", 1.90),
    ("egg", "grains", FM, "Happy Noodle", "Egg Noodles", "400g", 2.80),
    ("egg", "grains", VG, "ValuePick", "Egg Noodles", "500g", 2.10),
    ("egg", "snacks", QB, "Daily", "Egg Roll Snack", "100g", 2.20),
    ("vanilla extract", "dairy", VG, "ValuePick", "Vanilla Ice Cream", "1L", 5.50),
    ("vanilla extract", "snacks", QB, "Daily", "Vanilla Wafer Biscuits", "150g", 2.00),
    ("plain flour", "flour", VG, "ValuePick", "Plain Flour Tortilla Wraps", "8s", 2.80),
    ("caster sugar", "sugar", QB, "Daily", "Sugar-Free Sweetener Sachets", "50s", 3.50),
    ("brown sugar", "drinks", QB, "Daily", "Brown Sugar Boba Syrup", "500ml", 4.80),
    ("maple syrup", "pantry", VG, "ValuePick", "Pancake Syrup", "500ml", 3.20),
    ("chocolate chips", "snacks", FM, "Harvest Gold", "Chocolate Chip Cookies", "180g", 3.40),
]


def _slug(*parts: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", " ".join(parts).lower()).strip("-")


def _build() -> list[Product]:
    products: list[Product] = []
    for row in _RAW:
        key, cat, store, brand, name, size, price, *rest = row
        products.append(Product(_slug(store[:2], brand, name, size), store, key, cat, brand, name, size,
                                price, rest[0] if rest else True))
    for decoy_of, cat, store, brand, name, size, price in _DECOYS:
        products.append(Product(_slug(store[:2], brand, name, size), store, None, cat, brand, name, size,
                                price, True, decoy_of=decoy_of))
    # Keep a store's decoys that should sort first at the front of the list (insertion order is
    # the tie-breaker in search). Only QuickBasket's cocoa decoy needs this.
    products.sort(key=lambda p: not (p.store == QB and p.decoy_of == "cocoa powder"))
    return products


PRODUCTS: list[Product] = _build()
BY_ID: dict[str, Product] = {p.id: p for p in PRODUCTS}


def catalogue_keys() -> set[str]:
    return {p.key for p in PRODUCTS if p.key}


# ------------------------------------------------------------------ search
def _stem(word: str) -> str:
    """Very rough singularisation so "eggs" finds "egg" and "potatoes" finds "potato"."""
    if word.endswith("oes") and len(word) > 4:
        return word[:-2]
    if word.endswith("s") and not word.endswith("ss") and len(word) > 3:
        return word[:-1]
    return word


def _tokens(text: str) -> list[str]:
    return [_stem(t) for t in re.findall(r"[a-z0-9]+", text.lower())]


def search(store: str, query: str) -> list[Product]:
    """Plain keyword search like a simple shop: every query word must appear in the product name
    or brand. Ranking: exact phrase in the name first, then more matching words; ties keep list order.
    """
    q = _tokens(query)
    if not q:
        return []
    phrase = " ".join(q)
    hits = []
    for idx, p in enumerate(p for p in PRODUCTS if p.store == store):
        name_tokens = _tokens(p.name)
        if not all(t in name_tokens or t in _tokens(p.brand) for t in q):
            continue
        score = (2 if phrase in " ".join(name_tokens) else 0) + sum(t in name_tokens for t in q)
        hits.append((-score, idx, p))
    return [p for _, _, p in sorted(hits, key=lambda h: h[:2])]


def featured(store: str, n: int = 8) -> list[Product]:
    """Items shown on a store's home page: the first in-stock real products."""
    return [p for p in PRODUCTS if p.store == store and p.key and p.in_stock][:n]
