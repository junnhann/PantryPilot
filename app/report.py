"""Turn the agent's raw results into the final report shown on the results page.

For each ingredient we merge every store's evaluated options, rank them, and expose the best as
the pick (options[0]) with the others as alternatives. We also total the cost per store.
Pure functions: no browser, no network.
"""
from app import matching, units
from app.models import (Candidate, Ingredient, Report, ReportItem, ReviewVerdict, StoreTotal, TaskResult)

MAX_OPTIONS = 6


def build_report(items: list[Ingredient], results: list[TaskResult], stores: dict[str, str]) -> Report:
    by_item: dict[str, list[TaskResult]] = {}
    for r in results:
        by_item.setdefault(r.ingredient, []).append(r)

    report_items: list[ReportItem] = []
    for ing in items:
        rs = by_item.get(ing.name, [])
        pool = [c for r in rs for c in r.candidates]
        options = matching.rank(pool)[:MAX_OPTIONS]
        item = ReportItem(ingredient=ing.name, quantity=ing.quantity, unit=ing.unit, options=options)
        if not options:
            item.substitute = units.suggest_substitute(ing.name)
            reasons = [r.message for r in rs if r.message]
            item.message = reasons[0] if reasons else f"No store had “{ing.name}” in stock."
            if len(rs) > 1:
                item.message = f"None of the {len(rs)} stores had a usable “{ing.name}”."
        report_items.append(item)

    totals = []
    for slug, name in stores.items():
        total, found, to_confirm, missing = 0.0, 0, 0, []
        for ing in items:
            r = next((r for r in by_item.get(ing.name, []) if r.store == slug), None)
            best = r.candidates[0] if r and r.candidates else None
            if best:
                total += best.total_cost
                found += 1
                to_confirm += best.confidence == "low"
            else:
                missing.append(ing.name)
        totals.append(StoreTotal(store=slug, name=name, total=round(total, 2), found=found,
                                 missing=missing, to_confirm=to_confirm))

    best_mix = round(sum(i.options[0].total_cost for i in report_items if i.options), 2)
    return Report(items=report_items, store_totals=totals, best_mix_total=best_mix, stores=stores)


def apply_review(report: Report, verdicts: list[ReviewVerdict]) -> Report:
    """Fold the AI's opinion into the pick of each item (index = position in report.items).

    The AI can only make us LESS sure: confidence = the weaker of the rules' and the AI's.
    If the pick drops, a better-ranked alternative may take over.
    """
    for v in verdicts:
        if not (0 <= v.index < len(report.items)) or not report.items[v.index].options:
            continue
        item = report.items[v.index]
        pick = item.options[0]
        ai_conf = v.confidence if v.same_product else "low"
        if matching.RANK[ai_conf] < matching.RANK[pick.confidence]:
            pick.confidence = ai_conf
        if not v.same_product or ai_conf != "high":
            note = f"AI check: {v.reason or 'might not be the right product'}"
            if note not in pick.reasons:
                pick.reasons.append(note)
        item.options.sort(key=matching.sort_key)
    return report


def leftovers_of(picks: list[tuple[str, Candidate]]) -> list[dict]:
    """Significant leftovers (> 30% of what you buy) from the chosen products."""
    out = [{"name": ing, "amount": c.leftover_amount, "unit": c.leftover_unit, "pct": c.leftover_pct}
           for ing, c in picks if c.significant_leftover and c.leftover_amount > 0]
    return sorted(out, key=lambda x: -x["pct"])
