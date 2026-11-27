import { Api } from "./api.js";
import { VERSION } from "./config.js";
import { CliError, EXIT } from "./errors.js";
import { openBrowser } from "./login.js";
// An error the server gave as its final word on this signup: the pending
// entry is no use any more and may be forgotten. Anything else (network, a
// proxy's 403, a deploy's 404, a rate limit) leaves it to be continued.
export function finalError(message, exitCode, hint) {
    return new CliError(message, exitCode, hint, { signupFinal: true });
}
export function isFinal(err) {
    return err instanceof CliError && !!err.details?.signupFinal;
}
const sleep = (ms) => new Promise(resolve => setTimeout(resolve, ms));
export function priceLine(plan) {
    const amount = plan.amount.toLocaleString("en-US", { style: "currency", currency: (plan.currency || "usd").toUpperCase() });
    return `${plan.name} plan, ${amount} per ${plan.interval}`;
}
export async function startSignup(apiUrl, request) {
    const { body } = await new Api(apiUrl, undefined).call("POST", "/cli/signup/start", {
        body: { ...request, platform: process.platform, client_version: VERSION }
    });
    return body;
}
export async function quoteSignup(apiUrl, plan, interval, email) {
    const { body } = await new Api(apiUrl, undefined).call("GET", "/cli/signup/quote", {
        query: { plan, ...(interval ? { interval } : {}), ...(email ? { email } : {}) }
    });
    return body;
}
export async function paySignup(apiUrl, request) {
    // One attempt only: a retried payment could charge twice.
    const { body } = await new Api(apiUrl, undefined).call("POST", "/cli/signup/pay", {
        body: { ...request, platform: process.platform, client_version: VERSION },
        retry: false,
        // The server makes several Stripe calls, each retried; never give up on
        // a payment before it has answered.
        timeoutMs: 300_000
    });
    return body;
}
// The connect code emailed again (a lost email), with a new set-password
// link. The old code stops working.
export async function resendSignupCode(apiUrl, deviceCode) {
    const { body } = await new Api(apiUrl, undefined).call("POST", "/cli/signup/resend", { body: { device_code: deviceCode }, retry: false });
    return body;
}
// One poll. `code` is the connect code from the email, when there is one to try.
export async function pollSignup(apiUrl, deviceCode, code) {
    const res = await new Api(apiUrl, undefined).request("POST", "/cli/signup/token", {
        body: { device_code: deviceCode, ...(code ? { code } : {}) }
    });
    if (res.status === 429)
        throw new CliError("Too many signup checks from this network", EXIT.RATE_LIMITED, "Wait a few minutes, then run `ludo signup --continue`.");
    const known = ["pending", "code_required", "code_wrong", "completed", "failed", "expired"];
    if (res.status >= 200 && res.status < 300 && res.body && typeof res.body === "object" && known.includes(res.body.status)) {
        return res.body;
    }
    // Not an answer about this signup: keep it and let the person try again.
    throw new CliError((res.body && typeof res.body === "object" && res.body.message) || `Could not check the signup (HTTP ${res.status})`, EXIT.ERROR, "Run `ludo signup --continue` to try again.");
}
// Polls while the checkout is unpaid. Resolves with the first state that is
// not "pending", or "pending" when the link's time ran out.
export async function waitForPayment(apiUrl, pending) {
    const baseInterval = Math.max(0.01, pending.interval || 5) * 1000;
    let interval = baseInterval;
    let failures = 0;
    // One poll even when the link has just expired: the payment may have landed
    // in its last seconds.
    for (;;) {
        let state;
        try {
            state = await pollSignup(apiUrl, pending.device_code);
            failures = 0;
            interval = baseInterval;
        }
        catch (err) {
            // Wi-Fi handoff, sleep, a deploy, a rate limit: whoever is paying is
            // still on Stripe's page, and the signup waits for us.
            if (++failures >= 20)
                throw err;
            interval = Math.min(interval * 2, 15_000);
        }
        if (state && state.status !== "pending")
            return state;
        if (Date.now() >= pending.expires_at)
            return { status: "pending" };
        await sleep(interval);
    }
}
export function showCheckout(started, opts) {
    opts.log(`Creating a Ludo account for ${started.email}: ${priceLine(started.plan)}.`);
    opts.log("Pay on this Stripe page to create the account:");
    opts.log(`\n  ${started.checkout_url}\n`);
    opts.log(`The link works for ${Math.round(started.expires_in / 60)} minutes. Nothing is created or charged until it is paid.`);
    opts.log(`Once paid, we email ${started.email} a code that connects this CLI.`);
    if (opts.openBrowser && openBrowser(started.checkout_url))
        opts.log("Opened it in your browser.");
}
