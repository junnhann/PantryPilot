"""The safety guard. The agent may ONLY search and open product pages.

These are plain functions with no browser in them, so they are easy to unit-test.
They are enforced in code by SafePage (safe_page.py): every click, text entry and page
navigation the agent makes passes through one of the three checks below first.
A blocked action raises SafetyViolation and is never performed.

The rules deliberately err on the side of blocking. A false alarm costs one skipped
product; a missed one could cost real money.
"""
import re
from dataclasses import dataclass
from urllib.parse import parse_qs, urlparse


class SafetyViolation(Exception):
    """Raised when the agent tries to do something it must never do."""

    def __init__(self, reason: str, target: str = ""):
        super().__init__(reason)
        self.reason = reason
        self.target = target


# ---------------------------------------------------------------- forbidden wording
# Matched against lower-cased text where - _ / . : are turned into spaces, so the CSS class
# "add-to-cart" and the button label "Add to Cart" are both caught by the same pattern.
_FORBIDDEN = [
    ("add to cart", r"\badd\w*\s+(?:\w+\s+){0,3}?to\s*(?:my\s+|the\s+|your\s+)?(?:cart|basket|bag|trolley)\b|\baddtocart\b"),
    ("buy / purchase", r"\bbuy(?:\s*now)?\b|\bpurchase\b"),
    ("checkout", r"\bcheck\s*out\b"),
    ("payment", r"\bpay(?:ment|ments|ing|pal|now)?\b|\bpay\s*now\b"),
    ("place order", r"\bplace\s+(?:an?\s+|your\s+|my\s+|the\s+)?order\b|\border\s*now\b|\bsubmit\s+order\b"
                    r"|\bconfirm\s+(?:your\s+)?(?:order|purchase|payment)\b"),
    ("login / account", r"\blog\s*in\b|\blog\s*on\b|\bsign\s*in\b|\bsign\s*up\b|\bregister\b"
                        r"|\bcreate\s+(?:an?\s+)?account\b|\bmy\s+account\b"),
    ("cart", r"\bcart\b|\btrolley\b|\bshopping\s+bag\b|\b(?:view|open|go\s+to|my)\s+basket\b"),
    ("subscribe", r"\bsubscribe\b"),
]
_FORBIDDEN_RE = [(label, re.compile(rx)) for label, rx in _FORBIDDEN]

# URL path segments that are never opened (compared after removing - _ and .).
_FORBIDDEN_SEGMENTS = {
    "cart", "basket", "checkout", "login", "signin", "signup", "register", "account", "myaccount",
    "payment", "payments", "pay", "order", "orders", "trolley",
}


def _norm(text: str) -> str:
    return " ".join(re.sub(r"[-_/.:]+", " ", (text or "").lower()).split())


def find_forbidden(text: str) -> str | None:
    """Return the name of the forbidden action `text` describes, or None if it looks harmless."""
    t = _norm(text)
    for label, rx in _FORBIDDEN_RE:
        if rx.search(t):
            return label
    return None


# ---------------------------------------------------------------- elements
@dataclass
class ElementInfo:
    """Everything about an element that could reveal what clicking/typing in it would do."""

    tag: str = ""
    text: str = ""
    aria_label: str = ""
    title: str = ""
    value: str = ""
    href: str = ""
    id: str = ""
    classes: str = ""
    name: str = ""
    type: str = ""
    placeholder: str = ""
    role: str = ""
    form_action: str = ""
    # same facts about the nearest <a>/<button> around it, in case we target an inner <span>
    anc_text: str = ""
    anc_classes: str = ""
    anc_href: str = ""

    @classmethod
    def from_dict(cls, d: dict) -> "ElementInfo":
        return cls(**{k: str(v or "") for k, v in d.items() if k in cls.__dataclass_fields__})

    def describe(self) -> str:
        label = self.text or self.aria_label or self.title or self.value or self.name or self.id
        return f"<{self.tag.lower()}> {label.strip()[:60]!r}"


_SEARCH_NAMES = {"q", "query", "search", "s", "keyword", "keywords", "searchterm", "search_query", "term"}


def check_click(el: ElementInfo, allowed_hosts: set[str]) -> None:
    """Refuse to click anything that looks like cart / buy / checkout / pay / order / login."""
    for field in (el.text, el.aria_label, el.title, el.value, el.id, el.classes, el.name,
                  el.anc_text, el.anc_classes):
        hit = find_forbidden(field)
        if hit:
            raise SafetyViolation(f"Blocked click on {el.describe()}: looks like '{hit}'", el.describe())
    # Where would this click go? (links, and submit buttons inside forms)
    for url in (el.href, el.anc_href, el.form_action if el.type.lower() in ("submit", "image") else ""):
        if url and not url.startswith("#"):
            check_navigation(url, allowed_hosts)


def check_fill(el: ElementInfo) -> None:
    """Typing is only allowed in search boxes (never passwords, emails, card numbers, ...)."""
    if el.type.lower() in ("password", "email", "tel", "hidden", "file", "number") or \
            find_forbidden(" ".join([el.name, el.id, el.placeholder, el.aria_label])):
        raise SafetyViolation(f"Blocked typing into {el.describe()}: not a search box", el.describe())
    is_search = (
        el.type.lower() == "search" or el.role.lower() == "searchbox"
        or el.name.lower() in _SEARCH_NAMES
        or any("search" in x.lower() for x in (el.placeholder, el.aria_label, el.id, el.classes))
    )
    if not is_search:
        raise SafetyViolation(f"Blocked typing into {el.describe()}: only search boxes are allowed", el.describe())


# ---------------------------------------------------------------- navigation
def check_navigation(url: str, allowed_hosts: set[str]) -> None:
    """Only http(s) pages on the stores we were sent to, and never cart/checkout/login-style URLs."""
    if url in ("about:blank", ""):
        return
    u = urlparse(url)
    if u.scheme not in ("http", "https"):
        raise SafetyViolation(f"Blocked navigation to non-web address ({u.scheme or 'unknown'}:)", url)
    host = (u.hostname or "").lower()
    if not any(host == h or host.endswith("." + h) for h in allowed_hosts):
        raise SafetyViolation(f"Blocked navigation to {host or 'unknown host'}: not one of the allowed stores", url)
    for seg in u.path.lower().split("/"):
        if re.sub(r"[-_.]", "", seg) in _FORBIDDEN_SEGMENTS:
            raise SafetyViolation(f"Blocked navigation to {u.path}: cart/checkout/login-style page", url)
    for key in parse_qs(u.query):  # e.g. "?add-to-cart=123"
        hit = find_forbidden(key)
        if hit:
            raise SafetyViolation(f"Blocked navigation: URL parameter looks like '{hit}'", url)
