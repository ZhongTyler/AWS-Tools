import fs from "node:fs";
import { readText, withText } from "./png.js";
import { loadImage } from "./image.js";
import { armRestore, sleep } from "./visuals.js";
import { cellSize, crop, detectProtocol, imageSequence } from "./graphics.js";
import { exitNow } from "../shutdown.js";
export const GRID_KEY = "ludo:grid";
// The grid is stored in the saved PNG itself, so a Ludo spritesheet plays in
// `ludo preview` however it is renamed or moved.
export function gridFromResult(result) {
    const frames = Number(result?.num_frames);
    let cols = Number(result?.num_cols);
    let rows = Number(result?.num_rows);
    if (!frames || frames < 2)
        return undefined;
    if (!cols || !rows) {
        const side = Math.round(Math.sqrt(frames));
        if (side * side !== frames)
            return undefined;
        cols = rows = side;
    }
    // A sheet says its frame rate (Directional Sprites) or its duration.
    const rate = Number(result?.fps);
    const duration = Number(result?.duration);
    const fps = rate > 0 ? rate : duration > 0 ? frames / duration : 10;
    const grid = { cols, rows, frames, fps: Math.round(fps * 100) / 100 };
    if (result?.loop === false)
        grid.loop = false;
    return grid;
}
// A new grid for frames that came from `from`: a one-shot animation stays one.
export const keepLoop = (grid, from) => (from?.loop === false ? { ...grid, loop: false } : grid);
export function stampGrid(file, grid) {
    try {
        const buf = fs.readFileSync(file);
        const stamped = withText(buf, GRID_KEY, JSON.stringify(grid));
        if (stamped !== buf)
            fs.writeFileSync(file, stamped);
    }
    catch {
        // An unstamped sheet still previews as a still image.
    }
}
export function readGrid(buf) {
    try {
        const g = JSON.parse(readText(buf)[GRID_KEY] || "null");
        if (g && g.cols > 0 && g.rows > 0 && g.frames > 0) {
            const grid = { cols: g.cols, rows: g.rows, frames: g.frames, fps: g.fps > 0 ? g.fps : 10 };
            if (g.loop === false)
                grid.loop = false;
            return grid;
        }
    }
    catch {
        // Not ours.
    }
    return undefined;
}
// "8x4" -> {cols: 8, rows: 4}
export function parseGrid(spec) {
    const m = /^(\d+)\s*[x×]\s*(\d+)$/i.exec(spec.trim());
    return m ? { cols: Number(m[1]), rows: Number(m[2]) } : undefined;
}
// Real images only (Kitty's protocol or iTerm2's). A terminal without either
// gets a one-line note saying how to see the result instead.
export function canShowImages() {
    return !!detectProtocol();
}
// What to tell a person whose terminal cannot show the preview, and how to
// get one.
export function previewSkipped() {
    const inTmux = !!process.env.TMUX || /^screen/.test(process.env.TERM || "");
    return inTmux
        ? "Preview skipped: tmux does not pass images through. Run outside tmux, or add --open to view it."
        : "Preview skipped: this terminal can't show images. Previews work in iTerm2, Kitty, Ghostty and WezTerm; or add --open to view it.";
}
// Frames drawn in a reserved block of rows: save the spot, draw, restore.
function reserve(rows) {
    process.stderr.write("\n".repeat(rows) + `\x1b[${rows}A\x1b7`);
}
function release(rows) {
    process.stderr.write(`\x1b8\x1b[${rows}B\r`);
}
function imageFrame(img, r, v, id) {
    const frame = crop(img, r);
    const { cols, rows } = cellSize(frame, Math.min(48, v.columns - 4), 16);
    return { seq: imageSequence(detectProtocol(), frame, cols, rows, id), rows };
}
export function drawStill(img, v, region) {
    if (!canShowImages())
        return false;
    const r = region || { x: 0, y: 0, w: img.width, h: img.height };
    const { seq, rows } = imageFrame(img, r, v);
    reserve(rows);
    process.stderr.write(`\x1b[2C${seq}`);
    release(rows);
    return true;
}
function frameRect(img, grid, i) {
    if (img.width % grid.cols !== 0 || img.height % grid.rows !== 0)
        return undefined;
    const w = img.width / grid.cols;
    const h = img.height / grid.rows;
    return { x: (i % grid.cols) * w, y: Math.floor(i / grid.cols) * h, w, h };
}
// Plays the sheet a few times in place, then leaves the last frame on screen.
// Never reads stdin; Ctrl-C stops it and the exit hook restores the cursor.
// Returns "none" when this terminal has no good way to show it.
export async function playSheet(img, grid, v, loops = 3) {
    const first = frameRect(img, grid, 0);
    if (!first || grid.frames > grid.cols * grid.rows)
        return "invalid";
    if (!canShowImages())
        return "none";
    armRestore();
    const frameMs = Math.max(40, Math.min(500, 1000 / grid.fps));
    const total = Math.min(grid.frames * loops, Math.ceil(6000 / frameMs)); // cap at ~6s
    // Ctrl-C mid-animation: leave the terminal tidy and exit like any interrupt.
    const onInt = () => {
        process.stderr.write("\x1b[0m\x1b[?25h\n");
        exitNow(130);
    };
    process.once("SIGINT", onInt);
    process.stderr.write("\x1b[?25l");
    // Encode each frame once. Kitty replaces image 1 in place, so frames swap
    // without flicker; iTerm2 simply draws over the same cells.
    const frames = Array.from({ length: grid.frames }, (_, i) => imageFrame(img, frameRect(img, grid, i), v, 1));
    const rows = frames[0].rows;
    reserve(rows);
    for (let n = 0; n < total; n++) {
        process.stderr.write(`\x1b8\x1b[2C${frames[n % grid.frames].seq}`);
        await sleep(frameMs);
    }
    release(rows);
    process.stderr.write("\x1b[?25h");
    process.removeListener("SIGINT", onInt);
    return "played";
}
// The preview for a saved file: plays a sheet whose grid is known, shows
// anything else as a still. "unsupported" means this terminal cannot show
// images (see previewSkipped); "failed" that the file could not be read.
export async function previewFile(file, v, gridOverride) {
    if (!v.enabled)
        return "failed";
    if (!canShowImages())
        return "unsupported";
    try {
        const img = loadImage(file);
        if (!img)
            return "failed";
        const grid = gridOverride || readGrid(fs.readFileSync(file));
        if (grid) {
            const played = await playSheet(img, grid, v);
            if (played === "played")
                return "shown";
            if (played === "none")
                return "unsupported";
        }
        return drawStill(img, v) ? "shown" : "unsupported";
    }
    catch {
        return "failed";
    }
}
