import React from "react";
import { Icon } from "../components/Icon.jsx";

// Two doors to the developer pages. Each tile keeps the id of the home section it
// replaced (#cli, #engineering), so older links still land on it.
const TILES = [
  {
    id: "cli",
    href: "/cli/",
    prompt: "$_",
    k: "Command line and AI agents",
    v: "Generate from Terminal, script it with JSON, or let Claude and other MCP clients speak through Vocello.",
    more: "The command line guide",
  },
  {
    id: "engineering",
    href: "/engineering/",
    icon: "cpu",
    k: "Engineering",
    v: "How the Swift and MLX engine is built, how fast it runs on real Macs, and every current limitation.",
    more: "How the engine works",
  },
];

export const Developers = () => (
  <section className="section dev-section" id="developers" aria-labelledby="dev-title">
    <div className="container">
      <header className="section-head">
        <p className="section-note">For developers</p>
        <h2 id="dev-title" className="section-title">Open, scriptable and measured.</h2>
      </header>
      <div className="dev-tiles">
        {TILES.map((tile) => (
          <a className="dev-tile" id={tile.id} href={tile.href} key={tile.id}>
            <span className="dev-mark" aria-hidden="true">
              {tile.prompt ? <span className="dev-prompt">{tile.prompt}</span> : <Icon name={tile.icon} size={20} />}
            </span>
            <span className="dev-k">{tile.k}</span>
            <span className="dev-v">{tile.v}</span>
            <span className="dev-more">
              {tile.more}
              <Icon name="arrow-right" size={16} />
            </span>
          </a>
        ))}
      </div>
    </div>
  </section>
);
