# UAS design system

This document describes the shared Jinja and CSS foundation introduced in Phase 1. It is intended to support later page work without changing route, form, or workflow contracts. The `/design-system` showcase is enabled in development and testing only.

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

Spacing uses a 4px rhythm. Shared typography, radii, shadows, transition durations, z-index levels, and reading/normal/wide container widths are declared in `static/css/design-system.css`. Existing page-specific layout rules remain in `static/style.css` and each template's `page_styles` block; later redesign phases can migrate them deliberately.

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

## Security policy note

Content Security Policy remains deferred until the redesigned UI's inline scripts, external resources, and image needs are known. Do not introduce a restrictive policy that silently breaks existing workflows during this foundation phase.
