import fs from "node:fs";
import path from "node:path";
import { cacheDir } from "./config.js";
import { CliError, EXIT } from "./errors.js";
import { formatCredits } from "./pricing.js";
import { stateDir } from "./project.js";
export function spendFile(project) {
    return path.join(stateDir(project, cacheDir()), "spend.jsonl");
}
// The ledger is bookkeeping: a folder the CLI cannot write to (a read-only
// project, Windows Controlled Folder Access) must not stop a command after its
// job was submitted, so a failed write is a warning, given once per run.
let warnedUnwritable = false;
function append(project, line) {
    try {
        fs.appendFileSync(spendFile(project), JSON.stringify(line) + "\n");
    }
    catch (err) {
        if (warnedUnwritable)
            return;
        warnedUnwritable = true;
        process.stderr.write(`Warning: could not record spending (${err?.code || err?.message}); \`ludo spend\` and the budget will not count this run.\n`);
    }
}
export function recordEstimate(project, jobId, credits) {
    if (typeof jobId !== "string" || credits === undefined)
        return;
    append(project, { job_id: jobId, credits, kind: "estimate", at: new Date().toISOString() });
}
// What a finished job cost: its charge, or nothing when it failed or was
// canceled (refunded). A success without a charge keeps its estimate.
export function recordFinal(project, job) {
    if (!job || typeof job.id !== "string")
        return;
    const charged = typeof job.credits_charged === "number" ? job.credits_charged : job.status === "succeeded" ? undefined : 0;
    if (charged === undefined)
        return;
    append(project, { job_id: job.id, credits: charged, kind: "final", at: new Date().toISOString() });
}
export function readSpend(project) {
    let text = "";
    try {
        text = fs.readFileSync(spendFile(project), "utf8");
    }
    catch {
        // No ledger yet.
    }
    const perJob = new Map();
    let since;
    for (const raw of text.split("\n")) {
        if (!raw.trim())
            continue;
        let line;
        try {
            line = JSON.parse(raw);
        }
        catch {
            continue; // a torn line from a crash
        }
        if (line.kind === "reset") {
            perJob.clear();
            since = line.at;
            continue;
        }
        if (!line.job_id || typeof line.credits !== "number")
            continue;
        since = since || line.at;
        const j = perJob.get(line.job_id) || {};
        if (line.kind === "final")
            j.final = line.credits;
        else if (j.estimate === undefined)
            j.estimate = line.credits;
        perJob.set(line.job_id, j);
    }
    let spent = 0;
    for (const j of perJob.values())
        spent += j.final ?? j.estimate ?? 0;
    return { spent: Math.round(spent * 100) / 100, jobs: perJob.size, since: since || new Date().toISOString() };
}
export function resetSpend(project) {
    const at = new Date().toISOString();
    fs.writeFileSync(spendFile(project), JSON.stringify({ kind: "reset", at }) + "\n");
    return { spent: 0, jobs: 0, since: at };
}
export function budgetLimit(project) {
    const env = process.env.LUDO_MAX_CREDITS;
    if (env !== undefined && env !== "") {
        const n = Number(env);
        if (!Number.isFinite(n) || n < 0)
            throw new CliError(`LUDO_MAX_CREDITS must be a number of credits (got "${env}")`, EXIT.USAGE);
        return { limit: n, source: "LUDO_MAX_CREDITS" };
    }
    if (project?.config.max_credits !== undefined)
        return { limit: project.config.max_credits, source: `max_credits in ${project.file}` };
    return {};
}
// Adds up the estimates of everything about to be submitted.
export function totalOf(prices) {
    if (prices.some(p => p.credits === undefined))
        return { exact: false, note: prices.find(p => p.credits === undefined)?.note };
    return {
        credits: Math.round(prices.reduce((sum, p) => sum + (p.credits || 0), 0) * 10) / 10,
        exact: prices.every(p => p.exact),
        note: prices.find(p => !p.exact)?.note
    };
}
export function checkBudget(project, total, opts) {
    const { limit, source } = budgetLimit(project);
    if (opts.maxCredits === undefined && limit === undefined)
        return;
    if (total.credits === undefined) {
        if (opts.force)
            return;
        throw new CliError(`The price of this request cannot be known before it runs (${total.note || "unknown"}), and a spending limit is set.`, EXIT.BUDGET, "Check the price in the command's --help, then pass --force to run it anyway.");
    }
    if (opts.maxCredits !== undefined && total.credits > opts.maxCredits) {
        throw new CliError(`This would cost ${total.exact ? "" : "up to "}${formatCredits(total.credits)}, over --max-credits ${opts.maxCredits}.`, EXIT.BUDGET, "Raise --max-credits, or lower the duration, model or --n.");
    }
    if (limit !== undefined) {
        const { spent } = readSpend(project);
        if (spent + total.credits > limit) {
            throw new CliError(`Spending budget reached: ${formatCredits(spent)} spent of ${formatCredits(limit)} (${source}); this would cost ${total.exact ? "" : "up to "}${formatCredits(total.credits)}.`, EXIT.BUDGET, "Ask the user before spending more. They can raise the budget or start a new tally with `ludo spend reset`.");
        }
    }
}
