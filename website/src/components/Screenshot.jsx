import React from "react";

// WEB-02: a screenshot ships as AVIF with its PNG as the fallback, declares its
// intrinsic size so the layout reserves space, and loads lazily unless it is
// the above-the-fold hero. The site contract requires the AVIF sibling.
export const Screenshot = ({ src, width, height, alt, className, priority = false }) => (
  <picture>
    <source type="image/avif" srcSet={src.replace(/\.png$/, ".avif")} />
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
