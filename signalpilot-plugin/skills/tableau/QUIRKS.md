# Tableau quirks

Known problems and their fixes. Most are handled by `twb_build.py` and its
design layer. Read this when a publish or a render fails, or when you edit
workbook XML by hand.

## Publish and data sources

| You see | Cause | Do this |
|---|---|---|
| `Cannot publish with standalone extract file` | The file has an `<extract>` | `twb_retarget.py --strip-extracts` |
| `Datasource '<x>' not found for workbook` | The workbook uses a published data source that is not on this site | Publish it first, or point the reference at another one (`--published OLD=NEW`) |
| "Sign in to reconnect" in the browser, or a render error "data sources not connected" | A database connection without a saved password, or copied connection XML from another site | Publish with `tableau_publish_workbook` (it adds the passwords). Remove `saved-credentials-viewerid` attributes. |
| The `content_url` of a new data source has a number at the end | The name was used before and deleted | Use the `content_url` from the publish response |
| `Incorrect syntax near 'WITH'` in a custom SQL data source | Tableau puts custom SQL inside a subquery | Do not use CTEs. Use nested SELECTs. |
| "API usage limit reached" (429) | Too many data source metadata or query calls | Wait. Read column names from the warehouse instead. |
| Google Drive or Excel sources | Tableau Cloud cannot reach the user's files | Use a warehouse table or dbt seed with the same columns, or tell the user |

## Build and render

| You see | Cause | Do this |
|---|---|---|
| The whole dashboard is blank | Objects nested inside the root zone | Use `rows` in the dashboard spec (floating layout) |
| `####` in a card | The card is too short for its lines | Make the row taller (150 to 160 for 4 lines) |
| "cannot aggregate an aggregate" | A calculation over other aggregate calculations | The builder handles it. If you edit XML, the instance must be `usr:` with `derivation='User'` |
| Table columns in alphabetical order | Measure Names sorts by name | The builder adds a manual sort. Keep `columns` in reading order. |
| Default blue bars where you set status colors | A color map on an aggregate text field does not apply | Use `status_bars` (one measure per band) |
| A panel shows rows with no value (for example no plan) | Filters cannot remove aggregate nulls | `status_bars` removes them. By hand: `<filter class='quantitative' … included-values='non-null'/>` |
| Rotated month labels | Narrow columns | Use `mname(date)` |
| A line is flat at the top of the chart | The axis starts at zero | `range` on the combo |
| Numbers touch the ▲ change | Spaces at the start or end of a label part are removed | The card component adds an em space |
| "worksheet does not have a valid data source" | `Parameters` listed before the main data source in a sheet | The builder handles it. By hand: main data source first. |
| A calc name exists on two data sources and the sheet shows no data | You used the calc from the wrong data source | Name each calc once per data source. Check which data source the sheet uses. |

## Tableau Cloud limits

- No CSS. Style comes only from workbook format rules and zone styles.
- Fonts: use Tableau Book and Tableau Semibold. Other fonts change on the server.
- Rounded corners on zones work (`corner-radius`).
- Web page objects and extensions do not show in rendered images.
