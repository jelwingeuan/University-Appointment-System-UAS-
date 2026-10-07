# UAS design system

This document describes the shared Jinja and CSS foundation used across the Flask/Jinja portal. It is intended to support page work without changing route, form, or workflow contracts. The `/design-system` showcase is enabled in development and testing only.

## Theme and colors

Use semantic CSS variables rather than fixed colors. The light theme is the default and retains the existing university blue (`--color-primary: #145a83`). Dark colors are tuned separately. The `System` choice follows `prefers-color-scheme`; `Light` and `Dark` are explicit choices. Manual choices are stored in `localStorage` under `uas-theme`. If browser storage is disabled or unavailable, the page continues in System mode.

Core tokens include:

| Use | Token |
| --- | --- |
| Page background | `--color-bg` |
| Raised surface | `--color-surface-raised` |
| Muted surface | `--color-surface-muted` |
| Main and secondary text | `--color-text`, `--color-text-secondary` |
| Border and stronger border | `--color-border`, `--color-border-strong` |
| Primary control, text links, and focus | `--color-primary`, `--color-link`, `--color-focus` |
| Success, warning, danger, info | `--color-success`, `--color-warning`, `--color-danger`, `--color-info` |

Spacing uses a 4px rhythm. Shared typography, radii, shadows, transition durations, z-index levels, and reading/normal/wide container widths are declared in `static/css/design-system.css`. Page-specific rules belong in local static CSS files loaded with the `page_styles_after` or `public_page_styles` template block. Do not add inline `<style>` elements or `style` attributes: the response CSP rejects them.

## Components

Reusable Jinja macros live in `templates/components/ui.html`: `button`, `icon_button`, `field`, `badge`, `status_badge`, `alert`, `card`, `empty_state`, `dialog`, and `avatar`. Example:

```jinja
{% from "components/ui.html" import button, status_badge %}
{{ button('Save changes', 'primary', type='submit') }}
{{ status_badge(appointment.status) }}
```

Use `.btn` with `primary`, `secondary`, `ghost`, `danger`, or `link` variants and optional `sm`/`lg` sizes. Existing `.button` classes remain aliases for compatibility. Persistent Flask flashes are rendered in the base shell with a category, an accessible status/alert role, and a dismiss control. They do not disappear automatically.

Toasts are transient and use `window.UASUI.toast({kind, title, message})`. Success and info notices close after five seconds. Warning and error notices remain until dismissed. Timers pause while a toast is hovered or focused. Use `window.UASUI.openDialog(id)` and `window.UASUI.closeDialog(id)` with native `<dialog>` elements; native modal behavior supplies Escape handling and background blocking, while the helper restores focus to the opener.

Appointment statuses use `.status-pending`, `.status-accepted`, `.status-rejected`, `.status-cancelled`, `.status-completed`, and `.status-no-show`. Always render the status text as well; color is not the only indicator.

## Breakpoints and responsive behavior

Shared breakpoints are 640px (small), 768px (medium), 1024px (large), and 1280px (wide). Use fluid widths with a documented maximum container rather than fixed page widths. Tables should be wrapped in a labeled, keyboard-focusable horizontal scroll region when they cannot fit. At phone widths, form grids collapse to one column and the appearance control and notifications remain within the viewport.

## Accessibility

The base shell provides a skip link, a single main landmark, persistent feedback, and a labeled theme selector. Keep labels visible, associate hints and errors with fields, preserve visible keyboard focus, use semantic table headers, and retain status text. Native dialogs must have an accessible name and a clear close action. Shared motion honors `prefers-reduced-motion`; avoid adding animation that conveys no user feedback or state change.

## Authenticated application shell

Authenticated templates extend `templates/app_shell.html`; public content continues to extend `templates/base.html`. `templates/admin_base.html` remains as a thin compatibility layer for existing administrator templates. The app shell owns the role-aware sidebar, mobile navigation dialog, top bar, account disclosure, theme selector, page header, flashes, and the single main landmark. Page bodies remain in their existing templates.

Navigation is built on the server from `current_user.role` and Flask endpoint names in `uas/navigation.py`. Add a link only when a route already exists and is valid for that role. The active link uses an endpoint allowlist and `aria-current="page"`; it does not infer state from URL substrings. Authenticated public pages retain their public layout and expose only the same role-specific application destinations.

The sidebar is persistent at 1024px and wider. Below 1024px it becomes a native `<dialog>` drawer opened by the top-bar button. Native dialog behavior blocks background interaction and handles Escape; `window.UASUI` restores focus to the trigger. Navigation links and the close button dismiss the drawer. The account control is a native `<details>` disclosure, supports keyboard activation, closes on Escape, and returns focus to its summary. It shows the account name, human-readable role, and faculty for students/lecturers; its logout form remains a CSRF-protected POST.

