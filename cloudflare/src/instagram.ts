import { recordRun } from "./database";
import { sendTelegram, sendTelegramPhoto } from "./monitor";
import type { Env, RunSummary } from "./types";

const JSON_HEADERS = {
  "content-type": "application/json; charset=utf-8",
  "cache-control": "no-store",
};
const CONTENT_TYPES = new Set(["post", "carousel", "reel", "story"]);
const PREVIEW_HOST_SUFFIXES = [".cdninstagram.com", ".fbcdn.net"];

export interface InstagramPayload {
  event_key: string;
  instagram_id: string;
  username: string;
  content_type: "post" | "carousel" | "reel" | "story";
  caption: string;
  link: string;
  created_at: string | null;
  preview_url: string | null;
}

interface InstagramRow {
  event_key: string;
  telegram_status: string;
}

function json(value: unknown, status = 200): Response {
  return new Response(JSON.stringify(value), { status, headers: JSON_HEADERS });
}

function isAuthorized(request: Request, env: Env): boolean {
  if (!env.INSTAGRAM_INGEST_TOKEN) return false;
  return request.headers.get("authorization") === `Bearer ${env.INSTAGRAM_INGEST_TOKEN}`;
}

function cleanText(value: unknown, maximum: number): string {
  return typeof value === "string" ? value.trim().slice(0, maximum) : "";
}

function parseInstagramPreviewUrl(value: unknown): string | null {
  const previewUrl = cleanText(value, 4000);
  if (!previewUrl) return null;
  let parsed: URL;
  try {
    parsed = new URL(previewUrl);
  } catch {
    throw new Error("Invalid preview_url");
  }
  const hostname = parsed.hostname.toLowerCase();
  const allowed = hostname === "instagram.com" ||
    hostname.endsWith(".instagram.com") ||
    PREVIEW_HOST_SUFFIXES.some((suffix) => hostname.endsWith(suffix));
  if (parsed.protocol !== "https:" || !allowed) {
    throw new Error("preview_url must use an Instagram CDN");
  }
  return parsed.toString();
}

export function validateInstagramPayload(value: unknown): InstagramPayload {
  if (!value || typeof value !== "object") throw new Error("Payload must be an object");
  const raw = value as Record<string, unknown>;
  const eventKey = cleanText(raw.event_key, 240);
  const instagramId = cleanText(raw.instagram_id, 120);
  const username = cleanText(raw.username, 80).replace(/^@/, "");
  const contentType = cleanText(raw.content_type, 20);
  const caption = cleanText(raw.caption, 2200);
  const link = cleanText(raw.link, 1000);
  const createdAt = cleanText(raw.created_at, 80) || null;
  const previewUrl = parseInstagramPreviewUrl(raw.preview_url);

  if (!eventKey || !/^[A-Za-z0-9:._-]+$/.test(eventKey)) {
    throw new Error("Invalid event_key");
  }
  if (!instagramId || !/^[A-Za-z0-9._-]+$/.test(instagramId)) {
    throw new Error("Invalid instagram_id");
  }
  if (!username || !/^[A-Za-z0-9._]+$/.test(username)) throw new Error("Invalid username");
  if (!CONTENT_TYPES.has(contentType)) throw new Error("Invalid content_type");
  let parsedLink: URL;
  try {
    parsedLink = new URL(link);
  } catch {
    throw new Error("Invalid link");
  }
  if (!["instagram.com", "www.instagram.com"].includes(parsedLink.hostname)) {
    throw new Error("Link must use instagram.com");
  }
  if (createdAt && Number.isNaN(Date.parse(createdAt))) throw new Error("Invalid created_at");

  return {
    event_key: eventKey,
    instagram_id: instagramId,
    username,
    content_type: contentType as InstagramPayload["content_type"],
    caption,
    link: parsedLink.toString(),
    created_at: createdAt,
    preview_url: previewUrl,
  };
}

export function buildInstagramMessage(payload: InstagramPayload): string {
  const labels: Record<InstagramPayload["content_type"], string> = {
    post: "Gönderi",
    carousel: "Çoklu Gönderi",
    reel: "Reels",
    story: "Story",
  };
  const lines = [
    `Instagram ${labels[payload.content_type]}`,
    `Hesap: @${payload.username}`,
  ];
  if (payload.caption) lines.push(`Açıklama: ${payload.caption.slice(0, 650)}`);
  lines.push(`Bağlantı: ${payload.link}`);
  return lines.join("\n");
}

