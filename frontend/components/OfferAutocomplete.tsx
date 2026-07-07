"use client";

import { Loader2, Search } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { OfferSearchItem, apiRequest, errorMessage } from "@/lib/api";

type Props = {
  value: OfferSearchItem | null;
  onSelect: (offer: OfferSearchItem | null) => void;
  disabled?: boolean;
  placeholder?: string;
};

export function OfferAutocomplete({ value, onSelect, disabled = false, placeholder = "Search offer" }: Props) {
  const [query, setQuery] = useState(value ? `${value.id} ${value.name}` : "");
  const [items, setItems] = useState<OfferSearchItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const skipNextValueSync = useRef(false);

  useEffect(() => {
    if (skipNextValueSync.current) {
      skipNextValueSync.current = false;
      return;
    }
    setQuery(value ? `${value.id} ${value.name}` : "");
  }, [value]);

  useEffect(() => {
    const trimmed = query.trim();
    abortRef.current?.abort();
    setError(null);

    if (trimmed.length < 1 || (value && trimmed === `${value.id} ${value.name}`)) {
      setItems([]);
      setLoading(false);
      return;
    }

    const controller = new AbortController();
    abortRef.current = controller;
    const timer = window.setTimeout(async () => {
      setLoading(true);
      try {
        const data = await apiRequest<{ items: OfferSearchItem[] }>(
          `/api/offers/search?q=${encodeURIComponent(trimmed)}&limit=20`,
          { signal: controller.signal }
        );
        setItems(data.items);
        setOpen(true);
      } catch (requestError) {
        if (!controller.signal.aborted) {
          setError(errorMessage(requestError));
        }
      } finally {
        if (!controller.signal.aborted) {
          setLoading(false);
        }
      }
    }, 350);

    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [query, value]);

  return (
    <div className="autocomplete">
      <div style={{ position: "relative" }}>
        <input
          className="input"
          value={query}
          disabled={disabled}
          placeholder={placeholder}
          onChange={(event) => {
            if (value) {
              skipNextValueSync.current = true;
              onSelect(null);
            }
            setQuery(event.target.value);
            setOpen(true);
          }}
          onFocus={() => setOpen(true)}
        />
        <span style={{ position: "absolute", right: 10, top: 10, color: "var(--muted)" }}>
          {loading ? <Loader2 size={18} className="loading-icon" /> : <Search size={18} />}
        </span>
      </div>

      {error ? <div className="message message-error" style={{ marginTop: 8 }}>{error}</div> : null}

      {open && items.length > 0 ? (
        <div className="autocomplete-menu">
          {items.map((offer) => (
            <button
              className="autocomplete-option"
              key={offer.id}
              type="button"
              onClick={() => {
                onSelect(offer);
                setQuery(`${offer.id} ${offer.name}`);
                setOpen(false);
                setItems([]);
              }}
            >
              <span className="option-title">[{offer.id}] {offer.name}</span>
              <span className="option-meta">
                {[offer.country, offer.state, offer.affiliate_network].filter(Boolean).join(" / ")}
              </span>
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}
