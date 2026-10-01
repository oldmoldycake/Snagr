/**
 * Whether focus left a closing overlay (menu, sheet, dialog) for somewhere else
 * on purpose — the page a menu item navigated to took it for its heading, or a
 * dialog opened from the menu took it — so handing it back to the trigger would
 * steal it. Focus that was simply dropped (the focused row unmounted) sits on
 * the body.
 */
export function focusMovedElsewhere(overlay: EventTarget | null): boolean {
  const active = document.activeElement
  return active != null && active !== document.body && !(overlay instanceof Node && overlay.contains(active))
}
