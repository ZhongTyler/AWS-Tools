export function money(amount, currency) {
    return amount.toLocaleString("en-US", { style: "currency", currency: (currency || "usd").toUpperCase() });
}
export async function quoteTopup(api, credits) {
    return (await api.call("GET", "/assets/topup/quote", { query: { credits } })).body;
}
export async function payTopup(api, credits, paymentToken) {
    // One attempt only: a retried payment could charge twice.
    return (await api.call("POST", "/assets/topup/pay", { body: { credits, payment_token: paymentToken }, retry: false, timeoutMs: 300_000 })).body;
}
// `replace` ends the account's open payment page first, so two cannot both
// be paid.
export async function checkoutTopup(api, credits, replace = false) {
    return (await api.call("POST", "/assets/topup/link", { body: { credits, ...(replace ? { replace: true } : {}) }, retry: false })).body;
}
export async function topupStatus(api, sessionId) {
    return (await api.call("GET", `/assets/topup/link/${encodeURIComponent(sessionId)}`)).body;
}
const sleep = (ms) => new Promise(resolve => setTimeout(resolve, ms));
// Polls a payment-page top-up until its credits are in, it expires, or the
// deadline passes (then it is still open).
export async function waitForTopup(api, sessionId, until, intervalMs = 5000) {
    for (;;) {
        const state = await topupStatus(api, sessionId);
        if (state.status === "completed" || state.status === "expired" || Date.now() >= until)
            return state;
        await sleep(intervalMs);
    }
}
