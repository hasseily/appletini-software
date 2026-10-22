# libtini contributor instructions

## Scope

- Read README.md and design/PLAN.md before changing project scope.
- Build a C SDK for the Appletini's existing 65C02-facing interfaces.
- Do not change or require changes to Appletini firmware or FPGA logic.
- Keep the appletini-one repository unchanged.
- Keep private SmartPort services optional. Memory operations need standard CPU paths, including a build without private transport code.
- Exclude SuperSprite and manual slot swapping.
- Include simple speech in the first release. Prepared phrases and spoken numbers use existing SSI-263 registers; text conversion belongs in host tools.
- API examples in the plan express intent, not a frozen ABI.

## Project boundaries

- libtini lives in `libtini/` of the appletini-software repository. Keep it self-contained there: its tools may use the repository's development emulator (`tools/appletini`, `demos/doom_gs/tools/a2vm`), and nothing else outside `libtini/`.
- Do not link temporary, session or build-output locations into it.
- Do not make builds depend on sibling checkouts. Copy required inputs into libtini after checking their licenses, or use a documented installed dependency.
- libtini is MIT. Files that link GPL code, such as the browser player in `tools/web/`, carry their own SPDX notices.
- Source references are not runtime or build dependencies.
- Do not edit generated output as a substitute for changing its source.
- `docs/` is the HTML developer reference and `design/` holds the Markdown
  design notes. Update both when a public API, tool or format changes.

## Implementation

- Use near pointers for small working buffers and handles with explicit offsets for banked resources.
- Keep bank-switch code, mapping guards and interrupt ownership explicit.
- Keep video publication separate from AMEM PRIVATE working-memory transfers.
- Probe private services before use. Never silently retry a partly executed accelerated transfer with CPU copies.
- Keep speech, music and effects under one audio driver with bounded queues and waits.
- Do not promise a full keyboard matrix through the standard Apple keyboard interface.
- Keep prose plain and exact. State targets as targets until tests establish them.

## Verification

- Test actual CPU fallbacks and compare their results with optional fast paths.
- Cover bank boundaries, reserved memory, allocation failures and handle lifetime.
- Test at 33 MHz and TURBO; game and audio timing must remain stable.
- Separate host, emulator and board evidence. Only board tests establish real timing and output.
