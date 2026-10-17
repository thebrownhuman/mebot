# Plugin SDK

Drop mebot onto any site as a web component, a React component or one JS call. The SDK
only draws the launcher; the chat itself always runs in mebot's isolated `/embed`
iframe (its own origin, CSP `frame-ancestors`), so host-page CSS and scripts can't reach
it.

- Use your **public bot key** (`pk_…`, shown in Admin → Widget). Never an LLM/API key: the
  SDK refuses anything that isn't a `pk_` key, and any option it doesn't know.
- Add every site that embeds the bot to **Admin → Widget → allowed sites**. On hosted
  mebot, chat requests from any other site get "unavailable".
- `/widget/v1.js` (the one-line loader) keeps working; the SDK is an alternative.

## Plain HTML (CDN)

```html
<script src="https://YOUR-MEBOT/sdk/v1/mebot.js" async></script>
<mebot-chat bot-key="pk_xxxxxxxxxxxxxxxxxxxxxxxx" theme="auto" position="right"></mebot-chat>
```

`/sdk/v1/mebot.js` is the latest 1.x (cached one day). Pin an exact version with
`/sdk/1.0.0/mebot.js` (cached for a year). The CDN build defaults `host` to the server it
was loaded from.

Plain JS instead of the element:

```html
<script src="https://YOUR-MEBOT/sdk/v1/mebot.js"></script>
<script>
  const chat = Mebot.init({ botKey: "pk_xxxxxxxxxxxxxxxxxxxxxxxx", theme: "dark" });
  chat.on("ready", () => console.log("chat ready"));
  document.querySelector("#talk").onclick = () => chat.open();
</script>
```

If the page also has the one-line loader, `window.Mebot` stays the loader's; use
`<mebot-chat>` there.

## npm

```bash
npm install @npm-scope/mebot
```

(`@npm-scope/mebot` is a placeholder until the package is published under its real name.)

```js
import { Mebot } from "@npm-scope/mebot"; // also registers <mebot-chat>

const chat = Mebot.init({ botKey: "pk_…", host: "https://YOUR-MEBOT" });
```

With npm, pass `host` (your mebot server URL), as an option or the `host` attribute.

## React

```jsx
import { useRef } from "react";
import { MebotChat } from "@npm-scope/mebot/react";

export function Help() {
  const chat = useRef(null);
  return (
    <>
      <button onClick={() => chat.current.open()}>Ask me</button>
      <MebotChat ref={chat} botKey="pk_…" host="https://YOUR-MEBOT" accent="#0f766e"
                 onMessage={({ role }) => console.log(role)} />
    </>
  );
}
```

React (17+) is a peer dependency. The component renders nothing in your tree; it mounts
the launcher on `document.body` and removes it on unmount.

## Next.js

The SDK touches `window`, so load it on the client:

```jsx
"use client";
import dynamic from "next/dynamic";

const MebotChat = dynamic(() => import("@npm-scope/mebot/react").then((m) => m.MebotChat), {
  ssr: false,
});

export default function Chat() {
  return <MebotChat botKey="pk_…" host="https://YOUR-MEBOT" />;
}
```

Or with the CDN: `<Script src="https://YOUR-MEBOT/sdk/v1/mebot.js" strategy="lazyOnload" />`
from `next/script`, plus the `<mebot-chat>` tag.

## WordPress

Add a Custom HTML block (or your theme's footer) with:

```html
<script src="https://YOUR-MEBOT/sdk/v1/mebot.js" async></script>
<mebot-chat bot-key="pk_xxxxxxxxxxxxxxxxxxxxxxxx"></mebot-chat>
```

## API

| Method / event | |
| --- | --- |
| `open()`, `close()`, `toggle()` | On the instance, the element and the React ref |
| `on(event, fn)` → unsubscribe | `ready`, `open`, `close`, `message` |
| `destroy()` | Removes the launcher and iframe |
| element events | `ready`, `open`, `close`, `message` (`CustomEvent`, `detail = { role }`) |

`message` only carries the role (`user`, `assistant`, `owner`), never the text.
Messages from the iframe are accepted only from mebot's origin and only from the SDK's own
iframe.

## Theming

Options (`Mebot.init`, React props) or CSS variables on `<mebot-chat>`:

| Option | CSS variable | Allowed |
| --- | --- | --- |
| `theme` | attribute `theme` | `light`, `dark`, `auto` |
| `accent` | `--mebot-accent` | `#rrggbb` |
| `radius` | `--mebot-radius` | 0–32 px (chat panel corners) |
| `font` | `--mebot-font` | `system`, `serif`, `mono`, `rounded` |
| `launcherSize` | `--mebot-launcher-size` | 40–80 px |
| `offsetX` / `offsetY` | `--mebot-offset-x` / `--mebot-offset-y` | 0–200 px |
| `position` | attribute `position` | `right`, `left` |

Anything outside the list is ignored (owner defaults apply). `theme`, `accent` and `font`
are passed to the iframe as URL parameters, and the iframe validates them again, so
there's no way to inject CSS into the chat.

## Versioning and size

Semver. The core is ≤ 6 KB gzipped (CI checks it; currently about 3.5 KB). Releases
publish from the `sdk-v*` tag workflow (`.github/workflows/sdk-publish.yml`), which
refuses to run while the package name is still the placeholder.
