"""Unit tests for app/units.py: pack-size parsing, conversions, price per unit, pack choice."""
import pytest

from app.units import (PackOption, Quantity, canonical_name, choose_packs, describe_need,
                       format_amount, known_names, parse_size, price_per_unit, tidy_quantity,
                       to_standard)


# ---------------------------------------------------------------- parse_size
@pytest.mark.parametrize("text, amount, unit", [
    ("1kg", 1000, "g"),
    ("500 g", 500, "g"),
    ("500G", 500, "g"),
    ("500gm", 500, "g"),
    ("0.5 kg", 500, "g"),
    ("1,000g", 1000, "g"),
    ("1.5L", 1500, "ml"),
    ("1 litre", 1000, "ml"),
    ("250ml", 250, "ml"),
    ("33cl", 330, "ml"),
    ("6 x 50ml", 300, "ml"),
    ("6x50ml", 300, "ml"),
    ("6 × 50 ml", 300, "ml"),
    ("50ml x 6", 300, "ml"),
    ("2 x 1kg", 2000, "g"),
    ("12s", 12, "piece"),
    ("12's", 12, "piece"),
    ("12 pcs", 12, "piece"),
    ("10 pieces", 10, "piece"),
    ("Pack of 6", 6, "piece"),
    ("tray of 30", 30, "piece"),
    ("1 dozen", 12, "piece"),
    ("dozen", 12, "piece"),
    ("Anchor Butter 227g", 227, "g"),         # size embedded in a product name
    ("Fresh Eggs 10s", 10, "piece"),
    ("1 pack 500g", 500, "g"),                # prefer weight over a count
    ("8 oz", pytest.approx(226.796), "g"),
    ("1 lb", pytest.approx(453.592), "g"),
])
def test_parse_size_ok(text, amount, unit):
    q = parse_size(text)
    assert q is not None, text
    assert q.unit == unit and q.amount == pytest.approx(amount)


@pytest.mark.parametrize("text", ["", "family pack", "large", "per kg", "0g", "assorted", "2% fat"])
def test_parse_size_unparseable_returns_none(text):
    assert parse_size(text) is None


# ---------------------------------------------------------------- to_standard
def test_cup_of_flour_is_120g():
    assert to_standard("plain flour", 1, "cup") == Quantity(pytest.approx(120), "g")


def test_tbsp_butter_about_14g():
    q = to_standard("butter", 1, "tbsp")
    assert q.unit == "g" and q.amount == pytest.approx(14, abs=0.5)


def test_cup_of_milk_is_240ml_and_tsp_is_5ml():
    assert to_standard("milk", 1, "cup") == Quantity(pytest.approx(240), "ml")
    assert to_standard("vanilla extract", 1, "tsp") == Quantity(pytest.approx(5), "ml")


def test_egg_is_one_piece():
    assert to_standard("egg", 1, "piece") == Quantity(1, "piece")


def test_synonym_gets_same_density():
    assert to_standard("white sugar", 1, "cup").amount == to_standard("caster sugar", 1, "cup").amount


def test_kg_and_litres():
    assert to_standard("plain flour", 1.5, "kg") == Quantity(1500, "g")
    assert to_standard("milk", 2, "l") == Quantity(2000, "ml")


def test_grams_of_egg_become_pieces():
    assert to_standard("egg", 100, "g") == Quantity(pytest.approx(2), "piece")


def test_unknown_ingredient_spoons_fall_back_to_ml():
    assert to_standard("mystery sauce", 2, "tbsp") == Quantity(30, "ml")


def test_pinch_is_tiny_grams():
    q = to_standard("salt", 1, "pinch")
    assert q.unit == "g" and 0 < q.amount < 1


def test_canonical_and_known_names():
    assert canonical_name("Eggs") == "egg"
    assert canonical_name("all-purpose flour") == "plain flour"
    assert canonical_name("  Cocoa  ") == "cocoa powder"
    assert canonical_name("dragon fruit") is None
    assert "cocoa" in known_names("cocoa powder")
    assert known_names("dragon fruit") == {"dragon fruit"}


