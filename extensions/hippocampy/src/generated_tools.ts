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
    name: "arc_start_or_resume_thread",
    label: "Arc Start Or Resume Thread (HippoCampy)",
    description: "Read or create an investigation thread for ARC_AGI's trajectory Annatar, keyed by (task_id, anchor_type, anchor_ref). Returns the existing non-terminal thread (resumed) or creates a new one in state 'exploring'. A terminal thread (satisfied/exhausted) is reopened as a fresh, non-resumed start on the same anchor.",
    parameters: Type.Object({
    task_id: Type.String({}),
    anchor_ref: Type.Union([Type.String({}), Type.Number({})]),
    anchor_type: Type.Union([Type.Literal("goal"), Type.Literal("entity")]),
  }),
  },
];
