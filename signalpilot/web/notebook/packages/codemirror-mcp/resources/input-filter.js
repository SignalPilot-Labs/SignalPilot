import { EditorState, Transaction } from "@codemirror/state";
import { resourcesField } from "../state.js";
import { matchAllURIs } from "../utils.js";
/**
 * Check if cursor is at the end of a resource
 */
function getResourceAtCursor(state, pos) {
    const resources = state.field(resourcesField);
    const doc = state.doc;
    // Look at the entire line to find all resources
    const line = doc.lineAt(pos);
    const lineText = doc.sliceString(line.from, line.to);
    // Find all resources in the line
    const matches = Array.from(matchAllURIs(lineText));
    if (matches.length === 0)
        return null;
    // Look for a resource that ends exactly at the cursor position
    for (const match of matches) {
        const resourceStart = line.from + match.index;
        const resourceEnd = resourceStart + match[0].length;
        const uri = match[0].slice(1); // Remove @ prefix
        // Check if cursor is at the end of this resource and resource exists
        if (pos === resourceEnd && resources.has(uri)) {
            return { from: resourceStart, to: resourceEnd, uri };
        }
    }
    return null;
}
/**
 * Check if cursor is at the beginning of a resource
 */
function getResourceAfterCursor(state, pos) {
    const resources = state.field(resourcesField);
    const doc = state.doc;
    // Look forward from cursor to find resource
    const lineEnd = doc.lineAt(pos).to;
    const textAfter = doc.sliceString(pos, lineEnd);
    // Find resource starting at cursor position
    const matches = Array.from(matchAllURIs(textAfter));
    if (matches.length === 0)
        return null;
    const firstMatch = matches[0];
    if (!firstMatch)
        return null;
    if (firstMatch.index !== 0)
        return null; // Resource must start at cursor
    const resourceStart = pos;
    const resourceEnd = pos + firstMatch[0].length;
    const uri = firstMatch[0].slice(1); // Remove @ prefix
    // Check if resource exists
    if (resources.has(uri)) {
        return { from: resourceStart, to: resourceEnd, uri };
    }
    return null;
}
/**
 * Get all resources in the document and find which one contains the cursor position
 */
function getResourceAtPosition(state, pos) {
    const resources = state.field(resourcesField);
    const doc = state.doc;
    // Search around the cursor position for resources
    const line = doc.lineAt(pos);
    const lineText = doc.sliceString(line.from, line.to);
    const matches = Array.from(matchAllURIs(lineText));
    for (const match of matches) {
        const resourceStart = line.from + match.index;
        const resourceEnd = resourceStart + match[0].length;
        const uri = match[0].slice(1); // Remove @ prefix
        // Check if cursor is within this resource (not at boundaries) and it exists
        if (pos > resourceStart && pos < resourceEnd && resources.has(uri)) {
            return { from: resourceStart, to: resourceEnd, uri };
        }
    }
    return null;
}
/**
 * Find the next resource boundary when moving left
 */
function getResourceBoundaryLeft(state, pos) {
    const resources = state.field(resourcesField);
    const doc = state.doc;
    const line = doc.lineAt(pos);
    const lineText = doc.sliceString(line.from, pos);
    const matches = Array.from(matchAllURIs(lineText));
    // Find the rightmost resource that ends before or at cursor position
    let bestBoundary = null;
    for (const match of matches) {
        const resourceStart = line.from + match.index;
        const resourceEnd = resourceStart + match[0].length;
        const uri = match[0].slice(1);
        if (resources.has(uri) && resourceEnd <= pos) {
            if (pos > resourceEnd) {
                // Cursor is after resource - jump to end of resource
                bestBoundary = resourceEnd;
            }
            else if (pos === resourceEnd) {
                // Cursor is at end of resource - jump to start of resource
                bestBoundary = resourceStart;
            }
        }
    }
    return bestBoundary;
}
/**
 * Find the next resource boundary when moving right
 */
