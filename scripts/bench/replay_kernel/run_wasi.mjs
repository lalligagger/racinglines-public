// Run the replay kernel compiled to wasm32-wasip1 under Node's WASI: the same WebAssembly a browser would run.
//   node run_wasi.mjs <dir> <input.json> <output.json> [reps]     (files are relative to <dir>)
import { readFile } from "node:fs/promises";
import { WASI } from "node:wasi";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
const [dir, inp, out, reps = "5"] = process.argv.slice(2);
const here = dirname(fileURLToPath(import.meta.url));
const wasi = new WASI({ version: "preview1", args: ["replay_kernel", "/w/" + inp, "/w/" + out, reps], preopens: { "/w": dir } });
const mod = await WebAssembly.compile(await readFile(join(here, "target/wasm32-wasip1/release/replay_kernel.wasm")));
wasi.start(await WebAssembly.instantiate(mod, wasi.getImportObject()));
