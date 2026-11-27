const round1 = (n) => Math.round(n * 10) / 10;
// The price table names models by label ("Griffin", "Hydra+"); the model
// field's description pairs each label with its id:
//   - "griffin-hd" (Griffin): flat 12 credits per generation · ...
export function modelLabels(description) {
    const labels = new Map();
    for (const m of (description || "").matchAll(/^\s*-\s*"([^"]+)"\s*\(([^)]+)\)/gm))
        labels.set(m[2].trim(), m[1]);
    return labels;
}
// With no label listed: "Eagle with Audio" -> eagle-audio, "Forge Pixel" -> forge-pixel.
const modelId = (name, labels) => labels?.get(name.trim()) ?? name.trim().toLowerCase().replace(/\s+with\s+/g, "-").replace(/\s+/g, "-");
export function parseModelRates(text, labels) {
    const listed = text.split(/Available models:\s*/)[1];
    if (!listed)
        return [];
    const rates = [];
    for (const part of listed.split(" · ")) {
        const flat = /^(.+?) \(flat ([\d.]+) credits? per generation\)/.exec(part.trim());
        if (flat) {
            rates.push({ id: modelId(flat[1], labels), rate: 0, minimum: 0, shortest: 0, longest: 0, flat: Number(flat[2]) });
            continue;
        }
        const m = /^(.+?) \(([\d.]+) credits\/s(?:, shortest duration ([\d.]+)s, so ([\d.]+) credits minimum|, minimum charge ([\d.]+) credits? per generation)?(?:; ([^)]*))?\)/.exec(part.trim());
        if (!m)
            continue;
        const seconds = [...(m[6] || "").matchAll(/([\d.]+)s = /g)].map(x => Number(x[1]));
        rates.push({
            id: modelId(m[1], labels),
            rate: Number(m[2]),
            minimum: Number(m[4] || m[5] || 0),
            // Newer specs state only the minimum charge ("minimum charge 9 credits
            // per generation"); the duration table still starts at the shortest.
            shortest: Number(m[3] || 0) || (seconds.length ? Math.min(...seconds) : 0),
            longest: seconds.length ? Math.max(...seconds) : 0
        });
    }
    return rates;
}
function fieldDefault(command, name) {
    return command.fields.find(f => f.name === name)?.default;
}
// create3DModel prices each model and an optional rig:
//   "consumes 4 credits per call with model "prop" (default), 15 credits per
//    call with model "hero"; rig true adds 1 credit when the model comes back
//    rigged"
// The rig credit is charged only when the result is rigged, so with rig the
// estimate is an upper bound.
function perCallPrice(command, body, text, first) {
    const byModel = [...text.matchAll(/([\d.]+) credits? per call with model "([^"]+)"/gi)];
    let credits = first;
    const notes = [];
    if (byModel.length) {
        const model = String(body.model ?? fieldDefault(command, "model") ?? "");
        const known = byModel.find(m => m[2] === model);
        credits = known ? Number(known[1]) : Math.max(...byModel.map(m => Number(m[1])));
        if (!known)
            notes.push("the model's price is not listed, so the dearest model's price is used");
    }
    const rig = /rig true adds ([\d.]+) credits?/i.exec(text);
    const rigged = body.rig ?? fieldDefault(command, "rig");
    if (rig && (rigged === true || rigged === "true")) {
        credits += Number(rig[1]);
        notes.push("the rig credit is charged only if the model comes back rigged");
    }
    if (!notes.length)
        return { credits: round1(credits), exact: true };
    return { credits: round1(credits), exact: false, note: `at most (${notes.join("; ")})` };
}
export function estimatePrice(command, body) {
    const text = command.creditDetail || command.credits || "";
    if (!text)
        return { credits: 0, exact: true };
    const perResult = /consumes ([\d.]+) credits? per result/i.exec(text);
    if (perResult) {
        const n = Number(body.n ?? fieldDefault(command, "n") ?? 1) || 1;
        // editImage with a mask runs inpainting, which has its own rate.
        const masked = body.mask ? /([\d.]+) credits? per result with a mask/i.exec(text) : null;
        return { credits: round1(Number((masked || perResult)[1]) * n), exact: true };
    }
    // Directional Sprites / Stills: "consumes 0.5 credits per direction (one
    // image each)", times the directions asked for (the spec's default is ["SW"]).
    const perDirection = /consumes ([\d.]+) credits? per direction/i.exec(text);
    if (perDirection) {
        const directions = body.directions ?? fieldDefault(command, "directions") ?? ["SW"];
        const count = Array.isArray(directions)
            ? directions.length
            : String(directions).split(",").filter(s => s.trim()).length;
        return { credits: round1(Number(perDirection[1]) * Math.max(1, count)), exact: true };
    }
    const perCall = /consumes ([\d.]+) credits? per call/i.exec(text);
    if (perCall)
        return perCallPrice(command, body, text, Number(perCall[1]));
    const rates = parseModelRates(text, modelLabels(command.fields.find(f => f.name === "model")?.description));
    const requested = typeof body.duration === "number" ? body.duration : fieldDefault(command, "duration");
    const longest = Math.max(0, ...rates.map(r => r.longest));
    // editSpritesheet's loop fixes, outpaints and improves: flat per second,
    // model ignored, held for and capped at the source sheet's video length, so
    // `duration` does not change the price and the longest duration stands in.
    const mode = body.edit_mode ?? fieldDefault(command, "edit_mode");
    const flat = mode === "fix_loop" || mode === "outpaint"
        ? /edit_mode "fix_loop" \/ "outpaint": flat ([\d.]+) credits? per second/i.exec(text)
        : mode === "improve"
            ? /edit_mode "improve"[^:;]*: flat ([\d.]+) credits? per second/i.exec(text)
            : null;
    if (flat) {
        if (!longest)
            return { exact: false, note: "the price depends on the source's duration" };
        return { credits: round1(Number(flat[1]) * longest), exact: false, note: "at most, for the source's length" };
    }
    if (rates.length) {
        const model = String(body.model ?? fieldDefault(command, "model") ?? "");
        const known = rates.find(r => r.id === model);
        // An unlisted model (an alias, a new one) is priced as the dearest listed.
        const candidates = known ? [known] : rates;
        if (known?.flat !== undefined)
            return { credits: round1(known.flat), exact: true };
        const priceFor = (r) => {
            if (r.flat !== undefined)
                return round1(r.flat);
            const seconds = Math.max(requested ?? (r.longest || longest), r.shortest);
            return round1(Math.max(r.rate * seconds, r.minimum));
        };
        const credits = Math.max(...candidates.map(priceFor));
        const notes = [!known && "the model's price is not listed, so the dearest model's price is used", requested === undefined && "for the longest duration"].filter(Boolean);
        return { credits, exact: false, note: notes.length ? `at most (${notes.join("; ")})` : "at most" };
    }
    return { exact: false, note: "the price depends on the source file (see the command's --help)" };
}
export function formatCredits(n) {
    return `${n.toLocaleString("en-US", { maximumFractionDigits: 2 })} credit${n === 1 ? "" : "s"}`;
}
