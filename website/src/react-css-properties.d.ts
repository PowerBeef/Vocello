// Inline styles hand section colors to the stylesheet as CSS custom properties
// (--row-tone, --chip-color and the rest); React passes them through unchanged.
import "react";

declare module "react" {
  interface CSSProperties {
    [property: `--${string}`]: string | number | undefined;
  }
}
