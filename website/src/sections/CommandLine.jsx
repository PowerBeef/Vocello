import React from "react";
import { CodeBlock } from "../components/CodeBlock.jsx";
import { Icon } from "../components/Icon.jsx";
import { CLI_DMG, CLI_PKG, CLI_REFERENCE, RELEASES } from "../data/credits.js";
import { STABLE_MAC_RELEASE } from "../data/release.js";
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

// Prose with `flags` in backticks, rendered with the flags as unbroken code.
/** @param {string} text */
const withCode = (text) =>
  text.split("`").map((part, i) =>
    i % 2 === 1 ? <code key={i} className="cli-inline cli-flag">{part}</code> : part,
  );

// "3.1.0" reads as "3.1" in the note above the title, as in the home page's hero.
const releaseLabel = STABLE_MAC_RELEASE.version.replace(/\.0$/, "");

// /cli/: the full guide.
export const CommandLineGuide = () => (
  <section className="section cli-section cli-page" aria-labelledby="cli-title">
    <div className="container">
      <header className="cli-head page-head">
        <p className="section-note">Part of Vocello {releaseLabel}</p>
        <h1 id="cli-title" className="section-title page-title">Command line and agents.</h1>
        <p className="section-sub">
          <code className="cli-inline">vocello</code> brings the Mac app's features to the
          terminal: generate in all three modes, long-form and line by line included; manage saved
          voices and models; read and export History; read and change settings. It uses the app's
          models, saved voices and settings, so both see the same library.
        </p>
        <p className="cli-head-link">
          <a className="cta-meta-link" href={CLI_REFERENCE} target="_blank" rel="noreferrer">
            Read the full command line reference
          </a>
        </p>
      </header>
      <div className="cli-install">
        <ol className="cli-steps">
          <li className="cli-step">
            <h3 className="cli-step-k">Install the package</h3>
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
            <h3 className="cli-step-k">Or copy the folder</h3>
            <p className="cli-step-v">
              Open <a className="cta-meta-link" href={CLI_DMG}>Vocello-macos26-cli.dmg</a> and copy
              the complete Vocello CLI folder to a folder you own, keeping its executable and
              resource bundles together, then run <code className="cli-inline">vocello</code> by
              its full path. No administrator password is needed.
            </p>
          </li>
          <li className="cli-step">
            <h3 className="cli-step-k">Update</h3>
            <p className="cli-step-v">
              Vocello &gt; Check for Updates updates only the app. To update the command line,
              install the newer <code className="cli-inline">Vocello-macos26-cli.pkg</code> from
              the{" "}
              <a className="cta-meta-link" href={RELEASES} target="_blank" rel="noreferrer">
                releases page
              </a>
              : it replaces the previous install. For a copied folder, replace it with the newer
              Vocello CLI folder.
            </p>
          </li>
          <li className="cli-step">
            <h3 className="cli-step-k">Uninstall</h3>
            <p className="cli-step-v">
              The package's uninstaller removes the command line and leaves your models, voices
              and History untouched.
            </p>
            <CodeBlock block={UNINSTALL} />
            <p className="cli-step-v cli-step-note">
              If users other than root can change{" "}
              <code className="cli-inline">/usr/local/lib</code>, the uninstaller removes nothing:
              it prints the commands that make that folder root's alone. Run them, then run the
              uninstaller again. If a tool you installed since then needs that folder to stay yours,
              remove <code className="cli-inline">/usr/local/lib/vocello</code>,{" "}
              <code className="cli-inline">/usr/local/bin/vocello</code> and{" "}
              <code className="cli-inline">/usr/local/share/zsh/site-functions/_vocello</code>{" "}
              yourself, then run{" "}
              <code className="cli-inline">sudo pkgutil --forget com.qwenvoice.cli</code>.
            </p>
          </li>
        </ol>

        <div className="cli-first">
          <h3 className="cli-sub-title">First commands</h3>
          <p className="cli-sub-body">
            Model files are not bundled. Install one once, in the app or from the terminal, and
            both use it. These commands list the speakers and models, download the Built-in Voice
            model (about 2.2 GB, once), and save a first take to your Desktop.
          </p>
          <CodeBlock block={FIRST_COMMANDS} />
          <p className="cli-note">
            Voice Design and Voice Cloning each use their own model.{" "}
            <code className="cli-inline">vocello models install-recommended --plan</code> lists
            the model each mode uses and its download size, and downloads nothing.
          </p>
          <p className="cli-note">
            Coming from 3.0? Each mode now has one model, and the model ids are unchanged.{" "}
            <code className="cli-inline">vocello models list</code> marks a mode whose 3.0 model
            needs its update, and <code className="cli-inline">vocello models install</code>{" "}
            installs the new model and removes the earlier folders. Scripts written for 3.0 keep
            running: <code className="cli-inline">--variant quality</code>,{" "}
            <code className="cli-inline">models use</code> and{" "}
            <code className="cli-inline">models prefer-lower-memory</code> print a{" "}
            <code className="cli-inline">variant_retired</code> warning and use the mode's one
            model, and <code className="cli-inline">--variation balanced</code> or{" "}
            <code className="cli-inline">consistent</code> prints{" "}
            <code className="cli-inline">variation_retired</code> and generates as Expressive.
          </p>
        </div>
      </div>

      <div className="cli-bands">
        <div className="cli-band">
          <h3 className="cli-sub-title">Built for scripts</h3>
          <p className="cli-sub-body">
            <code className="cli-inline">--json</code> and <code className="cli-inline">--ndjson</code>{" "}
            give every command a stable machine contract: one envelope, typed error codes,
            documented exit statuses and progress events. Text output is for people and is not a
            contract. These commands pipe a script in for the JSON envelope, describe every
            command, option, error code and exit status, and send a JSON request on standard
            input; both takes use the Built-in Voice model installed above.
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
          <p className="cli-sub-body">This adds Vocello to Claude Code for every project:</p>
          <CodeBlock block={MCP_SETUP} />
          <p className="cli-note">
            The command names the installer package's link. With a copied folder, or when the
            installer added no link, use the path to your <code className="cli-inline">vocello</code>{" "}
            executable instead: run <code className="cli-inline">mcp --print-config claude-code</code>{" "}
            from that copy, for example{" "}
            <code className="cli-inline">/usr/local/lib/vocello/vocello mcp --print-config claude-code</code>,
            and it prints the command with that copy's own path.{" "}
            <code className="cli-inline">--print-config claude-desktop</code> prints the Claude
            Desktop setup the same way.
          </p>
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
