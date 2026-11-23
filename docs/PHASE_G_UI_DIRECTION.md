# Phase G UI direction

Status: design constraint for Phase G; not a requirement to freeze HumanConsole / AI Home Assistant boundaries.

**Current owner decision (2026-11-13):** Transform the already-existing Foundation Settings/Operator screen into the default one-page whole-system OVERVIEW dashboard, with all existing Settings and exception/approval functions retained as drill-downs. This is not a new dashboard application. The primary work-entry path is now existing ChatGPT/Muse/other AI -> authenticated MCP/API -> Foundation -> independently verified result -> the calling AI; Operator observes the same truth. The dated SETTINGS-first and LibreChat-primary descriptions are superseded by `END_GOAL.md`, `SYSTEM_ROLE_BOUNDARIES.md` and `PHASE_G_PLAN.md`. Retain C/I themes and one shared semantic layout per surface.

## Visual references
- Techwear-inspired UI
- Urban Tactical Interface
- Diegetic Industrial UI
- Tactical HMI

## Interpretation
Use these as interaction/visual references, not as decorative cosplay. Prefer dense but legible operational information, strong hierarchy, restrained industrial geometry, explicit system state, modular panels, compact controls, and interfaces that feel embedded in the operating system/environment.

The UI must preserve Foundation semantics visibly: normal result, waiting-human approval, failure, UNCERTAIN/reconciliation, recovery, provider/tool availability, credential presence without raw secrets, evidence/readback, backup/restore/update state. Safety-critical state must not rely on color alone. Motion, scanlines, fake telemetry, excessive HUD ornament, tiny text, and low-contrast decoration must never reduce usability.

Phase G should derive the concrete design system from these references while keeping the operator surface replaceable and preserving the Human -> Foundation -> execution -> independent verification path.

## Reference: Japan Digital Agency Dashboard Design Guidebook (2026-03-31; page updated 2026-07-17)
Official reference: https://www.digital.go.jp/resources/dashboard-guidebook
Use as an information-design/decision-support reference, not as a visual skin to copy.

Adopt for the final G6 redesign:
- Start from user questions, decisions, and actions; every visible block must support one of them.
- Use prototypes after the functional inventory is stable, then reorganize information hierarchy before visual polish.
- Apply a consistent layout grid and spacing system across Desktop/Smartphone/Echo surfaces.
- Prefer unambiguous labels and state representations; do not rely on decoration or color alone to convey meaning.
- Standardize reusable components and visual rules rather than hand-tuning each panel.
- Keep the existing AI FOUNDATION direction (dark-blue industrial HMI / techwear) as the visual identity, while applying the guidebook's clarity, hierarchy, consistency, and decision-support principles underneath it.
- Treat ATTENTION/ACTION/CRITICAL, provider health, quota, routing, verification, and recovery as decision-support information: show context needed to act, suppress internal implementation noise by default.
- During G6, run a Do/Don't review of each screen and remove elements that do not answer a user question or enable an action.

This reference does not change Foundation architecture, Guard authority, routing semantics, or current functional implementation order.

## Replaceability constraint — 2026-09-19
The accepted Variant I / industrial-HMI language is a replaceable presentation theme, not an application architecture. Do not encode Foundation behavior, Guard authority, routing semantics, provider state, task state, notification policy, or recovery logic in HTML/CSS or theme-specific renderer branches.

Required boundary: domain/runtime state -> semantic `HumanView` (presentation-neutral) -> surface renderer/theme -> HTML/CSS. Desktop/Mobile/Echo may select information appropriate to their authority/screen role, but that selection must remain semantic and testable independently of the current visual skin.

A future redesign must be possible by replacing renderer/theme code without changing Guard, execution, provider/routing, reconciliation, task intake, persistence, or operator action APIs. Avoid selectors, state names, data structures, or action contracts that only make sense for the current industrial-HMI appearance. Visual fixture/history modules are never canonical behavior.

## Dual-theme decision — 2026-09-19
Two designs are accepted: **C**, the earlier Endfield-like dense operational/telemetry design, and **I**, the current dark-blue industrial-HMI/techwear design. Neither is allowed to become the application architecture. C is no longer merely a reference and I is no longer the sole authoritative skin.

Required implementation boundary remains `domain/runtime -> HumanView -> surface semantics -> selected design renderer/theme`. The design switch changes presentation only. Both designs must expose the same state meanings, evidence, authority boundaries and available actions for a given Desktop/Mobile/Echo surface. This dual-design requirement is intentionally used as an anti-coupling test: if implementing C requires changing Guard/runtime/business APIs, the presentation boundary is wrong and must be corrected rather than patched.

