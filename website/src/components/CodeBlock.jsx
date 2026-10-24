import React, { useEffect, useRef, useState } from "react";

// A command block people can read and copy. Each line is its own block, so long
// commands wrap with a hanging indent instead of scrolling the page sideways.
// The shell prompt is drawn by CSS and is not selectable, so a selection copies
// the commands alone, as the Copy button does. The button's name is its visible
// word ("Copy", then "Copied") followed by the block's hidden copyName.
/** @param {{ block: { label: string, copyName: string, lines: string[] } }} props */
export const CodeBlock = ({ block }) => {
  const [copied, setCopied] = useState(false);
  /** @type {React.RefObject<HTMLElement | null>} */
  const codeRef = useRef(null);
  const commands = block.lines.join("\n");

  useEffect(() => {
    if (!copied) return undefined;
    const timer = window.setTimeout(() => setCopied(false), 2000);
    return () => window.clearTimeout(timer);
  }, [copied]);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(commands);
      setCopied(true);
    } catch {
      // No clipboard access (an insecure context or a denied permission):
      // select the block so Command-C copies it.
      const selection = window.getSelection();
      if (selection && codeRef.current) selection.selectAllChildren(codeRef.current);
    }
  };

  return (
    <div className="code-block" role="group" aria-label={block.label}>
      <pre className="code-pre">
        <code ref={codeRef}>
          {block.lines.map((line) => (
            <span key={line} className="code-line">{line}</span>
          ))}
        </code>
      </pre>
      <button type="button" className="code-copy" onClick={copy}>
        {copied ? "Copied" : "Copy"}
        <span className="sr-only"> {block.copyName}</span>
      </button>
      <span className="sr-only" role="status">{copied ? `Copied ${block.copyName}` : ""}</span>
    </div>
  );
};
