"use client";

import { useRouter } from "next/navigation";
import { Loader2, Plus, RefreshCw, RotateCcw, Trash2, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { OfferAutocomplete } from "@/components/OfferAutocomplete";
import { CampaignDetail, CampaignListItem, OfferSearchItem, apiRequest, errorMessage } from "@/lib/api";

export default function CampaignsPage() {
  const router = useRouter();
  const [campaigns, setCampaigns] = useState<CampaignListItem[]>([]);
  const [hasFetched, setHasFetched] = useState(false);
  const [loading, setLoading] = useState(false);
  const [working, setWorking] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [newCampaignName, setNewCampaignName] = useState("");
  const [newCampaignGeo, setNewCampaignGeo] = useState("");
  const [newCampaignOffer, setNewCampaignOffer] = useState<OfferSearchItem | null>(null);

  const hasPendingCampaigns = useMemo(
    () => campaigns.some((campaign) => campaign.pending_action === "delete"),
    [campaigns]
  );

  async function loadCampaigns() {
    setLoading(true);
    setError(null);
    try {
      const data = await apiRequest<{ items: CampaignListItem[] }>("/api/campaigns?limit=100&offset=0");
      setCampaigns(data.items);
      setHasFetched(true);
    } catch (requestError) {
      setError(errorMessage(requestError));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadCampaigns();
  }, []);

  async function fetchFromKt() {
    setWorking(true);
    setError(null);
    try {
      await apiRequest("/api/campaigns/fetch-from-kt", { method: "POST" });
      await loadCampaigns();
    } catch (requestError) {
      setError(errorMessage(requestError));
    } finally {
      setWorking(false);
    }
  }

  async function createCampaign() {
    const name = newCampaignName.trim();
    const geoCodes = parseGeoCodes(newCampaignGeo);
    if (!name || geoCodes.length === 0 || !newCampaignOffer) {
      return;
    }

    setWorking(true);
    setError(null);
    try {
      const created = await apiRequest<CampaignDetail>("/api/campaigns", {
        method: "POST",
        body: JSON.stringify({
          name,
          geo_codes: geoCodes,
          offer_id: newCampaignOffer.id
        })
      });
      setCreateOpen(false);
      setNewCampaignName("");
      setNewCampaignGeo("");
      setNewCampaignOffer(null);
      await loadCampaigns();
      router.push(`/campaigns/${created.id}`);
    } catch (requestError) {
      setError(errorMessage(requestError));
    } finally {
      setWorking(false);
    }
  }

  async function stageDelete(campaignId: number) {
    setWorking(true);
    setError(null);
    try {
      await apiRequest(`/api/campaigns/${campaignId}/stage-delete`, { method: "POST" });
      await loadCampaigns();
    } catch (requestError) {
      setError(errorMessage(requestError));
    } finally {
      setWorking(false);
    }
  }

  async function restore(campaignId: number) {
    setWorking(true);
    setError(null);
    try {
      await apiRequest(`/api/campaigns/${campaignId}/restore`, { method: "POST" });
      await loadCampaigns();
    } catch (requestError) {
      setError(errorMessage(requestError));
    } finally {
      setWorking(false);
    }
  }

  async function pushCampaigns() {
    setWorking(true);
    setError(null);
    try {
      await apiRequest("/api/campaigns/push-to-kt", { method: "POST" });
      await loadCampaigns();
    } catch (requestError) {
      setError(errorMessage(requestError));
    } finally {
      setWorking(false);
    }
  }

  async function cancelCampaigns() {
    setWorking(true);
    setError(null);
    try {
      await apiRequest("/api/campaigns/cancel-pending", { method: "POST" });
      await loadCampaigns();
    } catch (requestError) {
      setError(errorMessage(requestError));
    } finally {
      setWorking(false);
    }
  }

  function openCampaign(campaignId: number) {
    router.push(`/campaigns/${campaignId}`);
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
          <button className="button button-primary" type="button" disabled={working || loading} onClick={() => setCreateOpen(true)}>
            <Plus size={16} />
            New campaign
          </button>
          {hasPendingCampaigns ? (
            <>
              <button className="button button-primary" type="button" disabled={working || loading} onClick={() => void pushCampaigns()}>
                {working ? <Loader2 size={16} className="loading-icon" /> : null}
                Push to Keitaro
              </button>
              <button className="button button-ghost" type="button" disabled={working || loading} onClick={() => void cancelCampaigns()}>
                Cancel
              </button>
            </>
          ) : null}
          <button className="button button-ghost" type="button" disabled={working || loading} onClick={() => void fetchFromKt()}>
            {working || loading ? <Loader2 size={16} className="loading-icon" /> : <RefreshCw size={16} />}
            Fetch from KT
          </button>
        </div>
      </header>

      <div className="page">
        {error ? <div className="message message-error" style={{ marginBottom: 16 }}>{error}</div> : null}

        {!hasFetched && loading ? (
          <div className="message message-info">
            <Loader2 size={16} className="loading-icon" /> Loading local campaigns
          </div>
        ) : null}

        {hasFetched ? (
          <section className="panel">
            <div className="panel-header">
              <h2 className="panel-title">Campaign list</h2>
              {loading ? <Loader2 size={16} className="loading-icon" /> : null}
            </div>
            <div className="panel-body campaign-list">
              {campaigns.length === 0 && !loading ? (
                <div className="message message-info">No active campaigns were loaded from Keitaro</div>
              ) : null}
              {campaigns.map((campaign) => {
                const changed = campaign.has_pending_changes || campaign.status === "changed";
                const pendingDelete = campaign.pending_action === "delete";
                return (
                  <div
                    className={`item-card campaign-card ${pendingDelete ? "item-card-pending" : ""}`}
                    key={campaign.id}
                    role="button"
                    tabIndex={0}
                    onClick={() => openCampaign(campaign.id)}
                    onKeyDown={(event) => {
                      if (event.key === "Enter" || event.key === " ") {
                        event.preventDefault();
                        openCampaign(campaign.id);
                      }
                    }}
                  >
                    <div className="item-row">
                      <div>
                        <strong className="campaign-card-title">{campaign.name}</strong>
                        <div className="muted">{campaign.campaign_url}</div>
                      </div>
                      <div className="nav-actions">
                        {pendingDelete ? (
                          <button
                            className="button button-ghost"
                            type="button"
                            disabled={working || loading}
                            onClick={(event) => {
                              event.stopPropagation();
                              void restore(campaign.id);
                            }}
                          >
                            <RotateCcw size={16} />
                            Restore
                          </button>
                        ) : (
                          <button
                            className="button button-danger"
                            type="button"
                            disabled={working || loading}
                            onClick={(event) => {
                              event.stopPropagation();
                              void stageDelete(campaign.id);
                            }}
                            title="Delete"
                          >
                            <Trash2 size={16} />
                          </button>
                        )}
                      </div>
                    </div>
                    <div className="badge-row">
                      <span className={`badge ${changed || pendingDelete ? "badge-amber" : "badge-green"}`}>
                        {pendingDelete ? "delete" : changed ? "changed" : campaign.status}
                      </span>
                      {campaign.stream_count !== null ? <span className="badge">{campaign.stream_count} streams</span> : null}
                    </div>
                  </div>
                );
              })}
            </div>
          </section>
        ) : null}
      </div>

      {createOpen ? (
        <div className="modal-backdrop" role="presentation">
          <div className="modal" role="dialog" aria-modal="true" aria-labelledby="new-campaign-title">
            <div className="modal-header">
              <h2 className="panel-title" id="new-campaign-title">New campaign</h2>
              <button className="button button-icon button-ghost" type="button" disabled={working} onClick={() => setCreateOpen(false)}>
                <X size={16} />
              </button>
            </div>
            <div className="modal-body">
              <div className="form">
                <div className="field">
                  <label htmlFor="new-campaign-name">Campaign name</label>
                  <input
                    className="input"
                    id="new-campaign-name"
                    value={newCampaignName}
                    disabled={working}
                    onChange={(event) => setNewCampaignName(event.target.value)}
                  />
                </div>
                <div className="field">
                  <label htmlFor="new-campaign-geo">Country GEOs</label>
                  <input
                    className="input"
                    id="new-campaign-geo"
                    value={newCampaignGeo}
                    disabled={working}
                    placeholder="AU, RO"
                    onChange={(event) => setNewCampaignGeo(event.target.value.toUpperCase())}
                  />
                </div>
                <div className="field">
                  <span className="label">Offer</span>
                  <OfferAutocomplete
                    value={newCampaignOffer}
                    onSelect={setNewCampaignOffer}
                    disabled={working}
                    placeholder="Search offer by name or ID"
                  />
                </div>
                <div className="nav-actions modal-actions">
                  <button className="button button-ghost" type="button" disabled={working} onClick={() => setCreateOpen(false)}>
                    Cancel
                  </button>
                  <button
                    className="button button-primary"
                    type="button"
                    disabled={working || !newCampaignName.trim() || parseGeoCodes(newCampaignGeo).length === 0 || !newCampaignOffer}
                    onClick={() => void createCampaign()}
                  >
                    {working ? <Loader2 size={16} className="loading-icon" /> : <Plus size={16} />}
                    Create
                  </button>
                </div>
              </div>
            </div>
          </div>
        </div>
      ) : null}
    </main>
  );
}

function parseGeoCodes(value: string) {
  return value
    .split(/[,\s]+/)
    .map((code) => code.trim().toUpperCase())
    .filter(Boolean);
}
