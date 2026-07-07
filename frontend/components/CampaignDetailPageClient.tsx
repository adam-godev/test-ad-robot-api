"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { BarChart3, ChevronDown, ExternalLink, Loader2, Pin, Plus, RefreshCw, Trash2 } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { OfferAutocomplete } from "@/components/OfferAutocomplete";
import {
  CampaignDetail,
  CampaignFlow,
  CampaignOffer,
  OfferSearchItem,
  OffersUpdateResponse,
  apiRequest,
  errorMessage
} from "@/lib/api";

const pendingOfferActions = new Set(["add", "remove", "restore"]);
const inactiveOfferActions = new Set(["remove", "removed"]);

export default function CampaignPage() {
  const params = useParams<{ id: string }>();
  const campaignId = params.id;
  const [campaign, setCampaign] = useState<CampaignDetail | null>(null);
  const [selectedOffers, setSelectedOffers] = useState<Record<number, OfferSearchItem | null>>({});
  const [loading, setLoading] = useState(true);
  const [working, setWorking] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function loadCampaign({ refresh }: { refresh: boolean }) {
    const path = refresh ? `/api/campaigns/${campaignId}?refresh=true` : `/api/campaigns/${campaignId}?refresh=false`;
    const nextCampaign = await apiRequest<CampaignDetail>(path);
    setCampaign(nextCampaign);
    return nextCampaign;
  }

  async function refreshCampaign(refresh: boolean) {
    setLoading(true);
    setError(null);
    try {
      await loadCampaign({ refresh });
    } catch (requestError) {
      setError(errorMessage(requestError));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void refreshCampaign(false);
  }, [campaignId]);

  const streamCount = campaign?.flows.length ?? 0;
  const offerCount = useMemo(
    () => campaign?.flows.reduce((total, flow) => total + activeOfferCount(flow.offers), 0) ?? 0,
    [campaign]
  );
  function setFlowOffer(flowId: number, offer: OfferSearchItem | null) {
    setSelectedOffers((current) => ({ ...current, [flowId]: offer }));
  }

  function applyOffersUpdate(update: OffersUpdateResponse) {
    setCampaign((current) => {
      if (!current) {
        return current;
      }
      const nextCampaign = {
        ...current,
        flows: current.flows.map((flow) =>
          flow.id === update.flow_id
            ? {
                ...flow,
                offers: update.offers,
                has_pending_changes: update.offers.some((offer) => pendingOfferActions.has(offer.pending_action ?? ""))
              }
            : flow
        )
      };
      return nextCampaign;
    });
  }

  async function mutate(action: () => Promise<unknown>, after?: (result: unknown) => Promise<void> | void) {
    setWorking(true);
    setError(null);
    try {
      const result = await action();
      await after?.(result);
    } catch (requestError) {
      setError(errorMessage(requestError));
    } finally {
      setWorking(false);
    }
  }

  async function fetchFromKt() {
    await mutate(() => loadCampaign({ refresh: true }));
  }

  async function addOffer(flowId: number) {
    const offer = selectedOffers[flowId];
    if (!offer) {
      return;
    }
    await mutate(
      () => apiRequest<OffersUpdateResponse>(`/api/campaigns/${campaignId}/streams/${flowId}/offers`, {
        method: "POST",
        body: JSON.stringify({ offer_id: offer.id, name: offer.name })
      }),
      (result) => {
        applyOffersUpdate(result as OffersUpdateResponse);
        setFlowOffer(flowId, null);
      }
    );
  }

  async function removeOffer(flowId: number, offerId: number) {
    await mutate(
      () =>
        apiRequest<OffersUpdateResponse>(`/api/campaigns/${campaignId}/streams/${flowId}/offers/${offerId}/stage-remove`, {
          method: "POST"
        }),
      (result) => applyOffersUpdate(result as OffersUpdateResponse)
    );
  }

  async function restoreOffer(flowId: number, offerId: number) {
    await mutate(
      () =>
        apiRequest<OffersUpdateResponse>(`/api/campaigns/${campaignId}/streams/${flowId}/offers/${offerId}/restore`, {
          method: "POST"
        }),
      (result) => applyOffersUpdate(result as OffersUpdateResponse)
    );
  }

  async function togglePin(flowId: number, offerId: number) {
    await mutate(
      () =>
        apiRequest<OffersUpdateResponse>(`/api/campaigns/${campaignId}/streams/${flowId}/offers/${offerId}/toggle-pin`, {
          method: "POST"
        }),
      (result) => applyOffersUpdate(result as OffersUpdateResponse)
    );
  }

  async function pushChanges(flowId: number) {
    await mutate(
      () => apiRequest(`/api/campaigns/${campaignId}/streams/${flowId}/push-to-kt`, { method: "POST" }),
      async () => {
        await loadCampaign({ refresh: false });
      }
    );
  }

  async function cancelChanges(flowId: number) {
    await mutate(
      () => apiRequest(`/api/campaigns/${campaignId}/streams/${flowId}/cancel-pending`, { method: "POST" }),
      async () => {
        await loadCampaign({ refresh: false });
      }
    );
    setSelectedOffers((current) => ({ ...current, [flowId]: null }));
  }

  return (
    <main className="shell">
      <header className="topbar">
        <div className="brand">
          <div className="brand-mark">K</div>
          <div>
            <h1 className="brand-title">Keitaro API Client</h1>
          </div>
        </div>
        <div className="nav-actions">
          {campaign?.keitaro_admin_url ? (
            <a className="button button-ghost" href={campaign.keitaro_admin_url} target="_blank" rel="noreferrer">
              <ExternalLink size={16} />
              View in KT
            </a>
          ) : null}
          <button className="button button-ghost" type="button" disabled={working || loading} onClick={() => void fetchFromKt()}>
            {working || loading ? <Loader2 size={16} className="loading-icon" /> : <RefreshCw size={16} />}
            Fetch from KT
          </button>
        </div>
      </header>

      <div className="page">
        <nav className="breadcrumbs">
          <Link href="/campaigns">Campaigns</Link>
          <span>/</span>
          <span>{campaign?.name ?? `Campaign ${campaignId}`}</span>
        </nav>

        {loading ? (
          <div className="message message-info" style={{ marginTop: 16 }}>
            <Loader2 size={16} className="loading-icon" /> Loading local campaign
          </div>
        ) : null}

        {error ? <div className="message message-error" style={{ marginTop: 16 }}>{error}</div> : null}

        {!loading && !campaign ? (
          <section className="panel missing-campaign">
            <div className="panel-body">
              <div className="message message-info">
                Campaign is not available in local state. Fetch campaigns from Keitaro on the campaigns page to load it again.
              </div>
              <Link className="button button-primary" href="/campaigns">
                Back to campaigns
              </Link>
            </div>
          </section>
        ) : null}

        {campaign ? (
          <>
            <section className="detail-head">
              <div className="detail-title-row">
                <div>
                  <h2 className="detail-title">{campaign.name}</h2>
                </div>
              </div>
            </section>

            <section className="panel" style={{ marginBottom: 18 }}>
              <div className="panel-header">
                <h3 className="panel-title flow-title">
                  <BarChart3 size={16} />
                  Keitaro stats
                </h3>
              </div>
              <div className="panel-body">
                <div className="metric-grid">
                  <Stat label="Clicks" value={campaign.stats.clicks} />
                  <Stat label="Unique" value={campaign.stats.unique_clicks} />
                  <Stat label="Bots" value={campaign.stats.bots} />
                  <Stat label="Conversions" value={campaign.stats.conversions} />
                  <Stat label="Revenue" value={campaign.stats.revenue} money />
                  <Stat label="Cost" value={campaign.stats.cost} money />
                  <Stat label="Profit" value={campaign.stats.profit} money />
                  <Stat label="CR" value={campaign.stats.cr} suffix="%" />
                  <Stat label="Streams" value={streamCount} />
                  <Stat label="Offers" value={offerCount} />
                </div>
              </div>
            </section>

            <section className="stack" style={{ marginTop: 18 }}>
              {campaign.flows.length === 0 ? <div className="message message-info">No streams loaded from Keitaro</div> : null}
              {campaign.flows.map((flow) => (
                <StreamOffersTable
                  key={flow.id}
                  flow={flow}
                  working={working || loading}
                  selectedOffer={selectedOffers[flow.id] ?? null}
                  onSelectOffer={(offer) => setFlowOffer(flow.id, offer)}
                  onAdd={() => void addOffer(flow.id)}
                  onRemove={(offerId) => void removeOffer(flow.id, offerId)}
                  onRestore={(offerId) => void restoreOffer(flow.id, offerId)}
                  onTogglePin={(offerId) => void togglePin(flow.id, offerId)}
                  onPush={() => void pushChanges(flow.id)}
                  onCancel={() => void cancelChanges(flow.id)}
                />
              ))}
            </section>
          </>
        ) : null}
      </div>
    </main>
  );
}

