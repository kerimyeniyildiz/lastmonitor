import { claimSchedule, recordRun } from "./database";
import { storeInstagramPayload, type InstagramPayload } from "./instagram";
import type { AppConfig, Env, RunSummary } from "./types";

const RAPIDAPI_HOST = "flashapi1.p.rapidapi.com";
const REQUEST_GAP_MS = 1_050;
const HOUR_MS = 3_600_000;
const MEDIA_SIGNALS = [
  "__typename",
  "caption",
  "caption_text",
  "carousel_media",
  "code",
  "display_url",
  "image_versions2",
  "media_type",
  "product_type",
  "shortcode",
  "taken_at",
  "taken_at_timestamp",
  "thumbnail_url",
  "video_versions",
];

type JsonRecord = Record<string, unknown>;
type InstagramGroup = "feed" | "story";

interface NormalizedPayload {
  payload: InstagramPayload;
  sortTimestamp: number;
}

function asRecord(value: unknown): JsonRecord | null {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? value as JsonRecord
    : null;
}

function nested(value: unknown, ...path: string[]): unknown {
  let current = value;
  for (const part of path) {
    const record = asRecord(current);
    if (!record) return undefined;
    current = record[part];
  }
  return current;
}

function cleanString(value: unknown): string {
  return typeof value === "string" || typeof value === "number"
    ? String(value).trim()
    : "";
}

function firstString(...values: unknown[]): string {
  for (const value of values) {
    const text = cleanString(value);
    if (text) return text;
  }
  return "";
}

function instagramTimestamp(value: unknown): { iso: string | null; milliseconds: number } {
  const raw = cleanString(value);
  if (!raw) return { iso: null, milliseconds: 0 };
  const numeric = Number(raw);
  const milliseconds = Number.isFinite(numeric)
    ? numeric > 10_000_000_000 ? numeric : numeric * 1000
    : Date.parse(raw);
  if (!Number.isFinite(milliseconds)) return { iso: null, milliseconds: 0 };
  return { iso: new Date(milliseconds).toISOString(), milliseconds };
}

function isMediaRecord(record: JsonRecord): boolean {
  const id = firstString(record.pk, record.id, record.media_id, record.code, record.shortcode);
  return Boolean(id) && MEDIA_SIGNALS.some((key) => record[key] !== undefined);
}

function collectMediaRecords(value: unknown): JsonRecord[] {
  const records: JsonRecord[] = [];
  const visited = new WeakSet<object>();

  const visit = (candidate: unknown, depth: number): void => {
    if (depth > 10 || candidate === null || typeof candidate !== "object") return;
    if (visited.has(candidate)) return;
    visited.add(candidate);
    if (Array.isArray(candidate)) {
      for (const item of candidate) visit(item, depth + 1);
      return;
    }
    const record = candidate as JsonRecord;
    const node = asRecord(record.node);
    if (node && isMediaRecord(node)) {
      records.push(node);
      return;
    }
    if (isMediaRecord(record)) {
      records.push(record);
      return;
    }
    for (const child of Object.values(record)) visit(child, depth + 1);
  };

  visit(value, 0);
  return records;
}

function captionOf(record: JsonRecord): string {
  const edge = Array.isArray(nested(record, "edge_media_to_caption", "edges"))
    ? (nested(record, "edge_media_to_caption", "edges") as unknown[])[0]
    : undefined;
  return firstString(
    record.caption_text,
    typeof record.caption === "string" ? record.caption : undefined,
    nested(record, "caption", "text"),
    nested(edge, "node", "text"),
  ).slice(0, 2200);
}

function candidateUrl(record: JsonRecord): string {
  const imageCandidates = nested(record, "image_versions2", "candidates");
  const firstCandidate = Array.isArray(imageCandidates) ? imageCandidates[0] : undefined;
  const sidecarEdges = nested(record, "edge_sidecar_to_children", "edges");
  const firstSidecar = Array.isArray(sidecarEdges) ? sidecarEdges[0] : undefined;
  const carousel = Array.isArray(record.carousel_media) ? record.carousel_media[0] : undefined;
  const carouselRecord = asRecord(carousel);
  return firstString(
    record.thumbnail_url,
    record.display_url,
    record.thumbnail_src,
    nested(firstCandidate, "url"),
    nested(firstSidecar, "node", "display_url"),
    carouselRecord?.thumbnail_url,
    carouselRecord?.display_url,
    carouselRecord ? candidateUrl(carouselRecord) : undefined,
  );
}

