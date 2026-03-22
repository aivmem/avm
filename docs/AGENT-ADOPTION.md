# Making Agents Actually Use AVM

> "If you build it, they won't come. You have to build it into their daily routine."

---

## The Problem

Agents have access to AVM but don't use it because:

1. **No trigger** — nothing prompts them to remember or recall
2. **Extra effort** — remembering feels like "extra work"
3. **No feedback** — they don't see the benefit

---

## Solution 1: Automatic Context Injection

**Inject recent memories into every session start.**

```python
# In agent initialization
recent_context = avm.recall(
    query=f"recent context for {agent_id}",
    max_tokens=500,
    prefixes=[f"/memory/private/{agent_id}/"]
)

system_prompt += f"""

## Your Recent Memory
{recent_context}
"""
```

**Effect**: Agent sees its own memories without asking. Creates continuity.

---

## Solution 2: Session Hooks

**Auto-remember at session end.**

```yaml
# In agent config
hooks:
  on_session_end:
    - action: avm_remember
      content: "Session summary: {{session_summary}}"
      importance: 0.6
```

Or in code:

```python
@on_session_end
def auto_remember(session):
    if session.message_count > 3:  # Non-trivial session
        summary = llm.summarize(session.messages[-10:])
        avm.remember(
            summary,
            importance=0.5,
            tags=["session-summary", session.date]
        )
```

**Effect**: Memories accumulate without agent effort.

---

## Solution 3: SKILL.md Guidance

Add explicit guidance in the agent's SKILL.md:

```markdown
## Memory Usage

### When to Remember
- User shares a preference → remember it
- You learn something new about the task → remember it
- You make a mistake and correct it → remember the lesson
- User says "remember this" → remember it

### When to Recall
- Starting a new task → recall related context
- User mentions something from before → recall it
- You're unsure about user preferences → recall them

### Examples

**Good**: "User prefers concise responses" → `avm remember "User prefers concise responses" --importance 0.8`

**Bad**: Remembering every single message (too noisy)
```

---

## Solution 4: Proactive Memory Prompts

Add to system prompt:

```markdown
## Memory Awareness

You have access to persistent memory via AVM. Use it:

1. **Before answering complex questions**: Check if you've discussed this before
   ```
   avm recall "topic keywords" --max-tokens 500
   ```

2. **After learning user preferences**: Store them
   ```
   avm remember "User prefers X over Y" --importance 0.8
   ```

3. **After making mistakes**: Record the lesson
   ```
   avm remember "Lesson: Always check X before Y" --importance 0.9
   ```

Your memory helps you serve the user better over time. Use it.
```

---

## Solution 5: Memory-Aware Prompting

**Structured prompt that references memory:**

```markdown
## Your Working Memory

Recent relevant memories (auto-retrieved):
{{avm_recall(current_topic, max_tokens=300)}}

If you learn something important in this conversation, remember it with:
```avm remember "..." --importance 0.7```
```

---

## Solution 6: Make Memory Visible via FUSE

Mount AVM so the agent can browse it naturally:

```bash
avm-mount ~/memory --agent kearsarge
```

Then in SKILL.md:

```markdown
Your memory is mounted at ~/memory/. You can:
- `cat ~/memory/private/preferences.md` — read preferences
- `echo "learned X" >> ~/memory/private/lessons.md` — add a lesson
- `ls ~/memory/shared/` — see what other agents shared
```

---

## Solution 7: Memory Triggers in HEARTBEAT.md

```markdown
## Memory Maintenance (每次 heartbeat)

1. 检查是否有未整理的记忆
2. 如果今天没有记忆条目，主动写一条
3. 回顾 3 天前的记忆，看是否需要更新

```bash
# 检查最近记忆
avm list /memory/private/$(whoami)/ --since 24h
```
```

---

## Implementation Checklist

### For Agent Authors

- [ ] Add memory guidance to SKILL.md
- [ ] Add memory section to system prompt
- [ ] Set up auto-recall on session start
- [ ] Set up auto-remember on session end
- [ ] Include memory hooks in HEARTBEAT.md

### For AVM

- [ ] Provide `avm context` command that outputs recent memories for prompt injection
- [ ] Provide SDK hooks for session start/end
- [ ] Add "memory prompt" template generator

### For OpenClaw

- [ ] Auto-inject recent memories into session context
- [ ] Provide `memory_recall` tool alongside other tools
- [ ] Add memory status to `/status` output

---

## Example: Kearsarge's AGENTS.md Addition

```markdown
## Memory (AVM)

我有持久记忆，路径 `/memory/private/kearsarge/`。

### 什么时候记
- 指挥官的偏好（重要度 0.8）
- 学到的教训（重要度 0.9）
- 任务总结（重要度 0.6）

### 什么时候想
- 开始新任务前
- 指挥官问"上次..."
- 不确定偏好时

### 命令
```bash
avm remember "内容" --importance 0.7
avm recall "关键词" --max-tokens 500
```

记忆帮我更好地服务指挥官。用它。
```

---

## Metrics to Track

1. **Memory writes per session** — should be 1-3 for non-trivial sessions
2. **Memory recalls per session** — should be 1+ for returning users
3. **Memory age distribution** — healthy system has mix of recent and old
4. **Recall hit rate** — are recalled memories actually relevant?

---

## Summary

| Approach | Effort | Impact |
|----------|--------|--------|
| Auto-inject context | Low | High |
| Session hooks | Low | High |
| SKILL.md guidance | Low | Medium |
| System prompt | Low | Medium |
| FUSE mount | Medium | High |
| HEARTBEAT checks | Low | Low |

**Start with**: Auto-inject + SKILL.md guidance + session hooks.