function StreamOffersTable({
  flow,
  working,
  selectedOffer,
  onSelectOffer,
  onAdd,
  onRemove,
  onRestore,
  onTogglePin,
  onPush,
  onCancel
}: {
  flow: CampaignFlow;
  working: boolean;
  selectedOffer: OfferSearchItem | null;
  onSelectOffer: (offer: OfferSearchItem | null) => void;
  onAdd: () => void;
  onRemove: (offerId: number) => void;
  onRestore: (offerId: number) => void;
  onTogglePin: (offerId: number) => void;
  onPush: () => void;
  onCancel: () => void;
}) {
  const offerCount = activeOfferCount(flow.offers);
  return (
    <details id={`stream-${flow.id}`} className={`panel stream-details ${flow.has_pending_changes ? "stream-panel-pending" : ""}`} open>
      <summary className="stream-summary">
        <span className="stream-title">
          <strong>{flow.name}</strong>
        </span>
        <span className="summary-meta">
          {flow.has_pending_changes ? (
            <span className="stream-actions">
              <button
                className="button button-primary"
                type="button"
                disabled={working}
                onClick={(event) => {
                  event.preventDefault();
                  event.stopPropagation();
                  onPush();
                }}
              >
                {working ? <Loader2 size={16} className="loading-icon" /> : null}
                Push to KT
              </button>
              <button
                className="button button-ghost"
                type="button"
                disabled={working}
                onClick={(event) => {
                  event.preventDefault();
                  event.stopPropagation();
                  onCancel();
                }}
              >
                Cancel
              </button>
            </span>
          ) : null}
          <span className={`badge ${flow.has_pending_changes ? "badge-amber" : ""}`}>
            {flow.has_pending_changes ? "changed" : flow.status ?? "active"}
          </span>
          <span className="badge">{offerCount} offers</span>
          <ChevronDown className="stream-chevron" size={18} aria-hidden="true" />
        </span>
      </summary>

      <div className="panel-body">
        {flow.redirect_url ? (
          <a className="url-line" style={{ marginBottom: 14 }} href={flow.redirect_url} target="_blank" rel="noreferrer">
            <ExternalLink size={16} />
            <span>{flow.redirect_url}</span>
          </a>
        ) : null}
        <MetricPairs metrics={flow.metrics} compact />

        <div className="table-wrap" style={{ marginTop: 14 }}>
          <table className="data-table">
            <thead>
              <tr>
                <th>Offer</th>
                <th>Share</th>
                <th>Stats</th>
                <th>Trends</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {flow.offers.length === 0 ? (
                <tr>
                  <td colSpan={5}>No offers in this stream</td>
                </tr>
              ) : null}
              {flow.offers.map((offer) => (
                <OfferRow
                  key={offer.offer_id}
                  offer={offer}
                  working={working}
                  onRemove={() => onRemove(offer.offer_id)}
                  onRestore={() => onRestore(offer.offer_id)}
                  onTogglePin={() => onTogglePin(offer.offer_id)}
                />
              ))}
            </tbody>
          </table>
        </div>

        <div className="inline-form">
          <OfferAutocomplete
            value={selectedOffer}
            onSelect={onSelectOffer}
            disabled={working}
            placeholder={`Search offer for ${flow.name}`}
          />
          <button className="button button-primary" type="button" disabled={working || !selectedOffer} onClick={onAdd}>
            {working ? <Loader2 size={16} className="loading-icon" /> : <Plus size={16} />}
            Add
          </button>
        </div>
      </div>
    </details>
  );
}

