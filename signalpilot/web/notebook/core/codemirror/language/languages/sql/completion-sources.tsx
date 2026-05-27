import type { Completion, CompletionSource } from "@codemirror/autocomplete";
import {
  keywordCompletionSource,
  schemaCompletionSource,
} from "@codemirror/lang-sql";
import type { EditorState } from "@codemirror/state";
import { DefaultSqlTooltipRenders } from "@/packages/codemirror-sql";
import type { SqlKeywordInfo } from "@/packages/codemirror-sql/sql/hover";
import * as commonKeywordsJson from "@/packages/codemirror-sql/data/common-keywords.json";
import * as duckdbKeywordsJson from "@/packages/codemirror-sql/data/duckdb-keywords.json";
import { languageMetadataField } from "../../metadata";
import { SCHEMA_CACHE } from "./completion-store";
import type { SQLLanguageAdapterMetadata } from "./sql";

// Merged keyword docs map — common SQL keywords plus DuckDB-specific keywords.
// Include DuckDB for now, but we can remove this once we have a better way to handle dialect-specific keywords
const KEYWORD_DOCS: Record<string, SqlKeywordInfo> = {
  ...commonKeywordsJson.keywords,
  ...duckdbKeywordsJson.keywords,
};

function getSQLMetadata(state: EditorState): SQLLanguageAdapterMetadata {
  return state.field(languageMetadataField) as SQLLanguageAdapterMetadata;
}

/**
 * Custom schema completion source that dynamically gets the Dialect and SQL tables.
 */
export function tablesCompletionSource(): CompletionSource {
  return (ctx) => {
    const metadata = getSQLMetadata(ctx.state);
    const connectionName = metadata.engine;
    const config = SCHEMA_CACHE.getCompletionSource(connectionName);

    if (!config) {
      return null;
    }

    const completions = schemaCompletionSource(config)(ctx);
    if (!completions) {
      return null;
    }

    return completions;
  };
}

/**
 * Custom keyword completion source that dynamically gets the Dialect.
 * This also ignores keyword completions on table columns.
 */
export function customKeywordCompletionSource(): CompletionSource {
  return (ctx) => {
    const metadata = getSQLMetadata(ctx.state);
    const connectionName = metadata.engine;
    const dialect = SCHEMA_CACHE.getDialect(connectionName);

    // We want to ignore keyword completions on something like
    // `WHERE my_table.col`
    //                    ^cursor
    const textBefore = ctx.matchBefore(/\.\w*/);
    if (textBefore) {
      // If there is a match, we are typing after a dot,
      // so we don't want to trigger SQL keyword completion
      return null;
    }

    const keywordRenderer = (label: string, type: string): Completion => {
      return {
        label,
        type,
        info: () => {
          const keywordInfo = KEYWORD_DOCS[label.toLocaleLowerCase()];
          if (!keywordInfo) {
            return null;
          }

          const dom = document.createElement("div");
          dom.innerHTML = DefaultSqlTooltipRenders.keyword({
            keyword: label,
            info: keywordInfo,
          });
          return dom;
        },
      };
    };

    const uppercaseKeywords = true;
    const result = keywordCompletionSource(
      dialect,
      uppercaseKeywords,
      keywordRenderer,
    )(ctx);
    return result;
  };
}
