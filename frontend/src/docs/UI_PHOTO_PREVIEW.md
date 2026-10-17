Mobile-first horizontal photo scroller + inline preview
===================================================

What changed
------------
- General site photos and defect photos now use a mobile-first horizontal scroller (touch-friendly) for thumbnails.
- On larger screens (md and above) thumbnails appear as a denser grid for faster scanning.
- Clicking/tapping a thumbnail opens an inline preview directly beneath the scroller (no modal), with a simple Close button.

Design notes
------------
- Mobile-first: the scroller uses native momentum scrolling (iOS) and preserves keyboard/accessibility.
- No modal: previews are inline to avoid focus traps and to keep interactions simple on mobile devices.
- The scroller hides native scrollbars visually but keeps them available to assistive tech.

Containment / overflow behavior
--------------------------------
- The thumbnail area inside the dashed upload box is now constrained so extra thumbnails won’t spill outside the box. The inner area becomes scrollable (horizontal on mobile, vertical clipping/scroll on desktop) while the overall upload box keeps its fixed visual height.
- Inline preview size was limited so long previews remain inside the upload area and don’t overlap adjacent UI.

Developer notes
---------------
- See `frontend/src/components/InspectionForm.jsx` implementation for the exact structure and handlers:
  - `selectedGeneralPreviewIndex` state for general photos
  - `selectedDefectPreview` map for per-defect previews
- CSS helpers live in `frontend/src/index.css` (.photo-scroller, .hide-scrollbar, .thumbnail-preview)

Testing
-------
- Try on mobile / emulator: upload multiple photos and swipe the thumbnail row; tap to open inline preview.
- On desktop, the grid layout should show 3 (general) or 4 (defect) columns and clicking a thumbnail still opens inline preview.