function OfferRow({
  offer,
  working,
  onRemove,
  onRestore,
  onTogglePin
}: {
  offer: CampaignOffer;
  working: boolean;
  onRemove: () => void;
  onRestore: () => void;
  onTogglePin: () => void;
}) {
  const isInactive = inactiveOfferActions.has(offer.pending_action ?? "");
  const rowClass = isInactive ? "row-remove" : offer.pending_action ? "row-add" : "";
  return (
    <tr className={rowClass || (offer.pending_action ? "row-pending" : "")}>
      <td>
        <div className="offer-name">[{offer.offer_id}] {offer.name}</div>
        {offer.pending_action ? <span className="badge badge-amber">{offer.pending_action}</span> : null}
        {offer.is_pinned ? <span className="badge">pinned</span> : null}
      </td>
      <td>{offer.weight}%</td>
      <td><MetricCells metrics={offer.stats} /></td>
      <td><MetricCells metrics={offer.trends} emptyLabel="No trend data" /></td>
      <td>
        <div className="actions-cell">
          {!isInactive ? (
            <button
              className={`button button-ghost button-icon ${offer.is_pinned ? "button-pinned" : ""}`}
              type="button"
              disabled={working}
              onClick={onTogglePin}
              title={offer.is_pinned ? "Unpin" : "Pin"}
            >
              <Pin size={16} />
            </button>
          ) : null}
          {isInactive ? (
            <button className="button button-ghost button-restore" type="button" disabled={working} onClick={onRestore}>
              Restore
            </button>
          ) : (
            <button className="button button-danger" type="button" disabled={working} onClick={onRemove} title="Remove">
              <Trash2 size={16} />
            </button>
          )}
        </div>
      </td>
    </tr>
  );
}

