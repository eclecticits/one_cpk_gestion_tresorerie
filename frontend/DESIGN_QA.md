# Design QA Checklist (ONEC/CPK)

Use this checklist after UI changes to keep the app consistent and professional.

## Global
- [ ] No `window.alert/confirm/prompt` usage in `frontend/src`
- [ ] Confirm actions use `useConfirm()` with clear title/description
- [ ] Success/error/info use toasts via `useToast()`
- [ ] Page header follows `Title + Subtitle + Actions (right)`
- [ ] Buttons follow primary/secondary/destructive styles
- [ ] Monetary values are right-aligned and formatted with 2 decimals

## Tables
- [ ] Sticky header
- [ ] Light zebra rows + row hover
- [ ] Actions grouped (icon/ellipsis) and not visually dominant
- [ ] Empty state with a next action (create/import)
- [ ] Error state with retry action

## Forms
- [ ] Consistent labels, helper text, and inline errors
- [ ] Required fields are obvious
- [ ] Submit buttons show loading state

## Modals
- [ ] One clear action, one cancel
- [ ] Destructive action uses danger styling
- [ ] Closing with ESC/overlay is supported when safe

## Budget-Specific
- [ ] Close/Reopen uses Confirm dialog + toast feedback
- [ ] Export buttons show loading state
- [ ] Progress bars show % consumed + badges at 80%/100%
