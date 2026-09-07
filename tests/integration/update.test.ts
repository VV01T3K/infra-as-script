import { afterEach, beforeEach, expect, test } from "bun:test";
import { mkdirSync, readdirSync } from "node:fs";
import { cleanFixtures, copyRepository, data, environment, exists, join, parse, read, remove, run, success, temporary, tool } from "./support";
afterEach(cleanFixtures);
let root: string, repo: string, backups: string, lock: string, eventFile: string, env: ReturnType<typeof environment>;
const roles: Record<string, string[]> = {
  "verify-services": ["controller", "health"], "pause-gitops": ["arcane", "pause"], backup: ["proxmox", "backup_guest"],
  "backup-host": ["proxmox", "backup_host"], "update-packages": ["maintenance", "packages"], arcane: ["arcane", "configure"],
  gitops: ["arcane", "sync"], "technitium-config": ["technitium", "configure"], ready: ["proxmox", "ready"],
  "maintenance-backup": ["controller", "backup"], "bootstrap-gitops": ["arcane", "github_key"], technitium: ["technitium", "prepare"],
};
beforeEach(() => {
  root = temporary(); repo = join(root, "repo"); backups = join(root, "backups"); mkdirSync(backups); copyRepository(repo);
  lock = join(repo, "secrets/proxmox/maintenance.lock.d"); eventFile = join(root, "events");
  for (const [name, [role, task]] of Object.entries(roles)) {
    const tasks: any[] = [
      { "ansible.builtin.shell": 'printf "%s\\n" "$EVENT_NAME" >> "$EVENTS"; cat "$EVENTS"', environment: { EVENT_NAME: name }, register: "recorded_events", changed_when: false },
      { "ansible.builtin.fail": { msg: "Synthetic failure" }, when: `lookup('env', 'FAIL_AT') == '${name}'` },
    ];
    if (name === "verify-services") tasks.push({ "ansible.builtin.fail": { msg: "Synthetic final health failure" },
      when: "lookup('env', 'FAIL_FINAL_HEALTH') == '1' and recorded_events.stdout_lines | select('equalto', 'verify-services') | list | length == 3" });
    if (name === "gitops") tasks.push({ "ansible.builtin.assert": { that: `expected_git_commit == '${"a".repeat(40)}'` }, when: "maintenance_target is defined" });
    data(join(repo, "ansible/roles", role, "tasks", task + ".yml"), tasks);
  }
  for (const [role, task] of [["technitium", "verify"], ["maintenance", "recover_guest"]])
    data(join(repo, "ansible/roles", role, "tasks", task + ".yml"), [{ "ansible.builtin.command": "true", changed_when: false }]);
  for (const name of readdirSync(join(repo, "ansible/playbooks")).filter(n => n.endsWith(".yml"))) {
    const path = join(repo, "ansible/playbooks", name), plays = parse(path);
    for (const play of plays) if (!play.import_playbook) {
      play.gather_facts = false; play.tasks = (play.tasks ?? []).filter((t: any) => !("ansible.builtin.setup" in t));
    }
    data(path, plays);
  }
  tool(join(root, "bin"), "tofu", 'console.log(JSON.stringify({ip:"10.0.0.77",lxc_id:207}));');
  tool(join(root, "bin"), "git", `
if (args.includes('--show-toplevel')) console.log(env.REPO);
else if (args.includes('status')) process.stdout.write(env.DIRTY || '');
else if (args.includes('ls-remote')) console.log((env.REMOTE || 'a'.repeat(40)) + '\\trefs/heads/main');
else console.log('a'.repeat(40));`);
  env = environment(repo, { PATH: join(root, "bin") + ":" + process.env.PATH, REPO: repo, EVENTS: eventFile });
});
const events = () => exists(eventFile) ? read(eventFile).trim().split("\n") : [];
function reset() { remove(eventFile, { force: true }); remove(lock, { recursive: true, force: true }); }
function manifest() { return read(join(backups, readdirSync(backups)[0], "manifest.txt")); }
function update(target: string, overrides = {}) {
  return run(["ansible-playbook", "-i", join(repo, "inventory/hosts.yml"), join(repo, "ansible/playbooks", target === "pause-gitops" ? "pause.yml" : "update.yml"), "-e",
    JSON.stringify({ maintenance_target: target, backup_storage: "off-host", controller_backup_dir: backups, backup_passphrase: "test-only" })], { ...env, ...overrides });
}
test("every update backs up before mutation and checks health afterward", async () => {
  for (const [target, operation] of [["guest", "update-packages"], ["host", "update-packages"], ["arcane", "arcane"], ["technitium", "gitops"]]) {
    reset(); success(await update(target)); const log = events();
    expect(log.indexOf("maintenance-backup")).toBeLessThan(log.indexOf("backup"));
    expect(log.indexOf("pause-gitops")).toBeLessThan(log.indexOf("backup")); expect(log.indexOf("backup")).toBeLessThan(log.indexOf(operation));
    expect(log.at(-1)).toBe("verify-services");
    if (target === "host") expect(log.indexOf("backup-host")).toBeLessThan(log.indexOf(operation));
    expect(read(join(backups, readdirSync(backups).find(n => n.startsWith(`update-${target}-`))!, "manifest.txt"))).toContain("verified=true");
    expect(exists(lock)).toBe(false);
  }
});
test("backup failure blocks host mutation and retains the lock", async () => {
  for (const failure of ["maintenance-backup", "backup", "backup-host"]) {
    reset(); expect((await update("host", { FAIL_AT: failure })).code).not.toBe(0);
    expect(events()).not.toContain("update-packages"); expect(exists(lock)).toBe(true);
  }
});
test("failed package update is not reported as verified", async () => {
  expect((await update("guest", { FAIL_AT: "update-packages" })).code).not.toBe(0);
  expect(events().at(-1)).toBe("update-packages"); expect(manifest()).not.toContain("verified=true");
});
test("unpublished revision blocks Technitium update", async () => {
  expect((await update("technitium", { REMOTE: "b".repeat(40) })).code).not.toBe(0); expect(events()).toEqual([]);
});
test("failed final health check is not marked verified", async () => {
  expect((await update("guest", { FAIL_FINAL_HEALTH: "1" })).code).not.toBe(0);
  expect(events()).toContain("update-packages"); expect(events().at(-1)).toBe("verify-services"); expect(manifest()).not.toContain("verified=true");
});
test("concurrent maintenance is rejected", async () => {
  mkdirSync(lock, { recursive: true }); expect((await update("pause-gitops")).code).not.toBe(0); expect(events()).toEqual([]);
});
test("dirty checkout blocks application update", async () => {
  expect((await update("arcane", { DIRTY: " M arcane.yml" })).code).not.toBe(0); expect(events()).toEqual([]);
});
test("deployment uses shared lock and stops on failure", async () => {
  const command = ["ansible-playbook", "-i", join(repo, "inventory/hosts.yml"), join(repo, "ansible/playbooks/deploy.yml")];
  success(await run(command, env)); expect(events()).toEqual(["bootstrap-gitops", "arcane", "gitops", "verify-services"]); expect(exists(lock)).toBe(false);
  reset(); expect((await run(command, { ...env, FAIL_AT: "arcane" })).code).not.toBe(0);
  expect(events()).toEqual(["bootstrap-gitops", "arcane"]); expect(exists(lock)).toBe(true);
  expect((await update("pause-gitops")).code).not.toBe(0); expect(events()).toEqual(["bootstrap-gitops", "arcane"]);
});
test("pause neither backs up nor deploys", async () => {
  success(await update("pause-gitops", { DIRTY: " M arcane.yml" })); expect(events()).toEqual(["pause-gitops"]);
});
