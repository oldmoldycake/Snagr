import { clsx, type ClassValue } from 'clsx'
import { twMerge } from 'tailwind-merge'

/** Join class names, letting a later Tailwind utility override a conflicting earlier one. */
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}