function Stat({
  label,
  value,
  suffix = "",
  money = false
}: {
  label: string;
  value: number;
  suffix?: string;
  money?: boolean;
}) {
  const formatted = formatStatValue(value, { money, suffix });
  return (
    <div className="stat">
      <span className="muted">{label}</span>
      <strong>{formatted}</strong>
    </div>
  );
}

function activeOfferCount(offers: CampaignOffer[]) {
  return offers.filter((offer) => !inactiveOfferActions.has(offer.pending_action ?? "")).length;
}

function formatStatValue(value: number, { money = false, suffix = "" }: { money?: boolean; suffix?: string }) {
  const number = Number(value) || 0;
  if (suffix === "%") {
    return `${trimFixed(number, 2)}%`;
  }

  const compact = compactNumber(number, money ? 2 : 1);
  if (money) {
    return `$${compact}`;
  }
  return `${compact}${suffix}`;
}

function compactNumber(value: number, digits: number) {
  const absolute = Math.abs(value);
  const units = [
    { value: 1_000_000_000, suffix: "B" },
    { value: 1_000_000, suffix: "M" },
    { value: 1_000, suffix: "K" }
  ];
  const unit = units.find((item) => absolute >= item.value);
  if (!unit) {
    return trimFixed(value, Number.isInteger(value) ? 0 : 2);
  }
  return `${trimFixed(value / unit.value, digits)}${unit.suffix}`;
}

function trimFixed(value: number, digits: number) {
  return value.toFixed(digits).replace(/\.0+$/, "").replace(/(\.\d*[1-9])0+$/, "$1");
}

function MetricPairs({ metrics, compact = false }: { metrics?: Record<string, unknown> | null; compact?: boolean }) {
  const entries = Object.entries(metrics ?? {}).filter(([, value]) => value !== null && value !== undefined && value !== "");
  if (entries.length === 0) {
    return null;
  }
  return (
    <div className={compact ? "metric-pairs metric-pairs-compact" : "metric-pairs"}>
      {entries.map(([key, value]) => (
        <span className="metric-chip" key={key}>
          {key}: {String(value)}
        </span>
      ))}
    </div>
  );
}

function MetricCells({ metrics, emptyLabel = "No stats" }: { metrics?: Record<string, unknown> | null; emptyLabel?: string }) {
  const entries = Object.entries(metrics ?? {}).filter(([, value]) => value !== null && value !== undefined && value !== "");
  if (entries.length === 0) {
    return <span className="muted">{emptyLabel}</span>;
  }
  return (
    <div className="metric-pairs metric-pairs-compact">
      {entries.map(([key, value]) => (
        <span className="metric-chip" key={key}>
          {key}: {String(value)}
        </span>
      ))}
    </div>
  );
}