function getResourceBoundaryRight(state, pos) {
    const resources = state.field(resourcesField);
    const doc = state.doc;
    const line = doc.lineAt(pos);
    const lineText = doc.sliceString(line.from, line.to);
    const matches = Array.from(matchAllURIs(lineText));
    // Find the leftmost resource that starts at or after cursor position
    for (const match of matches) {
        const resourceStart = line.from + match.index;
        const resourceEnd = resourceStart + match[0].length;
        const uri = match[0].slice(1);
        if (resources.has(uri) && resourceStart >= pos) {
            if (pos < resourceStart) {
                // Cursor is before resource - jump to start of resource
                return resourceStart;
            }
            if (pos === resourceStart) {
                // Cursor is at start of resource - jump to end of resource
                return resourceEnd;
            }
        }
    }
    return null;
}
export const resourceInputFilter = EditorState.transactionFilter.of((tr) => {
    const userEvent = tr.annotation(Transaction.userEvent);
    if (!userEvent)
        return tr;
    const sel = tr.startState.selection.main;
    if (!sel.empty)
        return tr;
    // Handle text insertion near resources
    if (userEvent === "input.type" || userEvent.startsWith("input")) {
        // Check if we're inserting text
        if (tr.changes.empty)
            return tr;
        const resources = tr.startState.field(resourcesField);
        const doc = tr.startState.doc;
        let modifiedChanges = false;
        let cursorAdjustment = 0;
        const newChanges = [];
        tr.changes.iterChanges((fromA, toA, _fromB, _toB, inserted) => {
            const insertedText = inserted.toString();
            const insertPos = fromA;
            // Skip if inserting whitespace
            if (/^\s+$/.test(insertedText)) {
                newChanges.push({ from: fromA, to: toA, insert: insertedText });
                return;
            }
            // Find resources around the insertion point
            const line = doc.lineAt(insertPos);
            const lineText = doc.sliceString(line.from, line.to);
            const matches = Array.from(matchAllURIs(lineText));
            let needsSpaceBefore = false;
            let needsSpaceAfter = false;
            for (const match of matches) {
                const resourceStart = line.from + match.index;
                const resourceEnd = resourceStart + match[0].length;
                const uri = match[0].slice(1);
                if (resources.has(uri)) {
                    // Check if inserting directly before a resource
                    if (insertPos === resourceStart) {
                        // Check if there's no whitespace before the insertion point
                        const charBefore = insertPos > 0 ? doc.sliceString(insertPos - 1, insertPos) : "";
                        if (charBefore !== "" &&
                            charBefore !== " " &&
                            charBefore !== "\n" &&
                            charBefore !== "\t") {
                            needsSpaceBefore = true;
                        }
                    }
                    // Check if inserting directly after a resource
                    if (insertPos === resourceEnd) {
                        // Check if there's no whitespace after the insertion point
                        const charAfter = insertPos < doc.length ? doc.sliceString(insertPos, insertPos + 1) : "";
                        if (charAfter === "" ||
                            (charAfter !== " " && charAfter !== "\n" && charAfter !== "\t")) {
                            needsSpaceAfter = true;
                        }
                    }
                }
            }
            // Build the final insertion text
            let finalText = insertedText;
            if (needsSpaceBefore) {
                finalText = ` ${finalText}`;
                cursorAdjustment += 1;
            }
            if (needsSpaceAfter) {
                finalText = ` ${finalText}`;
                cursorAdjustment += 1;
            }
            if (finalText !== insertedText) {
                modifiedChanges = true;
            }
            newChanges.push({ from: fromA, to: toA, insert: finalText });
        });
        if (modifiedChanges) {
            // Adjust cursor position if we added spaces
            const newSelection = tr.selection
                ? {
                    anchor: tr.selection.main.anchor + cursorAdjustment,
                    head: tr.selection.main.head + cursorAdjustment,
                }
                : undefined;
            return [
                {
                    changes: newChanges,
                    selection: newSelection,
                    scrollIntoView: tr.scrollIntoView,
                },
            ];
        }
    }
    // Handle deletion events
    if (userEvent === "delete.backward" || userEvent === "delete.forward") {
        let resource = null;
        if (userEvent === "delete.backward") {
            resource = getResourceAtCursor(tr.startState, sel.head);
        }
        else if (userEvent === "delete.forward") {
            resource = getResourceAfterCursor(tr.startState, sel.head);
        }
        if (!resource)
            return tr;
        // Replace the resource with nothing, keep cursor at start
        return [
            {
                changes: { from: resource.from, to: resource.to, insert: "" },
                selection: { anchor: resource.from },
                scrollIntoView: true,
            },
        ];
    }
    // Handle cursor movement events - check if it's a selection change with no selection
    // BUT only if it's not a text insertion (input events should be handled above)
    if (tr.selection?.main.empty &&
        sel.empty &&
        !userEvent.startsWith("input") &&
        userEvent !== "input.type") {
        // This is likely a cursor movement (arrow keys, mouse clicks, etc.)
        const oldPos = sel.head;
        const newPos = tr.selection.main.head;
        let targetPos = null;
        if (newPos < oldPos) {
            // Moving left
            const currentResource = getResourceAtPosition(tr.startState, oldPos);
            if (currentResource && oldPos > currentResource.from) {
                // If cursor was inside a resource, jump to the start
                targetPos = currentResource.from;
            }
            else {
                // Check for resource boundary to the left
                targetPos = getResourceBoundaryLeft(tr.startState, oldPos);
            }
        }
        else if (newPos > oldPos) {
            // Moving right
            const currentResource = getResourceAtPosition(tr.startState, oldPos);
            if (currentResource && oldPos < currentResource.to) {
                // If cursor was inside a resource, jump to the end
                targetPos = currentResource.to;
            }
            else {
                // Check for resource boundary to the right
                targetPos = getResourceBoundaryRight(tr.startState, oldPos);
            }
        }
        // If we found a target position, override the cursor movement
        if (targetPos !== null && targetPos !== newPos) {
            return [
                {
                    selection: { anchor: targetPos },
                    scrollIntoView: true,
                },
            ];
        }
    }
    return tr;
});
//# sourceMappingURL=input-filter.js.map