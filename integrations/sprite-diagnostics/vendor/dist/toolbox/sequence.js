import { alignSprites, groundAlignment } from "./align.js";
import { resizeNearest, resizeSmooth } from "./resample.js";
import { blit } from "./sheet.js";
import { cropBounds, footedAlignment, frameFooting, nextSequenceSlot, paddedFrameLayout, sequenceCanvasBounds } from "./sequenceMath.js";
const resizer = (art) => (art === "pixel" ? resizeNearest : resizeSmooth);
const sized = (img, w, h, resize) => (w === img.width && h === img.height ? img : resize(img, w, h));
/** The box around a frame's content (alpha above 10), or null when empty. */
function contentBox(img) {
    let [minX, minY, maxX, maxY] = [img.width, img.height, -1, -1];
    for (let y = 0; y < img.height; y++) {
        for (let x = 0; x < img.width; x++) {
            if (img.rgba[(y * img.width + x) * 4 + 3] > 10) {
                if (x < minX)
                    minX = x;
                if (x > maxX)
                    maxX = x;
                if (y < minY)
                    minY = y;
                if (y > maxY)
                    maxY = y;
            }
        }
    }
    return maxX < 0 ? null : { minX, minY, maxX, maxY };
}
export function align(a, b, mode) {
    if (mode === "none")
        return { dx: 0, dy: 0, scale: 1, confidence: Number.NaN, method: "none" };
    if (mode === "ground")
        return groundAlignment(a, b);
    return footedAlignment(alignSprites(a, b), frameFooting(a.rgba, a.width, a.height), frameFooting(b.rgba, b.width, b.height));
}
export function buildSequence(animations, opts) {
    const first = animations[0][0];
    const slots = [{ x: 0, y: 0, w: first.width, h: first.height }];
    const transitions = [];
    for (let i = 0; i + 1 < animations.length; i++) {
        const prev = slots[i];
        const next = animations[i + 1][0];
        // The previous animation's last frame as it is drawn, against the next
        // one's first frame at its own size.
        const t = opts.transitions?.[i] ?? align(sized(animations[i][animations[i].length - 1], prev.w, prev.h, resizeSmooth), next, opts.align);
        transitions.push(t);
        slots.push(nextSequenceSlot(prev, t, next.width, next.height));
    }
    const { canvasW, canvasH, shiftX, shiftY } = sequenceCanvasBounds(slots);
    const resize = resizer(opts.art);
    const drawn = animations.map((frames, i) => frames.map(f => sized(f, slots[i].w, slots[i].h, resize)));
    // Each frame's content on the canvas; an empty frame counts as the whole
    // canvas, as the web's bounds scan does.
    const boxes = drawn.flatMap((frames, i) => frames.map(f => {
        const b = contentBox(f);
        const [x, y] = [slots[i].x + shiftX, slots[i].y + shiftY];
        return b ? { minX: b.minX + x, minY: b.minY + y, maxX: b.maxX + x, maxY: b.maxY + y } : { minX: 0, minY: 0, maxX: canvasW - 1, maxY: canvasH - 1 };
    }));
    const crop = cropBounds(boxes, canvasW, canvasH);
    const layout = paddedFrameLayout(crop.cropW, crop.cropH, opts.frameSize?.w, opts.frameSize?.h, opts.placement);
    const transformed = layout.frameW !== crop.cropW || layout.frameH !== crop.cropH || layout.drawH !== crop.cropH;
    const frames = drawn.map((list, i) => list.map(f => {
        const cropped = { width: crop.cropW, height: crop.cropH, rgba: new Uint8Array(crop.cropW * crop.cropH * 4) };
        blit(cropped, f, slots[i].x + shiftX - crop.minX, slots[i].y + shiftY - crop.minY);
        if (!transformed)
            return cropped;
        const out = { width: layout.frameW, height: layout.frameH, rgba: new Uint8Array(layout.frameW * layout.frameH * 4) };
        blit(out, sized(cropped, layout.drawW, layout.drawH, resize), layout.offsetX, layout.offsetY);
        return out;
    }));
    return { transitions, slots, content: { width: crop.cropW, height: crop.cropH, x: crop.minX - shiftX, y: crop.minY - shiftY }, layout, frames };
}
