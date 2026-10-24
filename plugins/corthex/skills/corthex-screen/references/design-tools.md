# Design tools

How stage 09 works with Figma and Claude Design. Whichever tool people use, the token file in the repository is the shared language: the tool and the code use its token names.

## Figma

Figma's MCP server lets the AI read a file's frames, variables and screenshots and, on paid plans, write to the canvas.

- Connect it once per host. In Claude Code: `claude mcp add --transport http figma https://mcp.figma.com/mcp`, then run `/mcp` and sign in; Figma's plugin, `claude plugin install figma@claude-plugins-official`, adds the same server with Figma's own skills. In Codex: `codex mcp add figma --url https://mcp.figma.com/mcp`, then sign in when asked.
- Limits depend on the plan and the seat. A Starter plan, or a View or Collab seat, gets only a few tool calls a month; Dev and Full seats on paid plans have per-minute limits. Writing to the canvas needs a Professional, Education, Organization or Enterprise plan, and writing outside your drafts needs a Full seat. When a call is refused, check Figma's current limits before you retry.
- Read only the frames you need: `get_metadata` for the outline of a large selection, `get_design_context` for one frame, `get_screenshot` to see it and `get_variable_defs` for the variables it uses.
- Draw the candidates with `use_figma` on a page of their own, each frame named with its screen ID and candidate, such as "SCR-002 · A". Never change frames people made; propose a change as a comment or in a copy of the frame.
- Keep Figma's variables equal to the token file. With the token file as the source, write its tokens to Figma as variables with `use_figma`. With Figma as the truth, read the variables with `get_variable_defs`, list the differences from the file and refresh the file.
- Code Connect links Figma components to the code's components, so generated code reuses them instead of guessing. Read the links with `get_code_connect_map`, and add one with `add_code_connect_map` when the user agrees.

## Claude Design

Claude Design drafts designs, prototypes and slides with Claude. Its documentation names no MCP server or API for other hosts, so outside Claude Code treat it as a human view without an API.

- In Claude Code, where artifacts are available, `/design <brief>` drafts artboards on one canvas and publishes it as an artifact that people edit in a browser. Give it the screen definitions and the token file, and ask for the candidates as artboards side by side. Each artboard can be exported as PNG or PDF.
- `/design-sync` uploads the repository's React design system to Claude Design, so its designs use the real components and tokens. Without a React design system, give it the token file and the brand assets instead.
- A design made in Claude Design can be handed to Claude Code from its Export menu, on this machine or on the web, so the work continues from the design rather than from a screenshot. Other exports include PDF, PPTX, standalone HTML and a ZIP file.
- In any other host, such as Codex, work from an export a person makes, as step 5 of the procedure in [SKILL.md](../SKILL.md) says.
- Before more screens are drawn, record the chosen direction with the user's words and a link to the chosen artboard, and keep an export of it, since the tool may keep no history of earlier versions.
