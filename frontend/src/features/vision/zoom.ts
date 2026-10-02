/** How far a click on a photo zooms in. */
export const PHOTO_ZOOM = 3

/**
 * Where to scroll a photo's frame after zooming in, so the spot that was
 * clicked stays under the pointer. `point` is the click's offset inside the
 * unzoomed frame. The zoomed photo is the frame scaled by `zoom` on both axes,
 * so a spot at x moves to x·zoom and needs x·(zoom − 1) of scroll to stay put;
 * the browser clamps anything past the edges.
 */
export function zoomScroll(point: { x: number; y: number }, zoom: number): { left: number; top: number } {
  return { left: point.x * (zoom - 1), top: point.y * (zoom - 1) }
}
