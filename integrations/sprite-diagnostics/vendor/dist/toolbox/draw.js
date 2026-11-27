import { ADVANCE, GLYPH_H, GLYPH_W, GLYPHS } from "./font.js";
import { scaleUp } from "./pixels.js";
import { resizeSmooth } from "./resample.js";
export function canvas(width, height, fill) {
    const rgba = new Uint8Array(width * height * 4);
    for (let i = 0; i < rgba.length; i += 4)
        rgba.set(fill, i);
    return { width, height, rgba };
}
// Source-over of one colour, with its alpha scaled by `cover` (0-1).
function blend(img, x, y, c, cover = 1) {
    if (x < 0 || y < 0 || x >= img.width || y >= img.height)
        return;
    const i = (y * img.width + x) * 4;
    const a = (c[3] / 255) * cover;
    if (a <= 0)
        return;
    const d = img.rgba;
    if (a >= 1) {
        d[i] = c[0];
        d[i + 1] = c[1];
        d[i + 2] = c[2];
        d[i + 3] = 255;
        return;
    }
    const da = d[i + 3] / 255;
    const oa = a + da * (1 - a);
    for (let k = 0; k < 3; k++)
        d[i + k] = Math.round((c[k] * a + d[i + k] * da * (1 - a)) / oa);
    d[i + 3] = Math.round(oa * 255);
}
export function fillRect(img, x, y, w, h, c) {
    const [x0, y0] = [Math.max(0, Math.round(x)), Math.max(0, Math.round(y))];
    const [x1, y1] = [Math.min(img.width, Math.round(x + w)), Math.min(img.height, Math.round(y + h))];
    for (let yy = y0; yy < y1; yy++)
        for (let xx = x0; xx < x1; xx++)
            blend(img, xx, yy, c);
}
// A box's outline, `t` pixels thick, drawn inside the box.
export function strokeRect(img, x, y, w, h, c, t = 1) {
    fillRect(img, x, y, w, t, c);
    fillRect(img, x, y + h - t, w, t, c);
    fillRect(img, x, y + t, t, h - 2 * t, c);
    fillRect(img, x + w - t, y + t, t, h - 2 * t, c);
}
// Bresenham's line, both ends included; `dash` draws that many pixels on,
// then as many off.
export function line(img, x0, y0, x1, y1, c, dash = 0) {
    [x0, y0, x1, y1] = [x0, y0, x1, y1].map(Math.round);
    const dx = Math.abs(x1 - x0);
    const dy = -Math.abs(y1 - y0);
    const sx = x0 < x1 ? 1 : -1;
    const sy = y0 < y1 ? 1 : -1;
    let err = dx + dy;
    for (let n = 0;; n++) {
        if (!dash || Math.floor(n / dash) % 2 === 0)
            blend(img, x0, y0, c);
        if (x0 === x1 && y0 === y1)
            return;
        const e2 = 2 * err;
        if (e2 >= dy) {
            err += dy;
            x0 += sx;
        }
        if (e2 <= dx) {
            err += dx;
            y0 += sy;
        }
    }
}
// A plus sign centred on (x, y), arms `arm` pixels long.
export function cross(img, x, y, arm, c, width = 1) {
    fillRect(img, x - arm, y - Math.floor((width - 1) / 2), 2 * arm + 1, width, c);
    fillRect(img, x - Math.floor((width - 1) / 2), y - arm, width, 2 * arm + 1, c);
}
export function dot(img, x, y, r, c) {
    for (let yy = -r; yy <= r; yy++)
        for (let xx = -r; xx <= r; xx++)
            if (xx * xx + yy * yy <= r * r + r)
                blend(img, Math.round(x) + xx, Math.round(y) + yy, c);
}
// The grey checkerboard editors draw under transparency, so a clear pixel
// and a black one look different.
export function checkerboard(img, x, y, w, h, size = 8, light = [204, 204, 204, 255], dark = [168, 168, 168, 255]) {
    for (let yy = 0; yy < h; yy++) {
        for (let xx = 0; xx < w; xx++) {
            const c = (Math.floor(xx / size) + Math.floor(yy / size)) % 2 ? dark : light;
            blend(img, x + xx, y + yy, c);
        }
    }
}
// `src` composited over `dst` at (x, y), its alpha times `opacity`.
export function drawImage(dst, src, x, y, opacity = 1) {
    for (let yy = 0; yy < src.height; yy++) {
        for (let xx = 0; xx < src.width; xx++) {
            const i = (yy * src.width + xx) * 4;
            const a = src.rgba[i + 3];
            if (a)
                blend(dst, x + xx, y + yy, [src.rgba[i], src.rgba[i + 1], src.rgba[i + 2], a], opacity);
        }
    }
}
// An image at `scale` times its size: whole factors by nearest neighbour,
// so pixel art keeps its pixels; anything smaller by area averaging (to the
// rounded size), so a big frame shrinks without aliasing.
export function scaled(img, scale) {
    if (scale === 1)
        return img;
    if (scale > 1 && Number.isInteger(scale))
        return scaleUp(img, scale);
    return resizeSmooth(img, Math.max(1, Math.round(img.width * scale)), Math.max(1, Math.round(img.height * scale)));
}
// The width of a line of text at `size` (pixels per font pixel); the
// height is textHeight.
export const textWidth = (text, size = 1) => Math.max(0, [...text].length * ADVANCE - 1) * size;
export const textHeight = (size = 1) => GLYPH_H * size;
// Text with its top-left at (x, y). Returns the x after it.
export function text(img, x, y, s, c, size = 1) {
    for (const ch of s) {
        const bits = GLYPHS.get(ch) ?? GLYPHS.get("?");
        for (let r = 0; r < GLYPH_H; r++) {
            for (let col = 0; col < GLYPH_W; col++) {
                if (bits[r] & (1 << (GLYPH_W - 1 - col)))
                    fillRect(img, x + col * size, y + r * size, size, size, c);
            }
        }
        x += ADVANCE * size;
    }
    return x;
}
// The longest prefix of `s` that fits `width` at `size`, with "..." when cut.
export function fitText(s, width, size = 1) {
    if (textWidth(s, size) <= width)
        return s;
    const chars = [...s];
    while (chars.length && textWidth(chars.join("") + "...", size) > width)
        chars.pop();
    return chars.length ? chars.join("") + "..." : "";
}
