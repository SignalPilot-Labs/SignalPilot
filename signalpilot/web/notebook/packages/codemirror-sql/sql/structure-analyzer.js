/**
 * Analyzes SQL documents to extract statement boundaries and information
 * for use with gutter markers and other SQL-aware features.
 */
export class SqlStructureAnalyzer {
    parser;
    cache = new Map();
    MAX_CACHE_SIZE = 10;
    constructor(parser) {
        this.parser = parser;
    }
    /**
     * Analyzes the document and extracts all SQL statements
     */
    async analyzeDocument(state) {
        const content = state.doc.toString();
        const cacheKey = this.generateCacheKey(content);
        // Check cache
        const cached = this.cache.get(cacheKey);
        if (cached) {
            return cached;
        }
        const statements = await this.extractStatements(content, state);
        this.cache.set(cacheKey, statements);
        // Keep cache size reasonable
        if (this.cache.size > this.MAX_CACHE_SIZE) {
            const firstKey = this.cache.keys().next().value;
            if (firstKey !== undefined) {
                this.cache.delete(firstKey);
            }
        }
        return statements;
    }
    /**
     * Gets the SQL statement at a specific cursor position
     */
    async getStatementAtPosition(state, position) {
        const statements = await this.analyzeDocument(state);
        return statements.find((stmt) => position >= stmt.from && position <= stmt.to) || null;
    }
    /**
     * Gets all SQL statements that intersect with a selection range
     */
    async getStatementsInRange(state, from, to) {
        const statements = await this.analyzeDocument(state);
        return statements.filter((stmt) => stmt.from <= to && stmt.to >= from);
    }
    async extractStatements(content, state) {
        const statements = [];
        // Split content by semicolons to find potential statement boundaries
        const parts = this.splitByStatementSeparators(content);
        let currentPosition = 0;
        for (const part of parts) {
            const trimmedPart = part.trim();
            if (trimmedPart.length === 0) {
                currentPosition += part.length;
                continue;
            }
            const from = currentPosition + part.indexOf(trimmedPart);
            const to = from + trimmedPart.length;
            const fromLine = state.doc.lineAt(from);
            const toLine = state.doc.lineAt(to);
            // Strip comments from the statement content
            const strippedContent = this.stripComments(trimmedPart);
            // Skip if the statement is empty after stripping comments
            if (strippedContent.trim().length === 0 || strippedContent.trim() === ";") {
                currentPosition += part.length;
                continue;
            }
            // Parse the statement to determine validity and type (use stripped content)
            const parseResult = await this.parser.parse(strippedContent, { state });
            const type = this.determineStatementType(strippedContent);
            // Remove trailing semicolon from content for cleaner display
            const cleanContent = strippedContent.endsWith(";")
                ? strippedContent.slice(0, -1).trim()
                : strippedContent.trim();
            statements.push({
                from,
                to,
                lineFrom: fromLine.number,
                lineTo: toLine.number,
                content: cleanContent,
                type,
                isValid: parseResult.success,
            });
            currentPosition += part.length;
        }
        return statements;
    }
    splitByStatementSeparators(content) {
        // More sophisticated splitting that handles semicolons in strings and comments
        const parts = [];
        let current = "";
        let inString = false;
        let stringChar = "";
        let inSingleLineComment = false;
        let inMultiLineComment = false;
        let i = 0;
        while (i < content.length) {
            const char = content[i];
            const nextChar = content[i + 1];
            // Handle single-line comments (-- comment)
            if (!inString && !inMultiLineComment && char === "-" && nextChar === "-") {
                inSingleLineComment = true;
                current += char + nextChar;
                i += 2;
                continue;
            }
            // Handle multi-line comments (/* comment */)
            if (!inString && !inSingleLineComment && char === "/" && nextChar === "*") {
                inMultiLineComment = true;
                current += char + nextChar;
                i += 2;
                continue;
            }
            // End multi-line comment
            if (inMultiLineComment && char === "*" && nextChar === "/") {
                inMultiLineComment = false;
                current += char + nextChar;
                i += 2;
                continue;
            }
            // End single-line comment on newline
            if (inSingleLineComment && (char === "\n" || char === "\r")) {
                inSingleLineComment = false;
                current += char;
                i++;
                continue;
            }
            // Include characters inside comments (for proper position tracking)
            if (inSingleLineComment || inMultiLineComment) {
                current += char;
                i++;
                continue;
            }
            // Handle string literals
            if (!inString && (char === "'" || char === '"' || char === "`")) {
                inString = true;
                stringChar = char;
                current += char;
            }
            else if (inString && char === stringChar) {
                // Check for escaped quotes
                if (nextChar === stringChar) {
                    current += char + nextChar;
                    i += 2;
                    continue;
                }
                inString = false;
                stringChar = "";
                current += char;
            }
            else if (!inString && char === ";") {
                current += char;
                parts.push(current);
                current = "";
            }
            else {
                current += char;
            }
            i++;
        }
        if (current.trim()) {
            parts.push(current);
        }
        return parts;
    }
    determineStatementType(sql) {
        const trimmed = sql.trim().toLowerCase();
        if (trimmed.startsWith("select"))
            return "select";
        if (trimmed.startsWith("insert"))
            return "insert";
        if (trimmed.startsWith("update"))
            return "update";
        if (trimmed.startsWith("delete"))
            return "delete";
        if (trimmed.startsWith("create"))
            return "create";
        if (trimmed.startsWith("drop"))
            return "drop";
        if (trimmed.startsWith("alter"))
            return "alter";
        if (trimmed.startsWith("use"))
            return "use";
        return "other";
    }
    stripComments(sql) {
        let result = "";
        let inString = false;
        let stringChar = "";
        let inSingleLineComment = false;
        let inMultiLineComment = false;
        let i = 0;
        while (i < sql.length) {
            const char = sql[i];
            const nextChar = sql[i + 1];
            // Handle single-line comments (-- comment)
            if (!inString && !inMultiLineComment && char === "-" && nextChar === "-") {
                inSingleLineComment = true;
                i += 2;
                continue;
            }
            // Handle multi-line comments (/* comment */)
            if (!inString && !inSingleLineComment && char === "/" && nextChar === "*") {
                inMultiLineComment = true;
                i += 2;
                continue;
            }
            // End multi-line comment
            if (inMultiLineComment && char === "*" && nextChar === "/") {
                inMultiLineComment = false;
                i += 2;
                continue;
            }
            // End single-line comment on newline
            if (inSingleLineComment && (char === "\n" || char === "\r")) {
                inSingleLineComment = false;
                result += char;
                i++;
                continue;
            }
            // Skip characters inside comments
            if (inSingleLineComment || inMultiLineComment) {
                i++;
                continue;
            }
            // Handle string literals
            if (!inString && (char === "'" || char === '"' || char === "`")) {
                inString = true;
                stringChar = char;
                result += char;
            }
            else if (inString && char === stringChar) {
                // Check for escaped quotes
                if (nextChar === stringChar) {
                    result += char + nextChar;
                    i += 2;
                    continue;
                }
                inString = false;
                stringChar = "";
                result += char;
            }
            else {
                result += char;
            }
            i++;
        }
        return result;
    }
    generateCacheKey(content) {
        // Simple hash function for caching
        let hash = 0;
        for (let i = 0; i < content.length; i++) {
            const char = content.charCodeAt(i);
            hash = (hash << 5) - hash + char;
            hash = hash & hash; // Convert to 32-bit integer
        }
        return hash.toString();
    }
    /**
     * Clears the internal cache
     */
    clearCache() {
        this.cache.clear();
    }
}
//# sourceMappingURL=structure-analyzer.js.map