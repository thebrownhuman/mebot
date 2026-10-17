# Embed on your site

Put the chat on your portfolio as a floating bubble or an inline panel. Works with plain
HTML, React / Next.js, WordPress, Webflow — anything that can take a `<script>` tag.

**1. Allow your site.** Admin → Widget → *Allowed sites*: add `https://your-site.com`
(and `https://*.your-site.com` for one level of subdomains). https only; plain http just
for `localhost` / `127.0.0.1`. Up to 20 sites. Only these sites can show the chat: the
embed page sends `Content-Security-Policy: frame-ancestors` with exactly this list, and
the launcher settings are readable (CORS) by these sites only, so anyone else who copies
your snippet gets nothing. *Allow any site* exists for testing; it needs a confirm, since
any site could then chat on your API key. Set `PUBLIC_URL` so the snippets use your
public address.

**2. Paste a snippet** (Admin → Widget has them with copy buttons):

```html
<!-- floating bubble, before </body> -->
<script src="https://bot.example.com/widget/v1.js" data-bot="your-slug" async></script>

<!-- inline panel inside your page -->
<div id="mebot-chat"></div>
<script src="https://bot.example.com/widget/v1.js" data-bot="your-slug"
        data-mode="inline" data-target="#mebot-chat" async></script>

<!-- no JavaScript at all -->
<iframe src="https://bot.example.com/embed/your-slug?mode=inline"
        title="Chat" style="width:100%;height:600px;border:0" loading="lazy"></iframe>
```

Optional attributes: `data-position="left|right"`, `data-color="#1d4ed8"` (override the
admin settings), `data-open="true"` (open on load). The launcher lives in a shadow root,
so your CSS can't break it, and the chat iframe is only created when a visitor first
opens it (or on auto-open). On screens under 480px the chat opens full screen; Esc closes
it. Loading the script twice (or on every SPA route) still gives one widget.

**JavaScript API.**

```js
window.MebotQueue = window.MebotQueue || [];       // calls made before the script loads
MebotQueue.push(["on", "open", () => console.log("chat opened")]);
// after load (or keep pushing to MebotQueue):
Mebot.open(); Mebot.close(); Mebot.toggle();
Mebot.on("message", ({ role }) => {});             // "user" | "assistant" | "owner", never the text
```

The host page and the chat talk only through versioned `postMessage` envelopes, checked
on both sides (exact origin and window), and never carry chat content or personal data.

**React / Next.js.**

```tsx
import Script from "next/script";

export default function Layout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        {children}
        <Script src="https://bot.example.com/widget/v1.js" data-bot="your-slug" strategy="lazyOnload" />
      </body>
    </html>
  );
}
```

**WordPress.** Add the floating snippet with a "header & footer code" plugin (footer), or
in a Custom HTML block for the inline panel. **Webflow.** Site settings → Custom code →
*Footer code* for the bubble; an *Embed* element for the inline panel.

**Sites with a strict Content-Security-Policy** need to allow mebot:

    script-src  https://bot.example.com
    frame-src   https://bot.example.com
    connect-src https://bot.example.com

If the chat can't load (site not allowed, CSP blocked, widget off), the launcher removes
itself after at most 8 seconds and logs a `[mebot]` warning in the browser console.

**Notes.** Host sites never call the chat API directly: the iframe runs on mebot's own
origin, so `CORS_ORIGINS` is only for local frontend development. In the iframe, the
browser may keep storage per host site (partitioned), so a visitor's chat on one site
isn't resumed on another. The 3D orb is off by default (adds ~220 KB) and only
downloaded when on. Turning the widget off makes embeds show "unavailable". Each opened
widget chat logs `WIDGET_OPENED` with the host site (only when it is on your list).
`/widget-test` (signed in) is a blank page with the widget, for trying it out.

**Self-hosting.** The Docker image serves everything from one process: `/embed/…` (with the
per-site headers), `/widget/v1.js` (cached for a day), the embed bundle and the app. Running
from source, `npm run build` in `frontend/` and the backend picks up `frontend/dist`
(`FRONTEND_DIST` to change). The advanced nginx layout in `deploy/nginx/` routes the same paths.
