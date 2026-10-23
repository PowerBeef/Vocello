import React, { useEffect, useRef, useState } from "react";
import { Icon } from "../components/Icon.jsx";
import { CLI_DMG, CLI_PKG } from "../data/credits.js";
import {
  CLI_LIMITS,
  EXIT_STATUSES,
  FIRST_COMMANDS,
  INSTALL_PACKAGE,
  MACHINE_COMMANDS,
  MCP_SETUP,
  MCP_TOOLS,
  UNINSTALL,
} from "../data/cli.js";

const isComment = (line) => line.startsWith("#");

// Prose with `flags` in backticks, rendered with the flags as unbroken code.
/** @param {string} text */
const withCode = (text) =>
  text.split("`").map((part, i) =>
    i % 2 === 1 ? <code key={i} className="cli-inline cli-flag">{part}</code> : part,
  );

// A command block people can read and copy. Each line is its own block, so long
// commands wrap with a hanging indent instead of scrolling the page sideways.
// The Copy button copies the commands alone; comment lines and the shell prompt
// (drawn by CSS) are not selectable either, since zsh does not accept pasted
// `#` comments by default.
/** @param {{ block: { label: string, lines: string[] } }} props */
const CodeBlock = ({ block }) => {
  const [copied, setCopied] = useState(false);
  /** @type {React.RefObject<HTMLElement | null>} */
  const codeRef = useRef(null);
  const commands = block.lines.filter((line) => line && !isComment(line)).join("\n");

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
          {block.lines.map((line, i) =>
            line === "" ? (
              <span key={i} className="code-gap" aria-hidden="true" />
            ) : (
              <span key={i} className={isComment(line) ? "code-comment" : "code-line"}>
                {line}
              </span>
            ),
          )}
        </code>
      </pre>
      <button
        type="button"
        className="code-copy"
        onClick={copy}
        aria-label={`Copy ${block.label.toLowerCase()}`}
      >
        {copied ? "Copied" : "Copy"}
      </button>
      <span className="sr-only" role="status">{copied ? `${block.label} copied` : ""}</span>
    </div>
  );
};

export const CommandLine = () => (
  <section className="section cli-section" id="cli" aria-labelledby="cli-title">
    <div className="container">
      <header className="cli-head">
        <p className="section-note">New in Vocello 3.0</p>
        <h2 id="cli-title" className="section-title">Command line and agents.</h2>
        <p className="section-sub">
          <code className="cli-inline">vocello</code> brings the Mac app's features to the
          terminal: generate in all three modes, long-form and line by line included; manage saved
          voices and models; read and export History; read and change settings. It uses the app's
          models, saved voices and settings, so both see the same library.
        </p>
      </header>

      <div className="cli-install">
        <ol className="cli-steps">
          <li className="cli-step">
            <p className="cli-step-k">Install the package</p>
            <p className="cli-step-v">
              <code className="cli-inline">Vocello-macos26-cli.pkg</code> installs{" "}
              <code className="cli-inline">vocello</code> in{" "}
              <code className="cli-inline">/usr/local/lib/vocello</code> and links{" "}
              <code className="cli-inline">/usr/local/bin/vocello</code> and its zsh completion.
              It is signed with Developer ID and notarized, asks for an administrator password,
              and runs on Apple Silicon (arm64) Macs with macOS 26 or later.
            </p>
            <div className="cli-step-actions">
              <a className="btn btn-primary" href={CLI_PKG}>
                <Icon name="download" size={16} />
                Download the CLI package
              </a>
            </div>
            <CodeBlock block={INSTALL_PACKAGE} />
            <p className="cli-step-v cli-step-note">
              The installer adds links only in folders that root alone can change. If your{" "}
              <code className="cli-inline">/usr/local/bin</code> belongs to your user, as some
              older Homebrew setups leave it, the command is installed but not linked there: run{" "}
              <code className="cli-inline">/usr/local/lib/vocello/vocello</code> or link it into
              your path yourself.
            </p>
          </li>
          <li className="cli-step">
            <p className="cli-step-k">Or copy the folder</p>
            <p className="cli-step-v">
              Open <a className="cta-meta-link" href={CLI_DMG}>Vocello-macos26-cli.dmg</a> and copy
              the complete Vocello CLI folder to a folder you own, keeping its executable and
              resource bundles together, then run <code className="cli-inline">vocello</code> by
              its full path. No administrator password is needed.
            </p>
          </li>
          <li className="cli-step">
            <p className="cli-step-k">Uninstall</p>
            <p className="cli-step-v">
              The package's uninstaller removes the command line and leaves your models, voices
              and History untouched.
            </p>
            <CodeBlock block={UNINSTALL} />
          </li>
        </ol>

        <div className="cli-first">
          <h3 className="cli-sub-title">First commands</h3>
          <p className="cli-sub-body">
            Model files are not bundled. Install one once, in the app or from the terminal, and
            both use it.
          </p>
          <CodeBlock block={FIRST_COMMANDS} />
        </div>
      </div>

      <div className="cli-bands">
        <div className="cli-band">
          <h3 className="cli-sub-title">Built for scripts</h3>
          <p className="cli-sub-body">
            <code className="cli-inline">--json</code> and <code className="cli-inline">--ndjson</code>{" "}
            give every command a stable machine contract: one envelope, typed error codes,
            documented exit statuses and progress events. Text output is for people and is not a
            contract.
          </p>
          <CodeBlock block={MACHINE_COMMANDS} />
          <table className="cli-exit-table">
            <caption>Some of the documented exit statuses</caption>
            <thead>
              <tr>
                <th scope="col">Exit</th>
                <th scope="col">Category</th>
                <th scope="col">Meaning</th>
              </tr>
            </thead>
            <tbody>
              {EXIT_STATUSES.map((row) => (
                <tr key={row.code}>
                  <th scope="row">{row.code}</th>
                  <td><code className="cli-inline cli-flag">{row.category}</code></td>
                  <td>{row.meaning}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="cli-band">
          <h3 className="cli-sub-title">For AI agents</h3>
          <p className="cli-sub-body">
            <code className="cli-inline">vocello mcp</code> serves Claude Code, Claude Desktop and
            other MCP clients over stdio. An agent can:
          </p>
          <ul className="cli-tools">
            {MCP_TOOLS.map((tool) => (
              <li key={tool}>{tool}</li>
            ))}
          </ul>
          <CodeBlock block={MCP_SETUP} />
        </div>
      </div>

      <h3 className="cli-sub-title cli-limits-title">Limits to know</h3>
      <dl className="cli-limits" aria-label="Command line limitations">
        {CLI_LIMITS.map((item) => (
          <div className="cli-limit" key={item.k}>
            <dt className="cli-limit-k">{item.k}</dt>
            <dd className="cli-limit-v">{withCode(item.v)}</dd>
          </div>
        ))}
      </dl>
    </div>
  </section>
);