export async function ingestInstagramEvent(request: Request, env: Env): Promise<Response> {
  if (!isAuthorized(request, env)) return json({ detail: "Unauthorized" }, 401);

  let payload: InstagramPayload;
  try {
    payload = validateInstagramPayload(await request.json());
  } catch (error) {
    return json({ detail: error instanceof Error ? error.message : "Invalid payload" }, 400);
  }

  const existing = await env.DB
    .prepare(
      `SELECT event_key, telegram_status
       FROM instagram_events WHERE event_key = ?`,
    )
    .bind(payload.event_key)
    .first<InstagramRow>();

  await env.DB
    .prepare(
      `INSERT INTO instagram_events (
         event_key, instagram_id, username, content_type, caption, link,
         preview_url, content_created_at, delivery_status, telegram_status, fetched_at
       ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', 'pending', CURRENT_TIMESTAMP)
       ON CONFLICT(event_key) DO UPDATE SET
         caption = excluded.caption,
         link = excluded.link,
         preview_url = COALESCE(excluded.preview_url, instagram_events.preview_url),
         content_created_at = COALESCE(excluded.content_created_at, instagram_events.content_created_at),
         fetched_at = CURRENT_TIMESTAMP`,
    )
    .bind(
      payload.event_key,
      payload.instagram_id,
      payload.username,
      payload.content_type,
      payload.caption || null,
      payload.link,
      payload.preview_url,
      payload.created_at,
    )
    .run();

  if (existing?.telegram_status === "sent") {
    return json({ status: "ok", duplicate: true, telegram_status: "sent" });
  }

  try {
    const message = buildInstagramMessage(payload);
    if (payload.preview_url) {
      try {
        await sendTelegramPhoto(env, payload.preview_url, message);
      } catch (error) {
        console.warn("instagram preview delivery failed; falling back to text", {
          eventKey: payload.event_key,
          error: error instanceof Error ? error.message : String(error),
        });
        await sendTelegram(env, message);
      }
    } else {
      await sendTelegram(env, message);
    }
    await env.DB
      .prepare(
        `UPDATE instagram_events
         SET delivery_status = 'sent', telegram_status = 'sent',
             delivered_at = CURRENT_TIMESTAMP, fetched_at = CURRENT_TIMESTAMP
         WHERE event_key = ?`,
      )
      .bind(payload.event_key)
      .run();
    return json({ status: "ok", duplicate: false, telegram_status: "sent" });
  } catch (error) {
    await env.DB
      .prepare(
        `UPDATE instagram_events
         SET delivery_status = 'send_failed', telegram_status = 'send_failed',
             fetched_at = CURRENT_TIMESTAMP
         WHERE event_key = ?`,
      )
      .bind(payload.event_key)
      .run();
    console.error("instagram telegram delivery failed", {
      eventKey: payload.event_key,
      error: error instanceof Error ? error.message : String(error),
    });
    return json(
      {
        status: "error",
        telegram_status: "send_failed",
        detail: error instanceof Error ? error.message : String(error),
      },
      502,
    );
  }
}

export async function ingestInstagramRun(request: Request, env: Env): Promise<Response> {
  if (!isAuthorized(request, env)) return json({ detail: "Unauthorized" }, 401);
  let value: Record<string, unknown>;
  try {
    value = await request.json<Record<string, unknown>>();
  } catch {
    return json({ detail: "Invalid JSON" }, 400);
  }
  const target = cleanText(value.target, 120);
  const status = cleanText(value.status, 20);
  const startedAt = cleanText(value.started_at, 80);
  const finishedAt = cleanText(value.finished_at, 80);
  if (!target || !["ok", "error", "skipped"].includes(status)) {
    return json({ detail: "Invalid run payload" }, 400);
  }
  if (Number.isNaN(Date.parse(startedAt)) || Number.isNaN(Date.parse(finishedAt))) {
    return json({ detail: "Invalid run timestamps" }, 400);
  }
  const summary: RunSummary = {
    kind: "instagram",
    target,
    status: status as RunSummary["status"],
    fetchedCount: Math.max(0, Number(value.fetched_count) || 0),
    newCount: Math.max(0, Number(value.new_count) || 0),
    filteredCount: 0,
    error: cleanText(value.error, 1000) || undefined,
    startedAt,
    finishedAt,
  };
  await recordRun(env.DB, summary);
  return json({ status: "ok" });
}
