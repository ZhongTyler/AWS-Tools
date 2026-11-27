// Engine files written next to a spritesheet (--engine): a Godot 4
// SpriteFrames .tres, a TexturePacker JSON atlas for PixiJS and Phaser, or
// Unity's import settings and AnimationClip.
import { writeGodotScene, writeGodotSpriteFrames } from "./godot.js";
import { writeTextureAtlas } from "./texturepacker.js";
import { writeUnityFiles } from "./unity.js";
import { noteFact } from "../telemetry.js";
export const ENGINES = ["godot", "texturepacker", "unity"];
export const ENGINE_FILE = {
    godot: "Godot SpriteFrames",
    texturepacker: "TexturePacker JSON",
    unity: "Unity sprite import and AnimationClip"
};
/**
 * Writes the engine's files for the sheet and returns their paths.
 * `animation` names the animation (default: "default" for Godot, as its
 * editor does; the sheet's file name for TexturePacker, whose atlases often
 * hold several, and for Unity). Throws a plain Error with a readable message.
 */
export function writeEngineFile(engine, sheetPath, width, height, grid, layout = {}, animation, options = {}) {
    noteFact("engine", engine);
    if (engine === "godot") {
        const tres = writeGodotSpriteFrames(sheetPath, width, height, grid, animation, layout);
        return options.pivot ? [tres, writeGodotScene(tres, width, height, grid, options.pivot, animation, layout)] : [tres];
    }
    if (engine === "unity")
        return writeUnityFiles(sheetPath, width, height, grid, animation, layout, options);
    const name = animation || sheetPath.replace(/^.*[\\/]/, "").replace(/\.[^.]+$/, "") || "default";
    return [writeTextureAtlas(sheetPath, width, height, grid, name, layout)];
}
