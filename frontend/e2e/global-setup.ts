import { execFileSync } from "node:child_process";
import { existsSync } from "node:fs";
import { join } from "node:path";

/** Generates the synthetic 90-second "gameplay" video the tests upload. */
export default function globalSetup() {
  const out = join(process.env.E2E_DATA_DIR!, "demo.mp4");
  if (!existsSync(out)) {
    execFileSync(process.env.E2E_PYTHON!, ["-m", "app.demo", out], { cwd: "../backend", stdio: "inherit" });
  }
}
