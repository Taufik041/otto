(function () {
  const IC = {
    menu: "M4 7h16M4 12h16M4 17h16",
    sidebar: "M4 5.5h16v13H4zM9.5 5.5v13",
    compose: "M12 20h8M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z",
    search: "M10.5 4a6.5 6.5 0 1 0 0 13 6.5 6.5 0 0 0 0-13zM15.5 15.5 20 20",
    chevDown: "M6 9.5l6 6 6-6",
    chevRight: "M9.5 6l6 6-6 6",
    chevLeft: "M14.5 6l-6 6 6 6",
    up: "M12 19V5M6 11l6-6 6 6",
    lock: "M7.5 11V8a4.5 4.5 0 0 1 9 0v3M5.5 11h13v9.5h-13z",
    globe: "M12 3.5a8.5 8.5 0 1 0 0 17 8.5 8.5 0 0 0 0-17zM3.5 12h17M12 3.5c2.4 2.6 3.4 5.4 3.4 8.5s-1 5.9-3.4 8.5c-2.4-2.6-3.4-5.4-3.4-8.5s1-5.9 3.4-8.5z",
    repo: "M5.5 18.5V5A1.5 1.5 0 0 1 7 3.5h11.5v13H7a1.5 1.5 0 0 0-1.5 1.5 1.5 1.5 0 0 0 1.5 1.5h11.5",
    check: "M5 12.5l4.5 4.5L19 7.5",
    checkCircle: "M12 3.5a8.5 8.5 0 1 0 0 17 8.5 8.5 0 0 0 0-17zM8 12.3l2.8 2.8L16.2 9.5",
    x: "M6.5 6.5l11 11M17.5 6.5l-11 11",
    alert: "M12 4 21 19.5H3zM12 10v4M12 17h.01",
    spin: "M12 3.5a8.5 8.5 0 1 0 8.5 8.5",
    run: "M4.5 17l5-5-5-5M11.5 18h8",
    file: "M14 3H7a1.5 1.5 0 0 0-1.5 1.5v15A1.5 1.5 0 0 0 7 21h10a1.5 1.5 0 0 0 1.5-1.5V7.5zM14 3v4.5h4.5",
    edit: "M4 20h4L19.5 8.5a2.1 2.1 0 0 0-4-4L4 16zM13.5 6.5l4 4",
    push: "M12 16V4M7 9l5-5 5 5M5 20h14",
    pr: "M6 8.5a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5zM6 8.5v7M6 20.5a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5zM18 20.5a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5zM18 15.5V9a3 3 0 0 0-3-3h-3M14 3.5 11.5 6 14 8.5",
    more: "M5.5 12h.01M12 12h.01M18.5 12h.01",
    panel: "M4 5.5h16v13H4zM13.5 5.5v13",
    gear: "M12 9a3 3 0 1 0 0 6 3 3 0 0 0 0-6zM10.7 3h2.6l.5 2.4 1.9 1.1 2.3-.8 1.3 2.3-1.8 1.6v2.2l1.8 1.6-1.3 2.3-2.3-.8-1.9 1.1-.5 2.4h-2.6l-.5-2.4-1.9-1.1-2.3.8-1.3-2.3 1.8-1.6v-2.2L4.7 8l1.3-2.3 2.3.8 1.9-1.1z",
    chart: "M5 20V11M12 20V5M19 20v-6",
    sun: "M12 4V2.5M12 21.5V20M4 12H2.5M21.5 12H20M6.3 6.3 5.2 5.2M18.8 18.8l-1.1-1.1M6.3 17.7l-1.1 1.1M18.8 5.2l-1.1 1.1M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8z",
    moon: "M20 14.5A8.5 8.5 0 0 1 9.5 4a8.5 8.5 0 1 0 10.5 10.5z",
    monitor: "M3.5 5h17v11h-17zM9 20h6M12 16v4",
    help: "M12 3.5a8.5 8.5 0 1 0 0 17 8.5 8.5 0 0 0 0-17zM9.6 9.5a2.5 2.5 0 1 1 3.4 2.3c-.6.3-1 .8-1 1.5v.4M12 16.8h.01",
    signout: "M14 4h4.5v16H14M10 8l-4 4 4 4M6 12h9",
    ext: "M14 4h6v6M20 4l-9 9M18 14v5.5H4.5V6H10",
    retry: "M4.5 12a7.5 7.5 0 1 0 2.2-5.3M4.5 4.5v4h4",
    at: "M16 12a4 4 0 1 1-8 0 4 4 0 0 1 8 0zM16 12v1.5a2.5 2.5 0 0 0 5 0V12a9 9 0 1 0-3.5 7.1",
    user: "M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM4.5 20a7.5 7.5 0 0 1 15 0",
    cpu: "M7 7h10v10H7zM10 3v4M14 3v4M10 17v4M14 17v4M3 10h4M3 14h4M17 10h4M17 14h4",
    palette: "M12 3.5a8.5 8.5 0 1 0 0 17c1 0 1.5-.7 1.5-1.5 0-1.2-1-1.5-1-2.5 0-.8.7-1.5 1.5-1.5H16a4.5 4.5 0 0 0 4.5-4.5c0-4-3.8-7-8.5-7zM7.5 12h.01M9.5 8h.01M14.5 8h.01",
    mail: "M3.5 6h17v12h-17zM3.5 6.5l8.5 6.5 8.5-6.5",
    box: "M12 3l8 4.5v9L12 21l-8-4.5v-9zM4 7.5l8 4.5 8-4.5M12 12v9",
    key: "M15 3.5a5.5 5.5 0 1 0 0 11 5.5 5.5 0 0 0 0-11zM11 13 3.5 20.5M6.5 17.5l2.5 2.5",
    stop: "M7 7h10v10H7z",
    commit: "M12 15.5a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7zM3 12h5.5M15.5 12H21",
    cursor: "M5 3.5l13 7.2-5.6 1.6L9.6 18z"
  };
  const GH = "M12 .5C5.65.5.5 5.65.5 12c0 5.08 3.29 9.39 7.86 10.91.58.1.79-.25.79-.56v-2c-3.2.7-3.87-1.37-3.87-1.37-.52-1.33-1.28-1.69-1.28-1.69-1.04-.71.08-.7.08-.7 1.15.08 1.76 1.19 1.76 1.19 1.03 1.76 2.69 1.25 3.35.96.1-.74.4-1.25.73-1.54-2.55-.29-5.24-1.28-5.24-5.68 0-1.26.45-2.28 1.19-3.09-.12-.29-.52-1.46.11-3.05 0 0 .97-.31 3.17 1.18a11 11 0 0 1 5.77 0c2.2-1.49 3.17-1.18 3.17-1.18.63 1.59.23 2.76.11 3.05.74.81 1.19 1.83 1.19 3.09 0 4.41-2.69 5.39-5.25 5.67.41.36.78 1.06.78 2.14v3.17c0 .31.21.67.8.56A11.5 11.5 0 0 0 23.5 12C23.5 5.65 18.35.5 12 .5z";

  const esc = (s) => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  const sp = (c, s) => '<span style="color:var(--c-' + c + ')">' + esc(s) + "</span>";
  function py(line) {
    const re = /(#.*$)|("""[^"]*(?:""")?|"[^"]*"|'[^']*')|\b(def|return|if|else|elif|import|from|class|for|in|not|and|or|None|True|False|assert|with|as)\b|\b(\d+(?:\.\d+)?)\b|\b([A-Z][A-Za-z_]\w*)\b|\b([a-z_]\w*)(?=\()/g;
    let out = "", last = 0, m;
    while ((m = re.exec(line))) {
      out += esc(line.slice(last, m.index));
      if (m[1]) out += sp("com", m[1]);
      else if (m[2]) out += sp("str", m[2]);
      else if (m[3]) out += sp("kw", m[3]);
      else if (m[4]) out += sp("num", m[4]);
      else if (m[5]) out += /^[A-Z_]+$/.test(m[5]) ? esc(m[5]) : sp("type", m[5]);
      else if (m[6]) out += sp("fn", m[6]);
      last = m.index + m[0].length;
    }
    return out + esc(line.slice(last)) || "&nbsp;";
  }
  const wrap = (rows) => '<div style="display:inline-flex;flex-direction:column;min-width:100%">' + rows.join("") + "</div>";
  const G = "flex:0 0 44px;text-align:right;padding-right:10px;color:var(--gutter);user-select:none";
  function diffHtml(rows) {
    return wrap(rows.map((r) => {
      if (r.h) return '<div style="display:flex;background:var(--hunk);color:var(--muted)"><span style="flex:0 0 108px"></span><span style="white-space:pre;padding-right:20px">' + esc(r.h) + "</span></div>";
      const add = r.m === "+", del = r.m === "-";
      return '<div style="display:flex;background:' + (add ? "var(--add-bg)" : del ? "var(--del-bg)" : "transparent") + '"><span style="' + G + '">' + (add ? "" : r.o) + '</span><span style="' + G + '">' + (del ? "" : r.n) + '</span><span style="flex:0 0 20px;text-align:center;color:' + (add ? "var(--ok)" : "var(--bad)") + '">' + (add ? "+" : del ? "−" : "") + '</span><span style="white-space:pre;padding-right:20px">' + py(r.t) + "</span></div>";
    }));
  }
  function fileHtml(start, lines, md) {
    return wrap(lines.map((l, i) => {
      const hl = md && /ten units or more/.test(l);
      const body = md ? (/^#/.test(l) ? '<span style="color:var(--c-kw);font-weight:600">' + esc(l) + "</span>" : esc(l) || "&nbsp;") : py(l);
      return '<div style="display:flex;background:' + (hl ? "color-mix(in srgb, var(--accent) 10%, transparent)" : "transparent") + '"><span style="' + G + '">' + (start + i) + '</span><span style="white-space:pre;padding:0 20px 0 10px">' + body + "</span></div>";
    }));
  }
  const T = (s) => '<div style="white-space:pre">' + s + "</div>";
  const c = (v, s) => '<span style="color:var(--' + v + ')">' + esc(s) + "</span>";
  const termHtml = (lines) => '<div style="display:inline-flex;flex-direction:column;min-width:100%">' + lines.map(T).join("") + "</div>";

  const FILES = {
    py: { path: "src/inventory/pricing.py", kind: "Edited", add: "+1", del: "−1", html: diffHtml([
      { h: "@@ -20,7 +20,7 @@ CENT = Decimal(\"0.01\")" },
      { o: 20, n: 20, t: "" },
      { o: 21, n: 21, t: "" },
      { o: 22, n: 22, t: "def qualifies_for_bulk(quantity: int) -> bool:" },
      { o: 23, n: 23, t: '    """Orders at or above the threshold get the bulk rate."""' },
      { o: 24, m: "-", t: "    return quantity > config.BULK_THRESHOLD" },
      { n: 24, m: "+", t: "    return quantity >= config.BULK_THRESHOLD" },
      { o: 25, n: 25, t: "" },
      { o: 26, n: 26, t: "" },
      { o: 27, n: 27, t: "def order_total(order: Order) -> Decimal:" }
    ]) },
    test: { path: "tests/test_pricing.py", kind: "Edited", add: "+3", del: "", html: diffHtml([
      { h: "@@ -41,3 +41,6 @@ def test_bulk_discount_at_threshold():" },
      { o: 41, n: 41, t: '    assert order_total(order) == Decimal("90.00")' },
      { o: 42, n: 42, t: "" },
      { o: 43, n: 43, t: "" },
      { n: 44, m: "+", t: "def test_bulk_discount_at_eleven_units():" },
      { n: 45, m: "+", t: '    order = Order(sku="WIDGET", unit_price=Decimal("10.00"), quantity=11)' },
      { n: 46, m: "+", t: '    assert order_total(order) == Decimal("99.00")' }
    ]) },
    md: { path: "docs/PRICING.md", kind: "Read", add: "", del: "", html: fileHtml(1, [
      "# Pricing", "", "Orders are priced per unit from the catalog.", "Totals are rounded half-up to the nearest cent.", "",
      "## Bulk discount", "", "An order of ten units or more receives a 10% discount", "on the subtotal. Smaller orders pay the list price.", "",
      "`legacy_pricing.py` keeps the old rules and is frozen", "for historical reports."
    ], true) }
  };

  const CMDS = [
    { id: "c1", step: "run1", cmd: "python -m pytest -q", exit: 1, time: "14:02:06", html: termHtml([
      c("ok", "...") + '<span style="color:var(--bad);font-weight:600">F</span>' + c("ok", "..") + '<span style="color:var(--bad);font-weight:600">F</span>' + c("ok", "..") + c("muted", "                              [100%]"),
      c("muted", "================ FAILURES ================"),
      c("bad", "_____ test_bulk_discount_at_threshold _____"),
      "    order = " + sp("type", "Order") + "(sku=" + sp("str", '"WIDGET"') + ", quantity=" + sp("num", "10") + ")",
      c("bad", ">") + "   " + sp("kw", "assert") + " order_total(order) == " + sp("type", "Decimal") + "(" + sp("str", '"90.00"') + ")",
      c("bad", "E   AssertionError: Decimal('100.00') != Decimal('90.00')"),
      c("muted", "tests/test_pricing.py:40: AssertionError"),
      c("bad", "FAILED") + " tests/test_pricing.py::test_bulk_discount_at_threshold",
      c("bad", "FAILED") + " tests/test_pricing.py::test_invoice_line_at_ten_units",
      '<span style="color:var(--bad);font-weight:600">2 failed</span>' + c("muted", ", ") + c("ok", "7 passed") + c("muted", " in 0.12s")
    ]) },
    { id: "c2", step: "search", cmd: "rg -n qualifies_for_bulk src", exit: 0, time: "14:02:11", html: termHtml([
      c("c-fn", "src/inventory/pricing.py") + c("muted", ":22:") + sp("kw", "def") + " qualifies_for_bulk(quantity: " + sp("type", "int") + ") -> " + sp("type", "bool") + ":",
      c("c-fn", "src/inventory/legacy_pricing.py") + c("muted", ":15:") + sp("kw", "def") + " qualifies_for_bulk(qty):"
    ]) },
    { id: "c3", step: "run2", cmd: "python -m pytest -q", exit: 0, time: "14:03:02", pass: "9 passed", dur: "in 0.09s", html: termHtml([c("ok", ".........") + c("muted", "                                [100%]")]) },
    { id: "c4", step: "push1", cmd: 'git commit -am "Fix bulk discount threshold"', exit: 0, time: "14:03:21", html: termHtml([
      c("muted", "[otto/4299fa2c3f 7c1e8a2] Fix bulk discount threshold"),
      c("muted", " 1 file changed, 1 insertion(+), 1 deletion(-)")
    ]) },
    { id: "c5", step: "prOpen", cmd: "git push -u origin otto/4299fa2c3f && gh pr create --fill --base main", exit: 0, time: "14:05:10", html: termHtml([
      c("muted", "To github.com:Taufik041/otto_test.git"),
      c("muted", " * [new branch]      otto/4299fa2c3f -> otto/4299fa2c3f"),
      c("c-fn", "https://github.com/Taufik041/otto_test/pull/3")
    ]) },
    { id: "c6", step: "run3", cmd: "python -m pytest -q", exit: 0, time: "16:40:18", pass: "10 passed", dur: "in 0.10s", html: termHtml([c("ok", "..........") + c("muted", "                               [100%]")]) },
    { id: "c7", step: "push2", cmd: 'git commit -am "Add test for 11-unit orders" && git push', exit: 0, time: "16:40:26", html: termHtml([
      c("muted", "[otto/4299fa2c3f 91b04dd] Add test for 11-unit orders"),
      c("muted", " 1 file changed, 3 insertions(+)"),
      c("muted", "   7c1e8a2..91b04dd  otto/4299fa2c3f -> otto/4299fa2c3f")
    ]) }
  ];

  const MAIN = [
    { id: "run1", icon: "run", verb: "Ran", now: "Running", code: "python -m pytest -q", res: "2 failed, 7 passed", tone: "bad", strong: true, go: { tab: "terminal", cmd: "c1" } },
    { id: "search", icon: "search", verb: "Searched", now: "Searching", code: "qualifies_for_bulk", res: "2 matches", sub: "src/inventory/pricing.py:22 · src/inventory/legacy_pricing.py:15", go: { tab: "terminal", cmd: "c2" } },
    { id: "read", icon: "file", verb: "Read", now: "Reading", code: "docs/PRICING.md", sub: "“ten units or more receives a 10% discount”", go: { tab: "changes", file: "md" } },
    { id: "edit1", icon: "edit", verb: "Edited", now: "Editing", code: "src/inventory/pricing.py", add: "+1", del: "−1", go: { tab: "changes", file: "py" } },
    { id: "run2", icon: "run", verb: "Ran", now: "Running", code: "python -m pytest -q", res: "9 passed", tone: "ok", strong: true, go: { tab: "terminal", cmd: "c3" } },
    { id: "push1", icon: "commit", verb: "Committed to", now: "Committing to", code: "otto/4299fa2c3f", go: { tab: "terminal", cmd: "c4" } },
    { id: "pr1", icon: "check", verb: "Prepared changes for review", now: "Preparing changes for review", code: "", go: { tab: "changes", file: "py" } }
  ];
  const FOLLOW = [
    { id: "edit2", icon: "edit", verb: "Edited", now: "Editing", code: "tests/test_pricing.py", add: "+3", go: { tab: "changes", file: "test" } },
    { id: "run3", icon: "run", verb: "Ran", now: "Running", code: "python -m pytest -q", res: "10 passed", tone: "ok", strong: true, go: { tab: "terminal", cmd: "c6" } },
    { id: "push2", icon: "push", verb: "Pushed to pull request", now: "Pushing to pull request", code: "#3", go: { tab: "terminal", cmd: "c7" } }
  ];

  const REPOS = [
    { name: "otto_test", priv: true, upd: "updated 2h ago" },
    { name: "portfolio", priv: false, upd: "updated 3d ago" },
    { name: "petal", priv: true, upd: "updated 1w ago" }
  ];
  const MODELS = [
    { id: "otto", group: "Otto", name: "Otto", desc: "Tuned for repo work. Free.", def: true, ok: true },
    { id: "gpt-mini", group: "Other models", name: "GPT-4.1 mini", desc: "Fast and capable", ok: true },
    { id: "gpt", group: "Other models", name: "GPT-4.1", desc: "Best for larger changes", ok: false, hint: "Unavailable right now. Try again later." }
  ];
  const USAGE14 = [8.2, 14.1, 6.3, 0, 3.4, 18.9, 22.4, 11.2, 9.8, 16.5, 4.1, 0, 7.7, 12.4];

  window.OttoData4 = { IC, GH, esc, py, FILES, CMDS, MAIN, FOLLOW, REPOS, MODELS, USAGE14 };
})();
