"""Report building, AI-review merging, leftovers, substitutes (no browser)."""
import pytest
from fastapi.testclient import TestClient

from app import ai, config
from app.main import app
from app.matching import Selector
from app.models import (Ingredient, LeftoverItem, ReviewVerdict, SearchHit, TaskResult)
from app.report import apply_review, build_report, leftovers_of
from app.units import Quantity, suggest_substitute, to_standard

STORES = {"a": "Alpha", "b": "Beta"}
ITEMS = [Ingredient(name="plain flour", quantity=225, unit="g"), Ingredient(name="vanilla extract", quantity=1, unit="tsp")]


def hit(store, name, size, price, pid=None, in_stock=True):
    return SearchHit(store=store, product_id=pid or f"{store}-{name}-{size}", name=name, size=size, price=price,
                     in_stock=in_stock, url=f"http://x/{store}/{name}")


def result(sel, store, ingredient, hits):
    h = sel.choose(ingredient, hits) if hits else None
    r = TaskResult(store=store, ingredient=ingredient, status="found" if h else "not_found",
                   message="" if h else f"{store} has no results")
    sel.enrich(r)
    return r


@pytest.fixture
def report():
    sel = Selector({i.name: to_standard(i.name, i.quantity, i.unit) for i in ITEMS})
    results = [
        result(sel, "a", "plain flour", [hit("a", "Alpha Plain Flour", "1kg", 2.6), hit("a", "Alpha Plain Flour", "500 g", 1.6)]),
        result(sel, "b", "plain flour", [hit("b", "Beta Plain Flour", "1kg", 1.85)]),
        result(sel, "a", "vanilla extract", []),
        result(sel, "b", "vanilla extract", []),
    ]
    return build_report(ITEMS, results, STORES)


def test_options_ranked_across_stores_cheapest_cover_first(report):
    flour = report.items[0]
    assert [o.total_cost for o in flour.options] == [1.6, 1.85, 2.6]   # 500g @1.6 covers 225g cheapest
    assert flour.options[0].store == "a" and flour.options[0].need_text == "Need 225g → 1 x 500 g pack"
    assert len(flour.options) >= 3  # pick + alternatives


def test_nothing_found_gives_message_and_substitute(report):
    v = report.items[1]
    assert v.options == [] and "None of the 2 stores" in v.message and v.substitute == "vanilla essence"


def test_store_totals_and_missing(report):
    tot = {t.store: t for t in report.store_totals}
    assert tot["a"].total == 1.6 and tot["a"].found == 1 and tot["a"].missing == ["vanilla extract"]
    assert tot["b"].total == 1.85
    assert report.best_mix_total == 1.6


def test_report_serialises_to_json(report):
    assert report.model_dump_json()


# ---------------------------------------------------------------- AI review can only lower confidence
def test_review_lowers_confidence_and_may_change_the_pick(report):
    flour = report.items[0]
    first = flour.options[0].product_id
    apply_review(report, [ReviewVerdict(index=0, same_product=False, confidence="high", reason="looks like a mix")])
    assert flour.options[0].product_id != first          # the doubted pick dropped below the others
    doubted = next(o for o in flour.options if o.product_id == first)
    assert doubted.confidence == "low" and any("AI check" in r for r in doubted.reasons)


def test_review_never_raises_confidence():
    sel = Selector({"plain flour": Quantity(100, "g")})
    r = result(sel, "a", "plain flour", [hit("a", "Alpha Self Raising Flour", "1kg", 2.0)])     # rules: low
    rep = build_report([ITEMS[0]], [r], {"a": "Alpha"})
    assert rep.items[0].options[0].confidence == "low"
    apply_review(rep, [ReviewVerdict(index=0, same_product=True, confidence="high")])
    assert rep.items[0].options[0].confidence == "low"


def test_review_ignores_bad_indexes(report):
    apply_review(report, [ReviewVerdict(index=99, same_product=False, confidence="low"),
                          ReviewVerdict(index=-1, same_product=False, confidence="low")])


async def test_review_skipped_in_demo_mode(monkeypatch):
    monkeypatch.setattr(config, "DEMO_MODE", True)
    assert await ai.review_matches([("flour", "Flour")]) == []


async def test_review_calls_model_in_real_mode(monkeypatch):
    monkeypatch.setattr(config, "DEMO_MODE", False)
    seen = {}

    async def fake(prompt, schema, image=None):
        seen["prompt"] = prompt
        return schema(verdicts=[ReviewVerdict(index=0, same_product=False, confidence="low", reason="drink")])

    monkeypatch.setattr(ai, "call_json", fake)
    v = await ai.review_matches([("cocoa powder", "Cocoa Drink Mix")])
    assert v[0].same_product is False and "cocoa powder" in seen["prompt"]


