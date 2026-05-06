import { useState, useEffect, useRef } from "react";
import type { NotebookInfo } from "@/lib/types";
import { getNotebooks, searchNotebooks, batchAnalyzeNotebooks, batchDeleteNotebooks } from "@/lib/api";
import { invalidateNotebooks } from "@/lib/hooks/use-gateway-data";
import { useToast } from "@/components/ui/toast";

const DEFAULT_SORT_BY = "updated_at";
const DEFAULT_SORT_DIR = "desc";
const DEFAULT_STATUS_FILTER = "all";

interface NotebookListInput {
  notebooks: NotebookInfo[];
  total: number;
}

export interface UseNotebookListReturn {
  // Modal
  modalOpen: boolean;
  setModalOpen: (open: boolean) => void;

  // Search
  query: string;
  setQuery: (q: string) => void;
  isSearching: boolean;

  // Computed visible list
  filtered: NotebookInfo[];
  counterText: string;

  // Load more (regular)
  showLoadMore: boolean;
  loadingMore: boolean;
  allItemsCount: number;
  baseTotal: number;
  handleLoadMore: () => Promise<void>;

  // Load more (search)
  showSearchLoadMore: boolean;
  loadingMoreSearch: boolean;
  searchResultsCount: number;
  searchTotal: number;
  handleSearchLoadMore: () => Promise<void>;

  // Sort / filter
  sortBy: string;
  sortDir: string;
  statusFilter: string;
  handleSortByChange: (value: string) => void;
  handleSortDirChange: (value: string) => void;
  handleStatusFilterChange: (value: string) => void;

  // Multi-select
  selectedIds: Set<string>;
  allSelected: boolean;
  toggleSelect: (id: string) => void;
  selectAll: () => void;
  deselectAll: () => void;

  // Batch operations
  batchAnalyzing: boolean;
  batchDeleting: boolean;
  deleteConfirmOpen: boolean;
  setDeleteConfirmOpen: (open: boolean) => void;
  handleBatchAnalyze: () => Promise<void>;
  handleBatchDeleteRequest: () => void;
  handleBatchDeleteConfirm: () => Promise<void>;
}

