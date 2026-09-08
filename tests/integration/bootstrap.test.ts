import { afterEach, expect, test } from "bun:test";
import { cleanFixtures, copyRepository, environment, join, read, rolePlaybook, run, success, temporary, tool } from "./support";
afterEach(cleanFixtures);
test("deploy key is reused and conflicting or writable keys are rejected", async () => {
  const root = temporary(), repo = join(root, "repo"), bin = join(root, "bin"); copyRepository(repo);
  tool(bin, "gh", `
const state = env.KEY_STATE;
if (args[0] === 'auth' && args[1] === 'status') {}
else if (args[0] === 'repo' && args[1] === 'view') console.log(JSON.stringify({isPrivate:true}));
else if (args[0] === 'api') {
  const keys = fs.existsSync(state) ? JSON.parse(read(state)) : [];
  if (keys.length && env.CONFLICT) keys[0].key = 'different';
  if (keys.length && env.WRITE_KEY) keys[0].read_only = false;
  console.log(JSON.stringify([keys]));
} else if (args.slice(0,3).join(' ') === 'repo deploy-key add') {
  assert(!fs.existsSync(state));
  fs.writeFileSync(state, JSON.stringify([{title:'arcane-gitops', key:read(args[3]).trim().split(/\\s+/).slice(0,2).join(' '), read_only:true}]));
} else process.exit(8);`);
  const env = environment(repo, { PATH: bin + ":" + process.env.PATH, KEY_STATE: join(root, "keys") });
  const command = ["ansible-playbook", rolePlaybook(repo, "arcane", "github_key")];
  success(await run(command, env)); const key = join(repo, "secrets/arcane/arcane-gitops"), original = read(key);
  success(await run(command, env)); expect(read(key)).toBe(original);
  for (const flag of ["CONFLICT", "WRITE_KEY"]) {
    expect((await run(command, { ...env, [flag]: "1" })).code).not.toBe(0); expect(read(key)).toBe(original);
  }
}, 180_000);
