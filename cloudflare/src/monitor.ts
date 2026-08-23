import type { AppConfig, Env, RunSummary } from "./types";
import {
  claimSchedule,
  getKnownNewsSources,
  getNewsMetadata,
  recordRun,
  reserveNews,
  reserveTweet,
  updateNewsStatus,
  updateNewsMetadata,
  updateTweetStatus,
} from "./database";
import { evaluateTweetFilter, shouldDropTweet } from "./filter";
import { runDueInstagramFlash } from "./instagramFlash";
import { buildNewsMessage, fetchNewsEntries, fetchNewsMetadata } from "./sitemap";
import { sendTelegram } from "./telegram";
import { buildTweetMessage, fetchLatestTweets } from "./twitter";

export async function runTweetTarget(
  env: Env,
  config: AppConfig,
  query: string,
): Promise<RunSummary> {
  const startedAt = new Date().toISOString();
  let fetchedCount = 0;
  let newCount = 0;
  let filteredCount = 0;
  try {
    const tweets = await fetchLatestTweets(env, config, query);
    fetchedCount = tweets.length;
    for (const tweet of tweets) {
      const reasons = evaluateTweetFilter(config, query, tweet);
      const requiredPrefixMissing = reasons.includes("required_prefix_missing");
      const filtered = requiredPrefixMissing ||
        (config.tweetFilterMode === "drop" && shouldDropTweet(reasons));
      const initialStatus = filtered
        ? "filtered"
        : config.deliveryMode === "shadow"
          ? "shadow"
          : "pending";
      const reserved = await reserveTweet(env.DB, tweet, query, initialStatus, reasons);
      if (!reserved) continue;
      if (filtered) {
        filteredCount += 1;
        console.log("tweet filtered", { query, link: tweet.link, reasons });
        continue;
      }
      if (config.deliveryMode === "shadow") {
        newCount += 1;
        console.log("tweet shadow", { query, link: tweet.link, reasons });
        continue;
      }
      try {
        await sendTelegram(env, buildTweetMessage(tweet));
        await updateTweetStatus(env.DB, tweet.link, "sent");
        newCount += 1;
      } catch (error) {
        await updateTweetStatus(env.DB, tweet.link, "send_failed");
        throw error;
      }
    }
    const summary: RunSummary = {
      kind: "tweets",
      target: query,
      status: "ok",
      fetchedCount,
      newCount,
      filteredCount,
      startedAt,
      finishedAt: new Date().toISOString(),
    };
    await recordRun(env.DB, summary);
    console.log("tweet run complete", summary);
    return summary;
  } catch (error) {
    const summary: RunSummary = {
      kind: "tweets",
      target: query,
      status: "error",
      fetchedCount,
      newCount,
      filteredCount,
      error: error instanceof Error ? error.message : String(error),
      startedAt,
      finishedAt: new Date().toISOString(),
    };
    await recordRun(env.DB, summary);
    console.error("tweet run failed", summary);
    return summary;
  }
}

export async function runNewsTarget(env: Env, config: AppConfig): Promise<RunSummary> {
  const startedAt = new Date().toISOString();
  let fetchedCount = 0;
  let newCount = 0;
  try {
    const entries = await fetchNewsEntries(config);
    const knownSources = await getKnownNewsSources(env.DB);
    const seededSources = new Set<string>();
    fetchedCount = entries.length;
    for (const entry of entries) {
      const seedSource = !knownSources.has(entry.source);
      const status = seedSource
        ? "seeded"
        : config.deliveryMode === "shadow"
          ? "shadow"
          : "pending";
      const reserved = await reserveNews(env.DB, entry, status);
      if (seedSource) {
        if (reserved) seededSources.add(entry.source);
        continue;
      }
      const storedMetadata = await getNewsMetadata(env.DB, entry.link);
      let title = entry.title || storedMetadata.title;
      let description = entry.description || storedMetadata.description;
      if (!storedMetadata.fetchedAt) {
        try {
          const metadata = await fetchNewsMetadata(entry.link);
          title ||= metadata.title;
          description ||= metadata.description;
          await updateNewsMetadata(env.DB, entry.link, title, description);
          console.log("news metadata stored", {
            link: entry.link,
            hasTitle: Boolean(title),
            hasDescription: Boolean(description),
          });
        } catch (error) {
          console.warn("news metadata fetch failed", {
            link: entry.link,
            error: error instanceof Error ? error.message : String(error),
          });
        }
      }
      if (!reserved) continue;
      const enrichedEntry = { ...entry, title, description };
      if (config.deliveryMode === "shadow") {
        newCount += 1;
        console.log("news shadow", { link: entry.link });
        continue;
      }
      try {
        await sendTelegram(env, buildNewsMessage(enrichedEntry));
        await updateNewsStatus(env.DB, entry.link, "sent");
        newCount += 1;
      } catch (error) {
        await updateNewsStatus(env.DB, entry.link, "send_failed");
        throw error;
      }
    }
    if (seededSources.size > 0) {
      console.log("news sources seeded", { sources: [...seededSources] });
    }
    const summary: RunSummary = {
      kind: "news",
      target: "sitemaps",
      status: "ok",
      fetchedCount,
      newCount,
      filteredCount: 0,
      startedAt,
      finishedAt: new Date().toISOString(),
    };
    await recordRun(env.DB, summary);
    console.log("news run complete", summary);
    return summary;
  } catch (error) {
    const summary: RunSummary = {
      kind: "news",
      target: "sitemaps",
      status: "error",
      fetchedCount,
      newCount,
      filteredCount: 0,
      error: error instanceof Error ? error.message : String(error),
      startedAt,
      finishedAt: new Date().toISOString(),
    };
    await recordRun(env.DB, summary);
    console.error("news run failed", summary);
    return summary;
  }
}

export async function runDueMonitors(
  env: Env,
  config: AppConfig,
  force = false,
): Promise<RunSummary[]> {
  const nowSeconds = Math.floor(Date.now() / 1000);
  const jobs: Array<Promise<RunSummary>> = [];
  for (const item of config.querySchedule) {
    const due = force ||
      (await claimSchedule(env.DB, `tweet:${item.query}`, nowSeconds, item.intervalSeconds));
    if (due) jobs.push(runTweetTarget(env, config, item.query));
  }
  const newsDue = force ||
    (await claimSchedule(env.DB, "news:sitemaps", nowSeconds, config.newsIntervalSeconds));
  if (newsDue) jobs.push(runNewsTarget(env, config));
  const [regular, instagram] = await Promise.all([
    Promise.all(jobs),
    runDueInstagramFlash(env, config, force),
  ]);
  return [...regular, ...instagram];
}
