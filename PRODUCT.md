# Contingency

## Register

product

## Users and purpose

Engineering review of a factory capacity study, demonstrated to hackathon attendees who may not know the energy vocabulary. Review documents, choose sourced inputs and explicit assumptions, then compare real local simulations. The pitch assigns one speaker to operate and narrate the entire demo. Demonstrate the AI contribution with actual document interpretation and source-linked model output, including withheld values when evidence is insufficient; distinguish this from deterministic checks and schedule optimisation.

## Design principles

Factory dashboard → add a machine → select/upload documents → review findings and inputs → simulation → explained results. The five navigation stages are Factory / Documents / Review / Simulation / Results. New machines create independent studies against the same existing factory demand. Review stays locked until a machine is added or explicitly selected and its documents have been analysed (or manual review is explicitly chosen). Document changes lock it again. Surface document contradictions before numeric inputs. Show why a schedule helps with the actual demand curve and overload duration. One primary action in a consistent position. One review decision at a time. Value, source and edit controls together; secondary technical details on demand. No decorative slogans or footer copy. Keep the approved animated grid/factory/battery diagram. English interface with original source quotations preserved. No provenance banners or process metadata in the main flow; model identity and live/replay status belong in AI details and the report. The machine list shows power, daily energy and proposed schedules; existing demand remains aggregated when individual machine data is unknown. Familiar terms such as factory. Never hide unresolved issues or infer consent.

## Identity and accessibility

Use the white and electric-blue reference chosen by Kusaila and the tokens in design.md. Full-width, legible, calm. Keyboard focus, labelled controls, mobile layouts and reduced motion remain supported. No fabricated customer claims, data or comparisons.

## Live analysis, 23 September

Live Nebius uses DeepSeek V4.1 Flash after the measured comparison; Qwen was the initial live fallback when Kimi timed out. New documents are analyzed, never matched to archived answers. Identical successful live extractions may be cached; changed documents or extraction configuration invalidate the cache. Archived responses cannot satisfy a live request. See evaluation-selection-modeles/README.md for verified cases and limitations.

## Defensibility

The current workflow is a product benefit, not a demonstrated moat. Do not claim proprietary data, switching costs, exclusive distribution or superiority to an engineer using a strong LLM without evidence. Compare the full repeated engineering workflow in a pilot before claiming time or quality gains; see docs/presentation/MODEL-AND-MOAT.md.
