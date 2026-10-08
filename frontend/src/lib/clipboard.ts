/** Copy text to the clipboard; true when it landed.
 *
 *  `navigator.clipboard` only exists in secure contexts, and a LAN install
 *  served over plain HTTP is a supported setup — so when the API is missing
 *  or refuses, fall back to selecting the text in a scratch textarea and
 *  `execCommand('copy')`, which browsers still honour there. */
export async function copyText(text: string): Promise<boolean> {
  if (navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(text)
      return true
    } catch {
      // Refused (permissions, unfocused document): the selection route below may still work.
    }
  }
  return copyViaSelection(text)
}

function copyViaSelection(text: string): boolean {
  const previous = document.activeElement instanceof HTMLElement ? document.activeElement : null
  // Inside a modal the textarea must live in the dialog: its focus trap would
  // pull focus straight back out of anything appended to <body>.
  const host = previous?.closest('[role="dialog"]') ?? document.body
  const area = document.createElement('textarea')
  area.value = text
  area.setAttribute('readonly', '')
  area.style.position = 'fixed'
  area.style.opacity = '0'
  host.append(area)
  area.select()
  try {
    return document.execCommand('copy')
  } catch {
    return false
  } finally {
    area.remove()
    previous?.focus()
  }
}
