import { expect } from "bun:test";
import { cpSync, existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync, chmodSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";

export { existsSync as exists, join, rmSync as remove };
export const repository = resolve(import.meta.dir, "../..");
export const read = (path: string) => readFileSync(path, "utf8");
export const parse = (path: string): any => Bun.YAML.parse(read(path));
export function write(path: string, value: string) {
  mkdirSync(dirname(path), { recursive: true });
  writeFileSync(path, value, { mode: 0o600 });
  return path;
}
// JSON is valid YAML; no serialization dependency is needed for fixture playbooks.
export const data = (path: string, value: unknown) => write(path, JSON.stringify(value, null, 2));
const cleanups: (() => void | Promise<void>)[] = [];
export const cleanup = (fn: () => void | Promise<void>) => cleanups.push(fn);
export async function cleanFixtures() { while (cleanups.length) await cleanups.pop()!(); }
export function temporary() {
  const root = mkdtempSync(join(tmpdir(), "infra-test-"));
  cleanup(() => rmSync(root, { recursive: true, force: true }));
  return root;
}
export function copyRepository(destination: string) {
  mkdirSync(destination, { recursive: true });
  for (const name of ["ansible", "inventory", "scripts", "stages/02-post-install"]) {
    cpSync(join(repository, name), join(destination, name), { recursive: true });
  }
  cpSync(join(repository, "ansible.cfg"), join(destination, "ansible.cfg"));
  mkdirSync(join(destination, "stages/03-provision/proxmox"), { recursive: true });
  data(join(destination, "inventory/hosts.yml"), { all: { hosts: {
    pve: { ansible_connection: "local", ansible_host: "127.0.0.1" },
    arcane: { ansible_connection: "local", ansible_host: "127.0.0.1" },
  } } });
  return join(destination, "ansible");
}
export function environment(repo: string, overrides: Record<string, string> = {}) {
  return { ...process.env, ANSIBLE_CONFIG: join(repo, "ansible.cfg"), ANSIBLE_NOCOLOR: "1", ...overrides };
}
export async function run(cmd: string[], env = process.env, input?: string) {
  // Async spawning keeps the in-process simulated HTTP APIs responsive.
  const child = Bun.spawn(cmd, { env, stdin: input === undefined ? "ignore" : new Blob([input]), stdout: "pipe", stderr: "pipe" });
  const [code, stdout, stderr] = await Promise.all([child.exited, new Response(child.stdout).text(), new Response(child.stderr).text()]);
  return { code, stdout, stderr };
}
export function success(result: Awaited<ReturnType<typeof run>>) {
  expect(result.code, result.stdout + result.stderr).toBe(0);
}
export function rolePlaybook(repo: string, role: string, task: string) {
  return data(join(repo, "ansible/playbooks/fixture.yml"), [{ hosts: "localhost", connection: "local", gather_facts: false,
    tasks: [{ "ansible.builtin.import_role": { name: role, tasks_from: task } }] }]);
}
export function tool(bin: string, name: string, body: string) {
  const path = write(join(bin, name), `#!${process.execPath}\nimport * as fs from "node:fs";\nimport assert from "node:assert/strict";\nconst args = process.argv.slice(2), env = process.env;\nconst read = p => fs.readFileSync(p, "utf8");\n${body}\n`);
  chmodSync(path, 0o700);
}
export async function keypair(path: string) {
  mkdirSync(dirname(path), { recursive: true });
  success(await run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", path]));
  return read(path + ".pub").trim();
}
