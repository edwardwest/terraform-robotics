// Lucide-style inline stroke icons, 1.5 stroke. Decorative by default (aria-hidden).
import type { SVGProps } from "react";

type P = SVGProps<SVGSVGElement> & { size?: number };

function Svg({ size = 18, children, ...rest }: P) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
      {...rest}
    >
      {children}
    </svg>
  );
}

export const IconArrowRight = (p: P) => (<Svg {...p}><path d="M5 12h14" /><path d="m13 6 6 6-6 6" /></Svg>);
export const IconArrowLeft = (p: P) => (<Svg {...p}><path d="M19 12H5" /><path d="m11 18-6-6 6-6" /></Svg>);
export const IconPlus = (p: P) => (<Svg {...p}><path d="M12 5v14" /><path d="M5 12h14" /></Svg>);
export const IconMinus = (p: P) => (<Svg {...p}><path d="M5 12h14" /></Svg>);
export const IconUpload = (p: P) => (<Svg {...p}><path d="M12 15V3" /><path d="m7 8 5-5 5 5" /><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" /></Svg>);
export const IconDownload = (p: P) => (<Svg {...p}><path d="M12 3v12" /><path d="m7 10 5 5 5-5" /><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" /></Svg>);
export const IconCheck = (p: P) => (<Svg {...p}><path d="M20 6 9 17l-5-5" /></Svg>);
export const IconLayers = (p: P) => (<Svg {...p}><path d="m12 2 10 5-10 5L2 7l10-5Z" /><path d="m2 17 10 5 10-5" /><path d="m2 12 10 5 10-5" /></Svg>);
export const IconPencil = (p: P) => (<Svg {...p}><path d="M17 3a2.85 2.85 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5Z" /></Svg>);
export const IconMap = (p: P) => (<Svg {...p}><path d="M14.1 5.9 9 3 3 5.6v15.4l6-2.6 6 3 6-2.6V3.6Z" /><path d="M9 3v15.4" /><path d="M15 6v15" /></Svg>);
export const IconFile = (p: P) => (<Svg {...p}><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8Z" /><path d="M14 2v6h6" /></Svg>);
export const IconDrone = (p: P) => (<Svg {...p}><circle cx="5" cy="5" r="2.5" /><circle cx="19" cy="5" r="2.5" /><circle cx="5" cy="19" r="2.5" /><circle cx="19" cy="19" r="2.5" /><rect x="9" y="9" width="6" height="6" rx="1" /><path d="M7 7l2 2M17 7l-2 2M7 17l2-2M17 17l-2-2" /></Svg>);
export const IconGlobe = (p: P) => (<Svg {...p}><circle cx="12" cy="12" r="10" /><path d="M2 12h20" /><path d="M12 2a15 15 0 0 1 0 20 15 15 0 0 1 0-20Z" /></Svg>);
export const IconPhone = (p: P) => (<Svg {...p}><rect x="6" y="2" width="12" height="20" rx="2" /><path d="M11 18h2" /></Svg>);
export const IconMountain = (p: P) => (<Svg {...p}><path d="m8 3 4 8 5-5 5 15H2L8 3Z" /></Svg>);
export const IconRuler = (p: P) => (<Svg {...p}><path d="M21.3 15.3a2.4 2.4 0 0 1 0 3.4l-2.6 2.6a2.4 2.4 0 0 1-3.4 0L2.7 8.7a2.4 2.4 0 0 1 0-3.4l2.6-2.6a2.4 2.4 0 0 1 3.4 0Z" /><path d="m14.5 12.5 2-2M11.5 9.5l2-2M8.5 6.5l2-2M17.5 15.5l2-2" /></Svg>);
export const IconRotate3d = (p: P) => (<Svg {...p}><path d="M16.5 6.5c3 1 5 2.6 5 4.5 0 3-5.6 5.5-12.5 5.5" /><path d="m6 14 3.5 2.5L6 19" /><path d="M12 3c-1.9 0-3.5 4-3.5 9 0 1.3.1 2.6.4 3.7" /><path d="M2.5 11c0-1.9 2-3.5 5-4.5" /></Svg>);
export const IconAlert = (p: P) => (<Svg {...p}><circle cx="12" cy="12" r="10" /><path d="M12 8v4" /><path d="M12 16h.01" /></Svg>);
export const IconX = (p: P) => (<Svg {...p}><path d="M18 6 6 18" /><path d="m6 6 12 12" /></Svg>);
