# research/configs/climada/

CLIMADA build configs of research runs. They are not part of the `packages/climada` package. They moved here byte-identical from `packages/climada/configs/` (MAR-185, ADR 0004 Q5), so their SHA256s still match the ones that research recorded.

| Config | Study |
|---|---|
| `florida_counties_cat_in_circle_{50,75,100,150}km_no_draws.yaml` | The cat-in-a-circle radius sensitivity (MAR-133): `research/notes/cat-in-circle-radius-sensitivity.md`, `research/data/cat-in-circle-radius-sensitivity/`. The 75 km build is also the no-draws counterpart of the D2 index (b) EventSet (MAR-145): `research/notes/d2-florida-eventset.md` |

How to read them:

- **Sibling paths in the comments** (`configs/…`) mean `packages/climada/configs/…`, the folder these files came from. So `configs/florida_counties_no_draws.yaml` is `packages/climada/configs/florida_counties_no_draws.yaml`, and the build command in each header now takes the path of the file here (below).
- **Paths in the settings** are relative to the config file. This folder is as deep as `packages/climada/configs/`, so `../../../data/…` still resolves to the git-ignored `data/` at the repository root, and the EventSets they build don't change.

Build from `packages/climada`, in its pixi environment:

```sh
cd packages/climada
pixi run --locked build-eventset --config ../../research/configs/climada/florida_counties_cat_in_circle_75km_no_draws.yaml
```
