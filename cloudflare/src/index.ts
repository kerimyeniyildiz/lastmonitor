import { handleRequest } from "./api";
import { loadConfig } from "./config";
import { runDueMonitors } from "./monitor";
import type { Env } from "./types";

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    return handleRequest(request, env, loadConfig(env));
  },

  async scheduled(_controller: ScheduledController, env: Env, ctx: ExecutionContext): Promise<void> {
    ctx.waitUntil(runDueMonitors(env, loadConfig(env)).then(() => undefined));
  },
} satisfies ExportedHandler<Env>;
