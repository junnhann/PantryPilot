"""Demo-mode AI tests: no network, no API key needed."""
import pytest

from app import ai, config
from app.models import IngredientList


@pytest.fixture(autouse=True)
def demo(monkeypatch):
    monkeypatch.setattr(config, "DEMO_MODE", True)


async def test_recipe_options():
    r = await ai.suggest_recipes("bake a cake", 6)
    assert 1 <= len(r.options) <= 3


async def test_ingredients_scale_with_servings():
    base = await ai.generate_ingredients("cake", "Classic Chocolate Cake", 6)
    double = await ai.generate_ingredients("cake", "Classic Chocolate Cake", 12)
    flour = lambda l: next(i for i in l.ingredients if i.name == "plain flour").quantity
    assert flour(double) == pytest.approx(2 * flour(base), rel=0.05)
    assert isinstance(base, IngredientList)


async def test_eggs_are_whole_pieces():
    r = await ai.generate_ingredients("cake", "Classic Chocolate Cake", 5)
    eggs = next(i for i in r.ingredients if i.name == "egg")
    assert eggs.unit == "piece" and eggs.quantity == int(eggs.quantity)


async def test_missing_key_gives_friendly_error(monkeypatch):
    monkeypatch.setattr(config, "DEMO_MODE", False)
    monkeypatch.setattr(config, "GEMINI_API_KEY", "")
    with pytest.raises(ai.AIError):
        await ai.suggest_recipes("cake", 4)


def test_ai_schemas_avoid_keywords_gemini_sdk_rejects():
    """Field(gt=..)/Field(lt=..) emit 'exclusiveMinimum/Maximum', which the Gemini SDK refuses.
    Use ge/le instead. This catches the mistake offline."""
    from app.models import FridgeScan, IngredientList, LeftoverIdeas, RecipeOptions, ReviewResult
    for schema in (RecipeOptions, IngredientList, FridgeScan, ReviewResult, LeftoverIdeas):
        text = str(schema.model_json_schema())
        assert "exclusiveMinimum" not in text and "exclusiveMaximum" not in text, schema.__name__
