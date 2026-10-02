/** The backend refuses a reference photo over this (`MAX_UPLOAD_BYTES`). */
export const MAX_REFERENCE_BYTES = 10 * 1024 * 1024

/**
 * Why a picked file can't be uploaded as a reference photo, or null if it
 * can — checked on pick so an oversized photo is refused before its upload
 * rather than after it.
 */
export function referenceFileError(file: Pick<File, 'size'>): string | null {
  return file.size > MAX_REFERENCE_BYTES ? 'Must be 10 MB or smaller' : null
}