@pytest.mark.parametrize("qty, unit, expected", [
    (0.88, "cup", 1.0), (0.38, "cup", 0.5), (0.3, "cup", 0.25), (0.75, "tsp", 0.75),
    (2.2, "piece", 3.0), (2.0, "piece", 2.0), (0.2, "piece", 1.0),
    (223, "g", 225.0), (1, "g", 5.0), (1, "pinch", 1.0),
])
def test_tidy_quantity(qty, unit, expected):
    assert tidy_quantity(qty, unit) == expected


# ---------------------------------------------------------------- price per unit
def test_price_per_100g():
    up = price_per_unit(3.00, Quantity(500, "g"))
    assert up.value == pytest.approx(0.60) and up.unit == "g"
    assert up.label == "S$0.60 / 100g"


def test_price_per_100ml_multipack():
    up = price_per_unit(3.00, parse_size("6 x 50ml"))  # 300 ml
    assert up.value == pytest.approx(1.00) and up.label == "S$1.00 / 100ml"


def test_price_per_piece():
    up = price_per_unit(3.60, parse_size("12s"))
    assert up.value == pytest.approx(0.30) and up.label == "S$0.30 / piece"


def test_ranking_by_unit_price_not_total_price():
    small = price_per_unit(1.50, parse_size("250g"))  # cheaper total, worse value
    big = price_per_unit(2.40, parse_size("1kg"))
    assert big.value < small.value


def test_price_per_unit_rejects_zero_size():
    with pytest.raises(ValueError):
        price_per_unit(1.0, Quantity(0, "g"))


# ---------------------------------------------------------------- choose_packs
def opts(*pairs):
    return [PackOption(key=f"p{i}", amount=a, price=p) for i, (a, p) in enumerate(pairs)]


def test_smallest_pack_that_covers():
    c = choose_packs(200, opts((500, 2.00), (1000, 3.00), (100, 1.00)))
    # 1 x 500g (2.00) vs 2 x 100g (2.00): tie on cost -> 100g needs 2 packs = 200 exactly, less waste
    assert c.total_cost == 2.00 and c.leftover == 0


def test_multiple_small_packs_beat_one_big():
    c = choose_packs(600, opts((250, 1.00), (1000, 3.50)))
    assert c.option.amount == 250 and c.count == 3 and c.total_cost == 3.00


def test_one_big_pack_beats_multiple_small():
    c = choose_packs(600, opts((250, 1.50), (1000, 2.50)))
    assert c.option.amount == 1000 and c.count == 1


def test_exact_fit_is_one_pack_not_two():
    c = choose_packs(500, opts((500, 2.0)))
    assert c.count == 1 and c.leftover == 0 and not c.significant_leftover


def test_float_noise_does_not_add_a_pack():
    c = choose_packs(0.1 + 0.2, opts((0.3, 1.0)))
    assert c.count == 1


def test_leftover_flag_over_30_percent():
    c = choose_packs(200, opts((500, 2.0)))
    assert c.leftover == 300 and c.leftover_pct == pytest.approx(0.6) and c.significant_leftover
    c2 = choose_packs(400, opts((500, 2.0)))
    assert c2.leftover_pct == pytest.approx(0.2) and not c2.significant_leftover


def test_exactly_30_percent_is_not_significant():
    c = choose_packs(700, opts((1000, 2.0)))
    assert c.leftover_pct == pytest.approx(0.3) and not c.significant_leftover


def test_no_options_or_bad_input():
    assert choose_packs(100, []) is None
    assert choose_packs(0, opts((500, 1.0))) is None
    assert choose_packs(100, opts((0, 1.0))) is None


def test_absurd_pack_count_skipped():
    assert choose_packs(10000, opts((5, 1.0))) is None  # would need 2000 packs


def test_describe_need_text():
    c = choose_packs(200, [PackOption("a", 500, 2.0)])
    assert describe_need(200, "g", c) == "Need 200g → 1 x 500g pack"
    c2 = choose_packs(600, [PackOption("a", 250, 1.0, label="250 g")])
    assert describe_need(600, "g", c2) == "Need 600g → 3 x 250 g packs"


def test_format_amount():
    assert format_amount(200, "g") == "200g"
    assert format_amount(1500, "g") == "1.5kg"
    assert format_amount(1000, "ml") == "1L"
    assert format_amount(999.7, "g") == "1kg" and format_amount(0.3, "g") == "0.3g" and format_amount(23.4, "ml") == "23ml"
    assert format_amount(1, "piece") == "1 pc" and format_amount(3, "piece") == "3 pcs"
