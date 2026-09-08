import { afterEach, beforeEach, expect, test } from "bun:test";
import { cleanup, cleanFixtures, copyRepository, data, environment, exists, join, keypair, parse, read, remove, run, success, temporary, tool, write } from "./support";
afterEach(cleanFixtures);
let root: string, repo: string, secretDir: string, bin: string, api: string, env: ReturnType<typeof environment>, state: any;
beforeEach(() => {
  root = temporary(); repo = join(root, "repo"); copyRepository(repo); secretDir = join(repo, "secrets"); bin = join(root, "bin");
  const hosts = Object.fromEntries(["pve", "arcane"].map(host => [host, {
    ansible_host: "127.0.0.1", ansible_connection: "local", rotation_authorized_keys: join(root, host + "-authorized"),
  }]));
  data(join(repo, "inventory/hosts.yml"), { all: { hosts } });
  tool(bin, "tofu", 'console.log(JSON.stringify({ip:"127.0.0.1",lxc_id:207}));');
  // Substitute only host password/service mutations, never run them on the test runner.
  data(join(repo, "ansible/roles/credentials/tasks/root.yml"), [{ "ansible.builtin.command": "true", changed_when: false }]);
  const path = join(repo, "ansible/roles/credentials/tasks/arcane-api.yml"), tasks = parse(path);
  function replaceServices(items: any[]) {
    for (const task of items) {
      if (task.register === "new_arcane_auth") { task.retries = 1; task.delay = 0; }
      if ("ansible.builtin.systemd_service" in task) { delete task["ansible.builtin.systemd_service"]; task["ansible.builtin.command"] = "true"; }
      for (const key of ["block", "rescue", "always"]) replaceServices(task[key] ?? []);
    }
  }
  replaceServices(tasks); data(path, tasks);
  state = { password: "old-password", failVerify: false, changed: false, events: [], sessions: [] };
  const server = Bun.serve({ hostname: "127.0.0.1", port: 0, async fetch(request) {
    const route = new URL(request.url).pathname, body = await request.text(), form = Object.fromEntries(new URLSearchParams(body));
    let status = 200, result: any = { status: "ok" };
    if (route.endsWith("/user/login")) {
      if (form.pass !== state.password || (state.changed && state.failVerify)) result = { status: "error" };
      else { const token = "session-" + state.sessions.length; state.sessions.push(token); result = { status: "ok", token }; }
    } else if (route.endsWith("/user/changePassword")) {
      if (form.pass !== state.password || !form.newPass) result = { status: "error" };
      else { state.password = form.newPass; state.changed = true; state.events.push("password-changed"); }
    } else if (route.endsWith("/user/profile/get")) {
      const current = request.headers.get("Authorization")!.split(" ")[1];
      result = { status: "ok", response: { sessions: state.sessions.map((t: string) => ({ partialToken: t, isCurrentSession: t === current })) } };
    } else if (route.endsWith("/user/session/delete")) state.sessions = state.sessions.filter((t: string) => t !== form.partialToken);
    else if (route.endsWith("/nodes")) {
      if (state.failVerify) status = 403;
      if (state.tokenFile && !JSON.parse(read(state.tokenFile)).some((n: string) => request.headers.get("Authorization") === `PVEAPIToken=automation@pve!${n}=synthetic-issued-secret`)) status = 401;
      result = { data: [] };
    } else if (route.includes("/customize/git-repositories")) {
      if (state.arcaneEnv) {
        const active = read(state.arcaneEnv).split("\n").find(l => l.startsWith("ADMIN_STATIC_API_KEY="))!.split("=")[1];
        if (request.headers.get("X-Api-Key") !== active || state.failVerify) status = 401;
      }
      result = { success: true, data: [] };
      if (state.githubState) {
        result = { success: true, data: [{ id: "repo1", name: "infra-as-script", url: "git@github.com:VV01T3K/infra-as-script.git" }] };
        if (request.method === "PUT") state.repoPrivate = JSON.parse(body).sshKey;
        if (route.endsWith("/test") && (state.failGitTest || state.repoPrivate !== read(state.candidatePath).trim())) status = 400;
      }
    }
    return Response.json(result, { status });
  } });
  cleanup(() => server.stop(true)); api = `http://127.0.0.1:${server.port}`;
  env = environment(repo, { PATH: bin + ":" + process.env.PATH, TEST_ROOT: root });
}, 180_000);
const put = (name: string, value: string) => write(join(secretDir, name), value);
const unlock = () => remove(join(secretDir, "proxmox/maintenance.lock.d"), { recursive: true });
function secrets(operation = "rotate", only = "all", variables = {}) {
  return run(["ansible-playbook", "-i", join(repo, "inventory/hosts.yml"), join(repo, "ansible/playbooks/secrets.yml"), "-e", JSON.stringify({
    secrets_action: operation, secrets_only: only, technitium_api: api, proxmox_api_url: api, arcane_api: api,
    technitium_password_path: join(root, "runtime-password"), ...variables,
  })], env);
}
test("credential generation is repeatable and never overwrites existing values", async () => {
  const first = await secrets("generate"); success(first);
  const names = ["proxmox/proxmox_bootstrap", "arcane/arcane-api-key", "arcane/arcane-gitops", "technitium/technitium-admin-password"];
  const originals = names.map(n => read(join(secretDir, n))); success(await secrets("generate"));
  names.forEach((n, i) => { expect(read(join(secretDir, n))).toBe(originals[i]); expect(first.stdout).not.toContain(originals[i].trim()); });
  expect(exists(join(secretDir, "proxmox/proxmox.env"))).toBe(false);
}, 180_000);
test("SSH failure preserves access and retry reuses the candidate", async () => {
  const key = join(secretDir, "proxmox/proxmox_bootstrap"), publicKey = await keypair(key), original = read(key);
  for (const host of ["pve", "arcane"]) write(join(root, host + "-authorized"), publicKey + "\n");
  tool(bin, "ssh", `
if (fs.existsSync(env.TEST_ROOT + '/fail-ssh')) process.exit(1);
for (const option of ['IdentitiesOnly=yes','ControlPath=none','IdentityAgent=none']) assert(args.includes(option));
const key = read(args[args.indexOf('-i')+1]+'.pub').trim();
for (const host of ['pve','arcane']) assert(read(env.TEST_ROOT+'/'+host+'-authorized').includes(key));`);
  write(join(root, "fail-ssh"), ""); expect((await secrets("rotate", "ssh")).code).not.toBe(0); expect(read(key)).toBe(original);
  const candidate = read(join(secretDir, ".pending/ssh/new")); expect(read(join(root, "pve-authorized"))).toContain(publicKey);
  unlock(); remove(join(root, "fail-ssh")); success(await secrets("rotate", "ssh")); expect(read(key)).toBe(candidate);
  for (const host of ["pve", "arcane"]) expect(read(join(root, host + "-authorized"))).not.toContain(publicKey);
}, 180_000);
test("Technitium rotation resumes after the server password changed", async () => {
  const current = put("technitium/technitium-admin-password", "old-password\n"); state.failVerify = true;
  expect((await secrets("rotate", "technitium")).code).not.toBe(0); expect(read(current)).toBe("old-password\n");
  const candidate = read(join(secretDir, ".pending/technitium/new")); expect(state.password).toBe(candidate.trim());
  unlock(); state.failVerify = false; success(await secrets("rotate", "technitium"));
  expect(read(current)).toBe(candidate); expect(state.events).toEqual(["password-changed"]); expect(read(join(root, "runtime-password"))).toBe(candidate);
}, 180_000);
test("Proxmox verifies new tokens before revoking old ones and resumes", async () => {
  const current = put("proxmox/proxmox.env", "export PROXMOX_VE_API_TOKEN_ID='automation@pve!iac'\n");
  state.tokenFile = data(join(root, "tokens.json"), ["iac"]);
  tool(bin, "pveum", `
const p = env.TEST_ROOT + '/tokens.json', names = JSON.parse(read(p)), op = args[2];
if (op === 'list') console.log(JSON.stringify(names.map(tokenid => ({tokenid}))));
else if (op === 'add') {
  names.push(args[4]); fs.writeFileSync(p, JSON.stringify(names));
  console.log(JSON.stringify({'full-tokenid':'automation@pve!'+args[4], value:'synthetic-issued-secret'}));
} else if (op === 'remove') fs.writeFileSync(p, JSON.stringify(names.filter(n => n !== args[4])));
else process.exit(9);`);
  state.failVerify = true; expect((await secrets("rotate", "proxmox-api")).code).not.toBe(0);
  expect(JSON.parse(read(state.tokenFile))).toContain("iac"); const candidate = read(join(secretDir, ".pending/proxmox-api/new"));
  unlock(); state.failVerify = false; success(await secrets("rotate", "proxmox-api")); expect(read(current)).toBe(candidate);
  expect(JSON.parse(read(state.tokenFile))).not.toContain("iac"); expect(JSON.parse(read(state.tokenFile))).toHaveLength(1);
}, 180_000);
test("Arcane retains its encryption key and retires the old API key", async () => {
  const current = put("arcane/arcane-api-key", "old-api-key\n");
  state.arcaneEnv = write(join(root, "arcane.env"), "ENCRYPTION_KEY=keep-this-encryption-key\nADMIN_STATIC_API_KEY=old-api-key\n");
  state.failVerify = true; expect((await secrets("rotate", "arcane-api", { arcane_env_file: state.arcaneEnv })).code).not.toBe(0);
  expect(read(current)).toBe("old-api-key\n"); expect(read(state.arcaneEnv)).toContain("ADMIN_STATIC_API_KEY=old-api-key");
  unlock(); state.failVerify = false; success(await secrets("rotate", "arcane-api", { arcane_env_file: state.arcaneEnv }));
  expect(read(state.arcaneEnv)).toContain("ENCRYPTION_KEY=keep-this-encryption-key");
  expect(read(state.arcaneEnv)).toContain("ADMIN_STATIC_API_KEY=" + read(current).trim()); expect(read(current).trim()).not.toBe("old-api-key");
}, 180_000);
test("GitOps retires the old key only after Arcane verifies its replacement", async () => {
  const key = join(secretDir, "arcane/arcane-gitops"), publicKey = (await keypair(key)).split(/\s+/).slice(0, 2).join(" "), original = read(key);
  put("arcane/arcane-api-key", "test-static-key");
  state.githubState = data(join(root, "github-keys.json"), [{ id: 1, key: publicKey, title: "arcane-gitops", read_only: true }]);
  state.candidatePath = join(secretDir, ".pending/gitops/new"); state.failGitTest = true;
  tool(bin, "gh", `
const p = env.TEST_ROOT + '/github-keys.json', keys = JSON.parse(read(p));
if (args.slice(0,2).join(' ') === 'auth status') {}
else if (args[0] === 'api' && !args.includes('DELETE')) console.log(JSON.stringify([keys]));
else if (args.slice(0,3).join(' ') === 'repo deploy-key add') {
  const key = read(args[3]).trim().split(/\\s+/).slice(0,2).join(' '); assert(!keys.some(k => k.key === key));
  keys.push({id:2,key,title:'arcane-gitops',read_only:true}); fs.writeFileSync(p, JSON.stringify(keys));
} else if (args.includes('DELETE')) fs.writeFileSync(p, JSON.stringify(keys.filter(k => k.id !== Number(args.at(-1).split('/').at(-1)))));
else process.exit(9);`);
  expect((await secrets("rotate", "gitops")).code).not.toBe(0); expect(read(key)).toBe(original);
  expect(JSON.parse(read(state.githubState))).toHaveLength(2); const candidate = read(state.candidatePath);
  unlock(); state.failGitTest = false; success(await secrets("rotate", "gitops")); expect(read(key)).toBe(candidate);
  expect(JSON.parse(read(state.githubState)).map((k: any) => k.id)).toEqual([2]);
}, 180_000);
test("post-install retirement runs once and removes installer profile keys", async () => {
  const key = join(secretDir, "proxmox/proxmox_bootstrap"), publicKey = await keypair(key);
  write(join(root, "pve-authorized"), publicKey + "\n");
  write(join(repo, "secrets/installer/pve/answer.toml"), '[global]\nroot-ssh-keys = ' + JSON.stringify([publicKey]) + '\n');
  tool(bin, "ssh", ""); success(await secrets("post-install")); const rotated = read(key);
  expect(read(join(root, "pve-authorized"))).not.toContain(publicKey); success(await secrets("post-install"));
  expect(read(key)).toBe(rotated); expect(exists(join(secretDir, "proxmox/installed-machine-id"))).toBe(true);
}, 180_000);
