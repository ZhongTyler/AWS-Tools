// The one error the WebP codec (webp.ts and the modules it uses) throws.
export class WebpError extends Error {
    code;
    constructor(code, message) {
        super(message);
        this.code = code;
    }
}
export const corrupt = (message) => new WebpError("CORRUPT", message);
