"""Product matching/selection: rule-based confidence flags, pack choice, ranking."""
import pytest

from app import matching
from app.matching import Selector, evaluate
from app.models import SearchHit
from app.units import Quantity, to_standard
from mock_stores import products as db


def hit(name, size, price, store="s", pid=None, in_stock=True):
    return SearchHit(store=store, product_id=pid or name.lower().replace(" ", "-") + size, name=name, size=size,
                     price=price, in_stock=in_stock, url="http://x/" + name)


G = lambda n: Quantity(n, "g")


# ---------------------------------------------------------------- confidence rules
def test_clean_match_is_high():
    c = evaluate("plain flour", G(225), hit("Golden Wheat Plain Flour", "1kg", 2.6))
    assert c.confidence == "high" and c.reasons == []


@pytest.mark.parametrize("ingredient, product", [
    ("cocoa powder", "Maltie Cocoa Drink Powder"),
    ("cocoa powder", "Quick Choice Cocoa Powder Drink Mix"),
    ("milk", "Daily Coconut Milk"),
    ("milk", "Moo Fresh Chocolate Milk Drink"),
    ("butter", "Misty Valley Butter Cookies"),
    ("butter", "Daily Butter Popcorn"),
    ("egg", "Happy Noodle Egg Noodles"),
    ("vanilla extract", "Daily Vanilla Wafer Biscuits"),
    ("vanilla extract", "ValuePick Vanilla Ice Cream"),
    ("plain flour", "ValuePick Plain Flour Tortilla Wraps"),
    ("plain flour", "Golden Wheat Self-Raising Flour"),
    ("plain flour", "Golden Wheat High Protein Bread Flour"),
    ("caster sugar", "Pure Farm Soft Brown Sugar"),
    ("caster sugar", "Pure Farm Icing Sugar"),
    ("caster sugar", "Daily Sugar-Free Sweetener Sachets"),
    ("brown sugar", "Daily Brown Sugar Boba Syrup"),
    ("maple syrup", "Daily Maple Flavoured Syrup"),
    ("chocolate chips", "Harvest Gold Chocolate Chip Cookies"),
])
def test_lookalikes_are_low(ingredient, product):
    c = evaluate(ingredient, G(100), hit(product, "400g", 3))
    assert c.confidence == "low", (product, c.reasons)
    assert c.reasons


@pytest.mark.parametrize("ingredient, product", [
    ("cocoa powder", "Harvest Gold Cocoa Powder"),
    ("butter", "Misty Valley Unsalted Butter"),
    ("butter", "ValuePick Salted Butter"),
    ("milk", "Moo Fresh Full Cream Milk"),
    ("egg", "Happy Hen Fresh Eggs"),
    ("white sugar", "Pure Farm Caster Sugar"),              # synonym of the ingredient name
    ("baking soda", "ValuePick Bicarbonate of Soda"),       # multi-word synonym
    ("vanilla extract", "ValuePick Vanilla Essence"),
    ("chocolate chips", "Harvest Gold Dark Chocolate Chips"),
    ("onion", "Fresh Farm Brown Onions"),                   # "brown" must not trip anything
    ("brown sugar", "Pure Farm Soft Brown Sugar"),
])
def test_real_products_are_high(ingredient, product):
    c = evaluate(ingredient, G(100), hit(product, "500g", 3))
    assert c.confidence == "high", (product, c.reasons)


def test_name_without_ingredient_is_low():
    c = evaluate("cocoa powder", G(40), hit("Golden Wheat Plain Flour", "1kg", 2.6))
    assert c.confidence == "low" and "doesn't mention" in c.reasons[0]


def test_generic_synonym_only_is_medium():
    c = evaluate("caster sugar", G(200), hit("Daily Sugar", "500g", 2))
    assert c.confidence == "medium" and "loosely" in c.reasons[0]


def test_generic_oats_for_rolled_oats_is_medium():
    assert evaluate("rolled oats", G(100), hit("Daily Oats", "500 g", 2.9)).confidence == "medium"


@pytest.mark.parametrize("ingredient, product", [
    ("cream", "Moo Fresh Full Cream Milk"),                # "cream" only appears inside another ingredient's name
    ("dark chocolate", "Harvest Gold Dark Chocolate Chips"),
])
def test_name_inside_a_longer_different_product_is_low(ingredient, product):
    assert evaluate(ingredient, G(100), hit(product, "400g", 3)).confidence == "low"


def test_unparseable_size_is_low():
    c = evaluate("baking powder", G(8), hit("ValuePick Baking Powder", "Value Tin", 1.2))
    assert c.confidence == "low" and "Size unclear" in c.reasons
    assert c.unit_price is None and c.pack_count == 1


