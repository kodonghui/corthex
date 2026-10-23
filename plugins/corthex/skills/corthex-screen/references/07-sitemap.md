# Stage 07 · Sitemap

| Slot | This stage |
| --- | --- |
| Inputs | User flows (FL) and the functional spec (SPEC) |
| Outputs | `sitemap.yaml`, by default `docs/07-sitemap/sitemap.yaml`: the screen tree, one SCR ID per screen with its parent, path, who can see it and the flows that pass through it |
| Human view | A board, a list or a slide, as set in `human`. The same data can be shown in all three ways |
| Sync | The YAML is the data and the views are drawn from it, so the default `truth` is `source` |
| Human checkpoints | The navigation structure is agreed |
| Trace IDs | SCR-001… |

## Steps

1. Collect every flow step that shows the user something; each distinct view is a screen candidate.
2. Merge candidates that are the same screen in different states. States belong to stage 08, not to the sitemap.
3. Arrange the screens in a tree with paths and access rules.
4. Add the SCR IDs back to the user flows.

## Checks

- Every flow step that shows something maps to a screen.
- Every screen is reachable from the root, and no two screens share a path.
- Every screen states who can see it.

## Output template

```yaml
- id: SCR-001
  name: Home
  path: /
  access: everyone
  flows: [FL-001, FL-002]
  children:
    - id: SCR-002
      name: Order detail
      path: /orders/:id
      access: signed-in customer
      flows: [FL-002]
```
