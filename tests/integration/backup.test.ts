import { afterEach, expect, test } from "bun:test";
import { mkdirSync, readdirSync } from "node:fs";
import { cleanFixtures, copyRepository, data, environment, exists, join, read, remove, rolePlaybook, run, success, temporary, tool, write } from "./support";
afterEach(cleanFixtures);
test("encrypted backups restore inputs, reject overwrite and clean up failures", async () => {
  const root = temporary(), repo = join(root, "repo"); copyRepository(repo);
  const inputs = { "stages/01-install/profiles/old-laptop.toml": "synthetic installer profile",
    "secrets/technitium/admin-password": "synthetic secret", "secrets/proxmox/proxmox_bootstrap": "synthetic private key" };
  for (const [name, value] of Object.entries(inputs)) write(join(repo, name), value);
  write(join(repo, "stages/03-provision/proxmox/terraform.tfstate"), '{"serial": 7}');
  mkdirSync(join(root, "gnupg"), { mode: 0o700 });
  const env = environment(repo, { GNUPGHOME: join(root, "gnupg") }), archive = join(root, "controller.gpg");
  const vars = data(join(root, "vars.json"), { backup_passphrase: "test-only", controller_backup_path: archive });
  const command = ["ansible-playbook", rolePlaybook(repo, "controller", "backup"), "-e", "@" + vars];
  success(await run(command, env));
  const encrypted = await Bun.file(archive).bytes(); expect(new TextDecoder().decode(encrypted)).not.toContain("synthetic secret");
  const restored = join(root, "restored.tar.gz");
  success(await run(["gpg", "--batch", "--pinentry-mode", "loopback", "--passphrase-fd", "0", "--output", restored, "--decrypt", archive], env, "test-only\n"));
  for (const [name, value] of Object.entries({ ...inputs, "terraform.tfstate": '{"serial": 7}' })) {
    const result = await run(["tar", "-xOzf", restored, name]); success(result); expect(result.stdout).toBe(value);
  }
  expect((await run(command, env)).code).not.toBe(0); expect(await Bun.file(archive).bytes()).toEqual(encrypted);
  const direct = ["bash", join(repo, "scripts/backup-controller.sh")];
  for (const [dest, pass] of [[join(repo, "secrets/backup.gpg"), "test-only\n"], [join(root, "empty.gpg"), "\n"]]) {
    expect((await run([...direct, dest], env, pass)).code).not.toBe(0); expect(exists(dest)).toBe(false);
  }
  remove(archive); tool(join(root, "bin"), "gpg", "process.exit(1);");
  expect((await run(command, { ...env, PATH: join(root, "bin") + ":" + env.PATH })).code).not.toBe(0);
  expect(exists(archive)).toBe(false);
  expect(readdirSync(root).filter(n => n.startsWith(".controller-encrypted-"))).toEqual([]);
}, 180_000);
