// ai-guard-token-enforcement — OpenCode tool guardrail. Installed into target repos by
// register-opencode-guardrail-hook.sh; missing binaries fail closed with an actionable tool error.
//
// C.12 (0-PLAN--2026.08.27-10.35--Native-Only-Harness-Runtime.md): resolveAiGuard is PATH-only,
// matching scripts/lib/ai-guard-resolve.sh's resolve_ai_guard contract exactly -- before this
// step it additionally probed `../ai-tools/target/release`, `~/.cargo/bin`, and `~/.local/bin`
// when `ai-guard` wasn't on PATH, the same class of violation C.1 already closed for every bash
// wrapper (a non-PATH executable satisfying "runtime availability" is exactly what the plan's
// Scope section forbids). The block-on-failure mechanism itself ("tool.execute.before" throws
// when this throws, or when the resolved binary exits nonzero) was already correct -- only the
// resolution *location* was too permissive.
import { accessSync, constants } from "node:fs"
import { homedir } from "node:os"
import { delimiter, join, resolve } from "node:path"
import { spawnSync } from "node:child_process"

function isExecutable(file) {
  try {
    accessSync(file, constants.X_OK)
    return true
  } catch {
    return false
  }
}

function resolveAiGuard() {
  for (const pathDir of (process.env.PATH ?? "").split(delimiter)) {
    if (!pathDir) continue
    const candidate = join(pathDir, "ai-guard")
    if (isExecutable(candidate)) return candidate
  }

  throw new Error(
    "required native binary 'ai-guard' is not available on PATH. Deploy it with: scripts/deploy-native-tools.sh deploy",
  )
}

function resolveRunnerHook(directory, name) {
  const candidates = [
    resolve(directory, "..", "COMMON", "hooks", name),
    join(homedir(), "DEV_REPOS", "COMMON", "hooks", name),
  ]
  return candidates.find(isExecutable)
}

function guardArgs(args) {
  const normalized = { ...args }
  for (const [source, target] of [
    ["filePath", "file_path"],
    ["oldString", "old_string"],
    ["newString", "new_string"],
    ["replaceAll", "replace_all"],
  ]) {
    if (normalized[target] === undefined && normalized[source] !== undefined) {
      normalized[target] = normalized[source]
    }
  }
  return normalized
}

function ceilingDecision(directory, event, input, output) {
  if (process.env.AI_PLAN_RUNNER !== "1") return undefined
  const hook = resolveRunnerHook(directory, "plan-runner-ceiling-hook.sh")
  if (!hook) return undefined

  const payload = JSON.stringify({
    hook_event_name: event,
    session_id: input.sessionID,
    tool_name: input.tool,
    tool_input: guardArgs(output.args),
  })
  const result = spawnSync(hook, ["--schema", "opencode"], {
    input: payload,
    encoding: "utf8",
    timeout: 5000,
  })
  if (result.error) throw new Error(`context ceiling hook failed: ${result.error.message}`)
  if (result.status !== 0) {
    throw new Error(`context ceiling hook failed (exit ${result.status}): ${result.stderr.trim()}`)
  }
  if (!result.stdout.trim()) return undefined
  try {
    return JSON.parse(result.stdout.trim())
  } catch {
    throw new Error("context ceiling hook returned invalid JSON")
  }
}

function sessionStartContext(directory, event) {
  if (process.env.AI_PLAN_RUNNER !== "1" || event.type !== "session.created") return undefined
  const hook = resolveRunnerHook(directory, "plan-runner-session-start-hook.sh")
  if (!hook) return undefined

  const sessionID = event.properties?.info?.id
  if (!sessionID) return undefined
  const result = spawnSync(hook, [], {
    input: JSON.stringify({
      session_id: sessionID,
      hook_event_name: "SessionStart",
      source: "startup",
    }),
    encoding: "utf8",
    timeout: 5000,
  })
  if (result.error) throw new Error(`session-start hook failed: ${result.error.message}`)
  if (result.status !== 0) {
    throw new Error(`session-start hook failed (exit ${result.status}): ${result.stderr.trim()}`)
  }
  return result.stdout.trim() || undefined
}

export const AiGuardPlugin = async ({ client, directory }) => ({
  event: async ({ event }) => {
    const context = sessionStartContext(directory, event)
    if (!context) return
    await client.session.prompt({
      path: { id: event.properties.info.id },
      body: { noReply: true, parts: [{ type: "text", text: context }] },
    })
  },
  "tool.execute.before": async (input, output) => {
    const binary = resolveAiGuard()
    const payload = JSON.stringify({
      tool_name: input.tool,
      tool_args: guardArgs(output.args),
    })
    const result = spawnSync(binary, ["--schema", "opencode", "--json"], {
      input: payload,
      encoding: "utf8",
      timeout: 5000,
    })

    if (result.error) throw new Error(`ai-guard execution failed: ${result.error.message}`)
    if (result.status !== 0) {
      throw new Error(`ai-guard execution failed (exit ${result.status}): ${result.stderr.trim()}`)
    }

    let decision
    try {
      decision = JSON.parse(result.stdout.trim())
    } catch {
      throw new Error("ai-guard returned invalid JSON")
    }
    if (decision.decision === "deny") {
      throw new Error(decision.reason || "Blocked by ai-guard")
    }
    if (decision.decision !== "allow") {
      throw new Error("ai-guard returned an unknown decision")
    }

    const ceiling = ceilingDecision(directory, "PreToolUse", input, output)
    if (ceiling?.decision === "deny") {
      throw new Error(ceiling.reason || "Plan-runner context hard ceiling reached")
    }
  },
  "tool.execute.after": async (input, output) => {
    const ceiling = ceilingDecision(directory, "PostToolUse", input, { args: input.args })
    if (ceiling?.additionalContext) output.output += `\n${ceiling.additionalContext}`
  },
})
