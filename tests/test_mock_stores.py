"""Mock-store tests: data sanity, search behaviour, and the HTML 'contract' the agent relies on."""
import re

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.units import parse_size
from mock_stores import products as db

client = TestClient(app)
STORES = list(db.STORES)

# Listings whose size text we intentionally can't parse (to test the "size unclear" flag).
EXPECTED_UNPARSEABLE = {"Value Tin"}


# ---------------------------------------------------------------- data
def test_catalogue_size():
    assert len(db.catalogue_keys()) >= 40


def test_ids_unique_and_prices_positive():
    assert len(db.BY_ID) == len(db.PRODUCTS)
    assert all(p.price > 0 for p in db.PRODUCTS)


@pytest.mark.parametrize("store", STORES)
def test_each_store_has_most_of_the_catalogue(store):
    keys = {p.key for p in db.PRODUCTS if p.store == store and p.key}
    assert len(keys) >= 30


def test_stores_really_differ():
    """Same item, different brand / size / price across stores."""
    flour = [p for p in db.PRODUCTS if p.key == "plain flour"]
    assert len({p.brand for p in flour}) >= 3 and len({p.price for p in flour}) >= 4


def test_sizes_parse_except_the_intentional_ones():
    bad = {p.size for p in db.PRODUCTS if parse_size(p.size) is None}
    assert bad == EXPECTED_UNPARSEABLE


def test_messy_size_formats_present():
    sizes = {p.size for p in db.PRODUCTS}
    for fmt in ("1kg", "500 g", "6 x 50ml", "12's", "1.5L", "Pack of 6", "1 litre", "10s"):
        assert fmt in sizes, fmt


@pytest.mark.parametrize("store", STORES)
def test_some_stock_variety(store):
    assert any(not p.in_stock for p in db.PRODUCTS if p.store == store)


def test_quickbasket_lacks_vanilla():
    assert db.search("quickbasket", "vanilla extract") == []


# ---------------------------------------------------------------- search
def names(store, q):
    return [p.name for p in db.search(store, q)]


def test_plural_and_case_insensitive():
    assert names("freshmart", "EGGS") == names("freshmart", "egg") != []


def test_all_words_must_match():
    assert all("Flour" in n for n in names("valuegrocer", "plain flour"))


def test_empty_query_returns_nothing():
    assert db.search("freshmart", "   ") == []


def test_lookalikes_come_back_for_the_real_search():
    got = names("valuegrocer", "plain flour")
    assert "Plain Flour" in got and "Plain Flour Tortilla Wraps" in got  # a decoy shares the phrase
    assert "Coconut Milk" in names("valuegrocer", "milk")
    assert "Egg Noodles" in names("freshmart", "egg")


def test_naive_first_result_is_wrong_at_quickbasket():
    first = db.search("quickbasket", "cocoa powder")[0]
    assert first.key is None and first.decoy_of == "cocoa powder"


def test_real_product_ranks_above_decoy_elsewhere():
    assert db.search("freshmart", "cocoa powder")[0].key == "cocoa powder"


# ---------------------------------------------------------------- HTML contract (all 3 stores)
def cards(html):
    return re.findall(r'class="product-card"[^>]*data-product-id="([^"]+)"', html)


@pytest.mark.parametrize("store", STORES)
def test_home_search_and_product_pages(store):
    home = client.get(f"/stores/{store}/")
    assert home.status_code == 200 and cards(home.text)

    res = client.get(f"/stores/{store}/search", params={"q": "butter"})
    ids = cards(res.text)
    assert ids and 'name="q"' in res.text
    for field in ("name", "size", "price", "stock"):
        assert f'data-field="{field}"' in res.text

    page = client.get(f"/stores/{store}/product/{ids[0]}")
    assert page.status_code == 200 and f'data-product-id="{ids[0]}"' in page.text
    for field in ("name", "size", "price", "stock", "brand", "description"):
        assert f'data-field="{field}"' in page.text
    p = db.BY_ID[ids[0]]
    assert f'data-price="{p.price:.2f}"' in page.text


@pytest.mark.parametrize("store", STORES)
def test_no_results_page(store):
    html = client.get(f"/stores/{store}/search", params={"q": "zzzzqqq"}).text
    assert "no-results" in html and not cards(html)


@pytest.mark.parametrize("store", STORES)
def test_out_of_stock_flagged_in_html(store):
    p = next(p for p in db.PRODUCTS if p.store == store and not p.in_stock)
    html = client.get(f"/stores/{store}/product/{p.id}").text
    assert 'data-in-stock="false"' in html


def test_unknown_store_or_product_is_404():
    assert client.get("/stores/nope/").status_code == 404
    assert client.get("/stores/freshmart/product/nope").status_code == 404
    pid = db.search("freshmart", "butter")[0].id  # right id, wrong store
    assert client.get(f"/stores/valuegrocer/product/{pid}").status_code == 404


@pytest.mark.parametrize("store", STORES)
def test_no_cart_or_checkout_pages_or_forms(store):
    """The only <form> on any page is the search box; there are no cart/checkout routes."""
    pid = db.search(store, "butter")[0].id
    for url in (f"/stores/{store}/", f"/stores/{store}/product/{pid}"):
        html = client.get(url).text
        assert len(re.findall(r"<form", html)) == 1 and 'action="/stores/' in html and "/search" in html
    for path in ("cart", "checkout", "login"):
        assert client.get(f"/stores/{store}/{path}").status_code == 404


def test_html_escapes_search_text():
    html = client.get("/stores/freshmart/search", params={"q": "<script>alert(1)</script>"}).text
    assert "<script>alert(1)</script>" not in html
