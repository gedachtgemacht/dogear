---
name: javascript-frontend
description: Vanilla JavaScript in the browser: modules, state, rendering, events, fetch, storage, accessibility, speed
triggers: javascript, js, dom, es modules, event delegation, addeventlistener, queryselector, fetch api, fetch request, fetch call, localstorage, innerhtml, browser script, klick handler, skript im browser
---
# JavaScript in the browser

Default to plain JavaScript, no framework, no bundler, unless the project already has one.

1. **Modules without a bundler.** `<script type="module" src="app.js">`, `import`/`export` with relative paths including the `.js` extension. One file per concern (state, api, render, events). No globals on `window`.
2. **State in one object.** `const state = {items: [], filter: "all", error: null}`. Change it only through small functions (`addItem`, `setFilter`), then call `render()`. The DOM is output, never the source of truth.
3. **Rendering functions.** `render()` builds the view from state: create nodes with `document.createElement` and `textContent`, or a template literal passed through an `escapeHtml` helper. Never put user data into `innerHTML` unescaped. Re-render the smallest region that changed.
4. **Events.** One listener on a stable container, route by `event.target.closest("[data-action]")` (event delegation). No inline `onclick=` attributes. Put the action name in `data-action`.
5. **fetch.** Check `response.ok` yourself, because fetch only rejects on network failure. Wrap in try/catch, parse JSON inside it, show the error in the UI, and disable the button while the request is in flight. Use `AbortController` for requests that can be superseded (search as you type, with a debounce of about 250 ms).
6. **localStorage.** Wrap reads and writes in try/catch (it throws in private mode and when full). `JSON.parse` the stored value inside the try and fall back to defaults. Store a version number with the data.
7. **Accessibility.** Real `<button>` and `<a>`, `<label for>` on inputs, visible `:focus-visible`, keyboard operable, `aria-live="polite"` on regions that update, alt text on images, contrast at least 4.5:1.
8. **Performance.** Do not read layout (`offsetHeight`, `getBoundingClientRect`) and write styles in the same loop; batch reads, then writes. Use `requestAnimationFrame` for animation, `DocumentFragment` for many nodes, passive listeners for scroll, and virtualize lists beyond roughly 1000 rows.

Avoid: jQuery-style global selectors scattered everywhere, copying state into data attributes, `var`, silent `catch {}`, `setInterval` polling when an event exists, and reading `innerHTML` back as data.

Verify: open the page, exercise each action, check the console is empty, reload to confirm stored state loads, and tab through it with the keyboard.
