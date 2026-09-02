import { expect, test, type Locator, type Page } from "@playwright/test";

/**
 * Structured tool cards in the chat transcript, exercised through the
 * fixture harness at /chats/test (no model, gateway, or warehouse needed).
 *
 * Tool timeline (lib/chat-test-fixture-data.ts + -tools.ts):
 * Group 1 (one activity group):
 * -  1 500 – 2 700ms  get_table_schema → schema card
 * -  3 200 – 4 100ms  validate_sql FAILS ("region_name does not exist")
 * -  4 700 – 7 400ms  query_database → table (50 preview rows of 1,204,
 *                     result_id res-31, PII column `email`)
 * -  7 460ms+         mid-run narration; the group collapses to chips
 * Answer narration streams 18 100 – 20 500ms (`writing` state).
 * Group 3 (21 200 – 23 950ms):
 * - 21 200 – 21 650ms list_tables (47 tables / 3 schemas)
 * - 21 800 – 22 300ms explore_columns
 * - 22 400 – 23 300ms dbt_execute (12 success / 1 error, 8.4 s)
 * - 23 400 – 23 650ms search_knowledge (3 docs)
 * - 23 700 – 23 950ms hubspot search_contacts → json
 * The run completes at 24 600ms; FIXTURE_TOTAL_MS is 24 800ms.
 *
 * Density policy (use-card-density.ts): a card that completes while the
 * frame is playing holds "expanded" for 900ms before folding to a chip, so
 * every `at` below sits away from a completion edge. Cards mounted already
 * complete get no hold at all.
 */

const BASE = process.env.SP_WEB_BASE_URL ?? "http://localhost:3200";
const at = (ms: number) => `${BASE}/chats/test?at=${ms}&paused=1`;

/** Clicks before React hydration are silently lost — gate on the harness
 * flag. In dev mode a second `goto` can briefly render the old and new
 * harness together, so poll until exactly one node is present and hydrated. */
async function waitForHydration(page: Page) {
  await expect
    .poll(
      () =>
        page
          .getByTestId("chat-test-harness")
          .evaluateAll((nodes) => nodes.map((node) => node.getAttribute("data-hydrated"))),
      { timeout: 15_000 },
    )
    .toEqual(["1"]);
}

/** A group's header strip; compact cards inside the (collapsed) timeline
 * also render `chat-tool-chip`, so chip assertions scope to the strip. */
function strip(group: Locator) {
  return group.getByTestId("chat-tool-chip-strip");
}

function cardOfKind(scope: Locator | Page, kind: string) {
  return scope.locator(`[data-testid="chat-tool-card"][data-kind="${kind}"]`);
}

