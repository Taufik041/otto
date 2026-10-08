// The sample session the screenshots, the landing page's replay and its vignettes all show: the
// design brief's run on Taufik041/otto_test (two failing tests, a one-character fix, a PR).
// Plain JavaScript, so scripts/screenshots.mjs (Node) imports it too; session.d.ts types it.

export const REPO = 'Taufik041/otto_test'
export const BRANCH = 'otto/4299fa2c3f'
export const TASK = 'two tests are failing, find out why and fix the source, not the tests'
export const INTRO = "On it. I'll reproduce the failures first."
export const PR_TITLE = 'Fix bulk discount threshold'
export const SEARCH_OUT =
  'src/inventory/pricing.py:22:def qualifies_for_bulk(quantity: int) -> bool:\nsrc/inventory/legacy_pricing.py:15:def qualifies_for_bulk(qty):'
export const PASSING = '.........                                [100%]\n9 passed in 0.09s'
export const COMMIT_OUT = '[otto/4299fa2c3f 7c1e8a2] Fix bulk discount threshold\n 1 file changed, 1 insertion(+), 1 deletion(-)'
export const PUSH_OUT = 'To github.com:Taufik041/otto_test.git\n * [new branch]      otto/4299fa2c3f -> otto/4299fa2c3f'

export const FAILING =
  "...F..F..                              [100%]\n================ FAILURES ================\n_____ test_bulk_discount_at_threshold _____\nE   AssertionError: Decimal('100.00') != Decimal('90.00')\nFAILED tests/test_pricing.py::test_bulk_discount_at_threshold\nFAILED tests/test_pricing.py::test_invoice_line_at_ten_units\n2 failed, 7 passed in 0.12s"
export const PRICING_MD =
  '# Pricing\n\nOrders are priced per unit from the catalog.\nTotals are rounded half-up to the nearest cent.\n\n## Bulk discount\n\nAn order of ten units or more receives a 10% discount\non the subtotal. Smaller orders pay the list price.\n\n`legacy_pricing.py` keeps the old rules and is frozen\nfor historical reports.\n'
export const FIX_DIFF = [
  '--- a/src/inventory/pricing.py',
  '+++ b/src/inventory/pricing.py',
  '@@ -20,7 +20,7 @@ CENT = Decimal("0.01")',
  ' ',
  ' ',
  ' def qualifies_for_bulk(quantity: int) -> bool:',
  '     """Orders at or above the threshold get the bulk rate."""',
  '-    return quantity > config.BULK_THRESHOLD',
  '+    return quantity >= config.BULK_THRESHOLD',
  ' ',
  ' ',
  ' def order_total(order: Order) -> Decimal:',
  '',
].join('\n')
export const TEST_DIFF = [
  '--- a/tests/test_pricing.py',
  '+++ b/tests/test_pricing.py',
  '@@ -41,3 +41,6 @@ def test_bulk_discount_at_threshold():',
  '     assert order_total(order) == Decimal("90.00")',
  ' ',
  ' ',
  '+def test_bulk_discount_at_eleven_units():',
  '+    order = Order(sku="WIDGET", unit_price=Decimal("10.00"), quantity=11)',
  '+    assert order_total(order) == Decimal("99.00")',
  '',
].join('\n')
export const PLAIN_REPLY = [
  'Yes. A threshold rule usually sits next to your other pricing logic and applies to the subtotal:',
  '',
  '```python',
  'def order_total(order: Order) -> Decimal:',
  '    subtotal = order.unit_price * order.quantity',
  '    if subtotal > Decimal("500"):',
  '        subtotal *= Decimal("0.95")',
  '    return round_money(subtotal)',
  '```',
  '',
  'I can write it, add tests and open a pull request once I know which codebase it goes in.',
].join('\n')
export const REPLY =
  "Found it. `qualifies_for_bulk` used `>` instead of `>=`, so exactly 10 units missed the bulk discount. The pricing sheet says ten or more qualify.\n\nI fixed the comparison and all 9 tests pass. I left `legacy_pricing.py` alone because it's frozen for historical reports."

/** GET /models, as the screenshots and the landing page show it */
export const MODELS = {
  default_model: 'openrouter:openrouter/free',
  models: [
    { id: 'openrouter:openrouter/free', label: 'Otto', provider: 'openrouter', description: 'Good for small tasks', available: true, hint: null },
    { id: 'openai:gpt-4.1-mini', label: 'GPT-4.1 mini', provider: 'openai', description: 'Fast and capable', available: true, hint: null },
    { id: 'openai:gpt-4.1', label: 'GPT-4.1', provider: 'openai', description: 'Best for larger changes', available: false, hint: 'Unavailable right now. Try again later.' },
  ],
}
