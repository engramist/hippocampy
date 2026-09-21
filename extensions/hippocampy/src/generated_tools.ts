/*
 * AUTO-GENERATED FILE. DO NOT EDIT.
 *
 * Source: campy/brain/thalamus/tool_schemas.py (TOOLS)
 * Strategy: additive generation for tools not already handwritten in
 * extensions/hippocampy/src/index.ts.
 *
 * Regenerate with:
 *   python scripts/generate_extension_tools.py
 */

import { Type, type TSchema } from "@sinclair/typebox";

export type GeneratedToolDefinition = {
  name: string;
  label: string;
  description: string;
  parameters: TSchema;
};

export const GENERATED_TOOL_DEFINITIONS: GeneratedToolDefinition[] = [
  {
    name: "route_task",
    label: "Route Task (HippoCampy)",
    description: "B382: recommend whether a task should go to a frontier or economy/local model, based on the calling session's graph state (an open, unfinalized Plan vs. a locked-in TaskGraph with pending work). Advisory only -- never calls a cloud model itself. Returns tier, provider, recommended_model, phase, rationale, a scoped context_bundle (the active Plans/TaskGraph status backing the recommendation), and latency_ms.",
    parameters: Type.Object({
    task_description: Type.String({ description: "The task to route. Checked first against a small formatting/lint/syntax-check keyword set for the local_reflex fast path." }),
    session_id: Type.Optional(Type.String({ description: "Session ID used to resolve the active quest, if quest_id is not given directly." })),
    quest_id: Type.Optional(Type.String({ description: "Optional explicit quest ID, bypassing session->quest resolution." })),
    token_budget: Type.Optional(Type.Number({ description: "Token budget for the returned context_bundle. Default 4000." })),
  }),
  },
];
