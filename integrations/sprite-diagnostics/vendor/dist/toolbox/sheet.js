// Where each frame sits, in reading order. Every frame has the same size,
// floor(W / cols) x floor(H / rows), placed at round(col * W / cols): the
// same cut as the web's exporter, so a sheet whose size does not divide
// evenly still gives equal frames.
export function frameRects(width, height, cols, rows, frames = cols * rows) {
    const w = Math.floor(width / cols);
    const h = Math.floor(height / rows);
    const out = [];
    for (let f = 0; f < frames; f++) {
        const c = f % cols;
        const r = Math.floor(f / cols);
        out.push({ x: Math.min(Math.round((c * width) / cols), width - w), y: Math.min(Math.round((r * height) / rows), height - h), w, h });
    }
    return out;
}
export function crop(img, r) {
    const rgba = new Uint8Array(r.w * r.h * 4);
    for (let y = 0; y < r.h; y++) {
        const from = ((r.y + y) * img.width + r.x) * 4;
        rgba.set(img.rgba.subarray(from, from + r.w * 4), y * r.w * 4);
    }
    return { width: r.w, height: r.h, rgba };
}
export function sliceSheet(img, cols, rows, frames = cols * rows) {
    return frameRects(img.width, img.height, cols, rows, frames).map(r => crop(img, r));
}
// Frames into a sheet, in reading order, `cols` to a row. Frames of
// different sizes are centred in cells of the largest width and height.
export function joinFrames(frames, cols) {
    const cellW = Math.max(...frames.map(f => f.width));
    const cellH = Math.max(...frames.map(f => f.height));
    const rows = Math.ceil(frames.length / cols);
    const width = cellW * cols;
    const sheet = { width, height: cellH * rows, rgba: new Uint8Array(width * cellH * rows * 4) };
    frames.forEach((f, i) => {
        const x0 = (i % cols) * cellW + Math.floor((cellW - f.width) / 2);
        const y0 = Math.floor(i / cols) * cellH + Math.floor((cellH - f.height) / 2);
        for (let y = 0; y < f.height; y++)
            sheet.rgba.set(f.rgba.subarray(y * f.width * 4, (y + 1) * f.width * 4), ((y0 + y) * width + x0) * 4);
    });
    return { sheet, cellW, cellH, rows };
}
// Copies `src` onto `dst` at (x, y), clipped to dst (source-over onto
// transparent cells is a copy).
export function blit(dst, src, x, y) {
    const x0 = Math.max(0, x);
    const x1 = Math.min(dst.width, x + src.width);
    if (x1 <= x0)
        return;
    for (let row = Math.max(0, y); row < Math.min(dst.height, y + src.height); row++) {
        const from = ((row - y) * src.width + (x0 - x)) * 4;
        dst.rgba.set(src.rgba.subarray(from, from + (x1 - x0) * 4), (row * dst.width + x0) * 4);
    }
}
/** Frames into a sheet of `cols` x `rows` cells, in reading order. */
export function layoutSheet(frames, cols, rows) {
    const { width: fw, height: fh } = frames[0];
    const sheet = { width: fw * cols, height: fh * rows, rgba: new Uint8Array(fw * cols * fh * rows * 4) };
    frames.forEach((f, i) => blit(sheet, f, (i % cols) * fw, Math.floor(i / cols) * fh));
    return sheet;
}
