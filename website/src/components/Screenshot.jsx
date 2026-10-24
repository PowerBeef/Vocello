import React from "react";

// WEB-02: a screenshot ships as AVIF with its PNG as the fallback, declares its
// intrinsic size so the layout reserves space, and loads lazily unless it is
// the above-the-fold hero. The site contract requires the AVIF sibling.
//
// Mac screenshots (2080 px wide) also ship AVIF copies 1040 and 1560 px wide
// (`name-1040.avif`, `name-1560.avif`, required by the site contract), so a
// phone decodes the size it shows instead of the full capture. The PNG
// fallback stays full size; only browsers without AVIF use it.
export const VARIANT_WIDTHS = Object.freeze([1040, 1560]);
export const VARIANT_SOURCE_WIDTH = 2080;

// The width a screenshot takes in each layout tier (website/DESIGN.md): the
// whole column below 900 px, a stacked hero or half a two-column row on
// tablets, about half the container on desktops.
const DEFAULT_SIZES = "(max-width: 899.98px) 100vw, (max-width: 1199.98px) 760px, 640px";

/** @param {{ src: string, width: number, height: number, alt: string, className?: string, priority?: boolean, sizes?: string }} props */
export const Screenshot = ({ src, width, height, alt, className, priority = false, sizes = DEFAULT_SIZES }) => {
  const avif = src.replace(/\.png$/, ".avif");
  const responsive = width === VARIANT_SOURCE_WIDTH;
  const avifSet = responsive
    ? [...VARIANT_WIDTHS.map((w) => `${src.replace(/\.png$/, `-${w}.avif`)} ${w}w`), `${avif} ${width}w`].join(", ")
    : avif;
  return (
    <picture>
      <source type="image/avif" srcSet={avifSet} sizes={responsive ? sizes : undefined} />
      <img
        className={className}
        src={src}
        width={width}
        height={height}
        alt={alt}
        loading={priority ? "eager" : "lazy"}
        decoding="async"
        fetchPriority={priority ? "high" : undefined}
      />
    </picture>
  );
};