function safePreviewUrl(value: string): string | null {
  if (!value) return null;
  try {
    const url = new URL(value);
    const host = url.hostname.toLowerCase();
    const allowed = host === "instagram.com" ||
      host.endsWith(".instagram.com") ||
      host.endsWith(".cdninstagram.com") ||
      host.endsWith(".fbcdn.net") ||
      host.endsWith(".fbsbx.com");
    return url.protocol === "https:" && allowed ? url.toString() : null;
  } catch {
    return null;
  }
}

function contentTypeOf(record: JsonRecord): InstagramPayload["content_type"] {
  const mediaType = Number(record.media_type || 0);
  const productType = cleanString(record.product_type).toLowerCase();
  const typename = cleanString(record.__typename).toLowerCase();
  if (mediaType === 8 || typename.includes("sidecar") || Array.isArray(record.carousel_media)) {
    return "carousel";
  }
  if (productType.includes("clip") || productType.includes("reel")) return "reel";
  return "post";
}

function normalizeMedia(
  record: JsonRecord,
  username: string,
  group: InstagramGroup,
): NormalizedPayload | null {
  const primaryKey = firstString(record.pk, record.id, record.media_id);
  const code = firstString(record.code, record.shortcode);
  if (!primaryKey && !code) return null;
  const rawId = primaryKey || code;
  const instagramId = group === "story" ? rawId.split("_", 1)[0] : code || rawId;
  if (!instagramId) return null;

  const timestamp = instagramTimestamp(firstString(
    record.taken_at,
    record.taken_at_timestamp,
    record.taken_at_ts,
    record.timestamp,
    record.created_at,
    record.date,
  ));
  const contentType = group === "story" ? "story" : contentTypeOf(record);
  const route = contentType === "reel" ? "reel" : "p";
  const link = group === "story"
    ? `https://www.instagram.com/stories/${username}/${instagramId}/`
    : code
      ? `https://www.instagram.com/${route}/${code}/`
      : `https://www.instagram.com/${username}/`;

  return {
    payload: {
      event_key: `instagram:${username}:${group}:${instagramId}`,
      instagram_id: instagramId,
      username,
      content_type: contentType,
      caption: captionOf(record),
      link,
      created_at: timestamp.iso,
      preview_url: safePreviewUrl(candidateUrl(record)),
    },
    sortTimestamp: timestamp.milliseconds,
  };
}

export function normalizeFlashInstagram(
  value: unknown,
  username: string,
  group: InstagramGroup,
): InstagramPayload[] {
  const unique = new Map<string, NormalizedPayload>();
  for (const record of collectMediaRecords(value)) {
    const normalized = normalizeMedia(record, username, group);
    if (normalized) unique.set(normalized.payload.event_key, normalized);
  }
  return [...unique.values()]
    .sort((left, right) => left.sortTimestamp - right.sortTimestamp)
    .map((item) => item.payload);
}

function numericId(value: unknown): string | null {
  const id = cleanString(value);
  return /^\d+$/u.test(id) ? id : null;
}

export function extractFlashUserId(value: unknown, username: string): string | null {
  const record = asRecord(value);
  if (!record) return numericId(value);
  const direct = [
    record.user_id,
    record.id_user,
    record.pk,
    record.id,
    nested(record, "data", "user_id"),
    nested(record, "data", "id_user"),
    nested(record, "data", "pk"),
    nested(record, "data", "id"),
    nested(record, "user", "pk"),
    nested(record, "user", "id"),
    nested(record, "result", "user_id"),
    nested(record, "result", "id"),
    record.data,
    record.result,
  ];
  for (const candidate of direct) {
    const id = numericId(candidate);
    if (id) return id;
  }

  const expected = username.toLowerCase();
  const visited = new WeakSet<object>();
  const search = (candidate: unknown, depth: number): string | null => {
    if (depth > 7 || candidate === null || typeof candidate !== "object") return null;
    if (visited.has(candidate)) return null;
    visited.add(candidate);
    if (Array.isArray(candidate)) {
      for (const child of candidate) {
        const found = search(child, depth + 1);
        if (found) return found;
      }
      return null;
    }
    const item = candidate as JsonRecord;
    const itemUsername = firstString(item.username, item.user_name).toLowerCase();
    if (itemUsername === expected) {
      return numericId(item.pk) || numericId(item.id) || numericId(item.user_id);
    }
    for (const child of Object.values(item)) {
      const found = search(child, depth + 1);
      if (found) return found;
    }
    return null;
  };
  return search(value, 0);
}