### Shared-layout rule — 2026-09-19
C/I selection changes **design only**. Layout is common per surface. The same Desktop HumanView must map to one Desktop layout; likewise Mobile and Echo each have one shared layout. Theme code must not alter section order, grid topology, grouping, responsive breakpoints, control placement or information inclusion. Those belong to the shared surface renderer/layout layer.

Allowed theme differences: palette, type treatment, border/line language, background treatment, iconography, decorative markers, shadows/glow, material feel and other presentation tokens that do not change geometry/semantics. When a desired C/I characteristic conflicts with the shared layout, treat it as a product decision and ask the user before changing layout. No theme-specific layout exception is permitted by default.

### C visual reference correction — 2026-09-19
Re-checked current Arknights: Endfield interface references before refining C. C should not be interpreted as warm brown/gold industrial HMI. Its visual identity is predominantly neutral black/graphite + cool gray/white surfaces and text, with a sharp acid/chartreuse-yellow used selectively for selected/action/instrumentation emphasis. Orange/red remain sparse state/attention accents. White/light control tiles against dark structural framing are part of the reference language. Preserve AI FOUNDATION's own information and branding; use these as palette/material principles, not copied game assets or layouts.

### Theme invariants tightened — 2026-09-19
C/I must share typography metrics as well as layout geometry: font family, font size, weight, letter spacing and line height are shared presentation structure and may not vary by theme. A theme must remain meaningfully distinct through non-geometric visual language: palette, material treatment, gradients/flat surfaces, border/line style, contrast hierarchy, icon/marker treatment and decorative instrumentation that does not alter component geometry. Theme CSS is tested to reject geometry and typography-metric properties.

The design switch is a shared surface control, not navigation content. It must remain reachable on Desktop, Mobile and Echo even where the navigation rail is hidden.

### C/I visual independence clarification — 2026-09-19
Only layout/information geometry and typography metrics are invariant. Do NOT converge C and I into a shared component skin. Their visual design systems are intentionally independent. I preserves its original dark-blue techwear/urban-tactical industrial-HMI identity: deep navy spatial field, cyan/steel-blue structural glow/lines, restrained amber authority markers, flat technical panels. C independently follows the Endfield-derived neutral graphite/light-surface/signal-yellow material language: asymmetric signal strips, pale control faces, hard graphite surfaces, yellow-green instrumentation and sparse orange/red alerts. Shared geometry does not imply shared borders, fills, gradients, shadows, material treatment, icon/marker language or decorative instrumentation.

Avoid white outline-box language in C. Light/white is a control *surface/fill* where appropriate, not a border around dark cards.

### I reference expansion — Death Stranding UI re-check (2026-09-19)
Re-checked multiple Death Stranding in-game UI references (map/information, cargo management, HUD/status and terminal screens) plus a UI designer portfolio/reference archive. Do not reduce I to a generic two-color blue/amber dashboard. The useful visual principles are: near-black/navy spatial field; thin technical rules and luminous cyan/blue readouts; white/off-white labels; orange/amber for selected/action/authority states; red for health/critical state; cyan/blue for stamina/system state; sparse geometric instrumentation and isolated status bars. Preserve AI FOUNDATION semantics and do not copy game assets/layouts.

### Motion system — 2026-09-19
Motion is semantic, not ambient decoration. Shared runtime state drives motion classes (`RUNNING`, `WAITING_HUMAN`, `UNCERTAIN`); themes only choose the visual motion language. C uses equipment/signal-scan behavior. I uses telemetry/transmission behavior. Provider health can expose a restrained activity marker, but no random/fake provider execution is invented. Continuous ambient animation is avoided. `prefers-reduced-motion: reduce` disables animation and transition globally while preserving static state information. Mobile uses a slower motion profile; Echo is lighter/slower and disables provider hover pulse. Motion may never alter shared layout geometry or typography metrics between C/I.

### Motion correction — 2026-09-19
Persistent hero/notification motion is rejected. Notifications are primarily persistent decision/status information and must remain visually stable. Motion emphasis belongs to actual operational activity: routing, provider/local-LLM execution, route changes, quota/health transitions, verification transitions, and direct control feedback. Buttons/inputs may use short interaction feedback. Operational sections must have deliberate whitespace so metrics, notifications, tasks, capacity and routing never visually collide. No decorative global state rail.
