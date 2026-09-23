// Starts Electron with a clean environment. Terminals inside VS Code set
// ELECTRON_RUN_AS_NODE=1, which makes Electron run as plain Node with no window.
const { spawn } = require("node:child_process");
const electron = require("electron");

const env = { ...process.env };
delete env.ELECTRON_RUN_AS_NODE;

const child = spawn(electron, ["."], { cwd: __dirname, env, stdio: "inherit" });
child.on("exit", (code) => process.exit(code ?? 0));
