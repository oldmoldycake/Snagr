/**
 * The toast after an admin deactivates or reactivates an account. Deactivation
 * takes effect on the user's next request, so the receipt says what it did to
 * them, not just which way the switch went.
 */
export function accountStatusReceipt(email: string, isActive: boolean): string {
  return isActive
    ? `Reactivated ${email} — they can sign in again`
    : `Deactivated ${email} — they're signed out and can't sign back in`
}