export function useNotebookList({ notebooks, total }: NotebookListInput): UseNotebookListReturn {
  const { toast } = useToast();

  // ── State (18 useState calls) ────────────────────────────────────────────────
  const [modalOpen, setModalOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [searchResults, setSearchResults] = useState<NotebookInfo[] | null>(null);
  const [searchTotal, setSearchTotal] = useState(0);
  const [isSearching, setIsSearching] = useState(false);
  const [loadingMoreSearch, setLoadingMoreSearch] = useState(false);
  const [extra, setExtra] = useState<NotebookInfo[]>([]);
  const [page, setPage] = useState(0);
  const [loadingMore, setLoadingMore] = useState(false);
  const [sortBy, setSortBy] = useState(DEFAULT_SORT_BY);
  const [sortDir, setSortDir] = useState(DEFAULT_SORT_DIR);
  const [statusFilter, setStatusFilter] = useState(DEFAULT_STATUS_FILTER);
  const [fetchedItems, setFetchedItems] = useState<NotebookInfo[] | null>(null);
  const [fetchedTotal, setFetchedTotal] = useState(0);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [batchAnalyzing, setBatchAnalyzing] = useState(false);
  const [batchDeleting, setBatchDeleting] = useState(false);
  const [deleteConfirmOpen, setDeleteConfirmOpen] = useState(false);

  // Ref to detect stale search responses
  const latestQueryRef = useRef("");

  // ── Search / debounce effect ─────────────────────────────────────────────────
  useEffect(() => {
    const trimmed = query.trim();
    latestQueryRef.current = trimmed;

    if (!trimmed) {
      setSearchResults(null);
      setSearchTotal(0);
      setIsSearching(false);
      // Reset pagination when search is cleared
      setExtra([]);
      setPage(0);
      // Clear selection when search query changes (prevents stale counts)
      setSelectedIds(new Set());

      // Search-clear edge case: if sort/filter differ from defaults, the SSR
      // prop reflects the server's default ordering — we need a fresh fetch.
      const nonDefault =
        sortBy !== DEFAULT_SORT_BY ||
        sortDir !== DEFAULT_SORT_DIR ||
        statusFilter !== DEFAULT_STATUS_FILTER;

      if (nonDefault) {
        let cancelled = false;
        (async () => {
          try {
            const response = await getNotebooks(50, 0, sortBy, sortDir, statusFilter);
            if (!cancelled) {
              setFetchedItems(response.items);
              setFetchedTotal(response.total);
            }
          } catch {
            if (!cancelled) {
              setFetchedItems(null);
            }
          }
        })();
        return () => { cancelled = true; };
      } else {
        // Back to defaults — fall through to SSR prop
        setFetchedItems(null);
        setFetchedTotal(0);
      }
      return;
    }

    setIsSearching(true);
    // Reset search state when query changes (avoid stale "X of Y")
    setSearchResults(null);
    setSearchTotal(0);
    setExtra([]);
    setPage(0);
    // Clear selection when search query changes
    setSelectedIds(new Set());

    const timer = setTimeout(async () => {
      const q = latestQueryRef.current;
      try {
        const response = await searchNotebooks(q, 50, 0, sortBy, sortDir, statusFilter);
        if (latestQueryRef.current === q) {
          setSearchResults(response.items);
          setSearchTotal(response.total);
        }
      } catch {
        if (latestQueryRef.current === q) {
          setSearchResults(null);
          setSearchTotal(0);
        }
      } finally {
        if (latestQueryRef.current === q) {
          setIsSearching(false);
        }
      }
    }, 300);

    return () => {
      clearTimeout(timer);
    };
  }, [query, sortBy, sortDir, statusFilter]);

  // ── Sort/filter helpers ──────────────────────────────────────────────────────
  function resetList() {
    setExtra([]);
    setPage(0);
    setSelectedIds(new Set());
  }

  function handleSortByChange(value: string) {
    setSortBy(value);
    resetList();
  }

  function handleSortDirChange(value: string) {
    setSortDir(value);
    resetList();
  }

  function handleStatusFilterChange(value: string) {
    setStatusFilter(value);
    resetList();
  }

  // ── Computed list values ─────────────────────────────────────────────────────
  const baseItems = fetchedItems !== null ? fetchedItems : notebooks;
  const baseTotal = fetchedItems !== null ? fetchedTotal : total;
  const allItems = [...baseItems, ...extra];

  const isServerSearch = searchResults !== null;
  // Whether we are currently in search mode (server or local filter)
  const isInSearchMode = isServerSearch || query.trim().length > 0;

  const filtered = isServerSearch
    ? searchResults
    : query.trim()
      ? allItems.filter((nb) => {
          const q = query.toLowerCase();
          return (
            nb.name.toLowerCase().includes(q) ||
            nb.tags.some((t) => t.toLowerCase().includes(q))
          );
        })
      : allItems;

  const counterText = isServerSearch
    ? `${filtered.length} result${filtered.length !== 1 ? "s" : ""}`
    : `${filtered.length} of ${baseTotal} notebook${baseTotal !== 1 ? "s" : ""}`;

  // ── Selection helpers ────────────────────────────────────────────────────────
  function toggleSelect(id: string) {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  }

  function selectAll() {
    setSelectedIds(new Set(filtered.map((nb) => nb.id)));
  }

  function deselectAll() {
    setSelectedIds(new Set());
  }

  const allSelected = filtered.length > 0 && filtered.every((nb) => selectedIds.has(nb.id));

  // ── Load more ────────────────────────────────────────────────────────────────
  const showLoadMore = !isInSearchMode && allItems.length < baseTotal;
  const showSearchLoadMore = isServerSearch && searchResults !== null && searchResults.length < searchTotal;

  async function handleLoadMore() {
    setLoadingMore(true);
    try {
      const nextPage = page + 1;
      const response = await getNotebooks(50, nextPage * 50, sortBy, sortDir, statusFilter);
      setExtra((prev) => [...prev, ...response.items]);
      setPage(nextPage);
    } catch {
      // Load more failing silently is acceptable — user can retry
    } finally {
      setLoadingMore(false);
    }
  }

  async function handleSearchLoadMore() {
    if (!searchResults) return;
    setLoadingMoreSearch(true);
    try {
      const trimmed = query.trim();
      const nextOffset = searchResults.length;
      const response = await searchNotebooks(trimmed, 50, nextOffset, sortBy, sortDir, statusFilter);
      if (latestQueryRef.current === trimmed) {
        setSearchResults((prev) => [...(prev ?? []), ...response.items]);
        setSearchTotal(response.total);
      }
    } catch {
      // Load more failing silently is acceptable — user can retry
    } finally {
      setLoadingMoreSearch(false);
    }
  }

  // ── Batch operations ─────────────────────────────────────────────────────────
  async function handleBatchAnalyze() {
    if (selectedIds.size === 0) return;
    setBatchAnalyzing(true);
    try {
      const result = await batchAnalyzeNotebooks([...selectedIds]);
      await invalidateNotebooks();
      setSelectedIds(new Set());
      const msg =
        result.failed > 0
          ? `Analyzed: ${result.succeeded} succeeded, ${result.failed} failed`
          : `Analyzed ${result.succeeded} notebook${result.succeeded !== 1 ? "s" : ""}`;
      toast(msg, result.failed > 0 ? "error" : "success");
    } catch (err) {
      toast(err instanceof Error ? err.message : "Batch analyze failed", "error");
    } finally {
      setBatchAnalyzing(false);
    }
  }

  function handleBatchDeleteRequest() {
    setDeleteConfirmOpen(true);
  }

  async function handleBatchDeleteConfirm() {
    setDeleteConfirmOpen(false);
    if (selectedIds.size === 0) return;
    setBatchDeleting(true);
    try {
      const result = await batchDeleteNotebooks([...selectedIds]);
      await invalidateNotebooks();
      setSelectedIds(new Set());
      const msg =
        result.failed > 0
          ? `Deleted: ${result.succeeded} succeeded, ${result.failed} failed`
          : `Deleted ${result.succeeded} notebook${result.succeeded !== 1 ? "s" : ""}`;
      toast(msg, result.failed > 0 ? "error" : "success");
    } catch (err) {
      toast(err instanceof Error ? err.message : "Batch delete failed", "error");
    } finally {
      setBatchDeleting(false);
    }
  }

  return {
    // Modal
    modalOpen,
    setModalOpen,

    // Search
    query,
    setQuery,
    isSearching,

    // Computed list
    filtered,
    counterText,

    // Load more (regular)
    showLoadMore,
    loadingMore,
    allItemsCount: allItems.length,
    baseTotal,
    handleLoadMore,

    // Load more (search)
    showSearchLoadMore,
    loadingMoreSearch,
    searchResultsCount: searchResults?.length ?? 0,
    searchTotal,
    handleSearchLoadMore,

    // Sort / filter
    sortBy,
    sortDir,
    statusFilter,
    handleSortByChange,
    handleSortDirChange,
    handleStatusFilterChange,

    // Multi-select
    selectedIds,
    allSelected,
    toggleSelect,
    selectAll,
    deselectAll,

    // Batch operations
    batchAnalyzing,
    batchDeleting,
    deleteConfirmOpen,
    setDeleteConfirmOpen,
    handleBatchAnalyze,
    handleBatchDeleteRequest,
    handleBatchDeleteConfirm,
  };
}
