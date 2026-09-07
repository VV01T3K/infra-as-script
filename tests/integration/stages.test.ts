import { afterEach, expect, test } from "bun:test";
import { cpSync, mkdirSync, readdirSync, statSync } from "node:fs";
import { cleanFixtures, copyRepository, data, environment, exists, join, parse, read, remove, repository, run, success, temporary, write } from "./support";
afterEach(cleanFixtures);
test("installer reuses credentials and rejects invalid regeneration without replacing them", async () => {
  const root = temporary(), destination = join(root, "secrets/installer/pve");
  cpSync(join(repository, "stages/01-install"), join(root, "stages/01-install"), { recursive: true });
  const command = ["bash", join(root, "stages/01-install/prepare.sh")], answer = join(destination, "answer.toml");
  success(await run(command)); const original = read(answer), key = read(join(destination, "bootstrap"));
  success(await run(command)); expect(read(answer)).toBe(original); expect(read(join(destination, "bootstrap"))).toBe(key);
  success(await run([...command, "--regenerate"])); expect(read(join(destination, "bootstrap"))).not.toBe(key);
  const parsed = Bun.TOML.parse(read(answer)) as any;
  expect(parsed.global["root-password-hashed"]).toStartWith("$6$");
  expect(parsed.global["root-ssh-keys"]).toEqual([read(join(destination, "bootstrap.pub")).trim()]);
  expect(readdirSync(join(root, "secrets"))).toEqual(["installer"]);
  expect(readdirSync(join(destination, "history")).some(n => read(join(destination, "history", n, "bootstrap")) === key)).toBe(true);
  const snapshot = () => Object.fromEntries(readdirSync(destination).filter(n => statSync(join(destination, n)).isFile()).map(n => [n, read(join(destination, n))]));
  const current = snapshot();
  const invalid = write(join(root, "invalid.toml"), read(join(root, "stages/01-install/profiles/old-laptop.example.toml")) + "\ninvalid = [\n");
  expect((await run([...command, "--regenerate", "--profile", invalid])).code).not.toBe(0);
  expect(snapshot()).toEqual(current); expect(readdirSync(destination).filter(n => n.startsWith(".prepare-"))).toEqual([]);
});
test("post-install preserves ordering and stops before rotation after a host failure", async () => {
  const root = temporary(); copyRepository(root); write(join(root, "secrets/proxmox/proxmox_bootstrap"), "synthetic existing key");
  const operations = [...["ready", "configure", "access", "template"].map(n => ["proxmox", n]), ...["prepare", "manage"].map(n => ["credentials", n])];
  for (const [role, name] of operations) data(join(root, "ansible/roles", role, "tasks", name + ".yml"), [
    { "ansible.builtin.lineinfile": { path: "{{ repo_root }}/events", line: name, create: true } },
    { "ansible.builtin.fail": { msg: "Simulated host failure" }, when: `lookup('env', 'FAIL_AT') == '${name}'` },
  ]);
  const command = ["ansible-playbook", join(root, "stages/02-post-install/main.yml")];
  success(await run(command, environment(root)));
  expect(read(join(root, "events")).trim().split("\n")).toEqual(operations.map(([, name]) => name));
  const lock = join(root, "secrets/proxmox/maintenance.lock.d"); expect(exists(lock)).toBe(false);
  remove(join(root, "events")); expect((await run(command, environment(root, { FAIL_AT: "configure" }))).code).not.toBe(0);
  expect(read(join(root, "events")).trim().split("\n")).toEqual(["ready", "configure"]); expect(exists(lock)).toBe(true);
});
test("system updates need no guest state and require an explicit target", async () => {
  const root = temporary(); copyRepository(root);
  const plays = parse(join(repository, "jobs/update-system.yml")); plays[1].gather_facts = false; plays[1].become = false;
  data(join(root, "jobs/update-system.yml"), plays);
  data(join(root, "ansible/roles/maintenance/tasks/packages.yml"), [{ "ansible.builtin.copy": { dest: "{{ repo_root }}/updated", content: "done" } }]);
  const command = ["ansible-playbook", join(root, "jobs/update-system.yml")], env = environment(root);
  expect((await run(command, env)).code).not.toBe(0); expect(exists(join(root, "updated"))).toBe(false);
  success(await run([...command, "-e", "system_update_hosts=pve"], env)); expect(exists(join(root, "updated"))).toBe(true);
  expect(exists(join(root, "secrets/proxmox/maintenance.lock.d"))).toBe(false);
});
