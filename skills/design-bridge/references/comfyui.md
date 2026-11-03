# ComfyUI: repeat the style, identical and in series

GPT discovers the style and ComfyUI **repeats it identically**. For that the
recipe is versioned, with the weights' hashes, the seed and the steps fixed.
`PROJECT.md` says whether this world is enabled, which GPU there is, where the
recipes live and which weights are allowed.

## What it is for

- A fixed illustration style in series: empty states, onboarding, errors.
- Avatar or character variations with the same identity.
- Reframing a piece per format (outpainting).
- Cut-outs with a transparent background (RGBA) and upscaling.
- Motion from an image, if the GPU can take it (see below).

**Not for:** components or code; icons (an icon is a vector); text, prices or
logos inside the image.

## Non-negotiable

1. **Server on `127.0.0.1` only**, with `--offline` and
   `--disable-partner-nodes`. A partner node is a paid API, that is, new
   spend: only with the owner's express authorisation.
2. **Only core nodes plus a closed list, pinned to a commit**, kept in
   `PROJECT.md`. A custom node is arbitrary code running on the machine:
   there has already been a botnet across more than 1,000 instances (03/2026)
   and a CVE in the Manager (CVE-2025-67303). A new node comes in through a
   card, with the commit reviewed.
3. **A weight with its licence read at the source, with a date.** Licences
   change between versions of the same model, and many new weights are
   non-commercial. Keep the table in `PROJECT.md`: weight, hash, licence, URL
   and the date it was read. A weight with no row in the table does not run.
4. **The GPU decides.** Know the VRAM before promising: 6 GB does images, not
   video. Video needs a bigger GPU or the cloud, and the cloud is new spend.

## Recipe

- A recipe is a graph in ComfyUI's **API format** (`<name>.json`) plus a
  header `<name>.recipe.json` with the weights and their hashes, the seed, the
  steps, the sampler, the resolution, the open parameters and what the recipe
  delivers.
- It is versioned in the project's repository, next to the tokens (path in
  `PROJECT.md`). The recipe is what guarantees "identical".
- **The agent picks a recipe from the list and fills in the open parameters;
  it does not build the graph.** A new recipe is card work, with the owner's
  acceptance of 3 sample outputs.

## Run

1. Check that the server answers on `127.0.0.1` and was started with
   `--offline --disable-partner-nodes` (from the process command line).
2. Submit the graph with the parameters filled in (`POST /prompt`), wait for
   the queue and download the outputs to the inbox
   (`~/.local/state/<project>/design-inbox/<date>-<subject>/`).
3. Write `origin.json` in the same format as `gpt-image.sh`, plus the recipe,
   the seed and the weights' hashes.
4. From there, follow the triage and the path to the product in `gpt-image.md`.