function apiError(value: unknown): string | null {
  const record = asRecord(value);
  if (!record) return null;
  const status = cleanString(record.status).toLowerCase();
  const error = firstString(record.error, record.detail);
  if (status === "error" || status === "fail" || record.success === false) {
    return error || firstString(record.message) || `FlashAPI status: ${status}`;
  }
  return error && !record.data && !record.items ? error : null;
}

class FlashApiClient {
  private lastRequestAt = 0;

  constructor(private readonly env: Env) {}

  private async get(path: string, parameters: Record<string, string>): Promise<unknown> {
    const waitMs = REQUEST_GAP_MS - (Date.now() - this.lastRequestAt);
    if (waitMs > 0) await new Promise((resolve) => setTimeout(resolve, waitMs));
    const url = new URL(`https://${RAPIDAPI_HOST}${path}`);
    for (const [key, value] of Object.entries(parameters)) url.searchParams.set(key, value);
    const response = await fetch(url, {
      headers: {
        accept: "application/json",
        "content-type": "application/json",
        "x-rapidapi-host": RAPIDAPI_HOST,
        "x-rapidapi-key": this.env.RAPIDAPI_KEY,
      },
      signal: AbortSignal.timeout(25_000),
    });
    this.lastRequestAt = Date.now();
    const text = await response.text();
    if (!response.ok) {
      throw new Error(`FlashAPI ${response.status}: ${text.slice(0, 300)}`);
    }
    let value: unknown;
    try {
      value = JSON.parse(text);
    } catch {
      throw new Error(`FlashAPI returned invalid JSON: ${text.slice(0, 200)}`);
    }
    const error = apiError(value);
    if (error) throw new Error(`FlashAPI: ${error}`);
    return value;
  }

  async userId(username: string): Promise<string> {
    const value = await this.get("/ig/user_id/", { user: username });
    const userId = extractFlashUserId(value, username);
    if (!userId) throw new Error(`FlashAPI user id missing for @${username}`);
    return userId;
  }

  posts(username: string): Promise<unknown> {
    return this.get("/ig/posts_username/", { user: username, nocors: "false" });
  }

  stories(userId: string): Promise<unknown> {
    return this.get("/ig/stories/", { id_user: userId, nocors: "false" });
  }
}

export function isInstagramShiftActive(now: Date, config: AppConfig): boolean {
  const anchor = Date.parse(config.instagramShiftAnchor);
  if (!Number.isFinite(anchor)) return false;
  const cycle = Math.max(1, config.instagramShiftCycleHours) * HOUR_MS;
  const work = Math.min(
    Math.max(0, config.instagramShiftWorkHours) * HOUR_MS,
    cycle,
  );
  const elapsed = now.getTime() - anchor;
  if (elapsed < 0) return false;
  const phase = ((elapsed % cycle) + cycle) % cycle;
  return phase < work;
}

async function cachedUserId(db: D1Database, username: string): Promise<string | null> {
  const row = await db
    .prepare("SELECT user_id FROM instagram_flash_profiles WHERE username = ?")
    .bind(username)
    .first<{ user_id: string }>();
  return row?.user_id || null;
}

async function storeUserId(db: D1Database, username: string, userId: string): Promise<void> {
  await db
    .prepare(
      `INSERT INTO instagram_flash_profiles (username, user_id, updated_at)
       VALUES (?, ?, CURRENT_TIMESTAMP)
       ON CONFLICT(username) DO UPDATE SET
         user_id = excluded.user_id,
         updated_at = CURRENT_TIMESTAMP`,
    )
    .bind(username, userId)
    .run();
}

