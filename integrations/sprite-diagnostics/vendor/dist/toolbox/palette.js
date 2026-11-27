import fs from "node:fs";
import path from "node:path";
import { encodePng, readPng } from "../tty/png.js";
import { readInput } from "./read-file.js";
import { makeDir } from "./io.js";
export const PALETTE_EXTENSIONS = [".hex", ".gpl", ".pal", ".txt", ".png"];
const hex2 = (n) => n.toString(16).padStart(2, "0");
export const hexOf = (c) => `#${hex2(c[0])}${hex2(c[1])}${hex2(c[2])}`;
const key = (c) => (c[0] << 16) | (c[1] << 8) | c[2];
function unique(colours) {
    const seen = new Set();
    return colours.filter(c => !seen.has(key(c)) && seen.add(key(c)));
}
export class PaletteError extends Error {
}
// "#1a1c2c,#5d275d" or "1a1c2c 5d275d".
export function parseHexList(text) {
    const parts = text.split(/[\s,;]+/).filter(Boolean);
    return unique(parts.map(p => {
        const m = /^#?([0-9a-f]{6}|[0-9a-f]{3})$/i.exec(p);
        if (!m)
            throw new PaletteError(`"${p}" is not a hex colour`);
        const h = m[1].length === 3 ? [...m[1]].map(c => c + c).join("") : m[1];
        return [parseInt(h.slice(0, 2), 16), parseInt(h.slice(2, 4), 16), parseInt(h.slice(4, 6), 16)];
    }));
}
export function parsePalette(text, ext) {
    const lines = text.replace(/^﻿/, "").split(/\r?\n/);
    const rgb = (l, n) => {
        const v = l.trim().split(/\s+/).slice(0, 3).map(Number);
        if (v.length < 3 || v.some(x => !Number.isInteger(x) || x < 0 || x > 255))
            throw new PaletteError(`line ${n + 1}: "${l.trim()}" is not "r g b"`);
        return v;
    };
    switch (ext) {
        case ".gpl": {
            if (!/^GIMP Palette\s*$/.test(lines[0] ?? ""))
                throw new PaletteError('a GIMP palette starts with "GIMP Palette"');
            const out = [];
            lines.slice(1).forEach((l, i) => {
                if (!l.trim() || l.startsWith("#") || /^(Name|Columns):/.test(l))
                    return;
                out.push(rgb(l, i + 1));
            });
            return unique(out);
        }
        case ".pal": {
            if (lines[0]?.trim() !== "JASC-PAL")
                throw new PaletteError('a JASC palette starts with "JASC-PAL"');
            const count = Number(lines[2]);
            if (!Number.isInteger(count) || count < 1)
                throw new PaletteError("a JASC palette's third line is its colour count");
            const out = lines
                .slice(3)
                .filter(l => l.trim())
                .slice(0, count)
                .map((l, i) => rgb(l, i + 3));
            if (out.length < count)
                throw new PaletteError(`the JASC palette says ${count} colours and has ${out.length}`);
            return unique(out);
        }
        case ".txt": {
            const out = [];
            lines.forEach((l, i) => {
                const t = l.trim();
                if (!t || t.startsWith(";"))
                    return;
                const m = /^([0-9a-f]{2})?([0-9a-f]{6})$/i.exec(t);
                if (!m)
                    throw new PaletteError(`line ${i + 1}: "${t}" is not aarrggbb`);
                out.push(parseHexList(m[2])[0]);
            });
            return unique(out);
        }
        default:
            return parseHexList(lines.filter(l => l.trim() && !l.trim().startsWith(";")).join(" "));
    }
}
export function formatPalette(colours, ext, name = "ludo") {
    switch (ext) {
        case ".gpl":
            return `GIMP Palette\nName: ${name}\nColumns: ${Math.min(colours.length, 16)}\n#\n${colours.map(c => `${String(c[0]).padStart(3)} ${String(c[1]).padStart(3)} ${String(c[2]).padStart(3)}\t${hexOf(c)}`).join("\n")}\n`;
        case ".pal":
            return `JASC-PAL\r\n0100\r\n${colours.length}\r\n${colours.map(c => c.join(" ")).join("\r\n")}\r\n`;
        case ".txt":
            return `;paint.net Palette File\n;Palette Name: ${name}\n;Colors: ${colours.length}\n${colours.map(c => `FF${hexOf(c).slice(1).toUpperCase()}`).join("\n")}\n`;
        default:
            return colours.map(c => hexOf(c).slice(1)).join("\n") + "\n";
    }
}
// A palette's swatches: one pixel per colour, in a row (up to 256 wide).
export function paletteImage(colours) {
    const w = Math.min(colours.length, 256) || 1;
    const h = Math.ceil(colours.length / w) || 1;
    const rgba = new Uint8Array(w * h * 4);
    colours.forEach((c, i) => rgba.set([...c, 255], i * 4));
    return { width: w, height: h, rgba };
}
// The opaque colours of an image (alpha over 0), in reading order, with how
// many pixels have each.
export function coloursOf(images) {
    const counts = new Map();
    for (const img of images) {
        for (let i = 0; i < img.rgba.length; i += 4) {
            if (!img.rgba[i + 3])
                continue;
            const k = (img.rgba[i] << 16) | (img.rgba[i + 1] << 8) | img.rgba[i + 2];
            counts.set(k, (counts.get(k) ?? 0) + 1);
        }
    }
    return [...counts].map(([k, count]) => ({ colour: [(k >> 16) & 255, (k >> 8) & 255, k & 255], count }));
}
// A palette from a file (by its extension; an image's colours for .png) or
// a list of hex colours.
export function loadPalette(spec) {
    const ext = path.extname(spec).toLowerCase();
    if (!fs.existsSync(spec)) {
        if (PALETTE_EXTENSIONS.includes(ext) || /[\\/]/.test(spec))
            throw new PaletteError(`File not found: ${spec}`);
        return parseHexList(spec);
    }
    const buf = readInput(spec, "a palette");
    if (ext === ".png")
        return coloursOf([readPng(buf).image]).map(c => c.colour);
    return parsePalette(buf.toString("utf8"), ext);
}
export function savePalette(file, colours) {
    const ext = path.extname(file).toLowerCase();
    makeDir(path.dirname(file));
    if (ext === ".png")
        fs.writeFileSync(file, encodePng(paletteImage(colours)));
    else
        fs.writeFileSync(file, formatPalette(colours, ext, path.basename(file, ext)));
}
