// The vocello command line, as docs/releases/v3.0.0.md and docs/reference/cli.md
// describe it. Commands are copied from those documents (their examples and the
// install, uninstall and MCP lines); change them only with the CLI reference.

// One copyable block: optional comment lines (`# ...`, not copied) and commands.
// A block's `copy` text is its commands, newline-separated.

export const INSTALL_PACKAGE = {
  label: "Check the install",
  lines: ["vocello --help"],
};

export const UNINSTALL = {
  label: "Uninstall command",
  lines: ["sudo sh /usr/local/lib/vocello/uninstall.sh"],
};

export const FIRST_COMMANDS = {
  label: "First commands",
  lines: [
    "# List speakers and models, then install the Built-in Voice Speed model",
    "vocello speakers list",
    "vocello models list",
    "vocello models install pro_custom_speed",
    "",
    "# Built-in Voice, Speed model, saved to a path",
    'vocello generate --mode custom --variant speed --text "The train left at dawn." --out /tmp/clip.wav',
    "",
    "# Voice Design from a brief",
    'vocello generate --mode design --voice-brief "A warm, calm narrator" --text "Once upon a time…"',
  ],
};

export const MACHINE_COMMANDS = {
  label: "Machine-readable commands",
  lines: [
    "# Pipe a script in and get the JSON envelope",
    'echo "Hello there." | vocello generate --variant speed --text - --json',
    "",
    "# Every command, option, error code and exit status",
    "vocello capabilities --json",
    "",
    "# A JSON generation request from a file or stdin",
    "vocello run --request request.json --json",
  ],
};

export const MCP_SETUP = {
  label: "Claude Code setup command",
  lines: [
    "# Add Vocello to Claude Code for every project",
    "claude mcp add --scope user vocello -- /usr/local/bin/vocello mcp",
    "",
    "# Print the setup for Claude Code or Claude Desktop",
    "vocello mcp --print-config claude-code",
    "vocello mcp --print-config claude-desktop",
  ],
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