test.describe("tool cards (fixture harness)", () => {
  test("a running query renders the table card at running density with its SQL and skeleton rows", async ({
    page,
  }) => {
    // 5.5s: query_database started at 4.7s and completes at 7.4s.
    await page.goto(at(5_500));
    await waitForHydration(page);
    const card = cardOfKind(page, "table");
    await expect(card).toHaveCount(1);
    await expect(card).toHaveAttribute("data-density", "running");
    await expect(card).toHaveAttribute("data-tool", "query_database");
    const frame = page.getByTestId("chat-tool-card-table");
    await expect(frame).toBeVisible();
    await expect(frame).toContainText(/SELECT/i);
    // Ghost rows stand in for the result while the warehouse works.
    await expect(frame.getByTestId("chat-skeleton-rows")).toBeVisible();
    await expect(page.getByTestId("chat-live-pill")).toHaveAttribute(
      "data-state",
      "tool",
    );
    // Nothing is compact-vs-expanded ambiguous: no expanded table yet.
    await expect(page.getByTestId("chat-data-table")).toHaveCount(0);
  });

  test("a failed validation stays expanded while the group is live", async ({
    page,
  }) => {
    // 6s: validate_sql failed at 4.1s; the query is still running so the
    // group is open. Errors never fold to a chip.
    await page.goto(at(6_000));
    await waitForHydration(page);
    const group = page.getByTestId("chat-activity-group").first();
    const card = cardOfKind(group, "validation");
    await expect(card).toHaveAttribute("data-density", "expanded");
    await expect(card).toHaveAttribute("data-tool", "validate_sql");
    const body = group.getByTestId("chat-validation-card");
    await expect(body).toBeVisible();
    await expect(body.getByTestId("chat-validation-verdict")).toHaveText(
      /Invalid/,
    );
    await expect(group.getByTestId("chat-tool-error")).toContainText(
      "does not exist",
    );
    // The failure message is shown once: the banner carries it, and the
    // card body does not repeat it.
    const mentions = await group.evaluate(
      (node) => (node.textContent?.match(/does not exist/g) ?? []).length,
    );
    expect(mentions).toBe(1);
  });

  test("a failed validation is still expanded after the group collapsed and is reopened", async ({
    page,
  }) => {
    // 9s: the chain completed at 7.4s and the agent is narrating; the
    // group folded to its chip strip.
    await page.goto(at(9_000));
    await waitForHydration(page);
    const group = page.getByTestId("chat-activity-group").first();
    const collapse = group.locator(".chat-collapse").first();
    await expect(collapse).toHaveAttribute("data-open", "false");
    await expect(strip(group).locator('[data-kind="validation"]')).toHaveAttribute(
      "data-ok",
      "false",
    );
    // The header toggle is the group's first button (the chips come after).
    await group.getByRole("button").first().click();
    await expect(collapse).toHaveAttribute("data-open", "true");
    const card = cardOfKind(group, "validation");
    await expect(card).toHaveAttribute("data-density", "expanded");
    const body = group.getByTestId("chat-validation-card");
    await expect(body).toBeVisible();
    await expect(group.getByTestId("chat-tool-error")).toBeVisible();
    await expect(group.getByTestId("chat-tool-error")).toContainText(
      "does not exist",
    );
    const mentions = await group.evaluate(
      (node) => (node.textContent?.match(/does not exist/g) ?? []).length,
    );
    expect(mentions).toBe(1);
    // The successful siblings stayed compact.
    await expect(cardOfKind(group, "schema")).toHaveAttribute(
      "data-density",
      "compact",
    );
    await expect(cardOfKind(group, "table")).toHaveAttribute(
      "data-density",
      "compact",
    );
  });

  test("the chip strip summarises the completed chain and a chip reopens its card", async ({
    page,
  }) => {
    await page.goto(at(9_000));
    await waitForHydration(page);
    const group = page.getByTestId("chat-activity-group").first();
    const chips = strip(group).getByTestId("chat-tool-chip");
    // Six distinct kinds of work fit exactly in the strip: no overflow pill.
    await expect(chips).toHaveCount(6);
    await expect(strip(group).getByTestId("chat-tool-chip-more")).toHaveCount(0);
    const tableChip = strip(group).locator('[data-testid="chat-tool-chip"][data-kind="table"]');
    await expect(tableChip).toHaveCount(1);
    await expect(tableChip).toContainText("1,204 rows");
    await expect(tableChip).toHaveAttribute("data-ok", "true");
    // Importance order: the failed check leads, the query result follows,
    // and the legacy plan/subagent chips trail.
    await expect(chips.nth(0)).toHaveAttribute("data-kind", "validation");
    await expect(chips.nth(0)).toContainText("invalid");
    await expect(chips.nth(0)).toHaveAttribute("data-ok", "false");
    await expect(chips.nth(1)).toHaveAttribute("data-kind", "table");
    await expect(chips.last()).toHaveAttribute("data-kind", "legacy");
    // Nothing is clipped: every chip is inside the strip's box.
    const clipped = await strip(group).evaluate((node) => {
      const box = node.getBoundingClientRect();
      return [...node.querySelectorAll('[data-testid="chat-tool-chip"]')].filter((chip) => {
        const r = chip.getBoundingClientRect();
        return r.bottom > box.bottom + 1 || r.top < box.top - 1;
      }).length;
    });
    expect(clipped).toBe(0);

    // Picking the table chip opens the group with the table expanded.
    await tableChip.click();
    await expect(group.locator(".chat-collapse").first()).toHaveAttribute(
      "data-open",
      "true",
    );
    const card = cardOfKind(group, "table");
    await expect(card).toHaveAttribute("data-density", "expanded");
    const table = group.getByTestId("chat-data-table");
    await expect(table).toBeVisible();
    await expect(table.locator("tbody tr")).toHaveCount(50);
    // PII column is present but redacted in every row.
    await expect(table.locator("thead")).toContainText("email");
    await expect(table.locator("tbody tr").first()).toContainText("[REDACTED]");

    // Header sort cycles none → ascending → descending.
    const sortButton = table.getByTestId("chat-data-table-sort-net_revenue");
    const header = table.locator('th:has([data-testid="chat-data-table-sort-net_revenue"])');
    await expect(header).toHaveAttribute("aria-sort", "none");
    await sortButton.click();
    await expect(header).toHaveAttribute("aria-sort", "ascending");
    await sortButton.click();
    await expect(header).toHaveAttribute("aria-sort", "descending");
    // Sorting is per column: the others stay unsorted.
    await expect(
      table.locator('th:has([data-testid="chat-data-table-sort-order_count"])'),
    ).toHaveAttribute("aria-sort", "none");

    // Load all pages the full 1,204 rows through the harness stub.
    const loadAll = table.getByTestId("chat-data-table-load-all");
    await expect(loadAll).toContainText("Load all 1,204 rows");
    await loadAll.click();
    await expect(group.getByTestId("chat-table-footer")).toContainText(
      "showing 1,204",
    );
    await expect(loadAll).toHaveCount(0);
  });

  test("the writing state shows the pill, the caret and the composer ring; none remain at the end", async ({
    page,
  }) => {
    // 18.5s: answer tokens are streaming (18.1s – 20.5s).
    await page.goto(at(18_500));
    await waitForHydration(page);
    await expect(page.getByTestId("chat-live-pill")).toHaveAttribute(
      "data-state",
      "writing",
    );
    await expect(page.locator('[data-caret="true"]')).toHaveCount(1);
    await expect(page.locator('.chat-stop-ring[data-state="writing"]')).toHaveCount(1);
    // The transcript-level thinking indicator is not stacked on the pill.
    await expect(page.getByTestId("chat-live-indicator")).toHaveCount(0);

    await page.goto(at(24_800));
    await waitForHydration(page);
    await expect(page.getByTestId("chat-live-pill")).toHaveCount(0);
    await expect(page.locator('[data-caret="true"]')).toHaveCount(0);
    await expect(page.locator(".chat-stop-ring")).toHaveCount(0);
  });

  test("list_tables runs at running density, then completes to a compact chip", async ({
    page,
  }) => {
    // 21.4s: list_tables started at 21.2s and completes at 21.65s.
    await page.goto(at(21_400));
    await waitForHydration(page);
    const running = cardOfKind(page, "table_list");
    await expect(running).toHaveAttribute("data-density", "running");
    await expect(running).toHaveAttribute("data-tool", "list_tables");
    const frame = page.getByTestId("chat-tool-card-table_list");
    await expect(frame).toBeVisible();
    // The input echo names the connection being listed (the real tool takes
    // only connection_name/database, so the fixture's schema_name is not
    // echoed) and the scan ticker runs beside it.
    await expect(frame).toContainText("warehouse_prod");
    await expect(frame.getByTestId("chat-table-list-ticker")).toBeVisible();
    await expect(frame.getByTestId("chat-skeleton-rows")).toBeVisible();
    await expect(page.getByTestId("chat-live-pill")).toHaveAttribute(
      "data-state",
      "tool",
    );
    await expect(page.getByTestId("chat-activity-group").last().locator(".chat-collapse").first()).toHaveAttribute(
      "data-open",
      "true",
    );

    // 22.6s: complete (and past its hold); dbt_execute is running so the
    // group is still open and the listing sits compact inside it.
    await page.goto(at(22_600));
    await waitForHydration(page);
    const group = page.getByTestId("chat-activity-group").last();
    const card = cardOfKind(group, "table_list");
    await expect(card).toHaveAttribute("data-density", "compact");
    const chip = card.getByTestId("chat-tool-chip");
    await expect(chip).toHaveAttribute("data-kind", "table_list");
    await expect(chip).toHaveAttribute("data-ok", "true");
    await expect(chip).toContainText("47 tables");
    await expect(chip).toContainText("3 databases");
    // Clicking the chip expands the card in place.
    await chip.click();
    await expect(card).toHaveAttribute("data-density", "expanded");
    await expect(group.getByTestId("chat-tool-card-table_list")).toBeVisible();
    await expect(card.getByTestId("chat-tool-chip")).toHaveCount(0);
  });

  test("the expanded list_tables card groups 47 tables by schema and filters by name", async ({
    page,
  }) => {
    await page.goto(at(21_400));
    await waitForHydration(page);
    await expect(page.getByTestId("chat-table-list-ticker")).toBeVisible();

    await page.goto(at(22_600));
    await waitForHydration(page);
    const group = page.getByTestId("chat-activity-group").last();
    const card = cardOfKind(group, "table_list");
    await card.getByTestId("chat-tool-chip").click();
    await expect(card).toHaveAttribute("data-density", "expanded");
    const list = group.getByTestId("chat-table-list");
    await expect(list).toBeVisible();
    // Three schema groups, none folded, so every entry is a row.
    await expect(list.getByTestId("chat-table-list-group")).toHaveCount(3);
    const rows = list.getByTestId("chat-table-list-row");
    await expect(rows).toHaveCount(47);
    await expect(rows.first()).toContainText("cols");

    const filter = list.getByTestId("chat-table-list-filter");
    await expect(filter).toBeVisible();
    await filter.fill("fct_");
    const filtered = await rows.count();
    expect(filtered).toBeGreaterThan(0);
    expect(filtered).toBeLessThan(47);
    for (const text of await rows.allTextContents()) {
      expect(text).toContain("fct_");
    }
    await filter.fill("zzz-no-such-table");
    await expect(rows).toHaveCount(0);
    await filter.fill("");
    await expect(rows).toHaveCount(47);
  });

  test("the dbt run card reports the tally and stays expanded on a failure", async ({
    page,
  }) => {
    // 23.5s: dbt_execute completed at 23.3s with 12 success / 1 error;
    // search_knowledge is running so the group is live.
    await page.goto(at(23_500));
    await waitForHydration(page);
    const group = page.getByTestId("chat-activity-group").last();
    const card = cardOfKind(group, "dbt_run");
    await expect(card).toHaveAttribute("data-tool", "dbt_execute");
    // A run with errors pins itself open while the group is live — no
    // click required, and it does not fold once the hold would elapse.
    await expect(card).toHaveAttribute("data-density", "expanded");
    const frame = group.getByTestId("chat-tool-card-dbt_run");
    await expect(frame).toContainText("12 ✓ 1 ✗");
    await expect(frame).toContainText("8.4 s");
    const body = frame.getByTestId("chat-dbt-run-card");
    await expect(body).toContainText("dbt run --select marts.revenue+");
    const tallies = body.getByTestId("chat-dbt-run-tallies");
    await expect(tallies).toContainText("Pass");
    await expect(tallies).toContainText("12");
    await expect(tallies).toContainText("Error");
    await expect(tallies).toContainText("1");
    const failures = body.getByTestId("chat-dbt-run-failures");
    await expect(failures.locator("li")).toHaveCount(1);
    await expect(failures).toContainText("rpt_region_rollup");
    await expect(failures).toContainText("does not exist");
    // The log opens by default when something failed.
    await expect(body.getByTestId("chat-dbt-run-log-toggle")).toHaveAttribute(
      "aria-expanded",
      "true",
    );
    // Folding by hand yields the same chip text as the strip will show.
    await frame.getByRole("button").first().click();
    await expect(card).toHaveAttribute("data-density", "compact");
    const chip = card.getByTestId("chat-tool-chip");
    await expect(chip).toContainText("12 ✓ 1 ✗");
    await expect(chip).toHaveAttribute("data-ok", "false");
  });

  test("end state: the follow-up group folds to chips and nothing is running", async ({
    page,
  }) => {
    await page.goto(at(24_800));
    await waitForHydration(page);
    await expect(page.locator('[data-testid="chat-tool-card"][data-density="running"]')).toHaveCount(0);
    await expect(page.getByTestId("chat-live-pill")).toHaveCount(0);

    const groups = page.getByTestId("chat-activity-group");
    await expect(groups).toHaveCount(3);
    const last = groups.last();
    await expect(last.locator(".chat-collapse").first()).toHaveAttribute(
      "data-open",
      "false",
    );
    const chips = strip(last).getByTestId("chat-tool-chip");
    await expect(chips).toHaveCount(5);
    const kinds = await chips.evaluateAll((nodes) =>
      nodes.map((node) => node.getAttribute("data-kind")),
    );
    // The failed dbt run leads; the rest follow kind priority.
    expect(kinds).toEqual(["dbt_run", "table_list", "column_profile", "knowledge", "json"]);
    const dbtChip = strip(last).locator('[data-testid="chat-tool-chip"][data-kind="dbt_run"]');
    await expect(dbtChip).toContainText("12 ✓ 1 ✗");
    await expect(dbtChip).toHaveAttribute("data-ok", "false");
    await expect(strip(last).locator('[data-kind="knowledge"]')).toContainText("3 docs");
    await expect(strip(last).locator('[data-kind="json"]')).toContainText("2 contacts");

    // The first group keeps its failed validation expanded even at rest.
    await expect(cardOfKind(groups.first(), "validation")).toHaveAttribute(
      "data-density",
      "expanded",
    );
    // Cards survive a reload of the same frame.
    await page.reload();
    await expect(strip(groups.last()).getByTestId("chat-tool-chip")).toHaveCount(5);
  });
});
