import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ArrowRight, Search, X } from "lucide-react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import type { PwaSearchResponse, PwaSearchResult } from "../api/types";

type SearchResultType = PwaSearchResult["type"];

const typeLabels: Record<SearchResultType, string> = {
  booking: "Bookings",
  customer: "Customers",
  calendar: "Calendars",
  staff: "Staff",
  payment: "Payments",
  waiver: "Waivers",
  note: "Notes",
};

export function GlobalSearch({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [query, setQuery] = useState("");
  const [debouncedQuery, setDebouncedQuery] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!open) {
      setDebouncedQuery("");
      return;
    }

    const timeout = window.setTimeout(() => {
      setDebouncedQuery(query.trim());
    }, 220);

    return () => window.clearTimeout(timeout);
  }, [open, query]);

  useEffect(() => {
    if (!open) return;

    inputRef.current?.focus();
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };

    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [open, onClose]);

  const canSearch = open && query.trim().length >= 2 && debouncedQuery.length >= 2;
  const isDebouncing = open && query.trim().length >= 2 && query.trim() !== debouncedQuery;

  const { data, error, isFetching } = useQuery({
    queryKey: ["global-search", debouncedQuery],
    queryFn: () =>
      api<PwaSearchResponse>(`/pwa/search?q=${encodeURIComponent(debouncedQuery)}&limit=6`),
    enabled: canSearch,
  });

  const groupedResults = useMemo(() => {
    const groups: Partial<Record<SearchResultType, PwaSearchResult[]>> = {};
    for (const result of data?.results ?? []) {
      (groups[result.type] ??= []).push(result);
    }
    return Object.entries(groups) as [SearchResultType, PwaSearchResult[]][];
  }, [data?.results]);

  if (!open) return null;

  const showMinimumQuery = query.trim().length < 2;

  return (
    <div
      className="global-search-overlay"
      role="presentation"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <section
        className="global-search-dialog"
        role="dialog"
        aria-modal="true"
        aria-label="Global search"
      >
        <div className="global-search-head">
          <div className="global-search-input-wrap">
            <Search size={18} aria-hidden="true" />
            <input
              ref={inputRef}
              className="global-search-input"
              type="search"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Search bookings, customers, staff..."
              aria-label="Search"
              autoComplete="off"
            />
          </div>
          <button type="button" className="icon-button" onClick={onClose} aria-label="Close search">
            <X size={18} aria-hidden="true" />
          </button>
        </div>

        <div className="global-search-results" aria-live="polite">
          {showMinimumQuery ? (
            <p className="global-search-empty">Type at least 2 characters to search.</p>
          ) : isDebouncing || isFetching ? (
            <p className="global-search-empty">Searching...</p>
          ) : error ? (
            <p className="global-search-empty" role="alert">
              Unable to search right now. Please try again.
            </p>
          ) : groupedResults.length === 0 ? (
            <p className="global-search-empty">No results found.</p>
          ) : (
            groupedResults.map(([type, results]) => (
              <section className="global-search-group" key={type}>
                <h3>{typeLabels[type]}</h3>
                {results.map((result) => (
                  <Link
                    className="global-search-result"
                    to={result.href}
                    key={`${result.type}-${result.id}`}
                    onClick={onClose}
                  >
                    <span>
                      <strong>{result.title}</strong>
                      {result.subtitle && <small>{result.subtitle}</small>}
                      {result.status && <small>{result.status}</small>}
                    </span>
                    <ArrowRight size={16} aria-hidden="true" />
                  </Link>
                ))}
              </section>
            ))
          )}
        </div>
      </section>
    </div>
  );
}
