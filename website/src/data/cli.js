// The vocello command line, as docs/releases/v3.0.0.md and docs/reference/cli.md
// describe it. Commands are copied from those documents (their examples and the
// install, uninstall and MCP lines); change them only with the CLI reference.

// One copyable block. Its lines are commands only, each runnable as written in
// Terminal on a fresh Mac once the earlier blocks have run: no `#` comments, which
// zsh does not accept when pasted, and no placeholder files. The prose around a
// block explains it. `label` names the block; `copyName` completes its Copy
// button's accessible name ("Copy the install check", then "Copied ...").

export const INSTALL_PACKAGE = {
  label: "Check the install",
  copyName: "the install check",
  lines: ["vocello --help"],
};

export const UNINSTALL = {
  label: "Uninstall command",
  copyName: "the uninstall command",
  lines: ["sudo sh /usr/local/lib/vocello/uninstall.sh"],
};

// pro_custom_speed is the Built-in Voice Speed model (about 2 GB in the catalog),
// the one model the take below needs.
export const FIRST_COMMANDS = {
  label: "First commands",
  copyName: "the first commands",
  lines: [
    "vocello speakers list",
    "vocello models list",
    "vocello models install pro_custom_speed",
    'vocello generate --mode custom --variant speed --text "The train left at dawn." --out ~/Desktop/hello.wav',
  ],
};

// Both takes use the Built-in Voice Speed model that FIRST_COMMANDS installs.
export const MACHINE_COMMANDS = {
  label: "Machine-readable commands",
  copyName: "the machine-readable commands",
  lines: [
    'echo "Hello there." | vocello generate --variant speed --text - --json',
    "vocello capabilities --json",
    `echo '{"mode":"custom","variant":"speed","text":"Good evening."}' | vocello run --request - --json`,
  ],
};

export const MCP_SETUP = {
  label: "Claude Code setup command",
  copyName: "the Claude Code setup command",
  lines: ["claude mcp add --scope user vocello -- /usr/local/bin/vocello mcp"],
};

// A few of the documented exit statuses (docs/reference/cli.md, Machine contract).
export const EXIT_STATUSES = [
  { code: "0", category: "ok", meaning: "Success." },
  { code: "2", category: "usage", meaning: "The invocation or its input was refused before any work." },
  { code: "69", category: "precondition", meaning: "A model is not installed, or speech recognition is unavailable." },
  { code: "75", category: "transient", meaning: "The engine or a store is busy, memory is short, or the network is unavailable: retry later." },
  { code: "77", category: "permission", meaning: "Voice-cloning consent is missing, or a path is not allowed." },
  { code: "130", category: "cancelled", meaning: "Interrupted by Control-C (SIGINT)." },
];

export const MCP_TOOLS = [
  "List voices, models, speakers and languages",
  "Generate speech, with progress and cancellation",
  "Enroll and delete saved voices",
  "Read History and export takes",
];

// Flags sit in backticks; the section renders them as unbroken code.
export const CLI_LIMITS = [
  {
    k: "Not in History yet",
    v: "Command-line takes are saved as files and do not appear in History yet; a 3.0 update adds that. Reading History from the command line needs the Mac app closed for now.",
  },
  {
    k: "Consent every time",
    v: "Cloning or saving a voice needs `--confirm-consent` on each command, or `confirmConsent` in each MCP request. It is never inherited from the app's Settings.",
  },
  {
    k: "Files stay in Vocello",
    v: "The MCP server reads and writes audio only inside Vocello's output folder, unless you start it with `--allow-dir` and name the folders it may use.",
  },
  {
    k: "One engine on 8 GB",
    v: "On an 8 GB Mac, one engine runs at a time and a running Vocello app counts: a second is refused as busy (exit 75), and `--wait-for-engine` waits for the other to exit.",
  },
];
