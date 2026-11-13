---
name: decomp-split
description: "Move a port's RE knowledge and code into the decomp repository of its exact build: fork the community decomp or create our own permissive one, verify the split against the user's files, move the RE docs and named addresses, pin it as a submodule, and plan the generated address constants. Use before any other work on a title whose port still holds RE notes or hand-written guest addresses, and whenever a title gains a decomp."
---

# Decomp split

The rule lives in the global instructions (Docs): RE knowledge and code belong to the decomp repository,
the port reads guest addresses from its symbol map. The split is the one-time move that makes a title
obey it, and it comes before any other work on that title.

## 1. The decomp repository

- Check `docs/prior-art.md` and search for a decomp of the exact build (serial, executable hash).
  A README's claim counts only when its files hold matched code or a symbol map for our build.
- **One exists:** fork it under the project's GitHub owner, disable Actions on the fork, and pin
  the fork as a submodule. Its licence stays; a fork of an unlicensed or copyleft decomp is evidence
  and naming only, its code is never copied into the port.
- **None exists:** create our own public repository (`<title>-decomp`, MIT unless the source
  material forces another permissive licence) with a splat config per executable and overlay. The
  README says bring your own disc and carries the AI-assistance line. Split the user's own files
  (copied out of the provisioned directory, never modified there); splat's SHA-1 check against the
  build is the proof. Disc copies and split output stay gitignored.

## 2. What moves

| into the decomp | stays in the port |
|---|---|
| decompiled source and splat configs | port code, overrides, native owners |
| C for every guest function the port has recovered | the port's native overrides of those functions |
| the symbol map: named addresses, structure sizes, field offsets | `docs/project-goals.md`, `project-state.md`, issues, plans |
| `docs/re-frontier.md` | `docs/codemap.md` and subsystem docs |
| behaviour notes (how the guest works) | docs mapping guest addresses to native owners |
| `docs/prior-art.md` for that build | prior art of other titles the repo holds |

- Each name the port uses goes into the symbol map at its address. Where upstream already names that
  address differently, upstream's name stays and the conflict is listed in `docs/our-names.md` with
  ours beside it; the port adopts upstream's name when the constants are generated.
- Overlay names go in the map of the overlay that holds them; a name with no known image waits in a
  list in the decomp, not in the map.
- A guest function the port decompiled (a Ghidra reading turned into an override, a reimplemented
  routine) is written into the decomp's source as C at its address: matched where the decomp builds
  matching, otherwise functional C marked non-matching in the decomp's own way. The port's override
  stays port code and cites the decomp function.
- Each moved port file becomes a one-line pointer to its new home, so references keep resolving.

## 3. Commits

- In a fork: findings (names, notes) and port-only changes (our layout, docs only we need) are
  separate commits. Upstream PRs are optional and carry findings only.
- The port change bumps the submodule and moves the docs in one commit; the plan is the next.
- From then on a change that needs a new finding commits it to the decomp first and bumps the
  submodule in the port change that uses it.

## 4. Generated constants

Write the port's plan `docs/plans/NNNN-addresses-from-the-decomp-symbol-map.md`: one generator in
the shared framework reads the splat symbol files into constants under `build/`, and the plan lists
the hand-written address headers it replaces, in order. Until it lands, new addresses still go to
the symbol map first.

## Done when

The fork or new repository is public and pinned; the split is verified against the user's build;
the port holds no RE notes, only pointers; the symbol map holds every name the port uses (or lists
the conflict); the plan exists; `project-state.md` names the decomp.

Reference: Spyro 1/2/3 (forks of open-spyro, spyro-2, spyro-3) and Tomba 2 (`tomba2-decomp`, ours).
