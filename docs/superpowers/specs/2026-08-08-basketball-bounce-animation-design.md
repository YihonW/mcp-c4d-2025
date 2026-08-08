# Basketball Bounce Animation Design

## Goal

Use the connected Cinema 4D MCP bridge to build a readable, realistic basketball-style drop and settling bounce in the active empty document.

## Scene

- Preserve the active document instead of opening or closing documents.
- Use the document's current 25 fps.
- Extend the range to frame 125 (five seconds).
- Create one sphere named `篮球` with a 12 cm radius and one floor plane named `地面`.
- Give the sphere a simple orange material and the floor a neutral material when the currently exposed MCP tool set permits it; geometry and animation are the required result.

## Motion

- The ball starts at Y=220 cm and first contacts the floor with its center at Y=12 cm.
- Animate the center on Y with spline keys for a gravity-like accelerating fall and four progressively lower, shorter rebounds.
- Keep X and Z fixed so the motion is easy to inspect.
- Add brief Y squash and compensating X/Z widening at each impact, returning to uniform scale immediately afterward.
- Add a small accumulated rotation during the bounce without lateral drift.
- End at Y=12 cm with scale `[1, 1, 1]` and no further keys after settling.

## Verification

- Read back the object list, document range, tracks, and keyframes.
- Sample the ball transform at the start, each contact/apex, and the final frame.
- Render MCP previews around the first impact, a middle bounce, and the final settled pose.
- Acceptance requires no floor penetration, declining bounce heights, shorter bounce intervals, restored final scale, and a stationary final segment.

## Safety

- All mutations stay in the current untitled scene and use MCP undo-aware operations.
- Do not save over any existing file.
- Do not enable arbitrary Python execution.