def test_unit_mismatch_is_low_but_g_vs_ml_is_an_estimate():
    c = evaluate("egg", Quantity(3, "piece"), hit("Fresh Eggs", "500g", 4))      # 150g of egg = 3 pcs ok via weight
    assert c.confidence == "high"
    c = evaluate("honey", Quantity(3, "piece"), hit("Pure Honey", "500g", 9))    # pieces of honey: nonsense
    assert c.confidence == "low" and "Sold by g" in c.reasons[0]
    c = evaluate("olive oil", G(100), hit("Olive Oil", "500ml", 8))
    assert c.confidence == "medium" and "Estimated" in c.reasons[0]


def test_piece_need_converts_to_weight_product():
    c = evaluate("onion", Quantity(2, "piece"), hit("Brown Onions", "1kg", 2.5))  # 2 x 150g = 300g
    assert c.confidence == "high" and c.pack_count == 1 and "300g" in c.need_text


# ---------------------------------------------------------------- pack maths + price per unit
def test_pack_count_cost_and_leftover():
    c = evaluate("plain flour", G(600), hit("Plain Flour", "250g", 1.0))
    assert c.pack_count == 3 and c.total_cost == 3.0 and c.leftover_amount == 150
    assert c.need_text == "Need 600g → 3 x 250g packs"
    c = evaluate("plain flour", G(200), hit("Plain Flour", "500 g", 1.5))
    assert c.significant_leftover and c.leftover_pct == pytest.approx(0.6)
    assert c.unit_price == pytest.approx(0.3) and c.unit_price_label == "S$0.30 / 100g"
    assert c.leftover_text == "300g left over"


# ---------------------------------------------------------------- ranking
def test_confidence_outranks_price():
    hits = [hit("Cheap Cocoa Drink Powder", "1kg", 1.0, pid="decoy"), hit("Real Cocoa Powder", "200g", 3.2, pid="real")]
    sel = Selector({"cocoa powder": G(40)})
    assert sel.choose("cocoa powder", hits).product_id == "real"


def test_cheapest_total_wins_among_equals():
    hits = [hit("Plain Flour", "1kg", 2.6, pid="a"), hit("Plain Flour", "500 g", 1.6, pid="b"),
            hit("Plain Flour", "2 x 1kg", 3.4, pid="c")]
    sel = Selector({"plain flour": G(225)})
    assert sel.choose("plain flour", hits).product_id == "b"


def test_out_of_stock_never_chosen():
    hits = [hit("Plain Flour", "1kg", 1.0, pid="oos", in_stock=False), hit("Plain Flour", "1kg", 2.0, pid="ok")]
    assert Selector({"plain flour": G(100)}).choose("plain flour", hits).product_id == "ok"
    assert Selector({"plain flour": G(100)}).choose("plain flour", [hits[0]]) is None


def test_only_lookalike_available_is_chosen_but_flagged_low():
    sel = Selector({"vanilla extract": Quantity(5, "ml")})
    h = sel.choose("vanilla extract", [hit("Vanilla Wafer Biscuits", "150g", 2.0, store="qb", pid="w")])
    assert h.product_id == "w"
    assert sel._ranked[("qb", "vanilla extract")][0].confidence == "low"


def test_enrich_flags_price_mismatch_on_product_page():
    from app.models import ProductDetails, TaskResult
    sel = Selector({"plain flour": G(100)})
    h = sel.choose("plain flour", [hit("Plain Flour", "1kg", 2.0, store="s", pid="p")])
    r = TaskResult(store="s", ingredient="plain flour", status="found", chosen=ProductDetails(
        store="s", product_id=h.product_id, name="Plain Flour", size="1kg", price=2.5, in_stock=True, url="u"))
    sel.enrich(r)
    assert r.candidates[0].confidence == "low" and "differs" in r.candidates[0].reasons[-1]


# ---------------------------------------------------------------- the whole mock catalogue
def _hits(store, key):
    return [SearchHit(store=store, product_id=p.id, name=f"{p.brand} {p.name}", size=p.size, price=p.price,
                      in_stock=p.in_stock, url="http://x/" + p.id) for p in db.search(store, key)]


@pytest.mark.parametrize("store", list(db.STORES))
@pytest.mark.parametrize("key", sorted(db.catalogue_keys()))
def test_best_pick_is_a_real_product_for_every_catalogue_item(store, key):
    """For every ingredient in every store, the pick is never a look-alike decoy."""
    hits = _hits(store, key)
    if not hits:
        pytest.skip("store doesn't sell it")
    need = (to_standard(key, 1, "piece") if key in ("egg", "lemon", "banana", "onion", "potato")
            else to_standard(key, 200, "ml" if key in ("milk", "cream", "vegetable oil", "olive oil",
                                                       "vanilla extract", "maple syrup") else "g"))
    sel = Selector({key: need})
    chosen = sel.choose(key, hits)
    if chosen is None:
        return  # everything out of stock: fine
    p = db.BY_ID[chosen.product_id]
    top = sel._ranked[(store, key)][0]
    assert p.key == key or top.confidence == "low", f"{store}/{key} picked decoy {p.name} as {top.confidence}"
    if p.key == key and key != "maple syrup":
        assert top.confidence in ("high", "medium")
