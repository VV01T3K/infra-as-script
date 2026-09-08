import { afterEach, beforeEach, expect, test } from "bun:test";
import { cleanFixtures, copyRepository, data, environment, exists, join, parse, read, remove, rolePlaybook, run, success, temporary, tool } from "./support";
afterEach(cleanFixtures);
let repo: string, playbook: string, output: string, env: ReturnType<typeof environment>;
beforeEach(() => {
  const root = temporary(); repo = join(root, "repo"); copyRepository(repo);
  playbook = rolePlaybook(repo, "controller", "inventory"); output = join(root, "inventory.json");
  const plays = parse(playbook);
  plays[0].tasks.push({ "ansible.builtin.copy": { dest: output,
    content: '{{ {"ip": hostvars["arcane"].ansible_host, "lxc_id": hostvars["arcane"].lxc_id} | to_json }}' } });
  data(playbook, plays);
  tool(join(root, "bin"), "tofu", 'if (env.TOFU_FAIL) { console.error("private diagnostic"); process.exit(1); } console.log(env.TOFU_OUTPUT);');
  env = environment(repo, { PATH: join(root, "bin") + ":" + process.env.PATH });
}, 180_000);
async function inventory(state: string, overrides = {}) {
  remove(output, { force: true });
  return run(["ansible-playbook", playbook], { ...env, TOFU_OUTPUT: state, ...overrides });
}
test("inventory uses applied address and guest ID", async () => {
  success(await inventory('{"ip":"10.0.0.77","lxc_id":207}'));
  expect(JSON.parse(read(output))).toEqual({ ip: "10.0.0.77", lxc_id: 207 });
}, 180_000);
test("invalid or missing state never emits inventory", async () => {
  for (const state of ['{}', 'not JSON', '{"ip":"invalid","lxc_id":200}', '{"ip":"10.0.0.60","lxc_id":1}',
    '{"ip":"999.0.0.1","lxc_id":200}', '{"ip":"010.0.0.1","lxc_id":200}', '{"ip":"10.0.0.1","lxc_id":true}']) {
    expect((await inventory(state)).code, state).not.toBe(0); expect(exists(output)).toBe(false);
  }
}, 180_000);
test("tofu failure does not fall back or expose diagnostics", async () => {
  const result = await inventory('{}', { TOFU_FAIL: "1" });
  expect(result.code).not.toBe(0); expect(exists(output)).toBe(false);
  expect(result.stdout + result.stderr).not.toContain("private diagnostic");
}, 180_000);
