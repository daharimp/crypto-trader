# Design system

The visual language of the Trading Profile Builder (`docs/profile-builder/`) is recorded as a
design system on claude.ai:

**https://claude.ai/artifact/XDMBHznBbVgcAiGCxPE1Fs** (title "crypto-trader", private to the owner)

It was synced on 2026-11-15 from `docs/profile-builder/template.html` at `main@b63213d`.
`index.html` is generated from that template by `scripts/build_profile_form.py` and uses the
same CSS, so the template is the only source.

## What it holds

All values are copied exactly from the template's `<style>` block.

| Area | Contents | Source in `template.html` |
| --- | --- | --- |
| Colors | 11 tokens × light/dark: `bg`, `surface`, `ink`, `muted`, `line`, `accent`, `accent-soft`, `warn`, `warn-soft`, `bad`, `bad-soft` | `:root` and the two dark-theme blocks |
| Type | Bricolage Grotesque (display), Instrument Sans (body), JetBrains Mono (mono); 13 text styles | Google Fonts `<link>`, `--display` / `--body` / `--mono`, element rules |
| Spacing | 2, 4, 6, 8, 10, 12, 14, 16, 28, 64px | paddings and gaps |
| Radii | 3, 4, 6, 8, 99px | `border-radius` values |
| Other | 1px hairline, 3px note rule, 2px focus ring; 860px column | borders, outlines, `.wrap` |
| Components | Button, StatusPill, StatusBar, RiskNote, OptionCard, QuestionCard, TextField, ChecksList, AnswersBlock, RefTag | markup and classes |

The component cards are static renditions of the builder's markup, styled by the template's own
stylesheet. The repository has no component library, so the system has no JavaScript bundle.
Fonts are hosted on Google Fonts, so no font files are stored.

## Open items

1. **Border contrast.** `--line` (`#d5dcd9` light, `#2c3934` dark) is about 1.4:1 against `bg`
   and `surface`. WCAG asks 3:1 for control borders (inputs, option cards). It was kept as-is
   and flagged; darkening it is the owner's call. All text pairs already pass 4.5:1 in both
   themes.
2. **Keeping it in sync.** If the template's `:root` variables, fonts or component classes
   change, the design system needs a re-sync. Ask for one in the claude.ai chat, or publish to
   the same artifact from Claude Code with the appifacts plugin's
   `appifacts-design-system-from-code` skill (or `/design-sync`) if it is installed.
3. **A real frontend.** If one is built later (React or similar), the components can be rebuilt
   as live components in the same system.

## Not in scope

This is documentation only. It changes no code, config, risk value or live gate.