The shared header takes its visible title from the page's existing `title` block. Templates may optionally supply `page_description`, `page_actions`, and `breadcrumbs` blocks. Breadcrumbs are for deeper routes and use a labeled navigation landmark with the current location marked by `aria-current="page"`. Set `content_width` to `normal` (default), `wide`, or `full` for content such as forms, tables, or calendars. The shell reuses `SiteSettings` branding and falls back to the existing university name when no setting or logo exists.

Browser requests that accept HTML use the public base layout for 403, 404, 409, 429, and 500 errors. API/non-HTML responses retain their status, plain response behavior, and headers such as `Retry-After`. The production `/design-system` showcase remains unavailable.

## JavaScript and security policy

Use `static/ui.js` for shared theme, toast, dialog, copy, and account-menu behavior. Small page behaviors belong in an existing or focused local static asset, are loaded with `defer`, and must tolerate pages where their target elements are absent. Use native forms and links for primary workflows; avoid inline handlers. Keep route data in escaped `data-*` attributes and delegate interactions from the shared helper where practical. Request nonces are generated server-side for each response; do not reuse or hard-code one.

Every response receives the enforced `Content-Security-Policy` below. It intentionally has no `unsafe-inline`, `unsafe-eval`, or wildcard sources. The only `data:` source is limited to fonts for FullCalendar’s bundled icon font:

| Directive | Allowed sources | Reason |
| --- | --- | --- |
| `default-src`, `base-uri`, `form-action`, `connect-src`, `worker-src`, `manifest-src` | `'self'` | Local application assets, forms, API requests, and workers only. |
| `script-src` | `'self'`, `https://cdn.jsdelivr.net` | Local scripts and the pinned FullCalendar 6.1.13 bundle. |
| `style-src` | `'self'`, `https://cdnjs.cloudflare.com`, one per-response nonce | Local styles and Font Awesome 6.4 CSS. The nonce is attached only to the FullCalendar script, which FullCalendar 6.1.13 uses to authorize its generated `<style>` elements. `style-src-attr 'none'` still rejects every inline style attribute. |
| `font-src` | `'self'`, `https://cdnjs.cloudflare.com`, `data:` | Local fonts and Font Awesome webfonts; FullCalendar 6.1.13 defines its small built-in icon font as a data URI. `data:` is limited to this directive, not images or other resources. |
| `img-src` | `'self'`, `cdn.eduadvisor.my`, `www.unstudio.com`, `i0.wp.com`, `www.forbes.com`, `www.degreequery.com`, `live.staticflickr.com`, `media.istockphoto.com`, `exploreengineering.ca`, `dcfwfuaf91uza.cloudfront.net` | Current public-home imagery and local uploads. Remove a source only after tracing its CSS/template references. |
| `frame-src` | `https://www.google.com` | The existing campus map embed. |
| `object-src` | `'none'` | No plugin content is needed. |
| `frame-ancestors` | `'self'` | Prevent third-party framing while allowing same-origin framing. |

Do not add an origin just to make a browser warning disappear. Trace the requesting page and asset, then document any required source here. The policy is enforced across environments, not report-only.

## Quality-check matrix

The cross-role smoke matrix uses the following representative pages. Page-specific business rules remain in the UI contract and are not changed by this visual/accessibility pass.

| Area | Pages and flows checked | Viewports |
| --- | --- | --- |
| Public and authentication | Home, sign in, registration, password reset; token completion has template/CSRF coverage | 320, 360, 390, 430, 768, 820, 1024, 1280, 1440, 1920px; portrait and landscape |
| Student | Booking across all widths; cancellation/history and profile across all widths including landscape; long account name | Same widths; Light, Dark, System |
| Lecturer | Dashboard and calendar across all widths; request acceptance/rejection, details, availability, and profile dialog flows | Same widths; Light, Dark, System; reduced motion; calendar text list |
| Administrator | User list across all widths; user/detail, invitation, appointment/detail, faculties/edit, settings, and audit workflows; long account/school names | Same widths; Light, Dark, System; portrait and landscape |

For each representative flow, check there is no unintended page-level horizontal scrolling, headings and landmarks are meaningful, controls are keyboard reachable with visible focus, dialogs restore focus, fields have visible labels, text remains visible in all themes, and there are no console/CSP errors. A table may have its own labeled, keyboard-focusable horizontal scroll region when its columns require it.

## Frontend contribution rules

- Keep the single main landmark, skip link, shell navigation, account controls, and role-specific destinations intact.
- Reuse `.btn`, `.field`, `.ui-card`, `.ui-status`, `.ui-alert`, `.ui-empty-state`, `.ui-dialog`, and pagination components. Keep status labels visible; never rely on color alone.
- Prefer fluid sizes, `min-width: 0`, `overflow-wrap: anywhere`, and the 640/768/1024/1280px breakpoints. Include `env(safe-area-inset-*)` where controls approach device edges. Controls should have at least a 44px target where practical.
- Use visible associated `<label>` elements, semantic fieldsets for radio groups, descriptive iframe titles, and `aria-live` only for actual status feedback. Do not duplicate headings or invent alternate workflows.
- Respect `prefers-reduced-motion`; motion should not be needed to discover content or controls.