# ---------------------------------------------------------------- leftovers
def test_leftovers_only_significant_and_sorted():
    sel = Selector({"milk": Quantity(150, "ml"), "plain flour": Quantity(225, "g"), "butter": Quantity(240, "g")})
    cs = [
        ("milk", sel.choose("milk", [hit("a", "Full Cream Milk", "1L", 3)]) and sel._ranked[("a", "milk")][0]),
        ("plain flour", (sel.choose("plain flour", [hit("a", "Plain Flour", "500 g", 1.5)]), sel._ranked[("a", "plain flour")][0])[1]),
        ("butter", (sel.choose("butter", [hit("a", "Butter", "250g", 4)]), sel._ranked[("a", "butter")][0])[1]),
    ]
    out = leftovers_of(cs)
    assert [o["name"] for o in out] == ["milk", "plain flour"]      # butter: 10 of 250 left = 4%, not significant
    assert out[0]["amount"] == 850 and out[0]["unit"] == "ml"


async def test_demo_leftover_ideas_use_the_leftovers(monkeypatch):
    monkeypatch.setattr(config, "DEMO_MODE", True)
    ideas = await ai.suggest_leftover_ideas(
        [LeftoverItem(name="milk", amount=850, unit="ml"), LeftoverItem(name="plain flour", amount=275, unit="g")], 4)
    titles = [i.title for i in ideas.ideas]
    assert 1 <= len(titles) <= 3 and "Fluffy Pancakes" in titles
    assert all(i.uses for i in ideas.ideas)
    # every demo idea can be turned into an ingredient list
    for t in titles:
        assert (await ai.generate_ingredients("x", t, 4)).ingredients


def test_leftover_endpoint_and_owned_flag(monkeypatch):
    monkeypatch.setattr(config, "DEMO_MODE", True)
    c = TestClient(app)
    r = c.post("/api/leftover-ideas", json={"leftovers": [{"name": "milk", "amount": 850, "unit": "ml"}], "servings": 4})
    assert r.status_code == 200 and r.json()["ideas"]
    r = c.post("/api/ingredients", json={"goal": "pancakes", "recipe_title": "Fluffy Pancakes", "servings": 4,
                                         "owned": ["milk", "white sugar"]})
    assert r.status_code == 200
    assert set(r.json()["owned"]) == {"milk", "caster sugar"}      # "white sugar" counted as caster sugar
    assert c.post("/api/leftover-ideas", json={"leftovers": [], "servings": 4}).status_code == 422


def test_substitutes():
    assert suggest_substitute("Vanilla Extract") == "vanilla essence"
    assert suggest_substitute("dragon fruit") == ""


async def test_leftover_ideas_never_repeat_the_recipe_just_bought(monkeypatch):
    left = [LeftoverItem(name="plain flour", amount=275, unit="g"), LeftoverItem(name="caster sugar", amount=300, unit="g"),
            LeftoverItem(name="milk", amount=850, unit="ml")]
    monkeypatch.setattr(config, "DEMO_MODE", True)
    ideas = await ai.suggest_leftover_ideas(left, 4, exclude=["fluffy pancakes"])
    assert "Fluffy Pancakes" not in [i.title for i in ideas.ideas]
    # real mode: the model ignores the instruction -> we still drop it, and tell the model up front
    monkeypatch.setattr(config, "DEMO_MODE", False)
    seen = {}

    async def fake(prompt, schema, image=None):
        seen["prompt"] = prompt
        from app.models import LeftoverIdea
        return schema(ideas=[LeftoverIdea(title="Classic Chocolate Cake", description="d", uses=["plain flour"]),
                             LeftoverIdea(title="Shortbread", description="d", uses=["plain flour"])])

    monkeypatch.setattr(ai, "call_json", fake)
    ideas = await ai.suggest_leftover_ideas(left, 4, exclude=["Classic Chocolate Cake"])
    assert [i.title for i in ideas.ideas] == ["Shortbread"] and "Classic Chocolate Cake" in seen["prompt"]
    # if filtering would leave nothing, keep what the model gave rather than showing an empty panel
    async def only_dupe(prompt, schema, image=None):
        from app.models import LeftoverIdea
        return schema(ideas=[LeftoverIdea(title="Classic Chocolate Cake", description="d", uses=["milk"])])
    monkeypatch.setattr(ai, "call_json", only_dupe)
    assert len((await ai.suggest_leftover_ideas(left, 4, exclude=["Classic Chocolate Cake"])).ideas) == 1
