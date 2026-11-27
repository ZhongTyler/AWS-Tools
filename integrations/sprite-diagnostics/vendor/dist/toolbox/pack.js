import { blit, crop } from "./sheet.js";
import { resizeNearest, resizeSmooth } from "./resample.js";
import { calculateAnimationCharacterHeight, calculateAnimationTrimBounds, calculateCharacterBounds, calculateGroundOffsetFromBounds, computeFramePlacement, computePackNormalization } from "./packMath.js";
const pixelData = (img) => ({ data: img.rgba, width: img.width, height: img.height });
export function buildPack(inputs, opts) {
    const prepared = inputs.map(input => {
        const data = input.frames.map(pixelData);
        const trim = calculateAnimationTrimBounds({ frames: data });
        const groundAuto = -calculateGroundOffsetFromBounds(calculateCharacterBounds(data[0]), trim);
        return { input, data, trim, groundAuto, animCharHeight: calculateAnimationCharacterHeight({ frames: data }) };
    });
    // The web's getters: a size of 0 means 1, a missing ground means 0 once
    // the default is filled in.
    const size = (p) => p.input.size || 1;
    const groundOffset = (p) => -(p.input.ground ?? p.groundAuto) || 0;
    const offsetX = (p) => p.input.offsetX || 0;
    const { targetHeight, scales, frameSize } = computePackNormalization(prepared.map(p => ({
        animCharHeight: p.animCharHeight,
        sizeMultiplier: size(p),
        groundOffset: groundOffset(p),
        horizontalOffset: offsetX(p),
        frameBounds: p.data.map(() => ({ width: p.trim.width, height: p.trim.height }))
    })), opts.frameSize);
    const maxGroundOffset = Math.max(0, ...prepared.map((p, i) => groundOffset(p) * scales[i]));
    const resize = opts.art === "pixel" ? resizeNearest : resizeSmooth;
    const animations = prepared.map((p, i) => {
        const scale = scales[i];
        const scaledWidth = p.trim.width * scale;
        const scaledHeight = p.trim.height * scale;
        const { charX, charY } = computeFramePlacement({
            frameWidth: frameSize.width,
            frameHeight: frameSize.height,
            maxGroundOffset,
            groundOffset: groundOffset(p) * scale,
            scaledWidth,
            scaledHeight,
            horizontalOffset: offsetX(p),
            scale
        });
        const [w, h] = [Math.round(scaledWidth), Math.round(scaledHeight)];
        const frames = p.input.frames.map(frame => {
            const out = { width: frameSize.width, height: frameSize.height, rgba: new Uint8Array(frameSize.width * frameSize.height * 4) };
            if (w > 0 && h > 0) {
                const box = crop(frame, { x: p.trim.cropX, y: p.trim.cropY, w: p.trim.cropWidth, h: p.trim.cropHeight });
                blit(out, w === box.width && h === box.height ? box : resize(box, w, h), charX, charY);
            }
            return out;
        });
        return { frames, scale, size: size(p), ground: -groundOffset(p) || 0, groundAuto: p.groundAuto || 0, offsetX: offsetX(p), trim: p.trim };
    });
    return { frameWidth: frameSize.width, frameHeight: frameSize.height, targetHeight, groundLine: maxGroundOffset, animations };
}
