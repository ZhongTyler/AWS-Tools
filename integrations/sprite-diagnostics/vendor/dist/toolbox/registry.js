import { hintId, noteFact } from "../telemetry.js";
export const TOOL_GROUPS = {
    sprite: "Spritesheets and frames",
    image: "Images",
    audio: "Sound effects, music and voices",
    model: "3D models",
    asset: "Folders of assets: inventories, gaps to fill with Ludo, loaders"
};
export const TOOLS = [];
// A path as the person would type it in their shell: bare when nothing in it
// needs quoting, else in double quotes. On Windows backslashes are the path's
// own (cmd and PowerShell don't escape with them), and a ~ inside a short
// name (RUNNER~1) is only a letter.
export const shellArg = (p) => {
    if (process.platform === "win32")
        return /^(?!~)[\w.\\/@:+~-]+$/.test(p) ? p : `"${p.replace(/"/g, '\\"')}"`;
    return /^[\w./@:+-]+$/.test(p) ? p : `"${p.replace(/(["\\$`])/g, "\\$1")}"`;
};
export const hint = (text, command) => {
    const id = hintId(command);
    if (id)
        noteFact("hint", id);
    return { text, command };
};
// The line after a tool writes a sheet that plays. `ludo preview` draws only
// in an interactive terminal, and refuses everyone else, coding agents (most
// toolbox runs) above all: they are shown Ludo's next step instead.
export const playHint = (ctx, sheet, text = "Preview it playing") => ctx.vis.enabled
    ? hint(text, `ludo preview ${sheet}`)
    : hint("Animate another move for the same character with Ludo", `ludo sprite animate --initial-image <a frame> --motion-prompt "<what it does>"`);