async function groupInitialized(
  db: D1Database,
  username: string,
  group: InstagramGroup,
): Promise<boolean> {
  const row = await db
    .prepare(
      "SELECT 1 AS initialized FROM instagram_flash_groups WHERE username = ? AND group_name = ?",
    )
    .bind(username, group)
    .first<{ initialized: number }>();
  return Boolean(row?.initialized);
}

async function markGroupInitialized(
  db: D1Database,
  username: string,
  group: InstagramGroup,
): Promise<void> {
  await db
    .prepare(
      `INSERT INTO instagram_flash_groups (username, group_name, initialized_at)
       VALUES (?, ?, CURRENT_TIMESTAMP)
       ON CONFLICT(username, group_name) DO NOTHING`,
    )
    .bind(username, group)
    .run();
}

async function processGroup(
  env: Env,
  username: string,
  group: InstagramGroup,
  events: InstagramPayload[],
): Promise<{ delivered: number; seeded: number }> {
  const initialized = await groupInitialized(env.DB, username, group);
  let delivered = 0;
  let seeded = 0;
  for (const event of events) {
    const result = await storeInstagramPayload(env, event, !initialized);
    if (!initialized && !result.duplicate) seeded += 1;
    if (initialized && !result.duplicate && result.telegramStatus === "sent") delivered += 1;
  }
  if (!initialized) await markGroupInitialized(env.DB, username, group);
  return { delivered, seeded };
}

async function runFlashTarget(
  env: Env,
  client: FlashApiClient,
  username: string,
): Promise<RunSummary> {
  const startedAt = new Date().toISOString();
  let fetchedCount = 0;
  let newCount = 0;
  try {
    let userId = await cachedUserId(env.DB, username);
    if (!userId) {
      userId = await client.userId(username);
      await storeUserId(env.DB, username, userId);
    }
    const postsValue = await client.posts(username);
    const storiesValue = await client.stories(userId);
    const posts = normalizeFlashInstagram(postsValue, username, "feed");
    const stories = normalizeFlashInstagram(storiesValue, username, "story");
    if (!posts.length) {
      throw new Error(`FlashAPI returned no parseable posts for @${username}`);
    }
    fetchedCount = posts.length + stories.length;
    const feedResult = await processGroup(env, username, "feed", posts);
    const storyResult = await processGroup(env, username, "story", stories);
    newCount = feedResult.delivered + storyResult.delivered;
    const summary: RunSummary = {
      kind: "instagram",
      target: username,
      status: "ok",
      fetchedCount,
      newCount,
      filteredCount: 0,
      startedAt,
      finishedAt: new Date().toISOString(),
    };
    await recordRun(env.DB, summary);
    console.log("instagram flash run complete", {
      ...summary,
      seededCount: feedResult.seeded + storyResult.seeded,
    });
    return summary;
  } catch (error) {
    const summary: RunSummary = {
      kind: "instagram",
      target: username,
      status: "error",
      fetchedCount,
      newCount,
      filteredCount: 0,
      error: error instanceof Error ? error.message : String(error),
      startedAt,
      finishedAt: new Date().toISOString(),
    };
    await recordRun(env.DB, summary);
    console.error("instagram flash run failed", summary);
    return summary;
  }
}

export async function runDueInstagramFlash(
  env: Env,
  config: AppConfig,
  force = false,
): Promise<RunSummary[]> {
  if (!config.instagramFlashEnabled || !config.instagramFlashTargets.length) return [];
  if (!force && !isInstagramShiftActive(new Date(), config)) return [];

  const nowSeconds = Math.floor(Date.now() / 1000);
  const dueTargets: string[] = [];
  for (const username of config.instagramFlashTargets) {
    const due = force || await claimSchedule(
      env.DB,
      `instagram:flash:${username}`,
      nowSeconds,
      config.instagramFlashIntervalSeconds,
    );
    if (due) dueTargets.push(username);
  }
  const client = new FlashApiClient(env);
  const summaries: RunSummary[] = [];
  for (const username of dueTargets) {
    summaries.push(await runFlashTarget(env, client, username));
  }
  return summaries;
}
