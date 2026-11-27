import { Api, apiError } from "./api.js";
import { resolveApiKey, resolveApiUrl } from "./config.js";
import { CliError, EXIT } from "./errors.js";
import { printJson } from "./generate.js";
const amount = (n) => n.toLocaleString("en-US", { minimumFractionDigits: n % 1 ? 2 : 0, maximumFractionDigits: 2 });
const money = (n, currency) => (currency.toLowerCase() === "usd" ? `$${amount(n)}` : `${amount(n)} ${currency.toUpperCase()}`);
const num = (n) => n.toLocaleString("en-US");
function planText(p, currency) {
    const price = p.prices.length
        ? p.prices
            .map(x => (x.interval === "year" ? `${money(x.amount, currency)}/year (${money(x.per_month ?? x.amount / 12, currency)}/month)` : `${money(x.amount, currency)}/month`))
            .join(" or ")
        : "free";
    const credits = p.credits_per_month !== null ? `${num(p.credits_per_month)} credits a month` : `${num(p.credits_at_signup || 0)} credits at sign-up`;
    const lines = [
        `${p.name}: ${price}`,
        `  ${credits} · ${p.seats} seat${p.seats === 1 ? "" : "s"} · ${p.queue_concurrency} generation${p.queue_concurrency === 1 ? "" : "s"} at a time · API, MCP and CLI: ${p.api_access ? "yes" : "no"}`
    ];
    for (const s of p.included)
        lines.push(`  + ${s}`);
    for (const s of p.not_included)
        lines.push(`  - no ${s.charAt(0).toLowerCase()}${s.slice(1)}`);
    return lines.join("\n");
}
// The "Extra credits" block. What an extra credit costs depends on the plan,
// so there is one line per plan; a server from before per-plan prices sends
// one table and gets one line.
export function topUpLines(top, currency) {
    const priced = (brackets) => brackets.map(b => `${num(b.credits)} for ${money(b.cents / 100, currency)}`).join(", ");
    if (top?.tiers?.length) {
        return [
            `Extra credits (${top.eligible}): ${num(top.min_credits)} to ${num(top.max_credits)} at a time, priced by plan:`,
            ...top.tiers.map(t => `  ${t.name} (from ${t.cents_per_credit}¢ a credit): ${priced(t.brackets)}`),
            ""
        ];
    }
    if (top?.brackets?.length) {
        return [`Extra credits (${top.eligible}): ${num(top.min_credits)} to ${num(top.max_credits)} at a time; ${priced(top.brackets)}.`, ""];
    }
    return [];
}
export async function pricing(ctx) {
    const apiUrl = resolveApiUrl(ctx.globals.apiUrl);
    const res = await new Api(apiUrl, resolveApiKey(ctx.globals.apiKey)).request("GET", "/pricing", { timeoutMs: 15_000 });
    if (res.status === 404) {
        throw new CliError("This Ludo server has no pricing guide yet", EXIT.ERROR, "See https://ludo.ai/pricing");
    }
    if (res.status !== 200)
        throw apiError(res);
    const guide = res.body;
    if (ctx.jsonOut) {
        printJson(guide, false);
        return EXIT.OK;
    }
    const currency = guide.currency || "usd";
    const out = [guide.summary, "", ...guide.plans.map((p) => planText(p, currency) + "\n")];
    out.push(...topUpLines(guide.top_ups, currency));
    out.push("Good to know:");
    for (const r of guide.rules || [])
        out.push(`  • ${r.text}`);
    out.push("", `Each command's price: ludo <group> <command> --help. Plans: ${guide.links?.pricing}. Buy or change plan: ludo billing.`);
    process.stdout.write(out.join("\n") + "\n");
    return EXIT.OK;
}
