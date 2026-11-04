// Types mirroring backend/app/schemas/segmentation.py.
// Boxes are HALF-OPEN source-image pixels: x1/y1 inclusive, x2/y2 exclusive.
// Mask rasters are box-local (width/height equal the paired box's w/h).
// svg_path traces pixel corners spanning [-0.5, width-0.5]; render in an
// SVG placed at the box origin sized to the box, with
// viewBox="-0.5 -0.5 {width} {height}" and preserveAspectRatio="none".

export interface SegmentBox {
  x1: number;
  y1: number;
  x2: number;
  y2: number;
}

export interface SegmentMask {
  width: number;
  height: number;
  svg_path: string;
  rle_counts: string;
}

export interface SegmentDetection {
  object_id: string;
  box: SegmentBox;
  mask: SegmentMask;
}

export interface SegmentImageInfo {
  width: number;
  height: number;
  mime_type: string;
  evidence_id: string;
}

export interface SegmentImageResponse {
  image: SegmentImageInfo;
  prompt: string;
  model: string;
  detections: SegmentDetection[];
  warnings: string[];
}
