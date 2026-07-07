export type ApiErrorBody = {
  error?: {
    code?: string;
    message?: string;
    details?: unknown;
  };
};

export class ApiError extends Error {
  status: number;
  code: string;
  details?: unknown;

  constructor(status: number, body: ApiErrorBody) {
    super(body.error?.message ?? "API request failed");
    this.status = status;
    this.code = body.error?.code ?? "API_ERROR";
    this.details = body.error?.details;
  }
}

const API_BASE_URL = (process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000").replace(/\/+$/, "");

export async function apiRequest<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers,
    cache: "no-store"
  });

  if (!response.ok) {
    let body: ApiErrorBody = {};
    try {
      body = await response.json();
    } catch {
      body = { error: { code: "API_ERROR", message: response.statusText } };
    }
    throw new ApiError(response.status, body);
  }

  if (response.status === 204) {
    return undefined as T;
  }

  return (await response.json()) as T;
}

export type OfferSearchItem = {
  id: number;
  name: string;
  country?: string | null;
  state?: string | null;
  affiliate_network?: string | null;
  url?: string | null;
};

export type CampaignOffer = {
  offer_id: number;
  name: string;
  weight: number;
  position?: number | null;
  is_pinned: boolean;
  pending_action?: string | null;
  stats?: Record<string, unknown> | null;
  trends?: Record<string, unknown> | null;
};

export type CampaignFlow = {
  id: number;
  keitaro_flow_id: number | null;
  name: string;
  position: number;
  type: "geo_redirect" | "offers_fallback" | string;
  redirect_url: string | null;
  geo_codes: string[];
  offers: CampaignOffer[];
  status?: string | null;
  pending_action?: string | null;
  metrics?: Record<string, unknown> | null;
  has_pending_changes?: boolean;
};

export type CampaignDetail = {
  id: number;
  keitaro_campaign_id: number | null;
  name: string;
  alias: string;
  campaign_url: string;
  keitaro_admin_url?: string | null;
  geo_codes: string[];
  status: string;
  pending_action?: string | null;
  metrics?: Record<string, unknown> | null;
  flows: CampaignFlow[];
  stats: {
    clicks: number;
    unique_clicks: number;
    bots: number;
    conversions: number;
    revenue: number;
    cost: number;
    profit: number;
    cr: number;
  };
};

export type CampaignListItem = {
  id: number;
  keitaro_campaign_id: number | null;
  name: string;
  alias: string;
  campaign_url: string;
  keitaro_admin_url?: string | null;
  geo_codes: string[];
  status: string;
  pending_action?: string | null;
  metrics?: Record<string, unknown> | null;
  stream_count: number;
  has_pending_changes?: boolean;
  created_at: string;
  updated_at: string;
};

export type OffersUpdateResponse = {
  campaign_id: number;
  flow_id: number;
  offers: CampaignOffer[];
};

export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    return `${error.code}: ${error.message}`;
  }
  if (error instanceof Error) {
    return error.message;
  }
  return "Unexpected error";
}
