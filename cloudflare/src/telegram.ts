import type { Env } from "./types";

export async function sendTelegram(env: Env, text: string): Promise<void> {
  if (!env.TELEGRAM_TOKEN || !env.TELEGRAM_CHAT_ID) {
    throw new Error("Telegram secrets missing in live mode");
  }
  const response = await fetch(`https://api.telegram.org/bot${env.TELEGRAM_TOKEN}/sendMessage`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      chat_id: env.TELEGRAM_CHAT_ID,
      text,
      disable_web_page_preview: false,
    }),
  });
  if (!response.ok) {
    throw new Error(`Telegram error ${response.status}: ${(await response.text()).slice(0, 300)}`);
  }
}

export async function sendTelegramPhoto(
  env: Env,
  photoUrl: string,
  caption: string,
): Promise<void> {
  if (!env.TELEGRAM_TOKEN || !env.TELEGRAM_CHAT_ID) {
    throw new Error("Telegram secrets missing in live mode");
  }
  const response = await fetch(`https://api.telegram.org/bot${env.TELEGRAM_TOKEN}/sendPhoto`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      chat_id: env.TELEGRAM_CHAT_ID,
      photo: photoUrl,
      caption: caption.slice(0, 1024),
    }),
  });
  if (!response.ok) {
    throw new Error(`Telegram photo error ${response.status}: ${(await response.text()).slice(0, 300)}`);
  }
}
