"""Safety guard tests (pure functions, no browser). The agent must never cart / buy / pay / log in."""
import pytest

from app.agent.safety import (ElementInfo, SafetyViolation, check_click, check_fill, check_navigation,
                              find_forbidden)

HOSTS = {"127.0.0.1"}
BASE = "http://127.0.0.1:8000"


# ---------------------------------------------------------------- forbidden wording
@pytest.mark.parametrize("text", [
    "Add to cart", "ADD TO CART", "add to basket", "Add to Bag", "Add 2 to cart", "Add to my trolley", "addtocart",
    "add-to-cart", "btn_add_to_cart", "Buy now", "Buy", "BUY NOW", "Purchase",
    "Checkout", "Check out", "Proceed to checkout", "checkout-button",
    "Pay now", "Payment", "PayPal", "Pay", "paynow",
    "Place order", "Place your order", "Order now", "Confirm order", "Confirm your purchase",
    "Log in", "Login", "Sign in", "Sign up", "Register", "Create an account", "My account",
    "View cart", "Cart (2)", "Shopping bag", "View basket", "Go to basket", "Subscribe",
])
def test_forbidden_text_is_caught(text):
    assert find_forbidden(text), text


@pytest.mark.parametrize("text", [
    "", "Search", "Go", "Find", "Next page", "ValuePick Baking Powder", "Harvest Gold Cocoa Powder",
    "Quick Choice Cocoa Powder Drink Mix", "QuickBasket", "FreshMart", "Home", "Deals", "Flyer", "Back",
    "product-link", "product-card", "S$3.60", "Payday-free butter cookies".replace("Payday-free", "Salted"),
    "Eggs 12's", "Cartwheel",  # "cart" inside another word is fine
])
def test_harmless_text_is_allowed(text):
    assert find_forbidden(text) is None, text


# ---------------------------------------------------------------- clicks
def el(**kw) -> ElementInfo:
    return ElementInfo(**kw)


@pytest.mark.parametrize("info", [
    el(tag="BUTTON", text="Add to cart"),
    el(tag="BUTTON", text="Add to basket", classes="btn"),
    el(tag="BUTTON", text="", classes="add-to-cart"),                     # no label, only a CSS class
    el(tag="BUTTON", text="", aria_label="Buy now"),                       # only an aria-label
    el(tag="BUTTON", text="Go", title="Proceed to checkout"),
    el(tag="INPUT", type="submit", value="Place order"),
    el(tag="A", text="Sign in", href=BASE + "/stores/freshmart/#"),
    el(tag="A", text="Click here", href=BASE + "/stores/freshmart/checkout"),  # innocent text, bad link
    el(tag="A", text="Continue", href=BASE + "/stores/freshmart/cart"),
    el(tag="SPAN", text="Add", anc_text="Add to cart", anc_classes="btn"),    # inner span of a bad button
    el(tag="SPAN", text="x", anc_classes="add-to-basket"),
    el(tag="BUTTON", type="submit", text="Continue", form_action=BASE + "/stores/freshmart/checkout"),
    el(tag="A", text="Product", href="https://evil.example.com/p/1"),          # other website
    el(tag="A", text="Product", href="javascript:buy()"),
])
def test_dangerous_clicks_are_blocked(info):
    with pytest.raises(SafetyViolation):
        check_click(info, HOSTS)


@pytest.mark.parametrize("info", [
    el(tag="A", text="ValuePick Baking Powder", href=BASE + "/stores/valuegrocer/product/va-valuepick-baking-powder-100-g",
       classes="product-link"),
    el(tag="BUTTON", type="submit", text="Search", form_action=BASE + "/stores/freshmart/search"),
    el(tag="A", text="Next", href=BASE + "/stores/freshmart/search?q=flour&page=2"),
    el(tag="A", text="Home", href="#"),
])
def test_normal_clicks_are_allowed(info):
    check_click(info, HOSTS)


def test_violation_has_a_friendly_reason():
    with pytest.raises(SafetyViolation) as e:
        check_click(el(tag="BUTTON", text="Add to cart"), HOSTS)
    assert "add to cart" in e.value.reason.lower()


# ---------------------------------------------------------------- typing
@pytest.mark.parametrize("info", [
    el(tag="INPUT", name="q", type="text"),
    el(tag="INPUT", type="search"),
    el(tag="INPUT", name="query"),
    el(tag="INPUT", placeholder="Search products"),
    el(tag="INPUT", role="searchbox"),
])
def test_search_boxes_may_be_typed_in(info):
    check_fill(info)


@pytest.mark.parametrize("info", [
    el(tag="INPUT", type="password", name="q"),                 # password never, even if named q
    el(tag="INPUT", type="email"),
    el(tag="INPUT", name="card_number"),
    el(tag="INPUT", name="username"),
    el(tag="INPUT", name="login_email"),
    el(tag="INPUT", name="coupon"),
    el(tag="TEXTAREA", name="message"),
    el(tag="INPUT", type="text"),                                # unknown input
])
def test_other_inputs_are_blocked(info):
    with pytest.raises(SafetyViolation):
        check_fill(info)


# ---------------------------------------------------------------- navigation
@pytest.mark.parametrize("url", [
    BASE + "/stores/freshmart/", BASE + "/stores/freshmart/search?q=cocoa+powder",
    BASE + "/stores/freshmart/product/fr-golden-wheat-plain-flour-1kg", "about:blank",
    BASE + "/stores/freshmart/product/va-order-of-the-day",     # "order" inside a slug is fine
])
def test_normal_navigation_allowed(url):
    check_navigation(url, HOSTS)


@pytest.mark.parametrize("url", [
    BASE + "/cart", BASE + "/stores/freshmart/cart", BASE + "/stores/freshmart/checkout/step1",
    BASE + "/stores/freshmart/login", BASE + "/sign-in", BASE + "/signup", BASE + "/my-account",
    BASE + "/account/orders", BASE + "/payment", BASE + "/stores/x/basket", BASE + "/order",
    BASE + "/stores/freshmart/search?add-to-cart=123",          # WooCommerce-style add-to-cart link
    "http://evil.example.com/stores/freshmart/", "https://www.google.com/", "http://127.0.0.1.evil.com/",
    "javascript:alert(1)", "file:///etc/passwd", "data:text/html,hi", "ftp://127.0.0.1/",
])
def test_dangerous_navigation_blocked(url):
    with pytest.raises(SafetyViolation):
        check_navigation(url, HOSTS)


def test_subdomains_of_an_allowed_host_are_allowed():
    check_navigation("https://www.shop.example/p/1", {"shop.example"})
    with pytest.raises(SafetyViolation):
        check_navigation("https://shop.example.evil.com/p/1", {"shop.example"})
