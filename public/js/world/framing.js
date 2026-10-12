import * as THREE from 'three';

// Camera framing, pure math with no DOM: which part of the canvas the UI leaves
// free, and how the orthographic camera must look for a set of points to fill it.
// The panels float over the canvas, so instead of shrinking the canvas the
// projection gets a lens shift (setViewOffset): the camera target is drawn at the
// centre of the free area, while pan, zoom, picking and labels keep working in
// plain canvas coordinates.

export const GAP = 12; // px kept clear between the picture and the UI
export const MARGIN = 0.04; // breathing room on the tighter axis
export const MIN_SAFE = Object.freeze({ w: 240, h: 160 }); // below this the UI is ignored
// The camera sits at target + VIEW_OFFSET: the angle the office has always had.
export const VIEW_OFFSET = Object.freeze(new THREE.Vector3(15, 40, 45));
// World units per CSS px of the old fixed framing at 1920×1080 (62 units across
// 1920 px). Close-ups and labels measure against it to keep today's on-screen size.
export const REF_UNITS_PER_PX = 62 / 1920;
// Zoom limits as sizes on screen (world units per px, unitsPerPx / zoom): never closer
// than the old closest close-up (zoom 4 at the reference scale), never farther than
// twice the fit.
export const CLOSEST_UNITS_PER_PX = REF_UNITS_PER_PX / 4;
export const MIN_ZOOM = 0.5;

const UP = new THREE.Vector3(0, 1, 0);

// The controls' maxZoom for a projection of unitsPerPx at zoom 1. The fit itself
// (zoom 1) stays within reach even on a screen so large that it is closer than that.
export function maxZoomFor(unitsPerPx) {
  return Math.max(1, unitsPerPx / CLOSEST_UNITS_PER_PX);
}

// The zoom at which a projection of unitsPerPx shows `scale` world units per px,
// kept within the controls' limits.
export function zoomFor(scale, unitsPerPx) {
  return Math.min(maxZoomFor(unitsPerPx), Math.max(MIN_ZOOM, unitsPerPx / scale));
}

// The canvas area the UI leaves free, in CSS px from the canvas' top-left corner.
// insets: how far the UI reaches into the canvas from each edge.
export function safeRect(width, height, insets = {}) {
  const inset = (side) => Math.max(0, insets[side] ?? 0);
  let x0 = inset('left') + GAP;
  let y0 = inset('top') + GAP;
  let x1 = width - inset('right') - GAP;
  let y1 = height - inset('bottom') - GAP;
  const fallback = x1 - x0 < MIN_SAFE.w || y1 - y0 < MIN_SAFE.h;
  // a window too small for its panels frames the whole canvas instead
  if (fallback) [x0, y0, x1, y1] = [GAP, GAP, width - GAP, height - GAP];
  const w = Math.max(1, x1 - x0);
  const h = Math.max(1, y1 - y0);
  return { x0, y0, x1: x0 + w, y1: y0 + h, w, h, cx: x0 + w / 2, cy: y0 + h / 2, fallback };
}

// Where the camera goes so that `envelope` (world points) fills the free area:
// the target on the floor (y 0) with the envelope centred on the line of sight,
// the world units per px at zoom 1, and the lens shift in px from the canvas centre.
export function fitOffice({ width, height, insets, envelope, offset = VIEW_OFFSET, margin = MARGIN }) {
  const safe = safeRect(width, height, insets);
  // camera basis, as Object3D.lookAt builds it for a camera at target + offset
  const back = offset.clone().normalize();
  const right = new THREE.Vector3().crossVectors(UP, back).normalize();
  const up = new THREE.Vector3().crossVectors(back, right);
  let minX = Infinity;
  let maxX = -Infinity;
  let minY = Infinity;
  let maxY = -Infinity;
  for (const p of envelope) {
    const x = p.dot(right);
    const y = p.dot(up);
    minX = Math.min(minX, x);
    maxX = Math.max(maxX, x);
    minY = Math.min(minY, y);
    maxY = Math.max(maxY, y);
  }
  // aim at the envelope's centre, then slide along the line of sight down to the
  // floor: an orthographic picture does not change along that line
  const target = new THREE.Vector3().addScaledVector(right, (minX + maxX) / 2).addScaledVector(up, (minY + maxY) / 2);
  target.addScaledVector(back, -target.y / back.y);
  return {
    target,
    position: target.clone().add(offset),
    unitsPerPx: Math.max((maxX - minX) / safe.w, (maxY - minY) / safe.h) * (1 + margin),
    lensX: safe.cx - width / 2,
    lensY: safe.cy - height / 2,
    safe,
  };
}

// Orthographic frustum for a canvas of width×height CSS px: unitsPerPx world units
// per px at zoom 1, the target drawn lensX/lensY px away from the canvas centre.
// right - left stays width * unitsPerPx, which keeps MapControls panning 1:1 under
// the cursor; zoom scales around the target, so it stays put at any zoom.
export function applyFrustum(camera, width, height, unitsPerPx, lensX = 0, lensY = 0) {
  if (!width || !height) return;
  camera.left = (-width / 2) * unitsPerPx;
  camera.right = (width / 2) * unitsPerPx;
  camera.top = (height / 2) * unitsPerPx;
  camera.bottom = (-height / 2) * unitsPerPx;
  camera.setViewOffset(width, height, -lensX, -lensY, width, height);
}
