export interface ContextMenuCoords {
  left: number;
  top: number;
}

/**
 * Clamps holographic context menu coordinates within viewport bounds so the
 * right-click popup never overflows off the right or bottom screen edges.
 */
export function clampContextMenuPosition(
  clientX: number,
  clientY: number,
  menuWidth: number,
  menuHeight: number,
  viewportWidth: number,
  viewportHeight: number,
  margin = 12
): ContextMenuCoords {
  const maxLeft = Math.max(margin, viewportWidth - menuWidth - margin);
  const maxTop = Math.max(margin, viewportHeight - menuHeight - margin);
  return {
    left: Math.round(Math.max(margin, Math.min(clientX, maxLeft))),
    top: Math.round(Math.max(margin, Math.min(clientY, maxTop))),
  };
}
