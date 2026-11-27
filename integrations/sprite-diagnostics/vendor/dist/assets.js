import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { CliError, EXIT } from "./errors.js";
import { extensionFor, isInlineFile } from "./inline.js";
import { containedPath, writeJsonFile } from "./project.js";
// `ludo-assets.json`: one entry per file a generation saved, next to the
// project's .ludo.json (or in the output folder outside a project). It records
// how each asset was made, so `ludo assets redo <file>` can make it again (with
// changes), agents can see what already exists before generating more, and a
// variation set stays recognisable as one request.
//
// Paths are relative to the log, so the project can move.
//
// The log is an index, not a store: file content a request carried inline as
// base64 is kept once in ludo-inputs/ (git-ignored), named by its hash, and the
// entry holds that path. Copying it into every entry (one per saved file, so once per
// frame) grew one log past the longest string Node can write.
export const LOG_NAME = "ludo-assets.json";
export const INPUTS_DIR = "ludo-inputs";
export function logFile(project, outDir) {
    return path.join(project ? project.root : outDir, LOG_NAME);
}
function readLog(file, strict) {
    let text;
    try {
        text = fs.readFileSync(file, "utf8");
    }
    catch {
        return { root: {}, assets: [] };
    }
    let parsed;
    try {
        parsed = JSON.parse(text);
    }
    catch {
        throw new CliError(`${file} is not valid JSON; fix or remove it`, EXIT.USAGE);
    }
    const isObject = parsed !== null && typeof parsed === "object" && !Array.isArray(parsed);
    const assets = isObject ? parsed.assets : undefined;
    if (isObject && (assets === undefined || Array.isArray(assets))) {
        return { root: parsed, assets: assets ?? [] };
    }
    if (strict) {
        throw new CliError(`${file} must be a JSON object whose "assets" is a list; fix or remove it (it was left as it is)`, EXIT.USAGE);
    }
    return { root: {}, assets: [] };
}
export function readAssets(file) {
    return readLog(file, false).assets;
}
const LOCK_STALE_MS = 10_000;
const LOCK_WAIT_MS = 15_000;
function sleepSync(ms) {
    Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, ms);
}
// Parallel ludo processes (a batch in one terminal, an agent in another) all
// update the log: each read-modify-write holds <log>.lock, created with O_EXCL.
// A lock older than 10s belongs to a process that died, and is taken over.
export function withLock(file, fn) {
    const lock = `${file}.lock`;
    fs.mkdirSync(path.dirname(file), { recursive: true });
    const started = Date.now();
    for (;;) {
        try {
            fs.closeSync(fs.openSync(lock, "wx"));
            break;
        }
        catch (err) {
            if (err?.code !== "EEXIST")
                throw err;
            let age = 0;
            try {
                age = Date.now() - fs.statSync(lock).mtimeMs;
            }
            catch {
                continue; // released between the two calls
            }
            if (age > LOCK_STALE_MS || Date.now() - started > LOCK_WAIT_MS) {
                fs.rmSync(lock, { force: true });
                continue;
            }
            sleepSync(20 + Math.random() * 30);
        }
    }
    try {
        return fn();
    }
    finally {
        fs.rmSync(lock, { force: true });
    }
}
// Writes inline file content to ludo-inputs/<sha256><ext> (once) and returns
// its path relative to the log; undefined for anything that isn't file content.
// Bare base64 counts only when its first bytes name a file type.
function storeInline(value, logDir, memo) {
    const known = memo.get(value);
    if (known)
        return known;
    if (!isInlineFile(value))
        return undefined;
    const m = /^data:([^;,]+)[^,]*,/.exec(value);
    const buffer = Buffer.from(m ? value.slice(m[0].length) : value, "base64");
    const ext = extensionFor(buffer, m?.[1]);
    const rel = path.join(INPUTS_DIR, crypto.createHash("sha256").update(buffer).digest("hex") + ext);
    const abs = path.join(logDir, rel);
    if (!fs.existsSync(abs)) {
        fs.mkdirSync(path.dirname(abs), { recursive: true });
        // Copies of what was sent, not project files: the folder keeps itself out of git.
        const ignore = path.join(path.dirname(abs), ".gitignore");
        if (!fs.existsSync(ignore))
            fs.writeFileSync(ignore, "*\n");
        const tmp = `${abs}.${process.pid}.tmp`;
        fs.writeFileSync(tmp, buffer);
        fs.renameSync(tmp, abs);
    }
    memo.set(value, rel);
    return rel;
}
// Every body value (or array item) that is inline file content becomes a path.
// Runs over the whole log on each write, so a log from an older CLI shrinks the
// first time it is written.
function storeInlineBodies(entries, logDir) {
    const memo = new Map();
    const one = (v) => (typeof v === "string" ? (storeInline(v, logDir, memo) ?? v) : v);
    return entries.map(e => {
        if (!e.body)
            return e;
        let changed = false;
        const body = {};
        for (const [k, v] of Object.entries(e.body)) {
            body[k] = Array.isArray(v) ? v.map(one) : one(v);
            if (Array.isArray(v) ? body[k].some((x, i) => x !== v[i]) : body[k] !== v)
                changed = true;
        }
        return changed ? { ...e, body } : e;
    });
}
// Every write is a read-modify-write under the lock, and keeps the log's other
// top-level keys (in their place: a log holding only `assets` is written as
// before).
function rewriteAssets(file, fn) {
    withLock(file, () => {
        const { root, assets } = readLog(file, true);
        writeJsonFile(file, { ...root, assets: storeInlineBodies(fn(assets), path.dirname(file)) });
    });
}
// Adds entries; one already there for the same job and file is replaced.
export function appendAssets(file, entries) {
    if (!entries.length)
        return;
    const key = (e) => `${e.job_id ?? ""}\u0000${e.file}`;
    const incoming = new Set(entries.map(key));
    rewriteAssets(file, existing => [...existing.filter(e => !incoming.has(key(e))), ...entries]);
}
export function updateAssets(file, fn) {
    rewriteAssets(file, fn);
}
// Local file paths in a request body, rewritten relative to the log (and back).
// `files` are the body fields that take files.
export function relativizeBody(body, fileFields, logDir) {
    const out = { ...body };
    const one = (v) => {
        if (typeof v !== "string")
            return v;
        const p = v.startsWith("@") ? v.slice(1) : v;
        if (/^(https?:|data:)/i.test(p) || !fs.existsSync(p))
            return v;
        return path.relative(logDir, path.resolve(p)) || ".";
    };
    for (const f of fileFields) {
        if (Array.isArray(out[f]))
            out[f] = out[f].map(one);
        else if (out[f] !== undefined)
            out[f] = one(out[f]);
    }
    return out;
}
// The recorded body, with its local paths made absolute again. The log is a
// file in the repository, so its paths must stay inside `root`.
export function absolutizeBody(body, fileFields, logDir, root) {
    const out = { ...body };
    const one = (field) => (v) => (typeof v === "string" ? containedPath(root, logDir, v, `${field} in the asset log`) : v);
    for (const f of fileFields) {
        if (Array.isArray(out[f]))
            out[f] = out[f].map(one(f));
        else if (out[f] !== undefined)
            out[f] = one(f)(out[f]);
    }
    return out;
}
export function findAsset(entries, file, logDir) {
    const rel = path.relative(logDir, path.resolve(file));
    // The newest entry wins when a file was overwritten.
    return [...entries].reverse().find(e => e.file === rel || e.file === file);
}
